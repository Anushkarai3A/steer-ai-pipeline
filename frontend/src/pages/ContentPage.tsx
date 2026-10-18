import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, downloadAsset } from "../lib/api";
import type {
  CarouselPayload,
  DeckPayload,
  DeckSlide,
  Deliverable,
  DeliverableDetail,
  PipelineRun,
  ReelPayload,
  StaticPayload,
  ValidationReport,
} from "../lib/types";
import { fmtDate, fmtBytes } from "../lib/format";
import { Card, EmptyState, ErrorNote, Spinner, StatusPill } from "../components/ui";
import { useAuth } from "../state/auth";

const FORMAT_TITLES: Record<string, string> = {
  carousel: "Carousel (IG swipe)",
  static: "Static post",
  reel: "Reel (storyboard + MP4)",
  deck: "PowerPoint deck",
};

export default function ContentPage() {
  const { projectId = "" } = useParams();
  const { user } = useAuth();
  const isDoctor = user?.role === "doctor" || user?.role === "admin";

  const [deliverables, setDeliverables] = useState<Deliverable[] | null>(null);
  const [detail, setDetail] = useState<DeliverableDetail | null>(null);
  // Single source of truth for which deliverable/format the user selected. It
  // is kept separate from `detail` so that loading, polling, or regeneration
  // clearing the preview can never drag the selection back to the first item
  // (Carousel).
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [run, setRun] = useState<PipelineRun | null>(null);
  const [editJson, setEditJson] = useState<string | null>(null);
  const [comment, setComment] = useState("");
  const timer = useRef<number | null>(null);
  // Mirrors the latest selection synchronously so an out-of-order detail
  // response can be discarded instead of replacing a newer format's preview.
  const selectedIdRef = useRef<string | null>(null);

  const loadList = useCallback(() => {
    api
      .get<Deliverable[]>(`/api/projects/${projectId}/deliverables`)
      .then(setDeliverables)
      .catch(setError);
  }, [projectId]);

  const loadDetail = useCallback((id: string) => {
    api
      .get<DeliverableDetail>(`/api/deliverables/${id}`)
      .then((d) => {
        if (selectedIdRef.current === id) setDetail(d);
      })
      .catch(setError);
  }, []);

  // The only place the selection changes when the user clicks a format card.
  // Recording `selectedId` here keeps the choice stable across every rerender.
  const selectDeliverable = useCallback(
    (id: string) => {
      selectedIdRef.current = id;
      setSelectedId(id);
      setDetail(null);
      setEditJson(null);
      loadDetail(id);
    },
    [loadDetail],
  );

  // Switching projects is a deliberate reset: the new project starts at its own
  // first deliverable instead of keeping a stale id from the previous project.
  useEffect(() => {
    selectedIdRef.current = null;
    setSelectedId(null);
    setDetail(null);
    setEditJson(null);
  }, [projectId]);

  useEffect(loadList, [loadList]);

  // Auto-select the FIRST deliverable only while the user has made no choice.
  // Keyed on `selectedId` (never on `detail`), so clearing the preview during a
  // load cannot re-trigger selection. Gated on the list belonging to the
  // current project so a stale list from another project is never selected.
  useEffect(() => {
    if (selectedId !== null) return;
    if (!deliverables || deliverables.length === 0) return;
    const first = deliverables.find((d) => d.project_id === projectId);
    if (!first) return;
    selectDeliverable(first.id);
  }, [deliverables, selectedId, projectId, selectDeliverable]);

  // poll an active generation run
  useEffect(() => {
    if (!run || run.status === "succeeded" || run.status === "failed") return;
    timer.current = window.setInterval(async () => {
      try {
        const fresh = await api.get<PipelineRun>(`/api/pipeline/runs/${run.id}`);
        setRun(fresh);
        if (fresh.status === "succeeded" || fresh.status === "failed") {
          loadList();
          if (selectedId) loadDetail(selectedId);
        }
      } catch (err) {
        setError(err);
      }
    }, 1500);
    return () => {
      if (timer.current) window.clearInterval(timer.current);
    };
  }, [run, selectedId, loadList, loadDetail]);

  async function generate(formats?: string[]) {
    setBusy(true);
    setError(null);
    try {
      const started = await api.post<PipelineRun>(`/api/projects/${projectId}/generate`, {
        formats: formats ?? ["carousel", "static", "reel"],
      });
      setRun(started);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  async function action(fn: () => Promise<DeliverableDetail>, after?: () => void) {
    setBusy(true);
    setError(null);
    try {
      const d = await fn();
      setDetail(d);
      loadList();
      after?.();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  const hasSummary = deliverables !== null; // generation endpoint enforces summary server-side

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <Link to={`/projects/${projectId}`} className="text-sm hover:underline" style={{ color: "#8a6c60" }}>
            ← project
          </Link>
          <h1 className="text-2xl">Content studio</h1>
          <p className="prose-quiet">
            Generated drafts are validated, then gated behind doctor approval on the exact version.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            className="btn btn-primary"
            disabled={busy || !!runRunning(run)}
            onClick={() => void generate()}
          >
            {runRunning(run) ? "Generating…" : "generate all formats"}
          </button>
          <button
            className="btn btn-secondary"
            disabled={busy || !!runRunning(run)}
            onClick={() => void generate(["deck"])}
          >
            {runRunning(run) ? "Generating…" : "generate powerpoint deck"}
          </button>
          <Link className="btn btn-secondary" to={`/projects/${projectId}/exports`}>
            export center
          </Link>
        </div>
      </div>

      <ErrorNote error={error} onDismiss={() => setError(null)} />

      {run && (
        <div
          className={`rounded-lg border px-3 py-2 text-sm ${
            run.status === "failed" ? "border-red-300 bg-red-50 text-red-900" : "border-sky-300 bg-sky-50 text-sky-900"
          }`}
        >
          <div className="flex flex-wrap items-center gap-2">
            <StatusPill status={run.status} />
            <span>generation run · {run.mode}</span>
            <span className="text-xs">{fmtDate(run.created_at)}</span>
          </div>
          {run.error && <p className="mt-1">{run.error}</p>}
          {run.status === "succeeded" && run.meta && run.meta.mode_label ? (
            <p className="mt-1 text-xs">{String(run.meta.mode_label)}</p>
          ) : null}
        </div>
      )}

      {!deliverables ? (
        <Spinner label="Loading deliverables…" />
      ) : deliverables.length === 0 ? (
        <EmptyState
          title="No content generated yet"
          hint={
            hasSummary
              ? "Generate carousel, static post and reel drafts from the research summary."
              : "Run the research pipeline first — generation needs a summary."
          }
          action={
            <button className="btn btn-primary" disabled={busy} onClick={() => void generate()}>
              generate all formats
            </button>
          }
        />
      ) : (
        <div className="grid gap-3 md:grid-cols-3 lg:grid-cols-4">
          {deliverables.map((d) => (
            <button
              key={d.id}
              type="button"
              onClick={() => selectDeliverable(d.id)}
              className={`card px-4 py-3 text-left transition ${
                selectedId === d.id ? "ring-2" : "hover:-translate-y-0.5"
              }`}
              style={selectedId === d.id ? { boxShadow: "0 0 0 2px #C04E2A" } : undefined}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="font-display text-base">{FORMAT_TITLES[d.format] ?? d.format}</span>
                <StatusPill status={d.status} />
              </div>
              <p className="mt-1 line-clamp-2 text-xs prose-quiet">{d.concept || "—"}</p>
              <p className="mt-1 text-xs">
                {d.approved_version_id && d.approved_version_id === d.current_version_id ? (
                  <span style={{ color: "#166534" }}>✓ approved version</span>
                ) : d.approved_version_id ? (
                  <span style={{ color: "#9a3e20" }}>approved version superseded — re-approval needed</span>
                ) : (
                  <span style={{ color: "#8a6c60" }}>not approved</span>
                )}
              </p>
            </button>
          ))}
        </div>
      )}

      {detail && (
        <DeliverableView
          detail={detail}
          isDoctor={isDoctor}
          busy={busy}
          editJson={editJson}
          setEditJson={setEditJson}
          comment={comment}
          setComment={setComment}
          onDetail={(d) => setDetail(d)}
          onError={setError}
          runAction={action}
        />
      )}
    </div>
  );
}

function runRunning(run: PipelineRun | null): PipelineRun | null {
  if (!run) return null;
  return run.status === "queued" || run.status === "running" ? run : null;
}

function DeliverableView({
  detail,
  isDoctor,
  busy,
  editJson,
  setEditJson,
  comment,
  setComment,
  onDetail,
  onError,
  runAction,
}: {
  detail: DeliverableDetail;
  isDoctor: boolean;
  busy: boolean;
  editJson: string | null;
  setEditJson: (v: string | null) => void;
  comment: string;
  setComment: (v: string) => void;
  onDetail: (d: DeliverableDetail) => void;
  onError: (e: unknown) => void;
  runAction: (fn: () => Promise<DeliverableDetail>, after?: () => void) => Promise<void>;
}) {
  const v = detail.current_version;
  const validation: ValidationReport = v?.validation ?? { issues: [] };
  const issues = validation.issues;
  const errors = issues.filter((i) => i.severity === "error");
  const warnings = issues.filter((i) => i.severity === "warning");
  const [commentBusy, setCommentBusy] = useState(false);
  const [regenTarget, setRegenTarget] = useState("");
  const approvedHere = !!detail.approved_version_id && detail.approved_version_id === detail.current_version_id;

  const regenOptions = ((): { value: string; label: string }[] => {
    if (!v?.payload) return [];
    const p = v.payload as unknown as Record<string, unknown>;
    if (detail.format === "carousel") {
      const slides = (p.slides ?? []) as { index: number; headline: string }[];
      return slides.map((s) => ({
        value: `slide:${s.index}`,
        label: `slide ${s.index + 1} — ${s.headline}`,
      }));
    }
    if (detail.format === "reel") {
      const scenes = (p.scenes ?? []) as { index: number; on_screen_text: string }[];
      return scenes.map((s) => ({
        value: `scene:${s.index}`,
        label: `scene ${s.index + 1} — ${s.on_screen_text}`,
      }));
    }
    if (detail.format === "deck") {
      const slides = (p.slides ?? []) as DeckSlide[];
      return slides.map((s) => ({
        value: `slide:${s.index}`,
        label: `slide ${s.index + 1} — ${s.title}`,
      }));
    }
    return [];
  })();

  function startEdit() {
    setEditJson(JSON.stringify(v?.payload ?? {}, null, 2));
  }

  async function saveEdit() {
    if (!editJson) return;
    let payload: unknown;
    try {
      payload = JSON.parse(editJson);
    } catch (err) {
      onError(new Error(`JSON is not valid: ${(err as Error).message}`));
      return;
    }
    await runAction(() =>
      api.post<DeliverableDetail>(`/api/deliverables/${detail.id}/edit`, {
        payload,
        note: "edited in content studio",
      }),
      () => setEditJson(null),
    );
  }

  async function doExport() {
    onError(null);
    try {
      const res = await api.post<{ asset_id: string; filename: string; approved: boolean }>(
        `/api/deliverables/${detail.id}/export`,
      );
      await downloadAsset(res.asset_id, res.filename);
    } catch (err) {
      onError(err);
    }
  }

  async function postComment() {
    if (!comment.trim()) return;
    setCommentBusy(true);
    try {
      await api.post(`/api/deliverables/${detail.id}/comments`, { body: comment.trim() });
      setComment("");
      onDetail(await api.get<DeliverableDetail>(`/api/deliverables/${detail.id}`));
    } catch (err) {
      onError(err);
    } finally {
      setCommentBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      {/* status banner */}
      <div className="card flex flex-wrap items-center gap-2 px-4 py-3">
        <span className="font-display text-lg">{FORMAT_TITLES[detail.format] ?? detail.format}</span>
        <StatusPill status={detail.status} />
        {v && <span className="pill border bg-blush text-maroon border-clay">v{v.version_number}</span>}
        {v && (
          <span
            className={`pill border ${
              validation.status === "failed"
                ? "bg-red-100 text-red-900 border-red-300"
                : validation.status === "warnings"
                  ? "bg-amber-100 text-amber-900 border-amber-300"
                  : "bg-emerald-100 text-emerald-900 border-emerald-300"
            }`}
          >
            validation: {validation.status ?? v.validation_status}
          </span>
        )}
        {approvedHere && <span className="pill border bg-emerald-100 text-emerald-900 border-emerald-300">approved</span>}
        {v && (
          <span className="pill border bg-blush text-maroon border-clay" title={v.model_name ?? ""}>
            {v.generation_mode_label || v.generation_mode}
          </span>
        )}
        {detail.blocked_claims.length > 0 && (
          <span className="pill border bg-red-100 text-red-900 border-red-300">
            blocked claims: {detail.blocked_claims.join(", ")}
          </span>
        )}
      </div>

      {detail.status === "awaiting_review" && (
        <div className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900">
          This version is awaiting doctor review. Editing while under review requires retracting first
          (the server enforces this).
        </div>
      )}
      {detail.status === "ready_to_publish" && (
        <div className="rounded-lg border border-emerald-300 bg-emerald-50 px-3 py-2 text-sm text-emerald-900">
          Approved and ready to publish — finish in the{" "}
          <Link className="underline" to="/publishing">publishing queue</Link>.
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-3">
        {/* preview */}
        <Card title="Preview" className="lg:col-span-2">
          {!v ? (
            <EmptyState title="No version yet" hint="Generate content first." />
          ) : (
            <PayloadPreview format={detail.format} payload={v.payload} />
          )}
        </Card>

        <div className="space-y-4">
          {/* actions */}
          <Card title="Actions">
            <div className="flex flex-col gap-2">
              {detail.status === "awaiting_review" ? (
                <button
                  className="btn btn-secondary"
                  disabled={busy}
                  onClick={() => void runAction(() => api.post<DeliverableDetail>(`/api/deliverables/${detail.id}/retract`))}
                >
                  retract from review
                </button>
              ) : (
                <button
                  className="btn btn-primary"
                  disabled={busy || !v}
                  onClick={() => void runAction(() => api.post<DeliverableDetail>(`/api/deliverables/${detail.id}/submit`, { note: "" }))}
                >
                  submit for doctor review
                </button>
              )}

              <button
                className="btn btn-secondary"
                disabled={busy || !v}
                onClick={() => void runAction(() => api.post<DeliverableDetail>(`/api/deliverables/${detail.id}/validate`))}
              >
                re-run validation
              </button>

              {editJson === null ? (
                <button className="btn btn-secondary" disabled={busy || !v || detail.status === "published"} onClick={startEdit}>
                  edit content (JSON)
                </button>
              ) : (
                <>
                  <button
                    className="btn btn-primary"
                    disabled={busy}
                    onClick={() => void saveEdit()}
                  >
                    save edited version
                  </button>
                  <button className="btn btn-secondary" onClick={() => setEditJson(null)}>
                    cancel edit
                  </button>
                </>
              )}

              {regenOptions.length > 0 && (
                <div className="space-y-1.5 border-t pt-2" style={{ borderColor: "rgba(181,135,119,.4)" }}>
                  <p className="label">regenerate a section</p>
                  <div className="flex gap-2">
                    <select
                      className="input"
                      style={{ width: "12rem" }}
                      value={regenTarget}
                      onChange={(e) => setRegenTarget(e.target.value)}
                    >
                      <option value="">choose a section…</option>
                      {regenOptions.map((o) => (
                        <option key={o.value} value={o.value}>
                          {o.label}
                        </option>
                      ))}
                    </select>
                    <button
                      className="btn btn-secondary"
                      disabled={busy || !regenTarget}
                      onClick={() => {
                        const sep = regenTarget.indexOf(":");
                        const tgt = sep === -1 ? regenTarget : regenTarget.slice(0, sep);
                        const idx = sep === -1 ? "" : regenTarget.slice(sep + 1);
                        const qs = `target=${encodeURIComponent(tgt)}${idx ? `&index=${encodeURIComponent(idx)}` : ""}`;
                        return confirm(
                          "Regenerate just this section? This creates a new version and (if previously approved) resets approval.",
                        ) && void runAction(() => api.post<DeliverableDetail>(`/api/deliverables/${detail.id}/regenerate-section?${qs}`));
                      }}
                    >
                      regenerate section
                    </button>
                  </div>
                </div>
              )}

              <button
                className="btn btn-secondary"
                disabled={busy || !v}
                onClick={() =>
                  confirm("Regenerate this format? This creates a new version (approval resets if re-approved).") &&
                  void runAction(() => api.post<DeliverableDetail>(`/api/deliverables/${detail.id}/regenerate-all`))
                }
              >
                regenerate this format
              </button>

              <button className="btn btn-secondary" disabled={busy || !v} onClick={() => void doExport()}>
                export bundle (zip)
              </button>
            </div>

            {editJson !== null && (
              <textarea
                className="mono mt-3"
                rows={14}
                style={{ width: "100%", border: "1px solid rgba(181,135,119,.6)", borderRadius: "0.5rem", padding: "0.6rem" }}
                value={editJson}
                onChange={(e) => setEditJson(e.target.value)}
              />
            )}
          </Card>

          {/* assets */}
          {v && v.assets.length > 0 && (
            <Card title="Rendered assets">
              <ul className="space-y-1.5 text-sm">
                {v.assets.map((a) => (
                  <li key={a.id} className="flex items-center justify-between gap-2">
                    <span className="min-w-0">
                      <span className="mono block truncate">{a.filename}</span>
                      <span className="text-xs prose-quiet">
                        {a.kind} · {fmtBytes(a.byte_size)}
                      </span>
                    </span>
                    <button className="btn btn-sm btn-secondary" onClick={() => void downloadAsset(a.id, a.filename)}>
                      download
                    </button>
                  </li>
                ))}
              </ul>
            </Card>
          )}
        </div>
      </div>

      {/* validation */}
      <Card
        title={
          <span>
            Validation{" "}
            <span className="text-sm font-normal prose-quiet">
              deterministic rules — not a clinical fact-check; doctor review still required
            </span>
          </span>
        }
        right={
          <div className="flex gap-2">
            <span className="pill border bg-red-100 text-red-900 border-red-300">{errors.length} errors</span>
            <span className="pill border bg-amber-100 text-amber-900 border-amber-300">{warnings.length} warnings</span>
          </div>
        }
      >
        {issues.length === 0 ? (
          <p className="prose-quiet text-sm">
            {validation.checked_at ? `No issues found (${fmtDate(validation.checked_at)}).` : "No validation run yet."}
            {validation.note ? ` ${validation.note}` : ""}
          </p>
        ) : (
          <ul className="space-y-1.5">
            {issues.map((i, idx) => (
              <li
                key={idx}
                className={`rounded-lg border px-3 py-1.5 text-sm ${
                  i.severity === "error" ? "border-red-200 bg-red-50" : "border-amber-200 bg-amber-50"
                }`}
              >
                <div className="flex flex-wrap items-center gap-2 text-xs">
                  <span className={`mono font-semibold ${i.severity === "error" ? "text-red-800" : "text-amber-800"}`}>
                    {i.rule}
                  </span>
                  {i.location && <span className="mono prose-quiet">{i.location}</span>}
                  {i.claim_id && (
                    <Link className="mono underline" to={`/projects/${detail.project_id}/evidence`}>
                      {i.claim_id}
                    </Link>
                  )}
                </div>
                <p>{i.message}</p>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        {/* version history */}
        <Card title={`Version history (${detail.versions.length})`}>
          {detail.versions.length === 0 ? (
            <p className="prose-quiet text-sm">No versions yet.</p>
          ) : (
            <ul className="max-h-72 space-y-2 overflow-auto pr-1 text-sm">
              {detail.versions
                .slice()
                .sort((a, b) => b.version_number - a.version_number)
                .map((ver) => {
                  const isCurrent = ver.id === detail.current_version_id;
                  const isApproved = ver.id === detail.approved_version_id;
                  return (
                    <li
                      key={ver.id}
                      className="rounded-lg border px-3 py-2"
                      style={{
                        borderColor: isCurrent ? "#C04E2A" : "rgba(181,135,119,.4)",
                        background: isCurrent ? "rgba(230,203,189,.4)" : undefined,
                      }}
                    >
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="mono font-semibold">v{ver.version_number}</span>
                        {isCurrent && <span className="pill border bg-blush text-maroon border-clay">current</span>}
                        {isApproved && (
                          <span className="pill border bg-emerald-100 text-emerald-900 border-emerald-300">approved</span>
                        )}
                        <span
                          className={`pill border ${
                            ver.validation_status === "failed"
                              ? "bg-red-100 text-red-900 border-red-300"
                              : ver.validation_status === "warnings"
                                ? "bg-amber-100 text-amber-900 border-amber-300"
                                : "bg-emerald-100 text-emerald-900 border-emerald-300"
                          }`}
                        >
                          {ver.validation_status}
                        </span>
                        <span className="text-xs prose-quiet">{fmtDate(ver.created_at)}</span>
                      </div>
                      <p className="text-xs">
                        {ver.generation_mode_label || ver.generation_mode}
                        {ver.model_name ? ` · ${ver.model_name}` : ""}
                      </p>
                    </li>
                  );
                })}
            </ul>
          )}
          <p className="mt-2 text-xs prose-quiet">
            Every edit or regeneration creates a new version. Approval is always tied to an exact version id.
          </p>
        </Card>

        {/* reviews */}
        <Card title="Review history">
          {detail.reviews.length === 0 ? (
            <p className="prose-quiet text-sm">No review decisions yet.</p>
          ) : (
            <ul className="space-y-2 text-sm">
              {detail.reviews.map((r) => (
                <li key={r.id} className="rounded-lg border px-3 py-2" style={{ borderColor: "rgba(181,135,119,.4)" }}>
                  <div className="flex flex-wrap items-center gap-2">
                    <StatusPill status={r.decision === "approved" ? "approved" : r.decision} />
                    <strong>{r.reviewer_name ?? "reviewer"}</strong>
                    <span className="text-xs prose-quiet">
                      v{r.version_number} · {fmtDate(r.created_at)}
                    </span>
                    {r.version_id === detail.current_version_id && (
                      <span className="pill border bg-blush text-maroon border-clay">this version</span>
                    )}
                  </div>
                  {r.comments && <p className="mt-1">{r.comments}</p>}
                </li>
              ))}
            </ul>
          )}
        </Card>

        {/* comments */}
        <Card title="Comments">
          <ul className="mb-3 space-y-2 text-sm">
            {detail.comments.length === 0 && <li className="prose-quiet">No comments yet.</li>}
            {detail.comments.map((c) => (
              <li key={c.id} className="rounded-lg bg-blush/40 px-3 py-2">
                <p className="text-xs font-semibold" style={{ color: "#8a6c60" }}>
                  {c.reviewer_name ?? "someone"} · {fmtDate(c.created_at)}
                  {c.anchor ? ` · ${c.anchor}` : ""}
                </p>
                <p>{c.body}</p>
              </li>
            ))}
          </ul>
          <div className="flex gap-2">
            <input
              className="input"
              placeholder="add a comment…"
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && void postComment()}
            />
            <button className="btn btn-secondary" disabled={commentBusy || !comment.trim()} onClick={() => void postComment()}>
              post
            </button>
          </div>
          {!isDoctor && (
            <p className="mt-2 text-xs prose-quiet">
              Approval decisions are doctor-only (server-enforced); editors can comment.
            </p>
          )}
        </Card>
      </div>
    </div>
  );
}

// --- previews ---------------------------------------------------------------

export function PayloadPreview({ format, payload }: { format: string; payload: Record<string, unknown> }) {
  if (format === "carousel") return <CarouselPreview p={payload as unknown as CarouselPayload} />;
  if (format === "reel") return <ReelPreview p={payload as unknown as ReelPayload} />;
  if (format === "deck") return <DeckPreview p={payload as unknown as DeckPayload} />;
  return <StaticPreview p={payload as unknown as StaticPayload} />;
}

function CommonFooter({ p }: { p: { caption?: string; hashtags?: string[]; limitations?: string[]; disclaimer?: string; source_notes?: { text: string }[] } }) {
  return (
    <div className="mt-4 space-y-2 border-t pt-3 text-sm" style={{ borderColor: "rgba(181,135,119,.4)" }}>
      <p className="prose-quiet"><span className="font-semibold">caption:</span> {p.caption || "—"}</p>
      {p.hashtags && p.hashtags.length > 0 && <p className="mono text-xs">{p.hashtags.join(" ")}</p>}
      {p.limitations && p.limitations.length > 0 && (
        <div>
          <p className="label">limitations</p>
          <ul className="list-inside list-disc prose-quiet">
            {p.limitations.map((l, i) => (<li key={i}>{l}</li>))}
          </ul>
        </div>
      )}
      {p.source_notes && p.source_notes.length > 0 && (
        <div>
          <p className="label">sources</p>
          <ul className="prose-quiet text-xs">
            {p.source_notes.map((s, i) => (<li key={i}>{s.text}</li>))}
          </ul>
        </div>
      )}
      <p className="rounded bg-blush/50 px-2 py-1 text-xs">{p.disclaimer}</p>
    </div>
  );
}

function CarouselPreview({ p }: { p: CarouselPayload }) {
  return (
    <div>
      <p className="mb-2 text-xs prose-quiet">
        {p.concept} · audience: {p.audience}
      </p>
      <ol className="grid gap-2 sm:grid-cols-2">
        {(p.slides ?? []).map((s) => (
          <li key={s.index} className="rounded-lg border p-3" style={{ borderColor: "rgba(181,135,119,.45)", background: "#fff" }}>
            <div className="flex items-center justify-between">
              <span className="mono text-xs" style={{ color: "#8a6c60" }}>slide {s.index + 1}</span>
              {s.claim_ids.length > 0 && (
                <span className="mono text-xs" style={{ color: "#C04E2A" }}>{s.claim_ids.join(" ")}</span>
              )}
            </div>
            <p className="font-display text-base">{s.headline}</p>
            <p className="mt-1 text-sm prose-quiet">{s.body}</p>
            {s.footnote && <p className="mt-1 text-xs" style={{ color: "#8a6c60" }}>{s.footnote}</p>}
          </li>
        ))}
      </ol>
      <CommonFooter p={p} />
    </div>
  );
}

function StaticPreview({ p }: { p: StaticPayload }) {
  return (
    <div>
      <div className="rounded-lg border p-4" style={{ borderColor: "rgba(181,135,119,.45)", background: "#fff" }}>
        <div className="flex items-center justify-between">
          <span className="mono text-xs" style={{ color: "#8a6c60" }}>static post</span>
          <span className="mono text-xs" style={{ color: "#C04E2A" }}>{(p.claim_ids ?? []).join(" ")}</span>
        </div>
        <p className="font-display text-xl">{p.headline}</p>
        <p className="mt-2 whitespace-pre-wrap text-sm">{p.body}</p>
      </div>
      <CommonFooter p={p} />
    </div>
  );
}

function ReelPreview({ p }: { p: ReelPayload }) {
  return (
    <div>
      <p className="mb-2 text-xs prose-quiet">
        {p.duration_seconds}s · hook: <strong>{p.hook}</strong>
      </p>
      <ol className="space-y-2">
        {(p.scenes ?? []).map((s) => (
          <li key={s.index} className="rounded-lg border p-3" style={{ borderColor: "rgba(181,135,119,.45)", background: "#fff" }}>
            <div className="flex items-center justify-between">
              <span className="mono text-xs" style={{ color: "#8a6c60" }}>
                scene {s.index + 1} · {s.start_seconds}s–{s.end_seconds}s
              </span>
              <span className="mono text-xs" style={{ color: "#C04E2A" }}>{(s.claim_ids ?? []).join(" ")}</span>
            </div>
            <p className="font-display text-base">{s.on_screen_text}</p>
            <p className="mt-1 text-sm prose-quiet">🎙 {s.voiceover}</p>
          </li>
        ))}
      </ol>
      <CommonFooter p={p} />
      {p.closing_takeaway && (
        <p className="mt-2 rounded bg-blush/50 px-2 py-1 text-sm">closing: {p.closing_takeaway}</p>
      )}
    </div>
  );
}

function DeckPreview({ p }: { p: DeckPayload }) {
  return (
    <div>
      <p className="mb-1 text-xs prose-quiet">
        {p.deck_title} {p.subtitle ? `· ${p.subtitle}` : ""} · {p.slides?.length ?? 0} slides
      </p>
      <ol className="grid gap-2 sm:grid-cols-2">
        {(p.slides ?? []).map((s) => (
          <li key={s.index} className="rounded-lg border p-3" style={{ borderColor: "rgba(181,135,119,.45)", background: "#fff" }}>
            <div className="flex items-center justify-between">
              <span className="mono text-xs" style={{ color: "#8a6c60" }}>
                slide {s.index + 1} · {s.kind}
              </span>
              {s.claim_ids.length > 0 && (
                <span className="mono text-xs" style={{ color: "#C04E2A" }}>{s.claim_ids.join(" ")}</span>
              )}
            </div>
            <p className="font-display text-base">{s.title}</p>
            {s.bullets.length > 0 && (
              <ul className="mt-1 list-inside list-disc space-y-0.5 text-sm prose-quiet">
                {s.bullets.map((b, i) => (<li key={i}>{b}</li>))}
              </ul>
            )}
            {s.table && s.table.rows.length > 0 && (
              <p className="mt-1 text-xs prose-quiet">
                table: {s.table.rows.length} row{s.table.rows.length === 1 ? "" : "s"} × {s.table.headers.length} cols
              </p>
            )}
            {s.source_notes.length > 0 && (
              <p className="mt-1 text-xs" style={{ color: "#8a6c60" }}>{s.source_notes.join(" · ")}</p>
            )}
          </li>
        ))}
      </ol>
      <CommonFooter p={p} />
      {p.disclaimer && <p className="mt-2 rounded bg-blush/50 px-2 py-1 text-xs">{p.disclaimer}</p>}
    </div>
  );
}
