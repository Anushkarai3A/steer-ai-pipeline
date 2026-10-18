# Architecture

```
┌──────────────┐   /api proxy    ┌───────────────────────────────┐   ┌────────────┐
│ React SPA    │ ──────────────► │ FastAPI (app/main.py)         │──►│ SQLite /   │
│ Vite + TS +  │   JWT-ish       │ routes → services → workers   │   │ Postgres   │
│ Tailwind     │   bearer token  └───────────────┬───────────────┘   └────────────┘
└──────────────┘                               │
                    ┌──────────────────────────┼──────────────────────────┐
                    ▼                          ▼                          ▼
             data/uploads                pipeline/prompts           data/generated
             (PDF sources)               pipeline/schemas           (renders, zips)
                                          pipeline/templates
```

## Backend

| Layer | Where | Responsibility |
|---|---|---|
| Routes | `backend/app/api/routes/*` | HTTP shape, auth deps, role gates, serialization |
| Services | `backend/app/services/*` | extraction, synthesis, claims+evidence, content generation, validation, rendering, review/publishing workflow |
| Workers | `backend/app/workers/{runner,stages}.py` | pipeline execution, stage state, honest failures, retries |
| Models | `backend/app/models/*` | SQLAlchemy ORM (15 tables) |
| Schemas | `backend/app/schemas/*` | Pydantic request/response DTOs (also exported to `pipeline/schemas/*.schema.json`) |

### Pipeline stages

Runs have a kind — `full`, `extraction`, `generation`, `rendering` — and each kind selects a
subset of the stage list (`workers/runner.py: STAGE_PLANS`).

| # | Stage | What it does | Failure/honesty behavior |
|---|---|---|---|
| 1 | `ingestion` | verifies stored PDFs, 1–3 sources | refuses empty projects, missing files |
| 2 | `extraction` | PyMuPDF text/page extraction, scanned-image heuristic | `ExtractionError` with actionable message (e.g. "no extractable text") |
| 3 | `metadata` | DOI/title/year from PDF; optional Crossref enrichment | never invents metadata; skips network calls on failure |
| 4 | `synthesis` | per-source findings buckets for the UI summary | deterministic in `none` mode |
| 5 | `claims` | claim candidates (`CLM-####`, globally unique) | deletes only this project's old claims before re-extract |
| 6 | `evidence` | verbatim excerpt location (exact → normalized → fuzzy) | claim without a passage stays `needs_human_review`/`unsupported` |
| 7 | `content` | carousel / static / reel payloads; deterministic templates or LLM | carries `generation_mode` + `generation_mode_label` on every version |
| 8 | `validation` | rule engine (see `services/validation/validate.py`) | issues have severity, rule id, location, claim id |
| 9 | `rendering` | PNG slides, static image, reel MP4 (imageio-ffmpeg) or storyboard fallback; **PowerPoint deck → native .pptx** (python-pptx, editable text boxes + tables) | honest fallback: storyboard is labeled as such; pptx failure falls back to storyboard-style rendering |
| 10 | `doctor_review` | **informational**: lists deliverables awaiting humans | always returns `status: "pending"` — the run succeeds, but the stage is never auto-completed |

Stage semantics (`workers/runner.py: execute_run`):

- a raised `StageError` → rollback of the stage's partial writes, remaining stages `skipped`,
  run `failed` with `Stage '<label>': <message>`.
- a returned `detail.status == "pending"` → stage stays `pending` while the run can still be
  `succeeded` (used by `doctor_review`).
- execution is an in-process `ThreadPoolExecutor(max_workers=2)` — no Redis required.
  `POST /api/pipeline/runs/{id}/retry` re-runs a failed plan (stages are idempotent).

### PowerPoint Studio (`services/rendering/pptx_builder.py`)

A 4th deliverable format, `deck`, reuses the full carousel/static/reel machinery (versioning,
validation, review, approval, publishing). It is generated on demand — not part of the default
`generate all formats` set — via `POST /api/projects/{id}/generate` with `{"formats":["deck"]}`.

- **Payload** (`schemas/content.py: DeckPayload`): `deck_title`, `subtitle`, and 10 ordered
  `slides` (`kind` ∈ title|background|methods|population|findings|quantitative|interpretation|
  limitations|takeaways|references), each with `bullets`, optional `table`, `claim_ids`,
  `source_notes`. Slide indexes must be sequential from 0.
- **Deterministic build** (`fallback.py: build_deck`): fills only real summary/claims data;
  missing sections read *"Not established in the provided sources."*; no usable evidence-linked
  claims → honest error, not an empty deck.
- **Render** (`pptx_builder.py: render_deck`): native 16:9 .pptx via python-pptx — real text
  boxes, bullets and tables (not a screenshot), design-system colors, claim-id footer, slide
  number, references slide. Exported as `kind="deck_pptx"` asset; also downloadable from the
  PowerPoint studio page.
- **Edit & regenerate**: full-JSON edit creates a new version (approval cleared);
  `regenerate-section?target=slide&index=N` rebuilds one slide from the current evidence.
- Validation adds a `deck_structure` rule (missing `deck_title`, fewer than 5 slides → warnings).

### Review & publishing workflow (`services/review/workflow.py`)

```
draft ──submit──► awaiting_review ──approve──► ready_to_publish ──confirm──► published
  ▲                    │                              │
  └──retract───────────┘        edits (apply_edit) ───┘  (new version → approval cleared
                                                          → back to awaiting_review, queue item removed)
```

- `decide()` requires `version_id`; a stale id (content edited after the reviewer loaded it)
  raises **409 Conflict**.
- `publishing_eligibility()` returns `(eligible, reasons)` — reasons are surfaced verbatim in
  the publishing UI (e.g. *"Approved version does not match current version"*).
- `confirm_published()` only records a human's external publication — the app never posts to
  social networks.

### Auth & roles

- Passwords: PBKDF2-HMAC-SHA256, 120k iterations (`core/security.py`).
- Sessions: HMAC-signed base64 token (`SECRET_KEY`), 12h TTL, sent as `Authorization: Bearer`.
- Roles `editor | doctor | admin` enforced with `api/deps.require_roles` — approvals and claim
  status changes are doctor/admin only (editor decision → HTTP 403).

## Frontend

- `src/lib/api.ts` — fetch wrapper, `ApiError` (status + field errors), asset downloads via
  blob fetch (auth header required).
- `src/state/auth.tsx` — token in `localStorage`, `/api/auth/me` refresh.
- Pages: Dashboard (real stats, failed-stage honesty list, pending-approvals card, claim-status
  counts), Projects, Project (tabs: overview/sources/pipeline/findings with run polling +
  workspace links to Evidence/Content/PowerPoint/Exports), Evidence lab (claims list + safety
  checks tab), Content studio (version history, per-section regeneration, deck preview),
  **PowerPoint studio** (slide navigator, native preview, edit/regenerate/export .pptx),
  **Export center** (evidence report, source manifest, captions, full bundle), **Settings**
  (runtime capabilities — never secrets), Doctor review (queue + version-bound decisions),
  Publishing queue.
- Status colors: single source of truth in `src/lib/format.ts` (`pillFor`, `claimPill`).

## Data model (15 tables)

`users`, `research_projects`, `research_sources`, `extracted_documents`, `research_findings`,
`evidence_claims`, `claim_evidence`, `content_deliverables`, `content_versions`,
`content_assets`, `reviews`, `review_comments`, `publishing_items`, `pipeline_runs`,
`pipeline_stage_runs`.

Key invariants:

- `content_deliverables.current_version_id` / `approved_version_id` — approval is a pointer to a
  **specific version row**, never "the deliverable".
- `claim_evidence` rows carry `locator_method` + `page` + excerpt → the Evidence lab shows the
  located passage for every claim.
- Dev note: sessions use `expire_on_commit=False`; code that adds related rows must
  `db.expire(obj, ["relation"])` so serializers see fresh collections.

## Honest-mode rules

1. Deterministic mode is the default; every generated version records
   `generation_mode`/`generation_mode_label` and shows it in the UI.
2. Validation output explicitly says it is a deterministic rules check, **not** a clinical
   fact-check.
3. Errors from stages/API surface verbatim (`core/errors.py`, `ApiError`, dashboard failed-stage
   list).
4. No secrets are required to run: `.env.example` placeholders only.
