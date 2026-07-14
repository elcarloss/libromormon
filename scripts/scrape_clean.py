"""
Scrape único y limpio del Libro de Mormón (oficial, español) usando el parser de
api.py tras el fix. Escribe los artefactos listos para subir a GitHub:

  staging/libromormon-data/
    README.md
    LICENSE
    books.json
    verses.jsonl
    summary.json
    by-chapter/
      1-ne-001.json
      1-ne-002.json
      ...
    by-book/
      1-ne.json     # índice de capítulos (metadatos)

Uso:
    python3 scrape_clean.py
"""
import json
import logging
import re
import sys
import time
from html import unescape
from pathlib import Path

sys.path.insert(0, "/home/calarcon/Proyectos")
from libromormon.api import (
    BoMAPI, BOOK_ORDER, NOMBRES, ABREV, BASE, _http, _parse_chapter, _norm,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("scrape")

OUT = Path("/libromormon-data")
STAGE_CACHE = OUT / "_cache"  # caché temporal para no re-descargar si se aborta
OUT_BOOK_DIR = OUT / "by-chapter"
OUT_BOOK_IDX = OUT / "by-book"


def download_all(force: bool = False) -> dict:
    """Descarga los 15 libros (capítulo a capítulo). Devuelve libros_meta."""
    OUT_BOOK_DIR.mkdir(parents=True, exist_ok=True)
    STAGE_CACHE.mkdir(parents=True, exist_ok=True)

    # 1) descubrir (books.json) usando BoMAPI para mantener la lógica central
    api = BoMAPI()  # sin singleton global; instancia limpia
    log.info("Descubriendo libros…")
    libros = api._discover_books(force=force) if hasattr(api, "_discover_books") else None
    if libros is None:
        # usar el módulo-level helper
        from libromormon.api import _discover_books
        libros = _discover_books(force=force)
    log.info("Libros: %d", len(libros))

    # 2) capítulo a capítulo
    for slug in BOOK_ORDER:
        meta = libros.get(slug)
        if not meta:
            log.warning("Falta slug %s", slug)
            continue
        nombre = meta["nombre"]
        total = meta["capitulos"]
        for chap in range(1, total + 1):
            out_path = OUT_BOOK_DIR / f"{slug}-{chap:03d}.json"
            if out_path.exists() and not force:
                continue
            url = f"{BASE}/study/scriptures/bofm/{slug}/{chap}?lang=spa"
            try:
                html = _http(url)
            except Exception as e:
                log.warning("HTTP error %s: %s", url, e)
                continue
            data = _parse_chapter(html, slug, chap)
            if not data:
                log.warning("Sin datos para %s cap %d", slug, chap)
                continue
            out_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            time.sleep(0.25)
        log.info("OK %s — %d capítulos", nombre, total)
    return libros


def build_artifacts(libros: dict):
    """Genera verses.jsonl, by-book/*.json, books.json, summary.json."""
    # 1) books.json (canónico)
    books_index = []
    for slug in BOOK_ORDER:
        m = libros.get(slug)
        if not m:
            continue
        books_index.append({
            "slug": slug,
            "nombre": m["nombre"],
            "abreviacion": m["abreviacion"],
            "orden": BOOK_ORDER.index(slug) + 1,
            "capitulos": m["capitulos"],
        })
    (OUT / "books.json").write_text(
        json.dumps(books_index, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 2) verses.jsonl  +  by-book/<slug>.json (índice de capítulos)
    verses_fp = (OUT / "verses.jsonl").open("w", encoding="utf-8")
    by_book: dict[str, dict] = {b["slug"]: {
        "slug": b["slug"],
        "nombre": b["nombre"],
        "abreviacion": b["abreviacion"],
        "orden": b["orden"],
        "capitulos": b["capitulos"],
        "versiculos": 0,
        "capitulos_meta": [],
    } for b in books_index}

    total = 0
    leaks = 0
    for slug in BOOK_ORDER:
        if slug not in by_book:
            continue
        meta = libros[slug]
        for chap in range(1, meta["capitulos"] + 1):
            path = OUT_BOOK_DIR / f"{slug}-{chap:03d}.json"
            if not path.exists():
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
            chap_doc = {
                "libro": data["libro"],
                "libro_slug": slug,
                "capitulo": chap,
                "titulo": data.get("titulo", f"{meta['nombre']} {chap}"),
                "sumario": data.get("sumario", ""),
                "url": data["url"],
                "versiculos": len(data["versiculos"]),
            }
            by_book[slug]["capitulos_meta"].append(chap_doc)
            for v in data["versiculos"]:
                # Detección de fuga: texto empieza por el número + espacio
                if v["texto"].startswith(f"{v['numero']} "):
                    leaks += 1
                verses_fp.write(json.dumps({
                    "libro": data["libro"],
                    "libro_slug": slug,
                    "abreviacion": meta["abreviacion"],
                    "capitulo": chap,
                    "versiculo": v["numero"],
                    "texto": v["texto"],
                    "referencia": f"{meta['abreviacion']} {chap}:{v['numero']}",
                    "url": f"{BASE}/study/scriptures/bofm/{slug}/{chap}.{v['numero']}?lang=spa",
                    "sumario": data.get("sumario", ""),
                }, ensure_ascii=False) + "\n")
                by_book[slug]["versiculos"] += 1
                total += 1
    verses_fp.close()

    if leaks:
        log.warning("Posibles fugas del número en texto: %d versículos", leaks)
    else:
        log.info("Sin fugas del número (versículos %d)", total)

    # 3) by-book/<slug>.json
    OUT_BOOK_IDX.mkdir(parents=True, exist_ok=True)
    for slug, idx in by_book.items():
        # quita cap internos del cache para mantener el repo ligero
        (OUT_BOOK_IDX / f"{slug}.json").write_text(
            json.dumps(idx, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # 4) summary.json
    summary = {
        "libros": len(books_index),
        "capitulos": sum(b["capitulos"] for b in books_index),
        "versiculos": total,
        "fuente": f"{BASE}/study/scriptures/bofm?lang=spa",
        "generado_en": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "parser_version": "libromormon-api 1.1",
        "nota": "Datos scrapeados puntualmente del sitio oficial en español. "
                "Sirven como snapshot estable; si la Iglesia modifica el HTML, "
                "ejecutar libromormon.api._discover_books + _fetch_chapter para regenerar.",
    }
    (OUT / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    log.info("Summary: %s", summary)


if __name__ == "__main__":
    force = "--force" in sys.argv
    log.info("Directorio destino: %s", OUT)
    libros = download_all(force=force)
    build_artifacts(libros)
    log.info("Fin.")
