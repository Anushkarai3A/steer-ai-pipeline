import { useEffect, useState } from "react";
import { api } from "../lib/api";
import type { SettingsInfo } from "../lib/types";
import { Card, ErrorNote, Spinner } from "../components/ui";

function Row({ label, value }: { label: string; value: string | boolean | number }) {
  const display =
    typeof value === "boolean" ? (value ? "yes" : "no") : String(value ?? "—");
  return (
    <div className="flex items-center justify-between gap-3 border-b py-2 text-sm last:border-b-0" style={{ borderColor: "rgba(181,135,119,.3)" }}>
      <span className="prose-quiet">{label}</span>
      <span className="mono font-medium">{display}</span>
    </div>
  );
}

export default function SettingsPage() {
  const [settings, setSettings] = useState<SettingsInfo | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    api.get<SettingsInfo>("/api/settings").then(setSettings).catch(setError);
  }, []);

  if (error) return <ErrorNote error={error} onDismiss={() => setError(null)} />;
  if (!settings) return <Spinner label="Loading settings…" />;

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl">Settings</h1>
        <p className="prose-quiet">
          Runtime configuration for this deployment. Secrets and API keys are never exposed here.
        </p>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <Card title="Application">
          <Row label="App" value={settings.app} />
          <Row label="Version" value={settings.version} />
          <Row label="Environment" value={settings.environment} />
          <Row label="Demo accounts" value={settings.demo} />
        </Card>

        <Card title="AI generation">
          <Row label="AI enabled" value={settings.ai.enabled} />
          <Row label="Provider" value={settings.ai.provider} />
          <Row label="Model" value={settings.ai.model ?? "—"} />
          {!settings.ai.enabled && (
            <p className="mt-2 rounded bg-blush/50 px-2 py-1 text-xs prose-quiet">
              Deterministic mode — generation is rule-based and clearly labelled. No AI model is configured.
            </p>
          )}
        </Card>

        <Card title="Database">
          <Row label="Engine" value={settings.database.engine} />
          <Row label="Connected" value={settings.database.connected} />
        </Card>

        <Card title="Worker">
          <Row label="Kind" value={settings.worker.kind} />
          <Row label="Max workers" value={settings.worker.max_workers} />
        </Card>

        <Card title="Rendering">
          <Row label="ffmpeg available" value={settings.rendering.ffmpeg_available} />
          <Row label="PowerPoint (pptx) available" value={settings.rendering.pptx_available} />
          <Row label="Reel FPS" value={settings.rendering.reel_fps} />
          <Row label="Carousel max slides" value={settings.rendering.carousel_max_slides} />
          {!settings.rendering.ffmpeg_available && (
            <p className="mt-2 rounded bg-amber-50 px-2 py-1 text-xs text-amber-900">
              No ffmpeg found — reels render as a labelled storyboard package instead of an MP4 (never a fake video).
            </p>
          )}
        </Card>

        <Card title="Limits">
          <Row label="Max upload size" value={`${Math.round(settings.limits.max_upload_bytes / (1024 * 1024))} MB`} />
          <Row label="Min sources / project" value={settings.limits.min_sources_per_project} />
          <Row label="Max sources / project" value={settings.limits.max_sources_per_project} />
        </Card>
      </div>
    </div>
  );
}
