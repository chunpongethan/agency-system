import { useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import { api, errorText } from "../api/client";
import { useI18n } from "../i18n/LanguageContext";
import LanguageToggle from "../components/LanguageToggle";

export default function ResetPassword() {
  const { t } = useI18n();
  const { token = "" } = useParams();
  const [form, setForm] = useState({ next: "", confirm: "" });
  const [error, setError] = useState<string | null>(null);

  const reset = useMutation({
    mutationFn: () => api.resetPassword(token, form.next),
    onError: (e) => setError(errorText(e, t)),
  });

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (form.next.length < 8) { setError(t("account.passwordTooShort")); return; }
    if (form.next !== form.confirm) { setError(t("account.passwordMismatch")); return; }
    setError(null);
    reset.mutate();
  }

  return (
    <div className="login-wrap">
      <form className="login-card" onSubmit={onSubmit}>
        <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 4 }}>
          <LanguageToggle />
        </div>
        <h1>{t("reset.title")}</h1>
        {reset.isSuccess ? (
          <>
            <div className="success" style={{ marginTop: 12 }}>{t("reset.done")}</div>
            <p className="hint"><Link to="/login">{t("reset.toLogin")}</Link></p>
          </>
        ) : (
          <>
            {error && <div className="error">{error}</div>}
            <label htmlFor="p">{t("account.newPassword")}</label>
            <input id="p" type="password" value={form.next} required autoFocus autoComplete="new-password"
              onChange={(e) => setForm({ ...form, next: e.target.value })} />
            <label htmlFor="c">{t("account.confirmPassword")}</label>
            <input id="c" type="password" value={form.confirm} required autoComplete="new-password"
              onChange={(e) => setForm({ ...form, confirm: e.target.value })} />
            <div style={{ marginTop: 18 }}>
              <button className="primary" type="submit" disabled={reset.isPending} style={{ width: "100%" }}>
                {reset.isPending ? t("common.saving") : t("reset.save")}
              </button>
            </div>
            <p className="hint"><Link to="/login">{t("forgot.backToLogin")}</Link></p>
          </>
        )}
      </form>
    </div>
  );
}
