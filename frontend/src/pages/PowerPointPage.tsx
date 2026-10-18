import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, downloadAsset } from "../lib/api";
import type {
  Deliverable,
  DeliverableDetail,
  DeckPayload,
  DeckSlide,
  ExportKind,
  ExportResult,
  ValidationReport,
} from "../lib/types";
import { fmtBytes, fmtDate } from "../lib/format";
import { Card, EmptyState, ErrorNote, Spinner, StatusPill } from "../components/ui";
import { useAuth } from "../state/auth";

const EXPORT_KINDS: { kind: ExportKind; label: string }[] = [
  { kind: "full", label: "Full bundle (zip)" },
  { kind: "evidence_report", label: "Evidence report (md)" },
  { kind: "source_manifest", label: "Source manifest (json)" },
  { kind: "captions", label: "Captions / script (txt)" },
];

export default function PowerPointPage() {
  const { projectId = "" } = useParams();
  const { user } = useAuth();
  const isDoctor = user?.role === "doctor" || user?.role === "admin";

  const [deliverables, setDeliverables] = useState<Deliverable[] | null>(null);
  const [detail, setDetail] = useState<DeliverableDetail | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState(0);
  const [editJson, setEditJson] = useState<string | null>(null);
  const [exporting, setExporting] = useState<ExportKind | null>(null);

  const deck = deliverables?.find((d) => d.format === "deck") ?? null;

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
        setDetail(d);
        setSelected(0);
      })
      .catch(setError);
  }, []);

  useEffect(loadList, [loadList]);

  useEffect(() => {
    if (deck && (!detail || detail.id !== deck.id)) loadDetail(deck.id);
  }, [deck, detail, loadDetail]);

  async function generateDeck() {
    setBusy(true);
    setError(null);
    try {
      await api.post(`/api/projects/${projectId}/generate`, { formats: ["deck"] });
      loadList();
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

  async function doExport(kind: ExportKind) {
    if (!detail) return;
    setExporting(kind);
    setError(null);
    try {
      const res = await api.post<ExportResult>(`/api/deliverables/${detail.id}/export`, { kind });
      await downloadAsset(res.asset_id, res.filename);
    } catch (err) {
      setError(err);
    } finally {
      setExporting(null);
    }
  }

  const payload = (detail?.current_version?.payload ?? null) as DeckPayload | null;
  const slides = payload?.slides ?? [];
  const current: DeckSlide | null = slides[selected] ?? null;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <Link to={`/projects/${projectId}`} className="text-sm hover:underline" style={{ color: "#8a6c60" }}>
            ← project
          </Link>
          <h1 className="text-2xl">PowerPoint studio</h1>
          <p className="prose-quiet">
            A 10-slide research briefing rendered as a native, editable .pptx. Same review + approval gate as every
            other format.
          </p>
        </div>
        <div className="flex gap-2">
          {!deck ? (
            <button className="btn btn-primary" disabled={busy} onClick={() => void generateDeck()}>
              generate deck
            </button>
          ) : (
            <button className="btn btn-secondary" disabled={busy} onClick={() => void generateDeck()}>
              regenerate deck
            </button>
          )}
          {deck && (
            <Link className="btn btn-secondary" to={`/projects/${projectId}/exports`}>
              export center
            </Link>
          )}
        </div>
      </div>

      <ErrorNote error={error} onDismiss={() => setError(null)} />

      {!deliverables ? (
        <Spinner label="Loading deliverables…" />
      ) : !deck ? (
        <EmptyState
          title="No deck yet"
          hint="Generate a 10-slide research briefing deck from the evidence-linked claims in this project."
          action={
            <button className="btn btn-primary" disabled={busy} onClick={() => void generateDeck()}>
              generate deck
            </button>
          }
        />
      ) : !payload ? (
        <Spinner label="Loading deck…" />
      ) : (
        <>
          {/* status banner */}
          <div className="card flex flex-wrap items-center gap-2 px-4 py-3">
            <span className="font-display text-lg">Research deck</span>
            <StatusPill status={detail?.status ?? "draft"} />
            {detail?.current_version && (
              <span className="pill border bg-blush text-maroon border-clay">
                v{detail.current_version.version_number}
              </span>
            )}
            {detail?.current_version && (
              <span
                className={`pill border ${
                  detail.current_version.validation_status === "failed"
                    ? "bg-red-100 text-red-900 border-red-300"
                    : detail.current_version.validation_status === "warnings"
                      ? "bg-amber-100 text-amber-900 border-amber-300"
                      : "bg-emerald-100 text-emerald-900 border-emerald-300"
                }`}
              >
                validation: {detail.current_version.validation_status}
              </span>
            )}
            {detail?.current_version && (
              <span className="pill border bg-blush text-maroon border-clay">
                {detail.current_version.generation_mode_label || detail.current_version.generation_mode}
              </span>
            )}
            {detail?.approved_version_id === detail?.current_version_id && (
              <span className="pill border bg-emerald-100 text-emerald-900 border-emerald-300">approved</span>
            )}
          </div>

          <div className="grid gap-4 lg:grid-cols-4">
            {/* slide navigator */}
            <Card title="Slides" className="lg:col-span-1">
              <ol className="space-y-1">
                {slides.map((s) => (
                  <li key={s.index}>
                    <button
                      onClick={() => setSelected(s.index)}
                      className={`w-full rounded-lg border px-3 py-2 text-left text-sm transition ${
                        selected === s.index ? "border-rust bg-blush/60" : "hover:bg-blush/30"
                      }`}
                      style={{ borderColor: selected === s.index ? "#C04E2A" : "rgba(181,135,119,.4)" }}
                    >
                      <span className="mono text-xs" style={{ color: "#8a6c60" }}>
                        {s.index + 1}/{slides.length}
                      </span>
                      <span className="block truncate font-medium">{s.title}</span>
                      {s.claim_ids.length > 0 && (
                        <span className="mono text-xs" style={{ color: "#C04E2A" }}>
                          {s.claim_ids.join(" ")}
                        </span>
                      )}
                    </button>
                  </li>
                ))}
              </ol>
            </Card>

            {/* preview */}
            <Card title={current ? current.title : "Preview"} className="lg:col-span-2">
              {!current ? (
                <EmptyState title="No slide selected" />
              ) : (
                <div>
                  <div className="rounded-lg border p-4" style={{ borderColor: "rgba(181,135,119,.45)", background: "#fff" }}>
                    <span className="mono text-xs" style={{ color: "#8a6c60" }}>
                      slide {current.index + 1} · {current.kind}
                    </span>
                    <p className="mt-1 font-display text-xl">{current.title}</p>
                    {current.bullets.length > 0 && (
                      <ul className="mt-2 list-inside list-disc space-y-1 text-sm prose-quiet">
                        {current.bullets.map((b, i) => (
                          <li key={i}>{b}</li>
                        ))}
                      </ul>
                    )}
                    {current.table && current.table.rows.length > 0 && (
                      <table className="mt-3 w-full border-collapse text-sm">
                        <thead>
                          <tr>
                            {current.table.headers.map((h, i) => (
                              <th
                                key={i}
                                className="border px-2 py-1 text-left"
                                style={{ borderColor: "rgba(181,135,119,.5)", background: "#661414", color: "#F5EBDF" }}
                              >
                                {h}
                              </th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {current.table.rows.map((row, ri) => (
                            <tr key={ri}>
                              {row.map((cell, ci) => (
                                <td key={ci} className="border px-2 py-1" style={{ borderColor: "rgba(181,135,119,.5)" }}>
                                  {cell}
                                </td>
                              ))}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    )}
                    {current.source_notes.length > 0 && (
                      <div className="mt-3 border-t pt-2 text-xs prose-quiet" style={{ borderColor: "rgba(181,135,119,.4)" }}>
                        <span className="label">sources</span>
                        <ul>
                          {current.source_notes.map((n, i) => (
                            <li key={i}>{n}</li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>
                  {payload.disclaimer && (
                    <p className="mt-3 rounded bg-blush/50 px-2 py-1 text-xs">{payload.disclaimer}</p>
                  )}
                </div>
              )}
            </Card>

            {/* actions */}
            <div className="space-y-4 lg:col-span-1">
              <Card title="Actions">
                <div className="flex flex-col gap-2">
                  {detail?.status === "awaiting_review" ? (
                    <button
                      className="btn btn-secondary"
                      disabled={busy}
                      onClick={() => void action(() => api.post<DeliverableDetail>(`/api/deliverables/${detail.id}/retract`))}
                    >
                      retract from review
                    </button>
                  ) : (
                    <button
                      className="btn btn-primary"
                      disabled={busy || !payload}
                      onClick={() =>
                        detail &&
                        void action(() =>
                          api.post<DeliverableDetail>(`/api/deliverables/${detail.id}/submit`, { note: "" }),
                        )
                      }
                    >
                      submit for doctor review
                    </button>
                  )}

                  {editJson === null ? (
                    <button
                      className="btn btn-secondary"
                      disabled={busy || !payload || detail?.status === "published"}
                      onClick={() => setEditJson(JSON.stringify(payload, null, 2))}
                    >
                      edit deck (JSON)
                    </button>
                  ) : (
                    <>
                      <button
                        className="btn btn-primary"
                        disabled={busy}
                        onClick={() => {
                          let parsed: unknown;
                          try {
                            parsed = JSON.parse(editJson);
                          } catch (err) {
                            setError(new Error(`JSON is not valid: ${(err as Error).message}`));
                            return;
                          }
                          detail &&
                            void action(
                              () =>
                                api.post<DeliverableDetail>(`/api/deliverables/${detail.id}/edit`, {
                                  payload: parsed,
                                  note: "edited in powerpoint studio",
                                }),
                              () => setEditJson(null),
                            );
                        }}
                      >
                        save edited version
                      </button>
                      <button className="btn btn-secondary" onClick={() => setEditJson(null)}>
                        cancel edit
                      </button>
                    </>
                  )}

                  {current && (
                    <button
                      className="btn btn-secondary"
                      disabled={busy || !detail}
                      onClick={() =>
                        detail &&
                        void action(() =>
                          api.post<DeliverableDetail>(
                            `/api/deliverables/${detail.id}/regenerate-section?target=slide&index=${current.index}`,
                          ),
                        )
                      }
                    >
                      regenerate this slide
                    </button>
                  )}

                  <button
                    className="btn btn-secondary"
                    disabled={busy || !detail}
                    onClick={() =>
                      detail &&
                      confirm("Regenerate the whole deck? This creates a new version and resets approval.") &&
                      void action(() => api.post<DeliverableDetail>(`/api/deliverables/${detail.id}/regenerate-all`))
                    }
                  >
                    regenerate whole deck
                  </button>
                </div>

                {editJson !== null && (
                  <textarea
                    className="mono mt-3"
                    rows={18}
                    style={{
                      width: "100%",
                      border: "1px solid rgba(181,135,119,.6)",
                      borderRadius: "0.5rem",
                      padding: "0.6rem",
                    }}
                    value={editJson}
                    onChange={(e) => setEditJson(e.target.value)}
                  />
                )}
              </Card>

              <Card title="Export">
                <div className="flex flex-col gap-2">
                  {EXPORT_KINDS.map((k) => (
                    <button
                      key={k.kind}
                      className="btn btn-secondary"
                      disabled={busy || !detail || exporting === k.kind}
                      onClick={() => void doExport(k.kind)}
                    >
                      {exporting === k.kind ? "exporting…" : k.label}
                    </button>
                  ))}
                </div>
              </Card>

              {detail?.current_version && detail.current_version.assets.length > 0 && (
                <Card title="Rendered assets">
                  <ul className="space-y-1.5 text-sm">
                    {detail.current_version.assets
                      .filter((a) => a.kind === "deck_pptx")
                      .map((a) => (
                        <li key={a.id} className="flex items-center justify-between gap-2">
                          <span className="min-w-0">
                            <span className="mono block truncate">{a.filename}</span>
                            <span className="text-xs prose-quiet">
                              {a.kind} · {fmtBytes(a.byte_size)}
                            </span>
                          </span>
                          <button className="btn btn-sm btn-secondary" onClick={() => void downloadAsset(a.id, a.filename)}>
                            download .pptx
                          </button>
                        </li>
                      ))}
                  </ul>
                </Card>
              )}

              {isDoctor && detail && <ReviewCard detail={detail} busy={busy} onAction={action} />}
            </div>
          </div>

          {/* validation */}
          <ValidationCard detail={detail} />
        </>
      )}
    </div>
  );
}

function ReviewCard({
  detail,
  busy,
  onAction,
}: {
  detail: DeliverableDetail;
  busy: boolean;
  onAction: (fn: () => Promise<DeliverableDetail>) => Promise<void>;
}) {
  const [decision, setDecision] = useState<"approved" | "changes_requested" | "rejected">("approved");
  const [comments, setComments] = useState("");
  const currentId = detail.current_version_id;

  if (!currentId) return null;
  if (detail.status !== "awaiting_review") {
    return (
      <Card title="Doctor review">
        <p className="text-sm prose-quiet">
          {detail.status === "ready_to_publish"
            ? "Approved and ready to publish."
            : "This deck is not awaiting review."}
        </p>
      </Card>
    );
  }

  return (
    <Card title="Doctor review">
      <div className="space-y-2">
        <select
          className="input"
          value={decision}
          onChange={(e) => setDecision(e.target.value as typeof decision)}
        >
          <option value="approved">approve</option>
          <option value="changes_requested">request changes</option>
          <option value="rejected">reject</option>
        </select>
        <textarea
          className="input"
          rows={3}
          placeholder="review comments…"
          value={comments}
          onChange={(e) => setComments(e.target.value)}
        />
        <button
          className="btn btn-primary w-full"
          disabled={busy}
          onClick={() =>
            void onAction(() =>
              api.post<DeliverableDetail>(`/api/deliverables/${detail.id}/reviews`, {
                version_id: currentId,
                decision,
                comments,
              }),
            )
          }
        >
          submit decision
        </button>
        <p className="text-xs prose-quiet">
          Approval is recorded against this exact version. Editing afterwards invalidates it (server-enforced).
        </p>
      </div>
    </Card>
  );
}

function ValidationCard({ detail }: { detail: DeliverableDetail | null }) {
  const v = detail?.current_version;
  const validation: ValidationReport = v?.validation ?? { issues: [] };
  const issues = validation.issues;
  const errors = issues.filter((i) => i.severity === "error");
  const warnings = issues.filter((i) => i.severity === "warning");

  return (
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
                  <Link className="mono underline" to={`/projects/${detail?.project_id}/evidence`}>
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
  );
}
