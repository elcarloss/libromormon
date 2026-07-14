"""
Capa de datos del Libro de Mormón en español.

NO raspa el sitio oficial — descarga el dataset estable desde el repo público:

    https://github.com/elcarloss/libromormon-data
    (raw: https://raw.githubusercontent.com/...)

Caché:
  Memoria: 5 min (en proceso; self._loaded_at)
  Disco:   ~/.cache/libromormon-data/    (30 días por defecto)

Uso:
    from libromormon.api import BoMAPI, get_api
    api = get_api()
    api.load()
    api.list_books()
    api.chapter("alma", 32)
    api.search("fe esperanza caridad")
    api.related("fe esperanza caridad", limit=10)
    api.one_per_book(seed=42)
"""
from __future__ import annotations

import json
import logging
import re
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from html import unescape
from pathlib import Path
from typing import Iterable, Optional

from . import sources

log = logging.getLogger("libromormon.api")

# ---------------------------------------------------------------------------
# Metadatos canónicos (orden y nombres oficiales). Se mantienen como fallback
# si books.json aún no se ha descargado; al cargar se sobreescriben desde el
# dataset.
# ---------------------------------------------------------------------------
_BOOK_ORDER_FALLBACK = [
    "1-ne", "2-ne", "jacob", "enos", "jarom", "omni",
    "w-of-m", "mosiah", "alma", "hel", "3-ne", "4-ne",
    "morm", "ether", "moro",
]
_NOMBRES_FALLBACK = {
    "1-ne": "1 Nefi", "2-ne": "2 Nefi", "3-ne": "3 Nefi", "4-ne": "4 Nefi",
    "jacob": "Jacob", "enos": "Enós", "jarom": "Jarom", "omni": "Omni",
    "w-of-m": "Palabras de Mormón", "mosiah": "Mosíah", "alma": "Alma",
    "hel": "Helamán", "morm": "Mormón", "ether": "Éter", "moro": "Moroni",
}
_ABREV_FALLBACK = {
    "1-ne": "1 Ne.", "2-ne": "2 Ne.", "3-ne": "3 Ne.", "4-ne": "4 Ne.",
    "jacob": "Jacob", "enos": "Enós", "jarom": "Jarom", "omni": "Omni",
    "w-of-m": "W de M.", "mosiah": "Mos.", "alma": "Alma", "hel": "Hel.",
    "morm": "Morm.", "ether": "Éter", "moro": "Moro.",
}

# Stopwords: artículos, preposiciones, pronombres, verbos auxiliares…
STOPWORDS = {
    "el", "la", "los", "las", "un", "una", "unos", "unas", "y", "o", "u",
    "de", "del", "al", "a", "que", "se", "me", "te", "nos", "le", "les",
    "lo", "en", "por", "con", "sin", "para", "sobre", "entre", "es", "son",
    "ser", "esta", "este", "estos", "estas", "su", "sus", "mi", "mis",
    "tu", "tus", "yo", "tú", "él", "ella", "ellos", "ellas", "como",
    "más", "ya", "no", "si", "sí", "tan", "muy", "también", "pero",
    "porque", "cuando", "donde", "ha", "han", "he", "hay", "sea", "fui",
    "fue", "era", "será", "sido", "sea", "todo", "todos", "toda", "todas",
    "otro", "otros", "otra", "otras", "mismo", "misma", "mismos", "mismas",
    "desde", "hasta", "cual", "cuyo", "cuya", "cuyos", "cuyas", "aquel",
    "aquella", "aquellos", "esas", "esto", "eso", "algo", "alguien", "nadie",
    "nada", "pues", "embargo", "luego", "ahí", "aquí", "ahora",
}

# TTLs
MEM_TTL_S = 300
DEFAULT_FILE_TTL_DAYS = 30

# ---------------------------------------------------------------------------
# Excepciones y singleton
# ---------------------------------------------------------------------------
class APIError(Exception):
    """Error de la API (validación, slug desconocido)."""


_instance: Optional["BoMAPI"] = None
_inst_lock = threading.Lock()


def get_api() -> "BoMAPI":
    global _instance
    with _inst_lock:
        if _instance is None:
            _instance = BoMAPI()
            _instance.load()
        return _instance


# ---------------------------------------------------------------------------
# Tokenización
# ---------------------------------------------------------------------------
def _norm(text: str) -> list[str]:
    """Tokeniza y quita stopwords. Mantiene tildes y ñ."""
    if not text:
        return []
    t = unescape(text).lower()
    t = re.sub(r"[^\wáéíóúüñ]+", " ", t, flags=re.UNICODE)
    out = []
    for w in t.split():
        if len(w) < 2:
            continue
        if w in STOPWORDS:
            continue
        out.append(w)
    return out


# ---------------------------------------------------------------------------
# API principal
# ---------------------------------------------------------------------------
class BoMAPI:
    def __init__(self, ttl_days: int = DEFAULT_FILE_TTL_DAYS):
        self._lock = threading.RLock()
        self._ttl_days = ttl_days
        self._libros: Optional[dict] = None         # {slug: meta}
        self._book_order: list[str] = list(_BOOK_ORDER_FALLBACK)
        self._nombres: dict[str, str] = dict(_NOMBRES_FALLBACK)
        self._abrev: dict[str, str] = dict(_ABREV_FALLBACK)
        self._verses: Optional[list[dict]] = None    # índice plano en memoria
        self._loaded_at: Optional[datetime] = None
        self._df: Optional[dict[str, int]] = None   # document frequency
        self._summary: dict = {}

    # --------------------------- carga ---------------------------
    def load(self, force: bool = False) -> int:
        """Carga/recarga el índice en memoria desde el repo de datos."""
        with self._lock:
            now = datetime.now()
            if (
                not force
                and self._verses is not None
                and self._loaded_at
                and (now - self._loaded_at).total_seconds() < MEM_TTL_S
            ):
                return len(self._verses)

            log.info("Cargando dataset desde %s", sources.RAW_BASE)

            # 1) resumen (stats + parser_version + fecha)
            self._summary = sources.dataset_summary()

            # 2) books.json: orden canónico + nombres + abreviaciones + capítulos
            books = sources.load_json("books.json", ttl_days=self._ttl_days, force=force)
            self._libros = {b["slug"]: {
                "slug": b["slug"],
                "nombre": b["nombre"],
                "abreviacion": b["abreviacion"],
                "orden": b.get("orden", 0),
                "capitulos": b["capitulos"],
            } for b in books}
            self._book_order = [b["slug"] for b in sorted(books, key=lambda b: b.get("orden", 0))]
            self._nombres = {b["slug"]: b["nombre"] for b in books}
            self._abrev = {b["slug"]: b["abreviacion"] for b in books}
            log.info("Libros descubiertos: %d", len(self._libros))

            # 3) verses.jsonl → índice plano (URL canónica para cada versículo)
            cap_meta = self._load_chapter_meta(force=force)
            all_v: list[dict] = []
            for v in sources.stream_jsonl(
                "verses.jsonl", ttl_days=self._ttl_days, force=force
            ):
                slug = v["libro_slug"]
                cap = v["capitulo"]
                all_v.append({
                    "slug": slug,
                    "libro": v["libro"],
                    "abreviacion": v["abreviacion"],
                    "capitulo": cap,
                    "versiculo": v["versiculo"],
                    "texto": v["texto"],
                    "norm": _norm(v["texto"]),
                    "sumario": v.get("sumario", ""),
                    "url": v["url"],
                    "titulo_cap": cap_meta.get((slug, cap), {}).get("titulo", f"{v['libro']} {cap}"),
                })
            self._verses = all_v
            self._loaded_at = now
            self._df = None
            log.info("Versículos indexados: %d", len(self._verses))
            return len(self._verses)

    def _load_chapter_meta(self, force: bool = False) -> dict[tuple[str, int], dict]:
        """Lee by-book/<slug>.json para tener título+sumario por capítulo (sin texto)."""
        meta: dict[tuple[str, int], dict] = {}
        for slug in self._book_order:
            try:
                data = sources.load_json(
                    f"by-book/{slug}.json",
                    ttl_days=self._ttl_days,
                    force=force,
                )
            except Exception as e:
                log.warning("No se pudo cargar by-book/%s.json: %s", slug, e)
                continue
            for c in data.get("capitulos_meta", []):
                meta[(slug, c["capitulo"])] = c
        return meta

    # --------------------------- helpers ---------------------------
    def _require_loaded(self):
        if self._verses is None:
            self.load()

    def _ensure_df(self):
        if self._df is None and self._verses:
            df: dict[str, int] = {}
            for v in self._verses:
                for t in set(v["norm"]):
                    df[t] = df.get(t, 0) + 1
            self._df = df

    def _validate_book(self, slug: str) -> str:
        if slug not in self._book_order:
            raise APIError(
                f"Libro desconocido: {slug!r}. "
                f"Libros válidos: {', '.join(self._book_order)}"
            )
        return slug

    # --------------------------- endpoints ---------------------------
    def health(self) -> dict:
        self._require_loaded()
        total_cap = sum(m["capitulos"] for m in (self._libros or {}).values())
        return {
            "ok": True,
            "libros": len(self._libros or {}),
            "capitulos": total_cap,
            "versiculos": len(self._verses or []),
            "cargado_en": self._loaded_at.isoformat() if self._loaded_at else None,
            "fuente": sources.RAW_BASE,
            "cache_dir": str(sources.cache_dir()),
            "dataset_summary": self._summary,
        }

    def list_books(self) -> dict:
        self._require_loaded()
        libros = []
        for slug in self._book_order:
            m = self._libros.get(slug)
            if not m:
                continue
            count = sum(1 for v in (self._verses or []) if v["slug"] == slug)
            libros.append({
                "slug": slug,
                "nombre": m["nombre"],
                "abreviacion": m["abreviacion"],
                "orden": m.get("orden", 0),
                "capitulos": m["capitulos"],
                "versiculos": count,
            })
        return {"total": len(libros), "libros": libros}

    def book(self, slug: str) -> Optional[dict]:
        self._require_loaded()
        slug = self._validate_book(slug)
        m = self._libros.get(slug)
        if not m:
            return None
        nombre = m["nombre"]
        try:
            data = sources.load_json(
                f"by-book/{slug}.json", ttl_days=self._ttl_days
            )
        except Exception:
            data = None
        if data and data.get("capitulos_meta"):
            lista = [{
                "capitulo": c["capitulo"],
                "versiculos": c.get("versiculos", 0),
                "titulo": c.get("titulo", f"{nombre} {c['capitulo']}"),
                "sumario": c.get("sumario", ""),
                "url": c.get("url") or sources.church_chapter_url(slug, c["capitulo"]),
            } for c in data["capitulos_meta"]]
        else:
            # fallback: derivar del índice en memoria
            lista = []
            for cap in range(1, m["capitulos"] + 1):
                vs = [v for v in self._verses or [] if v["slug"] == slug and v["capitulo"] == cap]
                titulo = vs[0]["titulo_cap"] if vs else f"{nombre} {cap}"
                sumario = vs[0]["sumario"] if vs else ""
                lista.append({
                    "capitulo": cap,
                    "versiculos": len(vs),
                    "titulo": titulo,
                    "sumario": sumario,
                    "url": sources.church_chapter_url(slug, cap),
                })
        return {
            "slug": slug,
            "nombre": nombre,
            "abreviacion": m["abreviacion"],
            "capitulos": m["capitulos"],
            "lista": lista,
        }

    def chapter(self, slug: str, chap: int) -> Optional[dict]:
        self._require_loaded()
        slug = self._validate_book(slug)
        m = self._libros.get(slug)
        if not m or not (1 <= int(chap) <= m["capitulos"]):
            raise APIError(
                f"Capítulo fuera de rango: {slug} sólo tiene {m['capitulos'] if m else '?'} capítulos"
            )
        try:
            data = sources.load_json(
                f"by-chapter/{slug}-{int(chap):03d}.json",
                ttl_days=self._ttl_days,
            )
        except Exception as e:
            log.warning("No se pudo cargar %s-%03d.json: %s", slug, chap, e)
            return None
        data["_ref"] = f"{m['abreviacion']} {chap}"
        return data

    def verse(self, slug: str, chap: int, vs: int) -> Optional[dict]:
        ch = self.chapter(slug, chap)
        if not ch:
            return None
        for v in ch["versiculos"]:
            if v["numero"] == vs:
                return {
                    "ref": f"{self._nombres[slug]} {chap}:{vs}",
                    "abreviacion": f"{self._abrev[slug]} {chap}:{vs}",
                    "libro": self._nombres[slug],
                    "capitulo": chap,
                    "versiculo": vs,
                    "texto": v["texto"],
                    "url": sources.church_verse_url(slug, chap, vs),
                    "sumario": ch.get("sumario", ""),
                }
        return None

    def one_per_book(self, seed: Optional[int] = None) -> list[dict]:
        """Una escritura aleatoria por cada libro (semilla opcional)."""
        import random

        self._require_loaded()
        rng = random.Random(seed)
        by_book: dict[str, list[dict]] = {}
        for v in self._verses or []:
            by_book.setdefault(v["slug"], []).append(v)
        out = []
        for slug in self._book_order:
            lst = by_book.get(slug, [])
            if not lst:
                continue
            v = rng.choice(lst)
            out.append({
                "libro": v["libro"],
                "libro_slug": slug,
                "abreviacion": v["abreviacion"],
                "referencia": f"{v['abreviacion']} {v['capitulo']}:{v['versiculo']}",
                "texto": v["texto"],
                "sumario": v["sumario"],
                "url": v["url"],
            })
        return out

    # --------------------------- búsqueda ---------------------------
    def search(
        self,
        query: str,
        limit: int = 30,
        libro: Optional[str] = None,
    ) -> list[dict]:
        """Búsqueda AND: cada versículo contiene TODAS las palabras."""
        self._require_loaded()
        if not query or not query.strip():
            raise APIError("query vacío")
        words = _norm(query)
        if not words:
            raise APIError(
                "La consulta no tiene palabras significativas tras eliminar stopwords"
            )
        slug = self._validate_book(libro) if libro else None
        out = []
        for v in self._verses or []:
            if slug and v["slug"] != slug:
                continue
            tokens = set(v["norm"])
            if not all(w in tokens for w in words):
                continue
            out.append({
                "libro": v["libro"],
                "libro_slug": v["slug"],
                "abreviacion": v["abreviacion"],
                "referencia": f"{v['abreviacion']} {v['capitulo']}:{v['versiculo']}",
                "texto": v["texto"],
                "sumario": v["sumario"],
                "url": v["url"],
                "score": 1.0,
            })
            if len(out) >= limit:
                break
        return out

    def related(
        self,
        words: str,
        limit: int = 20,
        libro: Optional[str] = None,
    ) -> list[dict]:
        """Top-N versículos contextualmente relacionados (TF-IDF + bonus capítulo)."""
        self._require_loaded()
        if not words or not words.strip():
            raise APIError("words vacío")
        qs = _norm(words)
        if not qs:
            raise APIError(
                "Sin palabras significativas tras eliminar stopwords"
            )
        slug = self._validate_book(libro) if libro else None

        self._ensure_df()
        n_docs = max(1, len(self._verses or []))
        idf = {w: (1.0 + (n_docs / (1 + self._df.get(w, 0)))) for w in qs}

        index: dict[str, dict[tuple[str, int], int]] = {w: {} for w in qs}
        for v in self._verses or []:
            if slug and v["slug"] != slug:
                continue
            tokens = v["norm"]
            cnts = {w: tokens.count(w) for w in qs if w in tokens}
            if not cnts:
                continue
            for w, c in cnts.items():
                index[w][(v["slug"], v["capitulo"])] = (
                    index[w].get((v["slug"], v["capitulo"]), 0) + c
                )

        scored: list[tuple[float, dict]] = []
        for v in self._verses or []:
            if slug and v["slug"] != slug:
                continue
            tokens = v["norm"]
            s = 0.0
            for w in qs:
                c = tokens.count(w)
                if c:
                    s += idf[w] * c
                else:
                    neigh = 0
                    for delta in (-1, 1, -2, 2):
                        key = (v["slug"], v["capitulo"])
                        if index[w].get(key, 0) > 0:
                            neigh = max(neigh, 1)
                    if neigh:
                        s += 0.15 * idf[w]
            if s <= 0:
                continue
            scored.append((s, {
                "libro": v["libro"],
                "libro_slug": v["slug"],
                "abreviacion": v["abreviacion"],
                "capitulo": v["capitulo"],
                "versiculo": v["versiculo"],
                "referencia": f"{v['abreviacion']} {v['capitulo']}:{v['versiculo']}",
                "texto": v["texto"],
                "sumario": v["sumario"],
                "url": v["url"],
                "score": round(s, 3),
            }))

        scored.sort(key=lambda x: (-x[0], x[1]["libro_slug"], x[1]["capitulo"]))
        return [item for _, item in scored[:limit]]

    def reload(self) -> int:
        """Fuerza recarga: invalida memoria y archivos en caché."""
        return self.load(force=True)


# ---------------------------------------------------------------------------
# CLI mini para inspección desde shell
# ---------------------------------------------------------------------------
def _cli():
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--list-books", action="store_true")
    p.add_argument("--one-per-book", action="store_true")
    p.add_argument("--show", action="store_true")
    p.add_argument("--search", type=str, default=None)
    p.add_argument("--related", type=str, default=None)
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--libro", type=str, default=None)
    args = p.parse_args()

    api = get_api()
    if args.list_books:
        print(json.dumps(api.list_books(), ensure_ascii=False, indent=2))
    if args.one_per_book:
        for v in api.one_per_book():
            print(f"\n=== {v['referencia']} ===\n{v['texto']}")
    if args.show:
        for slug in api._book_order:
            m = api.book(slug)
            if m:
                print(f"  {m['nombre']:<22} {m['capitulos']} capítulos")
    if args.search:
        print(json.dumps(
            api.search(args.search, limit=args.limit, libro=args.libro),
            ensure_ascii=False, indent=2,
        ))
    if args.related:
        print(json.dumps(
            api.related(args.related, limit=args.limit, libro=args.libro),
            ensure_ascii=False, indent=2,
        ))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    _cli()
