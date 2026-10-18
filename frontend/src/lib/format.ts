export function fmtDate(iso?: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function fmtBytes(n?: number | null): string {
  if (n == null) return "—";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

export function fmtDuration(ms?: number | null): string {
  if (ms == null) return "—";
  if (ms < 1000) return `${ms} ms`;
  return `${(ms / 1000).toFixed(1)} s`;
}

const CLAIM_PILL: Record<string, { label: string; cls: string }> = {
  supported: { label: "supported", cls: "bg-emerald-100 text-emerald-900 border-emerald-300" },
  partially_supported: { label: "partially supported", cls: "bg-amber-100 text-amber-900 border-amber-300" },
  unsupported: { label: "unsupported", cls: "bg-red-100 text-red-900 border-red-300" },
  conflicting: { label: "conflicting", cls: "bg-orange-100 text-orange-900 border-orange-300" },
  needs_human_review: { label: "needs review", cls: "bg-blush text-maroon border-clay" },
};

const STATUS_PILL: Record<string, { label: string; cls: string }> = {
  succeeded: { label: "succeeded", cls: "bg-emerald-100 text-emerald-900 border-emerald-300" },
  passed: { label: "passed", cls: "bg-emerald-100 text-emerald-900 border-emerald-300" },
  ready: { label: "ready", cls: "bg-emerald-100 text-emerald-900 border-emerald-300" },
  extracted: { label: "extracted", cls: "bg-emerald-100 text-emerald-900 border-emerald-300" },
  approved: { label: "approved", cls: "bg-emerald-100 text-emerald-900 border-emerald-300" },
  ready_to_publish: { label: "ready to publish", cls: "bg-emerald-100 text-emerald-900 border-emerald-300" },
  published: { label: "published", cls: "bg-emerald-900 text-cream border-emerald-900" },
  running: { label: "running", cls: "bg-sky-100 text-sky-900 border-sky-300" },
  processing: { label: "processing", cls: "bg-sky-100 text-sky-900 border-sky-300" },
  queued: { label: "queued", cls: "bg-sky-100 text-sky-900 border-sky-300" },
  awaiting_review: { label: "awaiting review", cls: "bg-amber-100 text-amber-900 border-amber-300" },
  warnings: { label: "warnings", cls: "bg-amber-100 text-amber-900 border-amber-300" },
  draft: { label: "draft", cls: "bg-blush text-maroon border-clay" },
  pending: { label: "pending", cls: "bg-blush text-maroon border-clay" },
  needs_evidence_review: { label: "evidence issues", cls: "bg-amber-100 text-amber-900 border-amber-300" },
  failed: { label: "failed", cls: "bg-red-100 text-red-900 border-red-300" },
  unsupported_status: { label: "unsupported", cls: "bg-red-100 text-red-900 border-red-300" },
  rejected: { label: "rejected", cls: "bg-red-100 text-red-900 border-red-300" },
  changes_requested: { label: "changes requested", cls: "bg-amber-100 text-amber-900 border-amber-300" },
  withdrawn: { label: "withdrawn", cls: "bg-blush text-maroon border-clay" },
  uploaded: { label: "uploaded", cls: "bg-blush text-maroon border-clay" },
  skipped: { label: "skipped", cls: "bg-blush text-maroon border-clay" },
};

export function pillFor(status: string): { label: string; cls: string } {
  return (
    STATUS_PILL[status] ??
    CLAIM_PILL[status] ?? {
      label: status.replaceAll("_", " "),
      cls: "bg-blush text-maroon border-clay",
    }
  );
}

export function claimPill(status: string): { label: string; cls: string } {
  return CLAIM_PILL[status] ?? { label: status.replaceAll("_", " "), cls: "bg-blush text-maroon border-clay" };
}

export function riskColor(risk: string): string {
  if (risk === "high") return "text-red-800 font-semibold";
  if (risk === "medium") return "text-amber-800 font-semibold";
  return "text-emerald-800 font-semibold";
}
