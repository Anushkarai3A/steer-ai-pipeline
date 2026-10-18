# DECISIONS — key technical trade-offs

Short, dated ADR-style notes for the hackathon build.

## 1. SQLite by default, Postgres in production
**Decision:** `DATABASE_URL` defaults to SQLite; docker-compose provides Postgres.
**Why:** the judging environment has no DB server; zero-setup runnability beat parity.
**Consequence:** dev runs `create_all` on boot; production uses Alembic (`alembic stamp head`
for pre-existing tables). Datetime/expire quirks documented in AGENTS.md.

## 2. In-process thread pool instead of Redis + RQ/Celery
**Decision:** `ThreadPoolExecutor(max_workers=2)` in `workers/runner.py`.
**Why:** no Redis in the environment; explicit stages are testable synchronously in tests.
**Consequence:** jobs die with the process (acceptable for demo scale); stage runs are
persisted so the UI shows real state; a production swap needs only `start_run_async`.

## 3. Deterministic demo generation is the default, LLM is opt-in
**Decision:** `LLM_PROVIDER=none` produces template-based content that is honestly labeled on
every version; any OpenAI-compatible endpoint can be configured via env.
**Why:** acceptance requires "no fake AI" and runnable-without-keys; also makes tests stable.
**Consequence:** UI shows "deterministic mode" chip and per-version generation labels;
`mode` is stored on each run/version.

## 4. Approval binds to a version id, not the deliverable
**Decision:** `reviews.version_id` is required; stale ids → 409; any edit creates a new
version, clears `approved_version_id`, returns the deliverable to `awaiting_review` and
removes its publishing-queue item.
**Why:** the core rule is "publish what the doctor actually saw".
**Consequence:** reviewers must re-approve after edits; `publishing_eligibility` returns
human-readable `reasons[]` shown verbatim in the UI.

## 5. Publishing is a manual, recorded step
**Decision:** export produces a zip bundle (assets + caption + evidence manifest + approval
metadata); "confirm published" records the human's external action (optional URL).
**Why:** no Instagram/Canva credentials exist, and auto-posting would violate the honesty
rules; a recorded confirmation still closes the loop.
**Consequence:** `PublishingItem.status` lifecycle queued → ready_to_publish → published;
published content is immutable until withdrawn.

## 6. Validation is a deterministic rules engine, not a fact-checker
**Decision:** rules (claim ids linked, evidence present, disclaimer present, forbidden
overclaim wording, numeric masking of ids/DOIs before scans…) emit `error|warning` issues with
rule id + location + claim id. Unlinked numbers are warnings; broken claim links are errors.
**Why:** auditable, testable, and it does not overstate what software can verify.
**Consequence:** UI and payload disclaimers state that doctor review is still mandatory.

## 7. Evidence located verbatim, ranked
**Decision:** excerpt lookup tries exact → whitespace/case-normalized → fuzzy (score
threshold), recording `locator_method`; claims without a passage cannot be marked supported
(server-enforced).
**Why:** traceability beats recall; fabricated "support" is the failure mode that matters.
**Consequence:** some extracted claims stay `needs_human_review` — shown honestly in UI.

## 8. Frontend is a hand-rolled SPA (React Router + fetch wrapper), no component library
**Decision:** Vite + TS + Tailwind 4 with a small in-repo UI kit (`components/ui.tsx`) and
palette tokens in `index.css`.
**Why:** full control over the design system (cream/rust/maroon "steer." identity) and minimal
dependency surface for offline installs.
**Consequence:** components are page-local; shared state is just `state/auth.tsx` + `lib/api.ts`.

## 9. Reels via bundled ffmpeg with storyboard fallback
**Decision:** render vertical MP4s with `imageio-ffmpeg`'s binary when available; otherwise
produce a labeled storyboard package.
**Why:** no system ffmpeg guaranteed; never ship a "video" that silently does not exist.
**Consequence:** fallback assets are clearly marked `storyboard` in the asset list.
