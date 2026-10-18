import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import type { DashboardStats } from "../lib/types";
import { fmtDate } from "../lib/format";
import { Card, EmptyState, ErrorNote, Spinner, StatusPill } from "../components/ui";

function Stat({ label, value, tone }: { label: string; value: number | string; tone?: string }) {
  return (
    <div className="card px-4 py-3">
      <p className="text-xs font-semibold uppercase tracking-wider" style={{ color: "#8a6c60" }}>
        {label}
      </p>
      <p className="font-display text-3xl" style={{ color: tone ?? "#661414" }}>
        {value}
      </p>
    </div>
  );
}

export default function DashboardPage() {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .get<DashboardStats>("/api/dashboard/stats")
      .then(setStats)
      .catch(setError)
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <Spinner label="Loading dashboard…" />;
  if (error) return <ErrorNote error={error} onDismiss={() => setError(null)} />;
  if (!stats) return null;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl">Dashboard</h1>
          <p className="prose-quiet">
            Research → evidence → content → human review → publishing.
          </p>
        </div>
        {!stats.ai_enabled && (
          <span className="pill border bg-blush text-maroon border-clay">
            deterministic mode — no AI model configured; generation is rule-based and labelled as such
          </span>
        )}
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
        <Stat label="projects" value={stats.projects} />
        <Stat label="papers processed" value={stats.papers_processed} />
        <Stat label="drafts generated" value={stats.drafts_generated} />
        <Stat label="awaiting review" value={stats.awaiting_review} tone="#9a3e20" />
        <Stat label="approved" value={stats.approved_deliverables} tone="#166534" />
        <Stat label="failed runs" value={stats.failed_jobs} tone={stats.failed_jobs ? "#991b1b" : undefined} />
      </div>

      {stats.claim_stats && (
        <Card
          title={
            <span>
              Claims{" "}
              <span className="text-sm font-normal prose-quiet">
                verified with a located passage = status “supported” (persisted rows only)
              </span>
            </span>
          }
        >
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
            <Stat label="total claims" value={stats.claim_stats.total} />
            <Stat label="supported" value={stats.claim_stats.supported} tone="#166534" />
            <Stat label="partially supported" value={stats.claim_stats.partially_supported} tone="#9a3e20" />
            <Stat label="needs human review" value={stats.claim_stats.needs_human_review} tone="#9a3e20" />
            <Stat label="conflicting" value={stats.claim_stats.conflicting} tone="#9a3e20" />
            <Stat label="high risk" value={stats.claim_stats.high_risk} tone="#991b1b" />
          </div>
        </Card>
      )}

      {stats.pending_reviews && stats.pending_reviews.length > 0 && (
        <Card
          title={
            <span>
              Pending approvals{" "}
              <span className="text-sm font-normal prose-quiet">
                (doctor decisions are required on the exact version before publishing)
              </span>
            </span>
          }
        >
          <ul className="divide-y" style={{ borderColor: "rgba(181,135,119,.3)" }}>
            {stats.pending_reviews.map((p) => (
              <li key={p.deliverable_id} className="flex flex-wrap items-center justify-between gap-2 py-2.5">
                <div className="min-w-0">
                  <Link
                    to={`/projects/${p.project_id}/content`}
                    className="block truncate font-medium hover:underline"
                  >
                    {p.project_name} · {p.format}
                  </Link>
                  <p className="text-xs prose-quiet">
                    {p.version_number ? `v${p.version_number} · ` : ""}
                    submitted {fmtDate(p.submitted_at)}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <StatusPill status={p.status} />
                  <Link className="btn btn-sm btn-secondary" to="/review">
                    review
                  </Link>
                </div>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {stats.failed_stage_runs.length > 0 && (
        <Card
          title={
            <span>
              Failed stage runs{" "}
              <span className="text-sm font-normal prose-quiet">
                (failures are shown, never hidden — RULE 6)
              </span>
            </span>
          }
        >
          <ul className="space-y-2 text-sm">
            {stats.failed_stage_runs.map((f, i) => (
              <li key={i} className="rounded-lg border border-red-200 bg-red-50 px-3 py-2">
                <div className="flex flex-wrap items-center gap-2">
                  <strong>{f.project_name}</strong>
                  <span className="pill border bg-red-100 text-red-900 border-red-300">{f.stage}</span>
                  <span className="text-xs prose-quiet">{fmtDate(f.at)}</span>
                </div>
                <p className="mt-1 text-xs text-red-800">{f.error}</p>
              </li>
            ))}
          </ul>
        </Card>
      )}

      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="Recent projects" className="lg:col-span-1">
          {stats.recent_projects.length === 0 ? (
            <EmptyState
              title="No projects yet"
              hint="Create a project or load the attributed sample project."
              action={
                <Link className="btn btn-primary btn-sm" to="/projects">
                  go to research library
                </Link>
              }
            />
          ) : (
            <ul className="divide-y" style={{ borderColor: "rgba(181,135,119,.3)" }}>
              {stats.recent_projects.map((p) => (
                <li key={p.id} className="flex items-center justify-between gap-2 py-2.5">
                  <div className="min-w-0">
                    <Link to={`/projects/${p.id}`} className="block truncate font-medium hover:underline">
                      {p.name}
                    </Link>
                    <p className="text-xs prose-quiet">
                      {p.source_count} sources · {p.claim_count} claims · {p.deliverable_count} drafts
                    </p>
                  </div>
                  <StatusPill status={p.status} />
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card title="Pipeline status">
          {stats.pipeline_status.length === 0 ? (
            <p className="prose-quiet">No pipelines yet.</p>
          ) : (
            <ul className="space-y-2 text-sm">
              {stats.pipeline_status.map((row) => (
                <li key={row.project_id} className="flex items-center justify-between gap-2">
                  <div className="min-w-0">
                    <Link to={`/projects/${row.project_id}`} className="block truncate hover:underline">
                      {row.project_name}
                    </Link>
                    {row.failed_error && (
                      <p className="truncate text-xs text-red-800">{row.failed_error}</p>
                    )}
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-xs prose-quiet">
                      {row.stages_succeeded}/{row.stages_total}
                    </span>
                    <StatusPill status={row.run_status ?? "pending"} />
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card title="Recent activity">
          {stats.recent_activity.length === 0 ? (
            <p className="prose-quiet">Nothing yet.</p>
          ) : (
            <ul className="space-y-2 text-sm">
              {stats.recent_activity.map((a, i) => (
                <li key={i} className="flex gap-2">
                  <span
                    className="pill border shrink-0"
                    style={{ background: "rgba(192,78,42,.12)", borderColor: "rgba(192,78,42,.4)", color: "#9a3e20" }}
                  >
                    {a.type}
                  </span>
                  <span className="min-w-0">
                    <span className="prose-quiet">{a.text}</span>
                    <span className="ml-1 text-xs" style={{ color: "#8a6c60" }}>
                      {fmtDate(a.at)}
                    </span>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </div>
  );
}
