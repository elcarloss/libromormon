"""
Web UI + REST API sobre las escrituras del Libro de Mormón en español.

Fuente de datos (NO scrapea el sitio oficial):
  https://github.com/elcarloss/libromormon-data
  raw: https://raw.githubusercontent.com/elcarloss/libromormon-data/main

Uso:
    python3 app.py                       # 0.0.0.0:5060
    python3 app.py --port 8090 --debug

Variables de entorno opcionales:
    BOM_GITHUB_OWNER   por defecto "elcarloss"
    BOM_GITHUB_REPO    por defecto "libromormon-data"
    BOM_GITHUB_BRANCH  por defecto "main"
    BOM_CACHE_DIR      por defecto ~/.cache/libromormon-data

Endpoints REST:
  GET  /
  GET  /api/health
  GET  /api/books
  GET  /api/book/<slug>
  GET  /api/chapter/<slug>/<chap>
  GET  /api/verse/<slug>/<chap>/<vs>
  GET  /api/one_per_book[?seed=N]
  GET  /api/search?q=…
  GET  /api/related?words=…
  POST /api/reload
"""
import argparse
import logging
import sys
from pathlib import Path

from flask import Flask, jsonify, render_template, request

from libromormon import sources
from libromormon.api import APIError, BoMAPI, get_api

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger("libromormon.web")

app = Flask(__name__)


# ---------- Helpers ----------
def _err(msg, code=400):
    return jsonify({"error": msg}), code


def _q(name, default=None):
    return request.args.get(name, default)


def _qi(name, default=None):
    v = request.args.get(name)
    if v is None or v == "":
        return default
    try:
        return int(v)
    except ValueError:
        raise APIError(f"{name} debe ser entero, recibí: {v!r}")


def _api(fn, *args, **kwargs):
    api = get_api()
    try:
        result = fn(api, *args, **kwargs)
        if isinstance(result, tuple) and len(result) == 2 and isinstance(result[1], int):
            body, status = result
            return jsonify(body), status
        return jsonify(result)
    except APIError as e:
        return _err(str(e), 400)


# ---------- UI ----------
@app.route("/")
def index():
    return render_template("index.html", dataset=sources.info())


# ---------- API ----------
@app.route("/api/health")
def api_health():
    return _api(BoMAPI.health)


@app.route("/api/books")
def api_books():
    return _api(BoMAPI.list_books)


@app.route("/api/book/<slug>")
def api_book(slug):
    def _call(api):
        b = api.book(slug)
        if not b:
            return ({"error": f"Libro {slug!r} no encontrado"}, 404)
        return b
    return _api(_call)


@app.route("/api/chapter/<slug>/<int:chap>")
def api_chapter(slug, chap):
    def _call(api):
        c = api.chapter(slug, chap)
        if not c:
            return ({"error": f"{slug} {chap} no encontrado"}, 404)
        return c
    return _api(_call)


@app.route("/api/verse/<slug>/<int:chap>/<int:vs>")
def api_verse(slug, chap, vs):
    def _call(api):
        v = api.verse(slug, chap, vs)
        if not v:
            return ({"error": f"{slug} {chap}:{vs} no encontrado"}, 404)
        return v
    return _api(_call)


@app.route("/api/one_per_book")
def api_one_per_book():
    seed = _qi("seed")
    return _api(BoMAPI.one_per_book, seed)


@app.route("/api/search")
def api_search():
    q = _q("q", "")
    limit = _qi("limit", 30)
    libro = _q("libro")
    return _api(BoMAPI.search, q, limit=limit, libro=libro)


@app.route("/api/related")
def api_related():
    words = _q("words", "")
    limit = _qi("limit", 20)
    libro = _q("libro")
    return _api(BoMAPI.related, words, limit=limit, libro=libro)


@app.route("/api/reload", methods=["POST"])
def api_reload():
    n = get_api().reload()
    return jsonify({"ok": True, "versiculos": n})


# ---------- Errores ----------
@app.errorhandler(APIError)
def _api_err(e):
    return jsonify({"error": str(e)}), 400


@app.errorhandler(404)
def _404(_):
    return jsonify({"error": "endpoint no encontrado"}), 404


@app.errorhandler(500)
def _500(e):
    log.exception("Error interno")
    return jsonify({"error": "error interno del servidor"}), 500


# ---------- Main ----------
def main():
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=5060)
    p.add_argument("--debug", action="store_true")
    args = p.parse_args()

    info = sources.info()
    log.info(
        "Cargando dataset desde %s (caché: %s)",
        info["raw_base"], info["cache_dir"],
    )
    get_api().load()
    n_total = len(get_api()._verses or [])
    print(f"\n  Libro de Mormón MX — http://{args.host}:{args.port}/")
    print(f"  {n_total} versículos indexados")
    print(f"  Datos: {info['raw_base']}\n")
    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
