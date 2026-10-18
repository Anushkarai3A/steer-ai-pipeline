import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import type { PublishingItem } from "../lib/types";
import { fmtDate } from "../lib/format";
import { EmptyState, ErrorNote, Spinner, StatusPill } from "../components/ui";

const FORMAT_TITLES: Record<string, string> = {
  carousel: "Carousel",
  static: "Static post",
  reel: "Reel",
};

export default function PublishingPage() {
  const [items, setItems] = useState<PublishingItem[] | null>(null);
  const [statusFilter, setStatusFilter] = useState("all");
  const [error, setError] = useState<unknown>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [urls, setUrls] = useState<Record<string, string>>({});

  const load = useCallback(() => {
    api
      .get<PublishingItem[]>("/api/publishing")
      .then(setItems)
      .catch(setError);
  }, []);

  useEffect(load, [load]);

  const filtered = (items ?? []).filter(
    (i) => statusFilter === "all" || i.status === statusFilter,
  );

  async function prepare(item: PublishingItem) {
    setBusyId(item.id);
    setError(null);
    try {
      await api.post<PublishingItem>(`/api/publishing/${item.id}/prepare`);
      load();
    } catch (err) {
      setError(err);
    } finally {
      setBusyId(null);
    }
  }

  async function confirm(item: PublishingItem) {
    setBusyId(item.id);
    setError(null);
    try {
      await api.post<PublishingItem>(`/api/publishing/${item.id}/confirm`, {
        note: "confirmed in publishing queue",
        external_url: urls[item.id]?.trim() || undefined,
      });
      load();
    } catch (err) {
      setError(err);
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl">Publishing queue</h1>
          <p className="prose-quiet">
            Only approved, validation-clean versions get here. Steer never posts to social networks
            by itself — you publish externally, then confirm it here.
          </p>
        </div>
        <div className="flex gap-2">
          <select
            className="input"
            style={{ maxWidth: "14rem" }}
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
          >
            <option value="all">all statuses</option>
            <option value="ready_to_publish">ready to publish</option>
            <option value="queued">queued</option>
            <option value="published">published</option>
            <option value="withdrawn">withdrawn</option>
          </select>
          <button className="btn btn-secondary" onClick={load}>
            refresh
          </button>
        </div>
      </div>

      <ErrorNote error={error} onDismiss={() => setError(null)} />

      <div className="rounded-lg border border-sky-300 bg-sky-50 px-3 py-2 text-sm text-sky-900">
        <strong>Manual publish, honestly.</strong> “Confirm published” records that a human posted
        the exported bundle externally (and optional link). No API keys or auto-posting exist in
        this build.
      </div>

      {!items ? (
        <Spinner label="Loading publishing queue…" />
      ) : filtered.length === 0 ? (
        <EmptyState
          title="Nothing in this queue yet"
          hint="Deliverables enter the queue after a doctor approves their current version."
          action={
            <Link className="btn btn-secondary" to="/review">
              open review queue
            </Link>
          }
        />
      ) : (
        <ul className="space-y-3">
          {filtered.map((it) => (
            <li key={it.id} className="card px-4 py-3">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-display text-lg">{FORMAT_TITLES[it.format] ?? it.format}</span>
                <StatusPill status={it.status} />
                <Link
                  to={`/projects/${it.project_id}/content`}
                  className="text-sm hover:underline"
                  style={{ color: "#C04E2A" }}
                >
                  {it.project_name}
                </Link>
                <span className="pill border bg-blush text-maroon border-clay">v{it.version_number}</span>
                <StatusPill status={it.deliverable_status} />
                {it.has_export && (
                  <span className="pill border bg-emerald-100 text-emerald-900 border-emerald-300">
                    export ready
                  </span>
                )}
                <span className="text-xs prose-quiet">{fmtDate(it.created_at)}</span>
              </div>

              <p className="mt-1 text-sm">{it.concept || "—"}</p>

              {it.eligible ? (
                <p className="mt-1 text-sm" style={{ color: "#166534" }}>
                  ✓ eligible — approved version matches current version and validation is clean.
                </p>
              ) : (
                <div className="mt-1 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900">
                  <p className="font-semibold">Not publishable yet:</p>
                  <ul className="list-inside list-disc">
                    {it.reasons.map((r, i) => (
                      <li key={i}>{r}</li>
                    ))}
                  </ul>
                </div>
              )}

              <div className="mt-3 flex flex-wrap items-center gap-2">
                {it.status === "queued" && (
                  <button
                    className="btn btn-primary"
                    disabled={busyId === it.id}
                    onClick={() => void prepare(it)}
                  >
                    {busyId === it.id ? "Working…" : "prepare for publishing"}
                  </button>
                )}

                {it.status === "ready_to_publish" && (
                  <>
                    <input
                      className="input"
                      style={{ maxWidth: "20rem" }}
                      placeholder="optional public link after you post"
                      value={urls[it.id] ?? ""}
                      onChange={(e) => setUrls((u) => ({ ...u, [it.id]: e.target.value }))}
                    />
                    <button
                      className="btn btn-primary"
                      disabled={busyId === it.id}
                      onClick={() => void confirm(it)}
                    >
                      confirm published
                    </button>
                    <button
                      className="btn btn-secondary"
                      disabled={busyId === it.id}
                      onClick={() => void prepare(it)}
                    >
                      re-check eligibility
                    </button>
                  </>
                )}

                {it.status === "published" && it.published_at && (
                  <span className="text-sm prose-quiet">
                    published {fmtDate(it.published_at)} · {it.note || "no note"}
                  </span>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
