"""
libromormon — Libro de Mormón en español (cliente de datos).

Lee el texto del Libro de Mormón desde el repo público
``elcarloss/libromormon-data`` (no hace scraping en línea).

    from libromormon.api import BoMAPI
    api = BoMAPI()
    api.load()
    api.chapter("alma", 32)
"""

__version__ = "1.1.0"
