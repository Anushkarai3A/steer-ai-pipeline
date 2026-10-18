import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../state/auth";
import { ErrorNote } from "../components/ui";

const DEMO = [
  { email: "editor@steer.demo", role: "editor" },
  { email: "doctor@steer.demo", role: "doctor" },
  { email: "admin@steer.demo", role: "admin" },
];

export default function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("editor@steer.demo");
  const [password, setPassword] = useState("demo1234");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(email.trim(), password);
      navigate("/");
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto flex min-h-screen max-w-md flex-col justify-center px-4">
      <div className="mb-6 text-center">
        <p className="font-display text-4xl" style={{ color: "#661414" }}>
          steer<span style={{ color: "#C04E2A" }}>.</span>
        </p>
        <p className="prose-quiet mt-1">evidence-linked content, reviewed before it ships</p>
      </div>

      <section className="card p-6">
        <h1 className="mb-4 text-lg font-semibold">Sign in</h1>
        <ErrorNote error={error} onDismiss={() => setError(null)} />
        <form onSubmit={submit} className="space-y-4">
          <div>
            <label className="label" htmlFor="email">email</label>
            <input
              id="email"
              className="input"
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </div>
          <div>
            <label className="label" htmlFor="password">password</label>
            <input
              id="password"
              className="input"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>
          <button className="btn btn-primary w-full" disabled={busy}>
            {busy ? "Signing in…" : "Sign in"}
          </button>
        </form>

        <div className="mt-5 border-t pt-4" style={{ borderColor: "rgba(181,135,119,.4)" }}>
          <p className="label">demo accounts (password demo1234)</p>
          <div className="flex flex-wrap gap-2">
            {DEMO.map((d) => (
              <button
                key={d.email}
                className="btn btn-sm btn-secondary"
                onClick={() => {
                  setEmail(d.email);
                  setPassword("demo1234");
                }}
              >
                {d.role}
              </button>
            ))}
          </div>
        </div>
      </section>
    </div>
  );
}
