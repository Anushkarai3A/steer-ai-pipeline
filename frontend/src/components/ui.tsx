import type { ReactNode } from "react";
import { ApiError } from "../lib/api";
import { pillFor } from "../lib/format";

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 text-sm" style={{ color: "#8a6c60" }}>
      <span
        aria-hidden
        className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2"
        style={{ borderColor: "#C04E2A", borderTopColor: "transparent" }}
      />
      {label ?? "Loading…"}
    </div>
  );
}

export function StatusPill({ status }: { status: string }) {
  const p = pillFor(status);
  return <span className={`pill border ${p.cls}`}>{p.label}</span>;
}

export function Card({
  children,
  className = "",
  title,
  right,
}: {
  children: ReactNode;
  className?: string;
  title?: ReactNode;
  right?: ReactNode;
}) {
  return (
    <section className={`card p-4 sm:p-5 ${className}`}>
      {(title || right) && (
        <header className="mb-3 flex items-start justify-between gap-3">
          {title && <h2 className="text-base font-semibold">{title}</h2>}
          {right}
        </header>
      )}
      {children}
    </section>
  );
}

export function ErrorNote({ error, onDismiss }: { error: unknown; onDismiss?: () => void }) {
  if (!error) return null;
  const err = error;
  const msg = err instanceof ApiError ? err.message : String((err as Error)?.message ?? err);
  const fields = err instanceof ApiError ? err.fields : [];
  return (
    <div
      role="alert"
      className="mb-4 rounded-lg border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-900"
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <strong className="font-semibold">Something went wrong. </strong>
          <span>{msg}</span>
          {fields.length > 0 && (
            <ul className="mt-1 list-inside list-disc text-xs">
              {fields.map((f, i) => (
                <li key={i}>
                  <span className="mono">{f.field}</span>: {f.message}
                </li>
              ))}
            </ul>
          )}
        </div>
        {onDismiss && (
          <button className="btn btn-sm btn-secondary" onClick={onDismiss}>
            dismiss
          </button>
        )}
      </div>
    </div>
  );
}

export function EmptyState({ title, hint, action }: { title: string; hint?: string; action?: ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed border-clay px-4 py-8 text-center">
      <p className="font-display text-lg">{title}</p>
      {hint && <p className="prose-quiet mx-auto mt-1 max-w-prose">{hint}</p>}
      {action && <div className="mt-3 flex justify-center">{action}</div>}
    </div>
  );
}

export function Pill({ children, tone = "neutral" }: { children: ReactNode; tone?: "neutral" | "rust" | "green" | "red" | "amber" }) {
  const tones: Record<string, string> = {
    neutral: "bg-blush text-maroon border-clay",
    rust: "bg-rust/15 text-rust-dark border-rust/40",
    green: "bg-emerald-100 text-emerald-900 border-emerald-300",
    red: "bg-red-100 text-red-900 border-red-300",
    amber: "bg-amber-100 text-amber-900 border-amber-300",
  };
  return <span className={`pill border ${tones[tone]}`}>{children}</span>;
}

export function FieldError({ fields, name }: { fields: { field: string; message: string }[]; name: string }) {
  const f = fields.find((x) => x.field === name || x.field.endsWith(name));
  if (!f) return null;
  return <p className="mt-1 text-xs text-red-700">{f.message}</p>;
}
