# Development

## Requirements

- [uv](https://docs.astral.sh/uv/). It installs Python 3.12 for you; `scripts/setup.sh` can install uv itself into `./tools/`.
- A MongoDB Atlas cluster. The free tier works. Transactions need a replica set, so a standalone local `mongod` isn't enough.
- Git Bash or any POSIX shell for `scripts/setup.sh` (Windows, macOS and Linux all work).

Everything stays inside the repo: the virtual environment in `.venv/`, and uv's cache and Python builds in `tools/`.

## Setup

```bash
bash scripts/setup.sh        # uv, Python 3.12, .venv, dependencies, .env from .env.example
```

Then fill in `.env`:

| Variable | What it's for |
|---|---|
| `MONGODB_URI` | Atlas connection string (use a least-privilege database user) |
| `MONGODB_DB` | app database, `irminsul` by default |
| `MONGODB_TEST_DB` | separate database for tests, dropped after each run |
| `JWT_SECRET` | long random string for signing sessions |
| `SEED_DEMO_PASSWORD` | password for every demo account (8+ characters) |
| `DATA_GOV_IN_API_KEY` | optional; reserved for live data.gov.in mandi prices. That API was down when this was built, so the app uses the dated snapshot |
| `ENVIRONMENT` | `development` or `production` (Secure cookies + HSTS) |
| `PUBLIC_BASE_URL` | optional; the absolute URL used in QR codes |

## Everyday commands

```bash
uv run uvicorn backend.app.main:app --reload          # http://127.0.0.1:8000
uv run pytest -q                                      # full suite (talks to Atlas, a few minutes)
uv run ruff check . && uv run ruff format --check . && uv run pyright
uv run python -I scripts/seed.py                      # demo data, safe to re-run
```

Interactive API docs are at `/docs` while the server runs.

## Scripts

```
scripts/
  setup.sh                    one-time local setup
  seed.py                     demo data: runs the stages in scripts/demo/
  create_admin.py             create or promote an admin (prompts for the password)
  demo/
    accounts.py               base demo accounts, a farm and two cold stores
    story.py                  stage v1: the Hooghly story
    more.py                   stage v2: more farmers, crops, deals, bookings, an alert, a drill
  data/
    build_mandi_snapshot.py   build the dated mandi CSV from AGMARKNET Parquet (uv --group data)
    geocode_markets.py        place mandi markets on the map with Nominatim (run once, cached)
  model/
    export.py                 export the PlantVillage MobileNetV2 model to ONNX (uv --group export)
    upload.py                 store the exported model in GridFS and write the checksum lock file
    download.py               fetch and verify the model from GridFS (used by the Render build)
```

The seed only adds records, and they're all marked `is_demo`. Each stage is recorded in the `seed_runs` collection, so running it twice does nothing the second time. The data goes through the real service functions, so hash chains, capacities and order states are genuine.

### The screening model

The model files are not in git. On a fresh clone, either:

- export it yourself: `uv run --group export python -I scripts/model/export.py`, or
- fetch it from your own GridFS with `scripts/model/download.py`, once someone has uploaded it with `scripts/model/upload.py`.

Without the model, screening says it's unavailable. Everything else works.

## Conventions

- **No inline anything in HTML:** the Content Security Policy blocks inline scripts, styles and event handlers. Put styles in `frontend/css/` and set dynamic values through CSS custom properties from JavaScript.
- **Translations:** every visible string has a key in all three files in `frontend/locales/`. Add the English text first, then Bengali and Hindi.
- **Demo data:** anything simulated or made up carries `is_demo` or `source: "simulated"`, and the UI shows a badge for it. Real data is never mixed with invented data.
- **Units:** quantities are stored in kg and money in paise, both as integers.
- **Tests:** they live in `backend/tests/` and run against `MONGODB_TEST_DB`. Pure logic (the FreshTrack engine, net realisation, the hash chain) is tested without a database.
