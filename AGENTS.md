# AGENTS.md — working notes for AI/human contributors

## Commands

```powershell
# backend tests (must stay green; ~5 min)
cd backend; python -m pytest tests -q --timeout=600

# backend dev server
cd backend; python -m uvicorn app.main:app --reload --port 8000

# frontend typecheck + build (must stay green)
cd frontend; npm run build

# frontend dev server (proxies /api → :8000)
cd frontend; npm run dev
```

There is no lint step configured; `tsc --noEmit` (strict, `noUnusedLocals`) is the frontend gate.

## Ground rules

- **No fake AI.** Default mode is deterministic (`LLM_PROVIDER=none`); generated content must
  keep `generation_mode`/`generation_mode_label` visible in the UI. Never invent metadata,
  evidence, or "estimated" numbers.
- **Approval gate is sacred.** Publishing eligibility requires `approved_version_id ==
  current_version_id` on a validation-clean version; edits always clear approval. Do not add
  bypasses.
- **Role checks server-side only** (`api/deps.require_roles`). Hiding a button is UX, not
  security.
- **Honest errors.** Stage failures carry actionable messages; never swallow or replace them
  with generic success. Validation ≠ clinical fact-check — keep the disclaimers.
- **No secrets in the repo.** `.env` is ignored; `.env.example` holds placeholders only.
- Evidence excerpting must remain verbatim from the source text (exact → normalized → fuzzy
  fallback), with `locator_method` recorded.

## Codebase gotchas

- `SessionLocal` uses `expire_on_commit=False`: after inserting related rows via FK only, call
  `db.expire(obj, ["relation"])` or serializers will return stale collections (this bit us in
  stages/content/sample_project/workflow).
- Claim ids (`CLM-####`) are **global** primary keys — allocate with `_next_claim_index()` in
  `workers/stages.py`, never per-project counters.
- `from __future__ import annotations` + FastAPI 204 → use 200 `{ok:true}` for deletes.
- SQLite returns naive datetimes; compare with `_ms()` in `workers/runner.py`.
- PyMuPDF base-14 font alias is `fontname="tiro"` (not `"times"`).
- Frontend pages read the route param `projectId`; nav links live in
  `components/AppShell.tsx`.
- PowerShell: no heredocs; write temp scripts to files instead of `python -c` with escapes.

## Where things live

- Enforcing code for the product rules → `docs/architecture.md` (table "What the acceptance
  rules map to" in the README points at the same files).
- API surface → `docs/api.md`. Ops → `docs/runbook.md`. Trade-offs → `DECISIONS.md`.
- Sample data → `samples/` (CC-BY papers + `ATTRIBUTION.json`); demo loader
  `app/services/sample_project.py`.
