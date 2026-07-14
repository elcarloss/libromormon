# Libro de Mormón — aplicación (Flask)

App Flask (REST API + UI web) sobre el Libro de Mormón en español. **No** raspa
el sitio oficial: lee un dataset estable desde el repo público gemelo
[`elcarloss/libromormon-data`](https://github.com/elcarloss/libromormon-data).

Texto sagrado © Intellectual Reserve, Inc. — uso no comercial con atribución.
Ver [LICENSE](LICENSE).

## Arquitectura

```
┌──────────────────────┐   raw.githubusercontent.com   ┌────────────────────────────┐
│  libromormon (este)  │ ◀───────────────────────────▶ │ libromormon-data           │
│  Flask + REST + UI   │   descarga y caché local     │ 15 libros, 239 capítulos,  │
│                      │                              │ 6604 versículos en JSON     │
└──────────────────────┘                              └────────────────────────────┘
        ▲
        │ usuario
        ▼
   http://localhost:5060/
```

Los datos se sirven desde **GitHub, no del sitio oficial**. Esto significa:

- ✅ Cero scraping → cero riesgo de ruptura si la Iglesia cambia el HTML.
- ✅ Funciona offline si ya tienes la caché local caliente.
- ✅ Versionable: cada cambio en el dataset es un commit en `libromormon-data`.
- ✅ Forks: quien quiera su propio dataset lo bifurca y cambia `BOM_GITHUB_*`.

## Estructura

```
.
├── README.md
├── LICENSE
├── requirements.txt
├── app.py                     ← Flask: UI + endpoints REST
├── libromormon/
│   ├── __init__.py
│   ├── api.py                 ← BoMAPI: list_books, chapter, verse, search, related…
│   └── sources.py             ← Descarga desde GitHub + caché local
├── templates/
│   └── index.html             ← UI oscura con búsqueda contextual
└── scripts/
    ├── scrape_clean.py        ← Regenerador del dataset (cuando cambia el sitio oficial)
    └── pull_data.py           ← Refresca la caché local desde GitHub
```

## Instalación

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Ejecución

```bash
python3 app.py                       # http://0.0.0.0:5060
python3 app.py --port 8090 --debug   # otro puerto + auto-reload
```

En el primer arranque se descargan `books.json`, `verses.jsonl` y
`summary.json` (~5 MB total) a `~/.cache/libromormon-data/`. Los
`by-chapter/<slug>-<NNN>.json` y `by-book/<slug>.json` se descargan
**bajo demanda** al consultarlos.

### Variables de entorno

| Variable            | Por defecto                    | Uso                                  |
|---------------------|--------------------------------|--------------------------------------|
| `BOM_GITHUB_OWNER`  | `elcarloss`                    | dueño del repo de datos              |
| `BOM_GITHUB_REPO`   | `libromormon-data`             | nombre del repo de datos             |
| `BOM_GITHUB_BRANCH` | `main`                         | rama/branch a leer                   |
| `BOM_CACHE_DIR`     | `~/.cache/libromormon-data`    | carpeta local para archivos en caché |

Para apuntar a un fork o mirror propio:

```bash
BOM_GITHUB_OWNER=mi-org BOM_GITHUB_REPO=bom-fork python3 app.py
```

## API

| Método | Ruta                          | Descripción                                     |
|--------|-------------------------------|--------------------------------------------------|
| GET    | `/`                            | UI web                                          |
| GET    | `/api/health`                  | estado, conteos, dataset summary                |
| GET    | `/api/books`                   | 15 libros + nº cap y vs                         |
| GET    | `/api/book/<slug>`             | metadatos del libro + lista de capítulos        |
| GET    | `/api/chapter/<slug>/<n>`      | versículos del capítulo                         |
| GET    | `/api/verse/<slug>/<n>/<v>`    | versículo individual                            |
| GET    | `/api/one_per_book[?seed=N]`   | 15 versículos aleatorios, uno por libro         |
| GET    | `/api/search?q=…[&limit=&libro=]`   | AND estricto (todas las palabras)         |
| GET    | `/api/related?words=…[&limit=&libro=]`| ranking TF-IDF + bonus capítulo           |
| POST   | `/api/reload`                  | fuerza recarga de la caché                      |

Ejemplos:

```bash
curl -s 'http://localhost:5060/api/health' | jq
curl -s 'http://localhost:5060/api/book/alma' | jq '.capitulos, .lista | length'
curl -s 'http://localhost:5060/api/verse/alma/32/21' | jq
curl -s 'http://localhost:5060/api/search?q=fe%20esperanza&limit=5' | jq
curl -s 'http://localhost:5060/api/related?words=caridad%20fe%20esperanza&limit=5' | jq
```

## Búsqueda

- **AND** (`/api/search`): cada versículo contiene TODAS las palabras
  (tras quitar stopwords en español).
- **Ranking** (`/api/related`): TF-IDF + bonus pequeño si la(s) palabra(s)
  aparecen en versículos vecinos del mismo capítulo. Mejor para consultas
  de una o dos palabras.

## Scripts utilitarios

### Refrescar caché local

```bash
python3 scripts/pull_data.py --prefetch-by-book --force
```

### Regenerar el dataset (cuando cambia el sitio oficial)

```bash
python3 scripts/scrape_clean.py --force
# Empuja el resultado al repo de datos:
cd ../libromormon-data && cp -r /tmp/opencode/staging/libromormon-data/. .
git add -A && git commit -m "Snapshot $(date -I)" && git push
```

## Licencia

- Código: MIT — ver [LICENSE](LICENSE).
- Texto del Libro de Mormón: © Intellectual Reserve, Inc. — uso no comercial
  con atribución. Se descarga desde el repo de datos en cada arranque.
