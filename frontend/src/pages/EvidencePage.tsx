import { useCallback, useEffect, useState, type ReactNode } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../lib/api";
import type { Claim, SafetyChecksReport, SourceExcerpt } from "../lib/types";
import { claimPill, riskColor } from "../lib/format";
import { Card, EmptyState, ErrorNote, Spinner } from "../components/ui";
import { useAuth } from "../state/auth";

const STATUSES = [
  "supported",
  "partially_supported",
  "unsupported",
  "conflicting",
  "needs_human_review",
];

function supportingCount(claim: Claim): number {
  return claim.evidence.filter((e) => e.relation === "supports" && e.excerpt.trim() !== "").length;
}

function contradictingCount(claim: Claim): number {
  return claim.evidence.filter((e) => e.relation === "contradicts").length;
}

export default function EvidencePage() {
  const { projectId = "" } = useParams();
  const { user } = useAuth();
  const canReview = user?.role === "doctor" || user?.role === "admin";

  const [claims, setClaims] = useState<Claim[] | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [filter, setFilter] = useState("all");
  const [query, setQuery] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [view, setView] = useState<"claims" | "safety">("claims");
  const [report, setReport] = useState<SafetyChecksReport | null>(null);
  const [reportLoading, setReportLoading] = useState(false);

  const load = useCallback(() => {
    api
      .get<Claim[]>(`/api/projects/${projectId}/claims`)
      .then((rows) => {
        setClaims(rows);
        setSelectedId((cur) => cur ?? rows[0]?.id ?? null);
      })
      .catch(setError);
  }, [projectId]);

  useEffect(load, [load]);

  useEffect(() => {
    if (view !== "safety" || report || reportLoading) return;
    setReportLoading(true);
    api
      .get<SafetyChecksReport>(`/api/projects/${projectId}/safety-checks`)
      .then(setReport)
      .catch(setError)
      .finally(() => setReportLoading(false));
  }, [view, report, reportLoading, projectId]);

  const filtered = (claims ?? []).filter(
    (c) =>
      (filter === "all" || c.status === filter) &&
      (query.trim() === "" ||
        c.claim_text.toLowerCase().includes(query.toLowerCase()) ||
        c.id.toLowerCase().includes(query.toLowerCase())),
  );
  const selected = claims?.find((c) => c.id === selectedId) ?? null;

  async function saveStatus(status: string, notes: string) {
    if (!selected) return;
    setBusy(true);
    setError(null);
    try {
      await api.patch<Claim>(`/api/claims/${selected.id}`, {
        status,
        verification_notes: notes,
      });
      load();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <Link to={`/projects/${projectId}`} className="text-sm hover:underline" style={{ color: "#8a6c60" }}>
            ← project
          </Link>
          <h1 className="text-2xl">Evidence lab</h1>
          <p className="prose-quiet">
            Every claim keeps its located passage, source and verification status.
          </p>
        </div>
        <span className="pill border bg-blush text-maroon border-clay">
          {canReview ? "you can update evidence status (doctor/admin)" : "read-only: doctors update evidence status"}
        </span>
      </div>

      <nav className="flex gap-1 border-b pb-1" style={{ borderColor: "rgba(181,135,119,.45)" }}>
        {([
          { id: "claims", label: "Claims" },
          { id: "safety", label: "Safety checks" },
        ] as const).map((t) => (
          <button
            key={t.id}
            onClick={() => setView(t.id)}
            className={`rounded-t-lg px-3 py-1.5 text-sm font-medium ${
              view === t.id ? "bg-paper text-maroon" : "text-ink/70 hover:bg-blush/50"
            }`}
            style={view === t.id ? { boxShadow: "inset 0 -2px 0 #C04E2A" } : undefined}
          >
            {t.label}
          </button>
        ))}
      </nav>

      {view === "safety" ? (
        <SafetyChecksPanel
          report={report}
          loading={reportLoading}
          projectId={projectId}
          onReload={() => {
            setReport(null);
            setError(null);
          }}
        />
      ) : (
        <>
      <ErrorNote error={error} onDismiss={() => setError(null)} />

      <div className="flex flex-wrap items-center gap-2">
        <input
          className="input"
          style={{ maxWidth: "18rem" }}
          placeholder="search claims…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <select className="input" style={{ maxWidth: "13rem" }} value={filter} onChange={(e) => setFilter(e.target.value)}>
          <option value="all">all statuses</option>
          {STATUSES.map((s) => (
            <option key={s} value={s}>{s.replaceAll("_", " ")}</option>
          ))}
        </select>
        <span className="text-sm prose-quiet">{filtered.length} claims</span>
      </div>

      {!claims ? (
        <Spinner label="Loading claims…" />
      ) : claims.length === 0 ? (
        <EmptyState title="No claims extracted yet" hint="Run the pipeline from the project page first." />
      ) : (
        <div className="grid gap-4 lg:grid-cols-5">
          <Card title="Claims" className="lg:col-span-2">
            <ul className="max-h-[32rem] space-y-2 overflow-auto pr-1">
              {filtered.map((c) => {
                const p = claimPill(c.status);
                const supporting = supportingCount(c);
                return (
                  <li key={c.id}>
                    <button
                      onClick={() => setSelectedId(c.id)}
                      className={`w-full rounded-lg border px-3 py-2 text-left transition ${
                        selectedId === c.id ? "bg-blush/70" : "bg-white/50 hover:bg-blush/40"
                      }`}
                      style={{
                        borderColor:
                          selectedId === c.id ? "#C04E2A" : "rgba(181,135,119,.4)",
                      }}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="mono">{c.id}</span>
                        <span className={`pill border ${p.cls}`}>{p.label}</span>
                      </div>
                      <p className="mt-1 line-clamp-3 text-sm">{c.claim_text}</p>
                      <p className={`mt-1 text-xs ${riskColor(c.risk_level)}`}>
                        {c.risk_level} risk · {supporting} supporting passage{supporting === 1 ? "" : "s"}
                      </p>
                    </button>
                  </li>
                );
              })}
              {filtered.length === 0 && <li className="prose-quiet text-sm">No claims match the filter.</li>}
            </ul>
          </Card>

          <div className="lg:col-span-3">
            {!selected ? (
              <Card><p className="prose-quiet">Select a claim.</p></Card>
            ) : (
              <ClaimDetail
                claim={selected}
                canReview={canReview}
                busy={busy}
                onSave={saveStatus}
              />
            )}
          </div>
        </div>
      )}
        </>
      )}
    </div>
  );
}

function SafetyChecksPanel({
  report,
  loading,
  projectId,
  onReload,
}: {
  report: SafetyChecksReport | null;
  loading: boolean;
  projectId: string;
  onReload: () => void;
}) {
  if (loading || !report) {
    return <Spinner label="Loading safety checks…" />;
  }
  const withIssues = report.claims.filter((c) => c.checks.some((ck) => ck.severity !== "info"));
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span className="pill border bg-red-100 text-red-900 border-red-300">
            {report.totals.error} error{report.totals.error === 1 ? "" : "s"}
          </span>
          <span className="pill border bg-amber-100 text-amber-900 border-amber-300">
            {report.totals.warning} warning{report.totals.warning === 1 ? "" : "s"}
          </span>
        </div>
        <button className="btn btn-secondary btn-sm" onClick={onReload}>
          re-run checks
        </button>
      </div>
      <p className="rounded bg-blush/50 px-3 py-2 text-xs prose-quiet">{report.note}</p>
      <Card title={`Claims with flags (${withIssues.length})`}>
        {withIssues.length === 0 ? (
          <p className="text-sm prose-quiet">No claim triggered a safety rule.</p>
        ) : (
          <ul className="space-y-2">
            {withIssues.map((c) => (
              <li key={c.claim_id} className="rounded-lg border px-3 py-2 text-sm" style={{ borderColor: "rgba(181,135,119,.4)" }}>
                <Link to={`/projects/${projectId}/evidence`} className="mono font-semibold underline">
                  {c.claim_id}
                </Link>
                <p className="mt-0.5">{c.claim_text}</p>
                <ul className="mt-1 space-y-0.5">
                  {c.checks
                    .filter((ck) => ck.severity !== "info")
                    .map((ck, i) => (
                      <li key={i} className="flex gap-2 text-xs">
                        <span
                          className={`pill border ${
                            ck.severity === "error"
                              ? "bg-red-100 text-red-900 border-red-300"
                              : "bg-amber-100 text-amber-900 border-amber-300"
                          }`}
                        >
                          {ck.severity}
                        </span>
                        <span className="mono shrink-0 prose-quiet">{ck.rule}</span>
                        <span className="min-w-0">{ck.message}</span>
                      </li>
                    ))}
                </ul>
              </li>
            ))}
          </ul>
        )}
      </Card>
      <Card title={`Deliverables (${report.deliverables.length})`}>
        {report.deliverables.length === 0 ? (
          <p className="text-sm prose-quiet">No deliverables yet.</p>
        ) : (
          <ul className="space-y-1.5 text-sm">
            {report.deliverables.map((d) => (
              <li key={d.deliverable_id} className="flex items-center justify-between gap-2">
                <span className="min-w-0 truncate">
                  {d.format} · v{d.version_number} · {d.status}
                </span>
                <Link className="btn btn-sm btn-secondary" to={`/projects/${projectId}/content`}>
                  open
                </Link>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

function ClaimDetail({
  claim,
  canReview,
  busy,
  onSave,
}: {
  claim: Claim;
  canReview: boolean;
  busy: boolean;
  onSave: (status: string, notes: string) => Promise<void>;
}) {
  const [status, setStatus] = useState(claim.status);
  const [notes, setNotes] = useState(claim.verification_notes);
  const [excerpt, setExcerpt] = useState<SourceExcerpt | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    setStatus(claim.status);
    setNotes(claim.verification_notes);
    setExcerpt(null);
  }, [claim.id, claim.status, claim.verification_notes]);

  const dirty = status !== claim.status || notes !== claim.verification_notes;
  const supporting = supportingCount(claim);
  const contradicting = contradictingCount(claim);

  async function openExcerpt(evidenceId: string) {
    setError(null);
    try {
      setExcerpt(await api.get<SourceExcerpt>(`/api/evidence/${evidenceId}/excerpt`));
    } catch (err) {
      setError(err);
    }
  }

  return (
    <div className="space-y-4">
      <Card
        title={<span>Claim <span className="mono">{claim.id}</span></span>}
        right={
          <span className="flex flex-wrap items-center justify-end gap-1.5">
            <span className={`pill border ${claimPill(claim.status).cls}`}>{claimPill(claim.status).label}</span>
            <span className={`pill border ${riskColor(claim.risk_level)}`}
              style={{ background: "rgba(255,255,255,.6)" }}>
              {claim.risk_level} risk
            </span>
            <span className="pill border bg-blush text-maroon border-clay">
              {supporting} supporting passage{supporting === 1 ? "" : "s"}
            </span>
          </span>
        }
      >
        <ErrorNote error={error} onDismiss={() => setError(null)} />
        <p className="font-display text-lg leading-snug">{claim.claim_text}</p>

        {contradicting > 0 || claim.status === "conflicting" ? (
          <div className="mt-3 rounded-lg border px-3 py-2 text-sm"
            style={{ background: "#fee2e2", color: "#7f1d1d", borderColor: "#fca5a5" }}>
            <span className="label" style={{ color: "#7f1d1d" }}>conflicting evidence</span>
            <p>
              Sources disagree on this claim{contradicting > 0 ? ` — ${contradicting} contradicting passage${contradicting === 1 ? "" : "s"} stored below` : ""}.
              Do not publish until a reviewer resolves the disagreement.
            </p>
          </div>
        ) : null}

        {(claim.status === "supported" || claim.status === "partially_supported") && supporting === 0 ? (
          <div className="mt-3 rounded-lg border px-3 py-2 text-sm"
            style={{ background: "#fef3c7", color: "#78350f", borderColor: "#fcd34d" }}>
            <span className="label" style={{ color: "#78350f" }}>no persisted evidence</span>
            <p>
              This claim is marked “{claim.status}” but has no supporting passage stored — its evidence
              was removed (for example with its source). It cannot be used for publishing until evidence
              is re-linked or a reviewer re-verifies it.
            </p>
          </div>
        ) : null}

        <dl className="mt-3 grid gap-x-6 gap-y-1.5 text-sm sm:grid-cols-2">
          <Meta k="risk" v={<span className={riskColor(claim.risk_level)}>{claim.risk_level}</span>} />
          <Meta k="kind" v={claim.kind} />
          <Meta k="population" v={claim.population ?? "—"} />
          <Meta k="study design" v={claim.study_design ?? "—"} />
          <Meta k="outcome" v={claim.outcome ?? "—"} />
          <Meta k="effect size" v={claim.effect_size ?? "—"} />
          <div className="sm:col-span-2">
            <Meta k="limitations" v={claim.limitations ?? "—"} />
          </div>
        </dl>

        <div className="mt-4 rounded-lg bg-blush/40 p-3 text-sm">
          <p className="label">verification notes</p>
          <p className="prose-quiet">{claim.verification_notes || "—"}</p>
        </div>

        {canReview ? (
          <div className="mt-4 space-y-2 border-t pt-3" style={{ borderColor: "rgba(181,135,119,.4)" }}>
            <div className="flex flex-wrap gap-2">
              <select className="input" style={{ maxWidth: "16rem" }} value={status} onChange={(e) => setStatus(e.target.value)}>
                {STATUSES.map((s) => (
                  <option key={s} value={s}>{s.replaceAll("_", " ")}</option>
                ))}
              </select>
              <button
                className="btn btn-primary"
                disabled={!dirty || busy}
                onClick={() => void onSave(status, notes)}
              >
                {busy ? "Saving…" : "save evidence status"}
              </button>
            </div>
            <textarea
              className="input"
              rows={2}
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="verification notes"
            />
            <p className="text-xs prose-quiet">
              Marking a claim supported without a linked passage is refused by the server.
            </p>
          </div>
        ) : (
          <p className="mt-4 border-t pt-3 text-sm prose-quiet" style={{ borderColor: "rgba(181,135,119,.4)" }}>
            Evidence status changes require the doctor/admin role (enforced server-side).
          </p>
        )}
      </Card>

      <Card title={`Located evidence (${claim.evidence.length})`}>
        {claim.evidence.length === 0 ? (
          <p className="prose-quiet text-sm">
            No evidence passage is stored for this claim. A claim without a persisted passage cannot be
            marked supported — if it was previously supported, its evidence was removed (for example with
            its source) and it must be re-linked or re-verified.
          </p>
        ) : (
          <ul className="space-y-3">
            {claim.evidence.map((ev) => (
              <li key={ev.id} className="rounded-lg border px-3 py-2" style={{ borderColor: "rgba(181,135,119,.4)" }}>
                <div className="flex flex-wrap items-center gap-2 text-xs">
                  <span
                    className="pill border"
                    style={
                      ev.relation === "supports"
                        ? { background: "#dcfce7", color: "#14532d", borderColor: "#86efac" }
                        : { background: "#fee2e2", color: "#7f1d1d", borderColor: "#fca5a5" }
                    }
                  >
                    {ev.relation === "contradicts" ? "contradicts claim" : ev.relation}
                  </span>
                  <span className="pill border bg-blush text-maroon border-clay">{ev.locator_method}</span>
                  <span className="prose-quiet">
                    {ev.source_title ?? ev.source_filename ?? ev.source_id}
                    {ev.page ? ` · p.${ev.page}` : ""}
                    {ev.section ? ` · ${ev.section}` : ""}
                    {ev.source_year ? ` (${ev.source_year})` : ""}
                  </span>
                </div>
                <blockquote className="mt-1.5 border-l-2 pl-2 text-sm italic" style={{ borderColor: "#C04E2A" }}>
                  {ev.excerpt}
                </blockquote>
                <div className="mt-1.5 flex flex-wrap items-center gap-3 text-xs">
                  <button className="btn btn-sm btn-secondary" onClick={() => void openExcerpt(ev.id)}>
                    view source context
                  </button>
                  {ev.doi ? (
                    <a className="hover:underline" style={{ color: "#8a6c60" }}
                      href={`https://doi.org/${ev.doi}`} target="_blank" rel="noreferrer">
                      doi:{ev.doi}
                    </a>
                  ) : null}
                  {ev.url ? (
                    <a className="hover:underline" style={{ color: "#8a6c60" }}
                      href={ev.url} target="_blank" rel="noreferrer">
                      {ev.url.length > 48 ? ev.url.slice(0, 48) + "…" : ev.url}
                    </a>
                  ) : null}
                </div>
              </li>
            ))}
          </ul>
        )}

        {excerpt && (
          <div className="mt-3 rounded-lg border p-3" style={{ borderColor: "rgba(181,135,119,.5)", background: "#fff" }}>
            <div className="flex items-start justify-between gap-2">
              <p className="text-sm font-semibold">
                {excerpt.title ?? excerpt.source_id}
                {excerpt.page ? ` — page ${excerpt.page}` : ""}
                {excerpt.section ? ` · ${excerpt.section}` : ""}
              </p>
              <button className="btn btn-sm btn-secondary" onClick={() => setExcerpt(null)}>
                close
              </button>
            </div>
            <p className="mono mt-2 flex flex-wrap gap-3 text-xs" style={{ color: "#8a6c60" }}>
              {excerpt.doi ? (
                <a className="hover:underline" href={`https://doi.org/${excerpt.doi}`} target="_blank" rel="noreferrer">
                  doi:{excerpt.doi}
                </a>
              ) : null}
              {excerpt.url ? (
                <a className="hover:underline" href={excerpt.url} target="_blank" rel="noreferrer">
                  {excerpt.url}
                </a>
              ) : null}
            </p>
            <pre className="mono mt-2 max-h-72 overflow-auto whitespace-pre-wrap rounded bg-blush/30 p-2">
              {excerpt.surrounding_text || excerpt.excerpt}
            </pre>
          </div>
        )}
      </Card>
    </div>
  );
}

function Meta({ k, v }: { k: string; v: ReactNode }) {
  return (
    <div className="flex gap-2">
      <dt className="shrink-0 font-semibold" style={{ color: "#8a6c60" }}>{k}</dt>
      <dd className="min-w-0">{v}</dd>
    </div>
  );
}
