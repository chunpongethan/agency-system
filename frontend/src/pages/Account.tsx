import { useState, type FormEvent } from "react";
import { useMutation } from "@tanstack/react-query";
import { api, errorText } from "../api/client";
import { useI18n } from "../i18n/LanguageContext";
import { useAuth } from "../auth/AuthContext";

export default function Account() {
  const { t } = useI18n();
  const { me } = useAuth();
  const [form, setForm] = useState({ current: "", next: "", confirm: "" });
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const change = useMutation({
    mutationFn: () => api.changePassword(form.current, form.next),
    onSuccess: () => {
      setMsg(t("account.saved")); setError(null);
      setForm({ current: "", next: "", confirm: "" });
    },
    onError: (e) => { setError(errorText(e, t)); setMsg(null); },
  });

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    setMsg(null);
    if (form.next.length < 8) { setError(t("account.passwordTooShort")); return; }
    if (form.next !== form.confirm) { setError(t("account.passwordMismatch")); return; }
    setError(null);
    change.mutate();
  }

  return (
    <div>
      <h1 className="page-title">{t("account.title")}</h1>
      <p className="page-sub">{me?.name} · {me?.email}</p>

      <form className="card" onSubmit={onSubmit} style={{ maxWidth: 420 }}>
        <h2>{t("account.changePassword")}</h2>
        {msg && <div className="success">{msg}</div>}
        {error && <div className="error">{error}</div>}
        <label>{t("account.currentPassword")}</label>
        <input type="password" value={form.current} required autoComplete="current-password"
          onChange={(e) => setForm({ ...form, current: e.target.value })} />
        <label>{t("account.newPassword")}</label>
        <input type="password" value={form.next} required autoComplete="new-password"
          onChange={(e) => setForm({ ...form, next: e.target.value })} />
        <label>{t("account.confirmPassword")}</label>
        <input type="password" value={form.confirm} required autoComplete="new-password"
          onChange={(e) => setForm({ ...form, confirm: e.target.value })} />
        <div style={{ marginTop: 14 }}>
          <button className="primary" type="submit" disabled={change.isPending}>
            {change.isPending ? t("common.saving") : t("account.save")}
          </button>
        </div>
      </form>
    </div>
  );
}
