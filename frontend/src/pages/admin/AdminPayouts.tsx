import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, errorText } from "../../api/client";
import { useI18n } from "../../i18n/LanguageContext";
import { money, currentPeriod } from "../../lib/format";
import type { PayoutResult, PeriodInfo } from "../../api/types";

export default function AdminPayouts() {
  const { t } = useI18n();
  const qc = useQueryClient();
  const [ym, setYm] = useState(currentPeriod().ym);
  const period = useQuery<PeriodInfo>({
    queryKey: ["period", ym],
    queryFn: () => api.period(ym),
  });
  const lock = useMutation({
    mutationFn: () => api.lockPeriod(ym),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["period", ym] }),
  });
  const unlock = useMutation({
    mutationFn: () => api.unlockPeriod(ym),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["period", ym] }),
  });
  const [payout, setPayout] = useState<PayoutResult | null>(null);
  const [payoutErr, setPayoutErr] = useState<string | null>(null);
  const runPayout = useMutation({
    mutationFn: () => api.runPayout(ym),
    onSuccess: (r) => { setPayout(r); setPayoutErr(null); },
    onError: (e) => setPayoutErr(errorText(e, t) || t("admin.payouts.failed")),
  });

  return (
    <div>
      <h1 className="page-title">{t("admin.payouts.title")}</h1>
      <p className="page-sub">{t("admin.payouts.subtitle")}</p>

      <div className="card">
        <h2>{t("admin.payouts.periodControl")}</h2>
        <div className="row">
          <div className="shrink" style={{ minWidth: 160 }}>
            <label>{t("admin.payouts.period")}</label>
            <input value={ym} onChange={(e) => setYm(e.target.value)} />
          </div>
          <div className="shrink" style={{ alignSelf: "flex-end", display: "flex", gap: 8 }}>
            {period.data?.is_locked ? (
              <button className="ghost" onClick={() => unlock.mutate()}>{t("admin.payouts.unlock")}</button>
            ) : (
              <button className="ghost" onClick={() => lock.mutate()}>{t("admin.payouts.lock")}</button>
            )}
            <button className="primary" onClick={() => runPayout.mutate()}>{t("admin.payouts.run")}</button>
          </div>
          <div style={{ alignSelf: "flex-end" }}>
            {period.data && (
              <span className={`badge ${period.data.is_locked ? "cancelled" : "settled"}`}>
                {period.data.is_locked ? t("admin.payouts.locked") : t("admin.payouts.open")}
              </span>
            )}
          </div>
        </div>
      </div>

      {(payoutErr || payout) && (
        <div className="card">
          <h2>{t("admin.payouts.result")}</h2>
          {payoutErr && <div className="error">{payoutErr}</div>}
          {payout && (
            <>
              <div className="success">
                {t("admin.payouts.summary", { period: payout.period, count: payout.new_entries_paid, total: money(payout.total) })}
              </div>
              <table>
                <thead>
                  <tr>
                    <th>{t("common.agent")}</th>
                    <th>{t("common.code")}</th>
                    <th>{t("common.unit")}</th>
                    <th className="num">{t("admin.payouts.thPayable")}</th>
                  </tr>
                </thead>
                <tbody>
                  {payout.payable.map((p) => (
                    <tr key={p.agent_id}>
                      <td>{p.agent_name ?? `#${p.agent_id}`}</td>
                      <td className="muted">{p.agent_code ?? "—"}</td>
                      <td>{p.unit_code ? <span className="badge unit">{p.unit_code}</span> : <span className="muted">—</span>}</td>
                      <td className="num">{money(p.total)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </div>
      )}
    </div>
  );
}
