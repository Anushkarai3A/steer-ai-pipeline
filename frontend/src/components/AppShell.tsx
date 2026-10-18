import { useEffect, useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import type { HealthInfo } from "../lib/types";
import { useAuth } from "../state/auth";
import { Pill } from "./ui";

const NAV = [
  { to: "/", label: "Dashboard", end: true },
  { to: "/projects", label: "Research" },
  { to: "/review", label: "Doctor review" },
  { to: "/publishing", label: "Publishing" },
  { to: "/settings", label: "Settings" },
];

export default function AppShell() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [health, setHealth] = useState<HealthInfo | null>(null);

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth(null));
  }, []);

  return (
    <div className="min-h-screen">
      <header
        className="sticky top-0 z-20 border-b"
        style={{ borderColor: "rgba(181,135,119,.45)", background: "rgba(248,242,235,.94)", backdropFilter: "blur(6px)" }}
      >
        <div className="mx-auto flex max-w-6xl items-center gap-4 px-4 py-2.5">
          <NavLink to="/" className="font-display text-xl tracking-tight" style={{ color: "#661414" }}>
            steer<span style={{ color: "#C04E2A" }}>.</span>
          </NavLink>

          <nav className="flex items-center gap-1 text-sm">
            {NAV.map((n) => (
              <NavLink
                key={n.to}
                to={n.to}
                end={n.end}
                className={({ isActive }) =>
                  `rounded-full px-3 py-1.5 font-medium transition ${
                    isActive ? "text-white" : "text-ink hover:bg-blush/60"
                  }`
                }
                style={({ isActive }) =>
                  isActive ? { background: "#C04E2A" } : undefined
                }
              >
                {n.label}
              </NavLink>
            ))}
          </nav>

          <div className="ml-auto flex items-center gap-2">
            {health && (
              <Pill tone={health.ai_enabled ? "green" : "neutral"}>
                {health.ai_enabled ? `AI: ${health.llm_provider}` : "deterministic mode"}
              </Pill>
            )}
            {user && (
              <div className="flex items-center gap-2 text-sm">
                <span className="hidden sm:inline">{user.name}</span>
                <Pill tone="rust">{user.role}</Pill>
                <button
                  className="btn btn-sm btn-secondary"
                  onClick={() => {
                    logout();
                    navigate("/login");
                  }}
                >
                  sign out
                </button>
              </div>
            )}
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-4 py-6">
        <Outlet />
      </main>

      <footer className="mx-auto max-w-6xl px-4 pb-8 pt-4 text-xs" style={{ color: "#8a6c60" }}>
        steer. research studio — generated content is never published without a
        doctor's approval on the exact version being published.
      </footer>
    </div>
  );
}
