import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../../api/client";
import { money, currentPeriod } from "../../lib/format";
import type { PayoutResult, PeriodInfo } from "../../api/types";

export default function AdminPayouts() {
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
    onError: (e) => setPayoutErr(e instanceof ApiError ? e.message : "Failed"),
  });

  return (
    <div>
      <h1 className="page-title">Periods &amp; payouts</h1>
      <p className="page-sub">Lock a period to freeze its statements, then run the payout batch</p>

      <div className="card">
        <h2>Period control</h2>
        <div className="row">
          <div className="shrink" style={{ minWidth: 160 }}>
            <label>Period (YYYY-MM)</label>
            <input value={ym} onChange={(e) => setYm(e.target.value)} />
          </div>
          <div className="shrink" style={{ alignSelf: "flex-end", display: "flex", gap: 8 }}>
            {period.data?.is_locked ? (
              <button className="ghost" onClick={() => unlock.mutate()}>Unlock period</button>
            ) : (
              <button className="ghost" onClick={() => lock.mutate()}>Lock period</button>
            )}
            <button className="primary" onClick={() => runPayout.mutate()}>Run payout</button>
          </div>
          <div style={{ alignSelf: "flex-end" }}>
            {period.data && (
              <span className={`badge ${period.data.is_locked ? "cancelled" : "settled"}`}>
                {period.data.is_locked ? "locked" : "open"}
              </span>
            )}
          </div>
        </div>
      </div>

      {(payoutErr || payout) && (
        <div className="card">
          <h2>Payout result</h2>
          {payoutErr && <div className="error">{payoutErr}</div>}
          {payout && (
            <>
              <div className="success">
                Payout {payout.period}: {payout.new_entries_paid} entries paid this run ·
                total {money(payout.total)}
              </div>
              <table>
                <thead><tr><th>Agent</th><th className="num">Payable</th></tr></thead>
                <tbody>
                  {payout.payable.map((p) => (
                    <tr key={p.agent_id}>
                      <td>#{p.agent_id}</td>
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
