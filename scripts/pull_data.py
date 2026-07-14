"""
Refresca la caché local del dataset desde GitHub.

Uso:
    python3 scripts/pull_data.py
    python3 scripts/pull_data.py --prefetch-by-book   # descarga by-book/* también
"""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from libromormon import sources
from libromormon.api import get_api, BoMAPI


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--force", action="store_true", help="ignorar TTL de 30 días")
    p.add_argument(
        "--prefetch-by-book",
        action="store_true",
        help="además descarga by-book/<slug>.json para todos los libros",
    )
    args = p.parse_args()

    info = sources.info()
    print(f"Repo:   {info['github_owner']}/{info['github_repo']}@{info['github_branch']}")
    print(f"Caché:  {info['cache_dir']}")
    print()

    print("→ Cargando books.json + verses.jsonl …")
    api = BoMAPI()
    api.load(force=args.force)
    n = len(api._verses)
    summary = api._summary
    print(f"  versículos en índice: {n}")
    if summary.get("generado_en"):
        print(f"  dataset generado_en: {summary['generado_en']}")
    if summary.get("parser_version"):
        print(f"  parser_version:      {summary['parser_version']}")
    print()

    if args.prefetch_by_book:
        print("→ Prefetch by-book/*.json …")
        for slug in api._book_order:
            sources.fetch(f"by-book/{slug}.json", ttl_days=30, force=args.force)
        print(f"  {len(api._book_order)} índices descargados.")
    else:
        print("  (los by-book/*.json y by-chapter/*.json se descargan bajo demanda)")
    print()
    print("OK.")


if __name__ == "__main__":
    main()
