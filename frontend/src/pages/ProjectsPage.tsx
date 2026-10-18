import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import type { Project } from "../lib/types";
import { fmtDate } from "../lib/format";
import { Card, EmptyState, ErrorNote, Spinner, StatusPill } from "../components/ui";

export default function ProjectsPage() {
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [sampleBusy, setSampleBusy] = useState(false);

  const load = useCallback(() => {
    api
      .get<Project[]>("/api/projects")
      .then(setProjects)
      .catch(setError);
  }, []);

  useEffect(load, [load]);

  async function create(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.post<Project>("/api/projects", {
        name: name.trim(),
        description: description.trim(),
      });
      setName("");
      setDescription("");
      load();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  async function loadSample() {
    setSampleBusy(true);
    setError(null);
    try {
      await api.post<Project>("/api/projects/sample");
      load();
    } catch (err) {
      setError(err);
    } finally {
      setSampleBusy(false);
    }
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl">Research library</h1>
          <p className="prose-quiet">
            Upload up to three PDFs per project, add DOI/URL references, then run the pipeline.
          </p>
        </div>
        <button className="btn btn-secondary" onClick={loadSample} disabled={sampleBusy}>
          {sampleBusy ? "Loading sample…" : "load sample project (real open-access papers)"}
        </button>
      </div>

      <ErrorNote error={error} onDismiss={() => setError(null)} />

      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="New project" className="lg:col-span-1">
          <form onSubmit={create} className="space-y-3">
            <div>
              <label className="label" htmlFor="pname">name</label>
              <input
                id="pname"
                className="input"
                required
                maxLength={255}
                placeholder="e.g. Sleep & blood pressure comms"
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </div>
            <div>
              <label className="label" htmlFor="pdesc">description</label>
              <textarea
                id="pdesc"
                className="input"
                rows={3}
                maxLength={4000}
                placeholder="What is this research about?"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
              />
            </div>
            <button className="btn btn-primary" disabled={busy || !name.trim()}>
              {busy ? "Creating…" : "Create project"}
            </button>
          </form>
        </Card>

        <Card title="All projects" className="lg:col-span-2">
          {!projects ? (
            <Spinner />
          ) : projects.length === 0 ? (
            <EmptyState title="No projects yet" hint="Create one on the left or load the sample project." />
          ) : (
            <table className="table-steer">
              <thead>
                <tr>
                  <th>project</th>
                  <th>status</th>
                  <th>sources</th>
                  <th>claims</th>
                  <th>drafts</th>
                  <th>updated</th>
                </tr>
              </thead>
              <tbody>
                {projects.map((p) => (
                  <tr key={p.id}>
                    <td>
                      <Link to={`/projects/${p.id}`} className="font-medium hover:underline">
                        {p.name}
                      </Link>
                      {p.demo_data && (
                        <span className="ml-2 pill border bg-amber-100 text-amber-900 border-amber-300">
                          demo data
                        </span>
                      )}
                      <p className="text-xs prose-quiet line-clamp-1">{p.description}</p>
                    </td>
                    <td><StatusPill status={p.status} /></td>
                    <td>{p.source_count}</td>
                    <td>{p.claim_count}</td>
                    <td>{p.deliverable_count}</td>
                    <td className="text-xs">{fmtDate(p.updated_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      </div>
    </div>
  );
}
