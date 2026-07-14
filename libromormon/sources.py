"""
Capa de orígenes de datos — descarga del repo público
``elcarloss/libromormon-data`` y caché local.

Sin scraping: si el repo de datos está caído o el usuario está sin red,
se sirve desde el caché local de 30 días.
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

log = logging.getLogger("libromormon.sources")

# ---------------------------------------------------------------------------
# Configuración:_repo de datos en GitHub_
# ---------------------------------------------------------------------------
GITHUB_OWNER = os.environ.get("BOM_GITHUB_OWNER", "elcarloss")
GITHUB_REPO = os.environ.get("BOM_GITHUB_REPO", "libromormon-data")
GITHUB_BRANCH = os.environ.get("BOM_GITHUB_BRANCH", "main")

RAW_BASE = f"https://raw.githubusercontent.com/{GITHUB_OWNER}/{GITHUB_REPO}/{GITHUB_BRANCH}"
# URL canónica al sitio oficial (no scraping, sólo para enlaces "ver original")
CHURCH_BASE = "https://www.churchofjesuschrist.org/study/scriptures/bofm"
CHURCH_LANG = "spa"
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
# Timeout más generoso para el archivo grande (verses.jsonl ~5MB)
TIMEOUT_S = 60

# URL fijos de los 3 artefactos globales
BOOKS_URL = f"{RAW_BASE}/books.json"
VERSES_URL = f"{RAW_BASE}/verses.jsonl"
SUMMARY_URL = f"{RAW_BASE}/summary.json"


def chapter_url(slug: str, n: int) -> str:
    return f"{RAW_BASE}/by-chapter/{slug}-{n:03d}.json"


def book_url(slug: str) -> str:
    return f"{RAW_BASE}/by-book/{slug}.json"


# ---------------------------------------------------------------------------
# Caché local: replica la estructura del repo
# ---------------------------------------------------------------------------
def cache_dir() -> Path:
    base = Path(os.environ.get("BOM_CACHE_DIR", Path.home() / ".cache" / "libromormon-data"))
    base.mkdir(parents=True, exist_ok=True)
    return base


def _local_path(remote_key: str) -> Path:
    """Devuelve la ruta local espejada de ``remote_key`` (e.g. 'books.json',
    'by-chapter/alma-032.json')."""
    return cache_dir() / remote_key


def _http(url: str) -> bytes:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": UA, "Accept": "*/*;q=0.9"},
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
        return r.read()


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------
def is_fresh(path: Path, ttl_days: int) -> bool:
    if not path.exists():
        return False
    age = time.time() - path.stat().st_mtime
    return age < ttl_days * 86400


def fetch(remote_key: str, ttl_days: int = 30, force: bool = False) -> Path:
    """Garantiza que ``remote_key`` (p. ej. 'books.json',
    'by-chapter/alma-032.json') esté disponible localmente.
    Devuelve la ruta del fichero (recién descargado o ya en caché)."""
    local = _local_path(remote_key)
    if not force and is_fresh(local, ttl_days):
        return local
    url = f"{RAW_BASE}/{remote_key}"
    local.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = _http(url)
        local.write_bytes(data)
        log.info("Descargado %s (%d B)", remote_key, len(data))
        return local
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
        if local.exists():
            log.warning(
                "No se pudo descargar %s (%s); usando versión en caché %s",
                remote_key, e, local,
            )
            return local
        raise


def load_json(remote_key: str, ttl_days: int = 30, force: bool = False):
    """Descarga/lee un JSON."""
    return json.loads(fetch(remote_key, ttl_days, force).read_text(encoding="utf-8"))


def stream_jsonl(remote_key: str, ttl_days: int = 30, force: bool = False):
    """Itera un JSONL línea por línea (no carga todo en memoria de golpe)."""
    p = fetch(remote_key, ttl_days, force)
    with p.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def dataset_summary() -> dict:
    """Resumen del dataset (libros, capítulos, versículos, fecha, parser)."""
    try:
        return load_json("summary.json", ttl_days=30)
    except Exception as e:
        log.warning("No se pudo cargar summary.json: %s", e)
        return {}


def info() -> dict:
    """Información de configuración (URLs, caché)."""
    return {
        "github_owner": GITHUB_OWNER,
        "github_repo": GITHUB_REPO,
        "github_branch": GITHUB_BRANCH,
        "raw_base": RAW_BASE,
        "cache_dir": str(cache_dir()),
    }


# ---------------------------------------------------------------------------
# Constructores de URL canónicas (al sitio oficial, no scraping)
# ---------------------------------------------------------------------------
def church_chapter_url(slug: str, n: int) -> str:
    return f"{CHURCH_BASE}/{slug}/{n}?lang={CHURCH_LANG}"


def church_verse_url(slug: str, chap: int, vs: int) -> str:
    return f"{CHURCH_BASE}/{slug}/{chap}.{vs}?lang={CHURCH_LANG}"


def church_book_url(slug: str) -> str:
    return f"{CHURCH_BASE}/{slug}?lang={CHURCH_LANG}"
