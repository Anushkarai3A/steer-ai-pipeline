# Runbook

## Local development (verified path)

```powershell
# terminal 1 — API (SQLite by default, no other services)
cd backend
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8000

# terminal 2 — SPA (proxies /api to :8000)
cd frontend
npm install
npm run dev          # http://localhost:5173
```

Smoke checks:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
# → status ok · database sqlite · ai_enabled false
```

1. Sign in (`editor@steer.demo` / `demo1234`).
2. Research → **load sample project** → **run pipeline** (~10–30 s deterministic).
3. Project → Evidence tab shows claims with located passages; Content tab shows three drafts.
4. Submit drafts → sign in as doctor → approve → Publishing → prepare → confirm.

## Environment

Settings load from process env first, then `.env` at the repo root or `backend/`
(`app/core/config.py`). Copy `.env.example` → `.env`.

| Variable | Notes |
|---|---|
| `DATABASE_URL` | default `sqlite:///backend/steer.db`; Postgres: `postgresql+psycopg://user:pass@host:5432/db` |
| `SECRET_KEY` | **must** be changed for any shared deployment (signs auth tokens) |
| `LLM_PROVIDER` | `none` (default, deterministic+labeled) or `openai` (any OpenAI-compatible endpoint) |
| `LLM_API_KEY`, `LLM_MODEL`, `LLM_BASE_URL` | only consulted when a provider is set |
| `UPLOAD_DIR`, `GENERATED_DIR` | PDF storage and generated assets |
| `CORS_ORIGINS` | comma-separated; default the Vite dev origins |
| `DEMO_*_EMAIL/_PASSWORD` | override the seeded demo accounts |

## Database & migrations

```powershell
cd backend
alembic upgrade head                 # create/update all 15 tables (uses DATABASE_URL)
alembic current                      # check revision
# If tables already exist (e.g. created by an older build via create_all):
alembic stamp head
```

- Dev/tests: the app runs `create_all()` on boot, so migrations are optional locally.
- Prod: run `alembic upgrade head` before starting the API (the provided Docker CMD does this).
- SQLite file: `backend/steer.db` (git-ignored). Back up by copying the file while the API is off.

## Tests

```powershell
cd backend
python -m pytest tests -q --timeout=600        # 42 tests, ~5 min

cd frontend
npm run build                                  # tsc --noEmit + vite build
```

Schema export (after changing `schemas/`):

```powershell
python scripts/export_schemas.py               # → pipeline/schemas/*.schema.json
```

## Docker (production-shaped, **not build-verified here**)

```powershell
docker compose up --build
# frontend http://localhost:3000 (nginx proxies /api → backend:8000)
# API      http://localhost:8000  (Postgres: db:5432, volume pgdata)
```

The backend image keeps the repo layout (`/app/{backend,pipeline,samples,data}`) because
`REPO_ROOT` is derived from `backend/app/core/config.py`. Demo users seed on first boot.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `Stage '…' failed: …` on dashboard | Read the message — it is actionable (e.g. scanned PDF, no summary). Fix inputs and hit **retry**. |
| Content stuck `needs_evidence_review` | Validation has errors tied to claims; open the claim ids shown, fix evidence/claim status (doctor), re-validate. |
| Approval rejected with 409 | The content changed after the reviewer loaded it — re-load and approve the current version. |
| Publish button blocked | `reasons[]` in the queue explain exactly what is missing (approval, version match, validation). |
| Vite can't reach the API | Start the backend on port 8000; the proxy targets `http://localhost:8000`. |
| Port 5173 refused on `127.0.0.1` | Vite 6 may bind `::1` — use `http://localhost:5173`. |
| `alembic` runs against the wrong DB | `DATABASE_URL` env always wins over `alembic.ini`. |
