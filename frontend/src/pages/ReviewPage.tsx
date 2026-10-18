import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import type { DeliverableDetail, Project } from "../lib/types";
import { fmtDate } from "../lib/format";
import { Card, EmptyState, ErrorNote, Spinner, StatusPill } from "../components/ui";
import { PayloadPreview } from "./ContentPage";
import { useAuth } from "../state/auth";

const FORMAT_TITLES: Record<string, string> = {
  carousel: "Carousel",
  static: "Static post",
  reel: "Reel",
};

export default function ReviewPage() {
  const { user } = useAuth();
  const canDecide = user?.role === "doctor" || user?.role === "admin";

  const [queue, setQueue] = useState<DeliverableDetail[] | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [comments, setComments] = useState("");
  const [newComment, setNewComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const load = useCallback(() => {
    api
      .get<DeliverableDetail[]>("/api/review/queue")
      .then((rows) => {
        setQueue(rows);
        setSelectedId((cur) =>
          cur && rows.some((r) => r.id === cur) ? cur : rows[0]?.id ?? null,
        );
      })
      .catch(setError);
    api
      .get<Project[]>("/api/projects")
      .then(setProjects)
      .catch(() => undefined);
  }, []);

  useEffect(load, [load]);

  const selected = queue?.find((q) => q.id === selectedId) ?? null;
  const projectName = (id: string) => projects.find((p) => p.id === id)?.name ?? id;

  async function decide(decision: "approved" | "rejected" | "changes_requested") {
    if (!selected || !selected.current_version_id) return;
    setBusy(true);
    setError(null);
    try {
      await api.post(`/api/deliverables/${selected.id}/reviews`, {
        decision,
        comments: comments.trim(),
        version_id: selected.current_version_id,
      });
      setComments("");
      load();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  async function addComment() {
    if (!selected || !newComment.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await api.post(`/api/deliverables/${selected.id}/comments`, { body: newComment.trim() });
      setNewComment("");
      const fresh = await api.get<DeliverableDetail>(`/api/deliverables/${selected.id}`);
      setQueue((rows) => (rows ?? []).map((r) => (r.id === fresh.id ? fresh : r)));
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
          <h1 className="text-2xl">Doctor review</h1>
          <p className="prose-quiet">
            Approve or reject the exact generated version you inspected — approvals carry the
            version id and cannot be satisfied by a later edit.
          </p>
        </div>
        <button className="btn btn-secondary" onClick={load}>
          refresh queue
        </button>
      </div>

      <ErrorNote error={error} onDismiss={() => setError(null)} />

      {!canDecide && (
        <div className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900">
          You are signed in as <strong>{user?.role}</strong>. You can read the queue and comment,
          but approval decisions are rejected server-side for non-doctor roles.
        </div>
      )}

      {!queue ? (
        <Spinner label="Loading review queue…" />
      ) : queue.length === 0 ? (
        <EmptyState
          title="Nothing awaiting review"
          hint="Editors submit content from the Content studio; submitted versions appear here."
          action={
            <Link className="btn btn-secondary" to="/projects">
              go to research
            </Link>
          }
        />
      ) : (
        <div className="grid gap-4 lg:grid-cols-5">
          <Card title={`Queue (${queue.length})`} className="lg:col-span-2">
            <ul className="max-h-[34rem] space-y-2 overflow-auto pr-1">
              {queue.map((d) => (
                <li key={d.id}>
                  <button
                    onClick={() => {
                      setSelectedId(d.id);
                      setComments("");
                    }}
                    className={`w-full rounded-lg border px-3 py-2 text-left transition ${
                      selectedId === d.id ? "bg-blush/70" : "bg-white/50 hover:bg-blush/40"
                    }`}
                    style={{ borderColor: selectedId === d.id ? "#C04E2A" : "rgba(181,135,119,.4)" }}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-semibold">{FORMAT_TITLES[d.format] ?? d.format}</span>
                      <span className="pill border bg-amber-100 text-amber-900 border-amber-300">
                        {projectName(d.project_id)}
                      </span>
                    </div>
                    <p className="mt-0.5 line-clamp-2 text-sm">{d.concept || "—"}</p>
                    <p className="mt-1 text-xs" style={{ color: "#8a6c60" }}>
                      v{d.current_version?.version_number ?? "?"} · updated{" "}
                      {fmtDate(d.current_version?.created_at ?? d.updated_at)}
                    </p>
                  </button>
                </li>
              ))}
            </ul>
          </Card>

          <div className="lg:col-span-3">
            {!selected ? (
              <Card><p className="prose-quiet">Select a deliverable to review.</p></Card>
            ) : (
              <div className="space-y-4">
                <div className="card flex flex-wrap items-center gap-2 px-4 py-3">
                  <span className="font-display text-lg">
                    {FORMAT_TITLES[selected.format] ?? selected.format}
                  </span>
                  <StatusPill status={selected.status} />
                  <Link
                    to={`/projects/${selected.project_id}/content`}
                    className="text-sm hover:underline"
                    style={{ color: "#C04E2A" }}
                  >
                    {projectName(selected.project_id)}
                  </Link>
                  {selected.blocked_claims.length > 0 && (
                    <span className="pill border bg-red-100 text-red-900 border-red-300">
                      blocked: {selected.blocked_claims.join(", ")}
                    </span>
                  )}
                  <Link
                    to={`/projects/${selected.project_id}/evidence`}
                    className="text-sm hover:underline"
                    style={{ color: "#8a6c60" }}
                  >
                    open evidence →
                  </Link>
                </div>

                <Card title="Version preview">
                  {selected.current_version ? (
                    <PayloadPreview
                      format={selected.format}
                      payload={selected.current_version.payload}
                    />
                  ) : (
                    <p className="prose-quiet text-sm">No version to review.</p>
                  )}
                </Card>

                <ValidationSummary detail={selected} />

                <div className="grid gap-4 lg:grid-cols-2">
                  <Card title="Your decision">
                    <textarea
                      className="input"
                      rows={4}
                      placeholder="review comments (what should change, or why this is approved)"
                      value={comments}
                      onChange={(e) => setComments(e.target.value)}
                    />
                    <div className="mt-3 flex flex-wrap gap-2">
                      <button
                        className="btn btn-primary"
                        disabled={busy || !selected.current_version_id}
                        onClick={() => void decide("approved")}
                      >
                        approve this version
                      </button>
                      <button
                        className="btn btn-secondary"
                        disabled={busy || !selected.current_version_id}
                        onClick={() => void decide("changes_requested")}
                      >
                        request changes
                      </button>
                      <button
                        className="btn btn-secondary"
                        disabled={busy || !selected.current_version_id}
                        onClick={() => void decide("rejected")}
                      >
                        reject
                      </button>
                    </div>
                    <p className="mt-2 text-xs prose-quiet">
                      Approving binds version{" "}
                      <span className="mono">{selected.current_version?.version_number}</span> (
                      <span className="mono">{selected.current_version_id}</span>). The server
                      rejects a stale version id if the content changed meanwhile.
                    </p>
                    {!canDecide && (
                      <p className="mt-1 text-xs" style={{ color: "#9a3e20" }}>
                        Requires the doctor/admin role — enforced server-side.
                      </p>
                    )}
                  </Card>

                  <Card title={`Comments (${selected.comments.length})`}>
                    <ul className="mb-3 max-h-48 space-y-2 overflow-auto text-sm">
                      {selected.comments.length === 0 && <li className="prose-quiet">No comments yet.</li>}
                      {selected.comments.map((c) => (
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
                        value={newComment}
                        onChange={(e) => setNewComment(e.target.value)}
                        onKeyDown={(e) => e.key === "Enter" && void addComment()}
                      />
                      <button
                        className="btn btn-secondary"
                        disabled={busy || !newComment.trim()}
                        onClick={() => void addComment()}
                      >
                        post
                      </button>
                    </div>
                  </Card>
                </div>

                {selected.reviews.length > 0 && (
                  <Card title="Past decisions on this deliverable">
                    <ul className="space-y-1.5 text-sm">
                      {selected.reviews.map((r) => (
                        <li key={r.id} className="flex flex-wrap items-center gap-2">
                          <StatusPill status={r.decision} />
                          <span className="mono text-xs">v{r.version_number}</span>
                          <strong>{r.reviewer_name ?? "reviewer"}</strong>
                          <span className="prose-quiet text-xs">{fmtDate(r.created_at)}</span>
                          {r.comments && <span className="prose-quiet">— {r.comments}</span>}
                        </li>
                      ))}
                    </ul>
                  </Card>
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function ValidationSummary({ detail }: { detail: DeliverableDetail }) {
  const v = detail.current_version;
  const issues = v?.validation?.issues ?? [];
  const errors = issues.filter((i) => i.severity === "error");
  const warnings = issues.filter((i) => i.severity === "warning");
  return (
    <Card
      title="Validation before you decide"
      right={
        <div className="flex gap-2">
          <span className="pill border bg-red-100 text-red-900 border-red-300">{errors.length} errors</span>
          <span className="pill border bg-amber-100 text-amber-900 border-amber-300">{warnings.length} warnings</span>
        </div>
      }
    >
      {issues.length === 0 ? (
        <p className="text-sm prose-quiet">
          Deterministic rules found no issues on this version. This is not a clinical fact-check —
          use your expertise, not just the green status.
        </p>
      ) : (
        <ul className="space-y-1.5">
          {issues.slice(0, 12).map((i, idx) => (
            <li
              key={idx}
              className={`rounded-lg border px-3 py-1.5 text-sm ${
                i.severity === "error" ? "border-red-200 bg-red-50" : "border-amber-200 bg-amber-50"
              }`}
            >
              <span className={`mono mr-2 text-xs font-semibold ${i.severity === "error" ? "text-red-800" : "text-amber-800"}`}>
                {i.rule}
              </span>
              {i.message}
              {i.claim_id && <span className="mono ml-2 text-xs" style={{ color: "#C04E2A" }}>{i.claim_id}</span>}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
