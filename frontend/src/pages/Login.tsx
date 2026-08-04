import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";

export default function Login() {
  const { login, me } = useAuth();
  const navigate = useNavigate();
  const [username, setUsername] = useState("A001");
  const [password, setPassword] = useState("demo1234");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (me) {
    navigate("/", { replace: true });
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await login(username, password);
      navigate("/", { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-wrap">
      <form className="login-card" onSubmit={onSubmit}>
        <h1>Agency Management</h1>
        <p className="muted" style={{ fontSize: 13 }}>Sign in to continue</p>
        {error && <div className="error">{error}</div>}
        <label htmlFor="u">Agent code or email</label>
        <input
          id="u"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          autoFocus
        />
        <label htmlFor="p">Password</label>
        <input
          id="p"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        <div style={{ marginTop: 18 }}>
          <button className="primary" type="submit" disabled={busy} style={{ width: "100%" }}>
            {busy ? "Signing in…" : "Sign in"}
          </button>
        </div>
        <p className="hint">
          Demo: <code>A001</code> (admin), <code>A003</code> (manager),
          <code> A004</code> (agent) — password <code>demo1234</code>.
        </p>
      </form>
    </div>
  );
}
