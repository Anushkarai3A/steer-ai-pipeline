import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, downloadAsset } from "../lib/api";
import type { Deliverable, DeliverableDetail, ExportKind, ExportResult } from "../lib/types";
import { fmtBytes, fmtDate } from "../lib/format";
import { Card, EmptyState, ErrorNote, Spinner, StatusPill } from "../components/ui";

const FORMAT_TITLES: Record<string, string> = {
  carousel: "Carousel",
  static: "Static post",
  reel: "Reel",
  deck: "Research deck",
};

const KINDS: { kind: ExportKind; label: string; desc: string }[] = [
  { kind: "full", label: "Full bundle (zip)", desc: "Assets + payload + evidence report + manifest + captions." },
  { kind: "evidence_report", label: "Evidence report (.md)", desc: "Human-readable claim + evidence walkthrough." },
  { kind: "source_manifest", label: "Source manifest (.json)", desc: "Machine-readable sources + claims + evidence." },
  { kind: "captions", label: "Captions / script (.txt)", desc: "Caption, hashtags, limitations and voiceover script." },
];

export default function ExportsPage() {
  const { projectId = "" } = useParams();
  const [deliverables, setDeliverables] = useState<Deliverable[] | null>(null);
  const [details, setDetails] = useState<Record<string, DeliverableDetail>>({});
  const [error, setError] = useState<unknown>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [exportKind, setExportKind] = useState<ExportKind>("full");

  const load = useCallback(() => {
    api
      .get<Deliverable[]>(`/api/projects/${projectId}/deliverables`)
      .then(async (list) => {
        setDeliverables(list);
        const pairs = await Promise.all(
          list.filter((d) => d.current_version_id).map(async (d) => [d.id, await api.get<DeliverableDetail>(`/api/deliverables/${d.id}`)] as const),
        );
        setDetails(Object.fromEntries(pairs));
      })
      .catch(setError);
  }, [projectId]);

  useEffect(load, [load]);

  async function exportOne(d: DeliverableDetail, kind: ExportKind) {
    setBusyId(d.id);
    setError(null);
    try {
      const res = await api.post<ExportResult>(`/api/deliverables/${d.id}/export`, { kind });
      await downloadAsset(res.asset_id, res.filename);
    } catch (err) {
      setError(err);
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <Link to={`/projects/${projectId}`} className="text-sm hover:underline" style={{ color: "#8a6c60" }}>
            ← project
          </Link>
          <h1 className="text-2xl">Export center</h1>
          <p className="prose-quiet">
            Download any generated deliverable — content, evidence report, source manifest or captions. Exports carry
            approval metadata; publishing remains a manual, gated step.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <label className="text-sm prose-quiet" htmlFor="kind-select">
            export kind:
          </label>
          <select
            id="kind-select"
            className="input"
            value={exportKind}
            onChange={(e) => setExportKind(e.target.value as ExportKind)}
          >
            {KINDS.map((k) => (
              <option key={k.kind} value={k.kind}>
                {k.label}
              </option>
            ))}
          </select>
          <button className="btn btn-secondary" onClick={load}>
            refresh
          </button>
        </div>
      </div>

      <ErrorNote error={error} onDismiss={() => setError(null)} />

      <Card title="Export kinds">
        <ul className="grid gap-2 sm:grid-cols-2">
          {KINDS.map((k) => (
            <li key={k.kind} className="rounded-lg border px-3 py-2 text-sm" style={{ borderColor: "rgba(181,135,119,.4)" }}>
              <span className="font-semibold">{k.label}</span>
              <p className="prose-quiet">{k.desc}</p>
            </li>
          ))}
        </ul>
      </Card>

      {!deliverables ? (
        <Spinner label="Loading deliverables…" />
      ) : deliverables.length === 0 ? (
        <EmptyState
          title="Nothing to export yet"
          hint="Generate content first — carousel, static post, reel or research deck."
          action={
            <Link className="btn btn-primary" to={`/projects/${projectId}/content`}>
              open content studio
            </Link>
          }
        />
      ) : (
        <div className="space-y-3">
          {deliverables.map((d) => {
            const full = details[d.id];
            const version = full?.current_version;
            const pptx = version?.assets.find((a) => a.kind === "deck_pptx");
            return (
              <div key={d.id} className="card px-4 py-3">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-display text-lg">{FORMAT_TITLES[d.format] ?? d.format}</span>
                      <StatusPill status={d.status} />
                      {version && <span className="pill border bg-blush text-maroon border-clay">v{version.version_number}</span>}
                      {d.approved_version_id === d.current_version_id && (
                        <span className="pill border bg-emerald-100 text-emerald-900 border-emerald-300">approved</span>
                      )}
                    </div>
                    <p className="mt-1 line-clamp-1 text-xs prose-quiet">{d.concept || "—"}</p>
                    {version && (
                      <p className="text-xs prose-quiet">
                        generated {fmtDate(version.created_at)} · {version.generation_mode_label || version.generation_mode}
                        {version.assets.length > 0 && ` · ${version.assets.length} asset(s)`}
                      </p>
                    )}
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {pptx && (
                      <button className="btn btn-sm btn-primary" onClick={() => void downloadAsset(pptx.id, pptx.filename)}>
                        download .pptx
                      </button>
                    )}
                    <button
                      className="btn btn-sm btn-secondary"
                      disabled={!full || busyId === d.id}
                      onClick={() => full && void exportOne(full, exportKind)}
                    >
                      {busyId === d.id ? "exporting…" : `export ${KINDS.find((k) => k.kind === exportKind)?.label ?? exportKind}`}
                    </button>
                  </div>
                </div>
                {version && version.assets.length > 0 && (
                  <ul className="mt-2 flex flex-wrap gap-2 text-xs">
                    {version.assets.map((a) => (
                      <li key={a.id}>
                        <button
                          className="btn btn-sm btn-secondary"
                          onClick={() => void downloadAsset(a.id, a.filename)}
                          title={`${a.kind} · ${fmtBytes(a.byte_size)}`}
                        >
                          {a.filename} · {fmtBytes(a.byte_size)}
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
