# API index

Base URL `/api` (dev: `http://127.0.0.1:8000`; Swagger UI: `/api/docs`).
All endpoints except `/health` and `/auth/login` require `Authorization: Bearer <token>`.

## Health & auth

| Method | Path | Notes |
|---|---|---|
| GET | `/health` | `status, version, ai_enabled, llm_provider, database` |
| POST | `/auth/login` | `{email, password}` → `{access_token}` |
| GET | `/auth/me` | current user |
| POST | `/auth/register` | self-registration (role defaults to editor) |

## Projects & sources

| Method | Path | Notes |
|---|---|---|
| GET/POST | `/projects` | list / create |
| POST | `/projects/sample` | loads the 3 CC-BY sample papers from `samples/` |
| GET/PATCH/DELETE | `/projects/{id}` | detail (sources+summary+findings) / rename / delete |
| POST | `/projects/{id}/sources` | multipart PDF upload (1–3 per project) |
| POST | `/projects/{id}/sources/reference` | add by DOI/URL |
| GET/DELETE | `/projects/{id}/sources/{sid}` | page-level extraction detail / remove |
| POST | `/projects/{id}/run` | start pipeline (`{}` = full run) → `202 {run}` |
| GET | `/projects/{id}/runs` | run history for the project |

## Pipeline

| Method | Path | Notes |
|---|---|---|
| GET | `/pipeline/runs` | all runs (dashboard) |
| GET | `/pipeline/runs/{run_id}` | run + stage rows (UI polls this) |
| POST | `/pipeline/runs/{run_id}/retry` | re-run a failed plan → `202` |

## Evidence

| Method | Path | Notes |
|---|---|---|
| GET | `/projects/{id}/claims` | claims with linked evidence |
| GET | `/claims/{claim_id}` | single claim |
| PATCH | `/claims/{claim_id}` | update `status`/`verification_notes` — **doctor/admin only** |
| GET | `/evidence/{evidence_id}/excerpt` | surrounding source text for a passage |
| POST | `/projects/{id}/revalidate` | re-run evidence verification |
| GET | `/projects/{id}/safety-checks` | deterministic per-claim rule checks (errors/warnings) |

## Content

| Method | Path | Notes |
|---|---|---|
| GET | `/projects/{id}/deliverables` | carousel/static/reel/deck summaries |
| POST | `/projects/{id}/generate` | `{formats:[…]}` → `202` generation run (needs a summary) |
| GET | `/deliverables/{id}` | detail: current version, validation, reviews, comments |
| POST | `/deliverables/{id}/edit` | structural schema check → new version, approval cleared |
| POST | `/deliverables/{id}/regenerate-all` / `regenerate-section` | new version from prompts |
| POST | `/deliverables/{id}/validate` | deterministic re-validation |
| POST | `/deliverables/{id}/submit` | draft → `awaiting_review` |
| POST | `/deliverables/{id}/retract` | awaiting → draft (editor) |
| POST | `/deliverables/{id}/export` | `{kind:"full"\|"evidence_report"\|"source_manifest"\|"captions"}` → asset download |

## Review

| Method | Path | Notes |
|---|---|---|
| GET | `/review/queue` | all deliverables awaiting a decision |
| GET | `/deliverables/{id}/reviews` | decision history |
| POST | `/deliverables/{id}/reviews` | `{decision, comments, version_id}` — **doctor/admin**, `201`; stale `version_id` → `409` |
| GET/POST | `/deliverables/{id}/comments` | any authenticated user can comment |

## Publishing

| Method | Path | Notes |
|---|---|---|
| GET | `/publishing?status=&format=` | queue rows incl. `eligible` + `reasons` |
| POST | `/publishing/{item_id}/prepare` | re-check eligibility → `409` with reasons if not ready |
| POST | `/publishing/{item_id}/confirm` | `{note, external_url}` — manual "I published it" record |

## Dashboard & assets

| Method | Path | Notes |
|---|---|---|
| GET | `/dashboard/stats` | counts, recent projects/activity, pipeline status, failed stage runs |
| GET | `/settings` | runtime config (AI mode, worker/rendering capabilities, limits) — never secrets |
| GET | `/assets/{id}` | authenticated asset download (zip/png/mp4/pdf/pptx) |
| GET | `/assets/{id}/inline` | inline disposition for previews |

## Error shape

```json
{ "detail": "human-readable message", "code": "machine_code", "errors": [{"field": "email", "message": "…"}] }
```

Validation failures from FastAPI are normalized to this shape with HTTP 422.
