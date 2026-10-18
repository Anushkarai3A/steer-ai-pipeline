# steer. Research Studio

Research papers in → evidence-linked Instagram content out, with a **mandatory doctor approval
gate** between generated drafts and publishing.

```
PDF sources → extraction → synthesis → claims → located evidence
           → content drafts (carousel / static / reel / PowerPoint deck) → deterministic validation
           → doctor review (bound to the exact version) → publishing queue → manual confirm
```

Runs fully offline by default: **deterministic, clearly-labeled demo generation**
(`LLM_PROVIDER=none`). Optional OpenAI-compatible LLM support via environment variables —
there is no hardcoded provider, no API key in the repo, and the UI shows which mode is active.

## Quickstart (development)

Backend (Python 3.10+, SQLite by default — no other services needed):

```powershell
cd backend
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8000
# health: http://127.0.0.1:8000/api/health
# interactive API docs: http://127.0.0.1:8000/api/docs
```

Frontend (Node 20+):

```powershell
cd frontend
npm install
npm run dev
# http://localhost:5173  (proxies /api to :8000)
```

**Demo accounts** (seeded on first boot, password `demo1234`):
`editor@steer.demo`, `doctor@steer.demo`, `admin@steer.demo`.

Fastest path through the product:

1. Sign in as **editor** → *Research* → **load sample project** (uses the 3 real CC-BY papers in
   `samples/`) → **run pipeline**.
2. Open the project → *Evidence* (claims + located passages + safety-checks tab) → *Content* →
   **submit** each format.
3. Open the project → *PowerPoint studio* → **generate powerpoint deck** (native, editable
   .pptx — not a screenshot) → review/edit/regenerate a slide → **submit for doctor review**.
4. Sign in as **doctor** → *Doctor review* → inspect preview + validation → **approve the version**.
5. *Publishing* → **prepare** → export the bundle → **confirm published** (manual step by design).
6. *Export center* → download the evidence report, source manifest or captions for any deliverable.

## Tests

```powershell
cd backend
python -m pytest tests -q --timeout=600     # 67 tests: unit + full-workflow integration
```

```powershell
cd frontend
npm run build                               # tsc --noEmit + vite build
```

## Configuration

Copy `.env.example` to `.env` (read from the repo root or `backend/`). Notable settings:

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `sqlite:///…/backend/steer.db` | Dev default; Postgres for production |
| `SECRET_KEY` | dev placeholder | Token signing — change in any deployment |
| `LLM_PROVIDER` | `none` | `none` = deterministic labeled demo, `openai` = any compatible endpoint |
| `LLM_API_KEY` / `LLM_MODEL` / `LLM_BASE_URL` | empty | Used only when a provider is configured |
| `UPLOAD_DIR` / `GENERATED_DIR` | `data/uploads`, `data/generated` | PDFs and generated assets |

Migrations (Alembic): `alembic upgrade head` (target URL comes from `DATABASE_URL`). The app also
runs `create_all` on boot, so an existing database should be stamped once:
`alembic stamp head`. Details: [docs/runbook.md](docs/runbook.md).

## Docker (production-shaped)

```powershell
docker compose up --build
# frontend http://localhost:3000 (nginx, proxies /api) · API http://localhost:8000 · Postgres
```

> Docker was not available in the build environment, so the images/compose file are provided but
> **not build-verified** — the local dev path above is the verified one.

## What the acceptance rules map to

| Rule | Enforced in |
|---|---|
| Every claim keeps its located passage | `services/evidence/*`, `workers/stages.py` (evidence stage), UI Evidence lab |
| Doctor approval required before publishing | `services/review/workflow.py` (`decide`, `publishing_eligibility`), `routes/publishing.py` |
| Approval is bound to the exact version | `ReviewIn.version_id` → 409 on stale version; edits clear approval |
| Honest errors (no fake success) | `core/errors.py`, stage failures surfaced on dashboard, frontend `ApiError` |
| Role checks are server-side | `api/deps.require_roles` (verified: editor decision → 403) |
| No fake AI / no hardcoded provider | `core/config.py` settings, deterministic mode labeled in UI payloads |
| No committed secrets | `.gitignore` (`.env`, `*.db`), `.env.example` contains placeholders only |
| Deterministic validation ≠ clinical fact-check | `services/validation/validate.py` + explicit disclaimers in UI |

## Repository layout

```
backend/    FastAPI app, SQLAlchemy models, pipeline stages, services, tests, Alembic
frontend/   React + TypeScript + Vite + Tailwind (SPA)
pipeline/   versioned prompts, JSON schemas, render templates
samples/    3 real open-attribution papers + ATTRIBUTION.json
scripts/    sample-source fetch, schema export
docs/       architecture, API index, runbook
data/       uploads + generated assets (git-ignored contents)
```

More detail: [docs/architecture.md](docs/architecture.md) · [docs/api.md](docs/api.md) ·
[docs/runbook.md](docs/runbook.md) · [AGENTS.md](AGENTS.md) · [DECISIONS.md](DECISIONS.md)
