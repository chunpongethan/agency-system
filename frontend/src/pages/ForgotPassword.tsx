import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import { api } from "../api/client";
import { useI18n } from "../i18n/LanguageContext";
import LanguageToggle from "../components/LanguageToggle";

export default function ForgotPassword() {
  const { t } = useI18n();
  const [email, setEmail] = useState("");

  // Always succeeds (the API never reveals whether the email exists).
  const send = useMutation({ mutationFn: () => api.forgotPassword(email) });

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    send.mutate();
  }

  return (
    <div className="login-wrap">
      <form className="login-card" onSubmit={onSubmit}>
        <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 4 }}>
          <LanguageToggle />
        </div>
        <h1>{t("forgot.title")}</h1>
        <p className="muted" style={{ fontSize: 13 }}>{t("forgot.subtitle")}</p>
        {send.isSuccess ? (
          <div className="success" style={{ marginTop: 12 }}>{t("forgot.sent")}</div>
        ) : (
          <>
            <label htmlFor="e">{t("common.email")}</label>
            <input id="e" type="email" value={email} required autoFocus
              onChange={(e) => setEmail(e.target.value)} />
            <div style={{ marginTop: 18 }}>
              <button className="primary" type="submit" disabled={send.isPending} style={{ width: "100%" }}>
                {send.isPending ? t("forgot.sending") : t("forgot.send")}
              </button>
            </div>
          </>
        )}
        <p className="hint"><Link to="/login">{t("forgot.backToLogin")}</Link></p>
      </form>
    </div>
  );
}
