import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../lib/api";
import type { PipelineRun, ProjectDetail, SourceDetail, SummaryBucket } from "../lib/types";
import { fmtBytes, fmtDate, fmtDuration } from "../lib/format";
import { Card, EmptyState, ErrorNote, Spinner, StatusPill } from "../components/ui";

type Tab = "overview" | "sources" | "pipeline" | "findings";

export default function ProjectPage() {
  const { projectId = "" } = useParams();
  const [project, setProject] = useState<ProjectDetail | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [tab, setTab] = useState<Tab>("overview");

  const load = useCallback(() => {
    api
      .get<ProjectDetail>(`/api/projects/${projectId}`)
      .then(setProject)
      .catch(setError);
  }, [projectId]);

  useEffect(load, [load]);

  if (error) return <ErrorNote error={error} onDismiss={() => setError(null)} />;
  if (!project) return <Spinner label="Loading project…" />;

  const tabs: { id: Tab; label: string }[] = [
    { id: "overview", label: "Research summary" },
    { id: "sources", label: `Sources (${project.sources.length})` },
    { id: "pipeline", label: "Pipeline" },
    { id: "findings", label: `Findings (${project.findings.length})` },
  ];

  return (
    <div className="space-y-5">
      <div>
        <div className="flex flex-wrap items-center gap-2">
          <Link to="/projects" className="text-sm hover:underline" style={{ color: "#8a6c60" }}>
            ← research library
          </Link>
          <StatusPill status={project.status} />
          {project.demo_data && <span className="pill border bg-amber-100 text-amber-900 border-amber-300">demo data</span>}
        </div>
        <h1 className="mt-1 text-2xl">{project.name}</h1>
        {project.description && <p className="prose-quiet max-w-prose">{project.description}</p>}
        <div className="mt-3 flex flex-wrap gap-2">
          <Link className="btn btn-secondary btn-sm" to={`/projects/${projectId}/evidence`}>
            evidence lab ({project.claim_count} claims)
          </Link>
          <Link className="btn btn-secondary btn-sm" to={`/projects/${projectId}/content`}>
            content studio ({project.deliverable_count} drafts)
          </Link>
          <Link className="btn btn-secondary btn-sm" to={`/projects/${projectId}/powerpoint`}>
            powerpoint studio
          </Link>
          <Link className="btn btn-secondary btn-sm" to={`/projects/${projectId}/exports`}>
            export center
          </Link>
        </div>
      </div>

      <nav className="flex gap-1 border-b pb-1" style={{ borderColor: "rgba(181,135,119,.45)" }}>
        {tabs.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`rounded-t-lg px-3 py-1.5 text-sm font-medium ${
              tab === t.id ? "bg-paper text-maroon" : "text-ink/70 hover:bg-blush/50"
            }`}
            style={tab === t.id ? { boxShadow: "inset 0 -2px 0 #C04E2A" } : undefined}
          >
            {t.label}
          </button>
        ))}
      </nav>

      {tab === "overview" && <OverviewTab project={project} />}
      {tab === "sources" && <SourcesTab project={project} onChanged={load} />}
      {tab === "pipeline" && <PipelineTab project={project} onChanged={load} />}
      {tab === "findings" && <FindingsTab project={project} />}
    </div>
  );
}

// --- overview ---------------------------------------------------------------

const BUCKET_TITLES: Record<string, string> = {
  key_findings: "Key findings",
  limitations: "Limitations & caveats",
  population: "Population studied",
  methods: "Methods",
  study_design: "Study design",
  numbers: "Key numbers",
  practical_interpretation: "Practical interpretation",
};

function OverviewTab({ project }: { project: ProjectDetail }) {
  const summary = project.summary;
  if (!summary) {
    return (
      <EmptyState
        title="No summary yet"
        hint="Run the pipeline to extract findings, claims and evidence from the uploaded sources."
      />
    );
  }
  const mode = String(summary.mode ?? "");
  const modeLabel = String(summary.mode_label ?? "");
  const buckets = Object.entries(summary).filter(
    ([k, v]) => Array.isArray(v) && v.length > 0 && k !== "excluded_sources",
  ) as [string, SummaryBucket[]][];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="pill border bg-blush text-maroon border-clay">summary: {summary.status ?? "ready"}</span>
        {mode && (
          <span className="pill border bg-blush text-maroon border-clay">
            {modeLabel || mode}
          </span>
        )}
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        {buckets.map(([key, entries]) => (
          <Card key={key} title={BUCKET_TITLES[key] ?? key.replaceAll("_", " ")}>
            <ul className="space-y-2 text-sm">
              {entries.map((e, i) => (
                <li key={i} className="flex gap-2">
                  <span aria-hidden className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: "#C04E2A" }} />
                  <span>
                    {e.text}
                    <span className="ml-1 text-xs" style={{ color: "#8a6c60" }}>
                      {e.page ? `p.${e.page}` : ""}
                      {e.section ? ` · ${e.section}` : ""}
                    </span>
                  </span>
                </li>
              ))}
            </ul>
          </Card>
        ))}
      </div>
    </div>
  );
}

// --- sources ----------------------------------------------------------------

function SourcesTab({ project, onChanged }: { project: ProjectDetail; onChanged: () => void }) {
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [detail, setDetail] = useState<SourceDetail | null>(null);
  const [refKind, setRefKind] = useState<"doi" | "url">("doi");
  const [refValue, setRefValue] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  const full = project.sources.length >= 3;

  async function upload(file: File) {
    setBusy(true);
    setError(null);
    try {
      const fd = new FormData();
      fd.append("file", file);
      await api.upload(`/api/projects/${project.id}/sources`, fd);
      onChanged();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  async function addReference(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.post(`/api/projects/${project.id}/sources/reference`, {
        kind: refKind,
        doi: refKind === "doi" ? refValue.trim() : null,
        url: refKind === "url" ? refValue.trim() : null,
      });
      setRefValue("");
      onChanged();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  async function removeSource(id: string) {
    if (!confirm("Remove this source? Findings/claims from it disappear on the next run.")) return;
    setError(null);
    try {
      await api.del(`/api/projects/${project.id}/sources/${id}`);
      if (detail?.id === id) setDetail(null);
      onChanged();
    } catch (err) {
      setError(err);
    }
  }

  async function openDetail(id: string) {
    setError(null);
    try {
      setDetail(await api.get<SourceDetail>(`/api/projects/${project.id}/sources/${id}`));
    } catch (err) {
      setError(err);
    }
  }

  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <div className="space-y-4 lg:col-span-1">
        <Card title="Upload a PDF">
          <ErrorNote error={error} onDismiss={() => setError(null)} />
          <input
            ref={fileRef}
            type="file"
            accept="application/pdf"
            disabled={full || busy}
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) void upload(f);
            }}
          />
          <p className="mt-2 text-xs prose-quiet">
            {full
              ? "Maximum of 3 sources per project reached."
              : "Text-based PDFs only. Corrupt/scanned files fail honestly at extraction."}
          </p>
        </Card>

        <Card title="Add reference (DOI / URL)">
          <form onSubmit={addReference} className="space-y-2">
            <div className="flex gap-2">
              <select
                className="input"
                style={{ width: "5.5rem" }}
                value={refKind}
                onChange={(e) => setRefKind(e.target.value as "doi" | "url")}
              >
                <option value="doi">doi</option>
                <option value="url">url</option>
              </select>
              <input
                className="input"
                required
                placeholder={refKind === "doi" ? "10.1371/journal.pone.0337232" : "https://…"}
                value={refValue}
                onChange={(e) => setRefValue(e.target.value)}
              />
            </div>
            <button className="btn btn-secondary btn-sm" disabled={busy || !refValue.trim()}>
              add reference
            </button>
            <p className="text-xs prose-quiet">
              Paywalled sources are marked unsupported — steer never bypasses paywalls.
            </p>
          </form>
        </Card>
      </div>

      <div className="space-y-4 lg:col-span-2">
        <Card title="Sources">
          {project.sources.length === 0 ? (
            <EmptyState title="No sources yet" hint="Upload a PDF or add a DOI reference." />
          ) : (
            <table className="table-steer">
              <thead>
                <tr>
                  <th>source</th>
                  <th>status</th>
                  <th>pages</th>
                  <th>citation</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {project.sources.map((s) => (
                  <tr key={s.id}>
                    <td>
                      <button className="text-left font-medium hover:underline" onClick={() => void openDetail(s.id)}>
                        {s.title || s.original_filename || s.doi || s.id}
                      </button>
                      <p className="text-xs prose-quiet mono">{s.original_filename ?? s.url ?? s.doi ?? ""}</p>
                      {s.error && <p className="text-xs text-red-800">{s.error}</p>}
                    </td>
                    <td><StatusPill status={s.status} /></td>
                    <td>{s.page_count ?? "—"}</td>
                    <td className="text-xs prose-quiet">
                      {s.journal ? `${s.journal}${s.year ? ` (${s.year})` : ""}` : "metadata unavailable"}
                      {s.is_sample && (
                        <span className="ml-1 pill border bg-emerald-100 text-emerald-900 border-emerald-300">
                          open access sample
                        </span>
                      )}
                    </td>
                    <td className="text-right">
                      <button className="btn btn-sm btn-secondary" onClick={() => void removeSource(s.id)}>
                        remove
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>

        {detail && (
          <Card
            title={`Source detail — ${detail.title ?? detail.original_filename ?? detail.id}`}
            right={
              <button className="btn btn-sm btn-secondary" onClick={() => setDetail(null)}>
                close
              </button>
            }
          >
            <div className="space-y-3 text-sm">
              <div className="flex flex-wrap gap-2">
                <StatusPill status={detail.status} />
                <span className="pill border bg-blush text-maroon border-clay">
                  {detail.extraction_method ?? "no extraction"}
                </span>
                {detail.byte_size != null && <span className="pill border bg-blush text-maroon border-clay">{fmtBytes(detail.byte_size)}</span>}
              </div>
              <p className="prose-quiet">
                {detail.doi && <span className="mono">doi:{detail.doi} </span>}
                {detail.canonical_url && (
                  <a className="underline" href={detail.canonical_url} target="_blank" rel="noreferrer">
                    {detail.canonical_url}
                  </a>
                )}
              </p>
              {detail.pages.length > 0 && (
                <div className="space-y-2">
                  {detail.pages.map((p) => (
                    <details key={p.page} className="rounded-lg border px-3 py-2" style={{ borderColor: "rgba(181,135,119,.4)" }}>
                      <summary className="cursor-pointer text-sm font-medium">
                        page {p.page} <span className="text-xs prose-quiet">({p.chars} chars)</span>
                      </summary>
                      <pre className="mono mt-2 max-h-64 overflow-auto whitespace-pre-wrap">{p.preview}</pre>
                    </details>
                  ))}
                </div>
              )}
            </div>
          </Card>
        )}
      </div>
    </div>
  );
}

// --- pipeline ---------------------------------------------------------------

function PipelineTab({ project, onChanged }: { project: ProjectDetail; onChanged: () => void }) {
  const [runs, setRuns] = useState<PipelineRun[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [starting, setStarting] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);
  const timer = useRef<number | null>(null);

  const load = useCallback(() => {
    api
      .get<PipelineRun[]>(`/api/projects/${project.id}/runs`)
      .then(setRuns)
      .catch(setError);
  }, [project.id]);

  useEffect(load, [load]);

  const active =
    runs?.some((r) => r.status === "queued" || r.status === "running") ?? false;

  useEffect(() => {
    if (!active) return;
    timer.current = window.setInterval(load, 1500);
    return () => {
      if (timer.current) window.clearInterval(timer.current);
    };
  }, [active, load]);

  useEffect(() => {
    if (runs && runs.length > 0 && expanded === null) setExpanded(runs[0].id);
  }, [runs, expanded]);

  async function runPipeline() {
    setStarting(true);
    setError(null);
    try {
      const run = await api.post<PipelineRun>(`/api/projects/${project.id}/run?kind=full`);
      setExpanded(run.id);
      load();
      onChanged();
    } catch (err) {
      setError(err);
    } finally {
      setStarting(false);
    }
  }

  async function retry(runId: string) {
    setError(null);
    try {
      await api.post(`/api/pipeline/runs/${runId}/retry`);
      load();
    } catch (err) {
      setError(err);
    }
  }

  return (
    <div className="space-y-4">
      <ErrorNote error={error} onDismiss={() => setError(null)} />
      <div className="flex flex-wrap items-center gap-3">
        <button
          className="btn btn-primary"
          onClick={() => void runPipeline()}
          disabled={starting || active || project.sources.length === 0}
        >
          {active ? "Pipeline running…" : starting ? "Starting…" : "Run full pipeline"}
        </button>
        <span className="text-xs prose-quiet">
          stages: ingestion → extraction → metadata → synthesis → claims → evidence → content → validation → rendering
        </span>
      </div>

      {!runs ? (
        <Spinner />
      ) : runs.length === 0 ? (
        <EmptyState
          title="No runs yet"
          hint={project.sources.length === 0 ? "Add a source first." : "Run the pipeline to process the sources."}
        />
      ) : (
        <div className="space-y-3">
          {runs.map((run) => (
            <Card key={run.id}>
              <button
                className="flex w-full flex-wrap items-center justify-between gap-2 text-left"
                onClick={() => setExpanded(expanded === run.id ? null : run.id)}
              >
                <div className="flex flex-wrap items-center gap-2">
                  <StatusPill status={run.status} />
                  <span className="text-sm font-medium">{run.kind} run</span>
                  <span className="text-xs prose-quiet">{fmtDate(run.created_at)}</span>
                  <span className="pill border bg-blush text-maroon border-clay">{run.mode}</span>
                </div>
                <span className="text-xs prose-quiet">{expanded === run.id ? "hide stages ▲" : "show stages ▼"}</span>
              </button>

              {run.error && (
                <p className="mt-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-900">
                  {run.error}
                </p>
              )}

              {expanded === run.id && (
                <ol className="mt-3 space-y-1.5">
                  {run.stages
                    .slice()
                    .sort((a, b) => a.ordinal - b.ordinal)
                    .map((s) => (
                      <li key={s.id} className="rounded-lg border px-3 py-2" style={{ borderColor: "rgba(181,135,119,.35)" }}>
                        <div className="flex flex-wrap items-center gap-2 text-sm">
                          <span className="mono" style={{ color: "#8a6c60" }}>{s.ordinal + 1}</span>
                          <strong>{s.label}</strong>
                          <StatusPill status={s.status} />
                          <span className="text-xs prose-quiet">{fmtDuration(s.duration_ms)}</span>
                        </div>
                        {s.error && <p className="mt-1 text-xs text-red-800">{s.error}</p>}
                        {s.status === "failed" && (
                          <button className="btn btn-sm btn-secondary mt-1.5" onClick={() => void retry(run.id)}>
                            retry from this run
                          </button>
                        )}
                        {Object.keys(s.detail ?? {}).length > 0 && s.status === "succeeded" && (
                          <details className="mt-1">
                            <summary className="cursor-pointer text-xs prose-quiet">stage detail</summary>
                            <pre className="mono mt-1 max-h-48 overflow-auto rounded bg-blush/40 p-2">
                              {JSON.stringify(s.detail, null, 2)}
                            </pre>
                          </details>
                        )}
                      </li>
                    ))}
                </ol>
              )}
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}

// --- findings ---------------------------------------------------------------

function FindingsTab({ project }: { project: ProjectDetail }) {
  const [category, setCategory] = useState<string>("all");
  const categories = ["all", ...new Set(project.findings.map((f) => f.category))];
  const rows = project.findings.filter((f) => category === "all" || f.category === category);

  if (project.findings.length === 0) {
    return <EmptyState title="No findings yet" hint="Run the pipeline to extract findings from the sources." />;
  }

  return (
    <Card
      title="Extracted findings"
      right={
        <select className="input" style={{ width: "10rem" }} value={category} onChange={(e) => setCategory(e.target.value)}>
          {categories.map((c) => (
            <option key={c} value={c}>{c}</option>
          ))}
        </select>
      }
    >
      <table className="table-steer">
        <thead>
          <tr>
            <th>category</th>
            <th>finding</th>
            <th>location</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((f) => (
            <tr key={f.id}>
              <td><span className="pill border bg-blush text-maroon border-clay">{f.category}</span></td>
              <td>{f.text}</td>
              <td className="text-xs prose-quiet">
                {f.section ?? "—"}
                {f.page ? ` · p.${f.page}` : ""}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}
