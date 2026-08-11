import { useState, type FormEvent } from "react";
import { useNavigate, Link } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { useI18n } from "../i18n/LanguageContext";
import { errorText } from "../api/client";
import LanguageToggle from "../components/LanguageToggle";

export default function Login() {
  const { login, me } = useAuth();
  const { t } = useI18n();
  const navigate = useNavigate();
  const [username, setUsername] = useState("A004");
  const [password, setPassword] = useState("demo1234");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const homeFor = (role?: string) => (role === "admin" ? "/admin" : "/");

  if (me) {
    navigate(homeFor(me.role), { replace: true });
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const profile = await login(username, password);
      navigate(homeFor(profile.role), { replace: true });
    } catch (err) {
      setError(errorText(err, t));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-wrap">
      <form className="login-card" onSubmit={onSubmit}>
        <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 4 }}>
          <LanguageToggle />
        </div>
        <h1>{t("login.brand")}</h1>
        <p className="muted" style={{ fontSize: 13 }}>{t("login.subtitle")}</p>
        {error && <div className="error">{error}</div>}
        <label htmlFor="u">{t("login.username")}</label>
        <input
          id="u"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          autoFocus
        />
        <label htmlFor="p">{t("login.password")}</label>
        <input
          id="p"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        <div style={{ marginTop: 18 }}>
          <button className="primary" type="submit" disabled={busy} style={{ width: "100%" }}>
            {busy ? t("login.signingIn") : t("login.signIn")}
          </button>
        </div>
        <p className="hint" style={{ marginTop: 12 }}>
          <Link to="/forgot-password">{t("login.forgot")}</Link>
        </p>
        <p className="hint">{t("login.hint")}</p>
      </form>
    </div>
  );
}
