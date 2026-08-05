import { useState, type FormEvent } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../../api/client";
import { pct } from "../../lib/format";

const PRODUCT_TYPES = ["insurance", "fund", "eam_account", "other"];

export default function AdminRules() {
  const qc = useQueryClient();
  const rules = useQuery({ queryKey: ["overrideRules"], queryFn: () => api.overrideRules() });

  const [rule, setRule] = useState({
    product_type: "insurance", level_gap: "1", override_rate: "0.25",
    valid_from: "", valid_to: "",
  });
  const [ruleErr, setRuleErr] = useState<string | null>(null);
  const createRule = useMutation({
    mutationFn: () =>
      api.createOverrideRule({
        product_type: rule.product_type,
        level_gap: Number(rule.level_gap),
        override_rate: rule.override_rate,
        valid_from: rule.valid_from || undefined,
        valid_to: rule.valid_to || undefined,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["overrideRules"] });
      setRuleErr(null);
    },
    onError: (e) => setRuleErr(e instanceof ApiError ? e.message : "Failed"),
  });

  return (
    <div>
      <h1 className="page-title">Override rules</h1>
      <p className="page-sub">
        An upline earns this percentage of the closing agent's commission, by level gap (1st–4th upline).
      </p>

      <div className="card">
        <h2>Current rules</h2>
        <table>
          <thead>
            <tr><th>Product type</th><th>Gap</th><th className="num">Rate (of commission)</th><th>Valid from</th><th>Valid to</th></tr>
          </thead>
          <tbody>
            {rules.data?.map((r) => (
              <tr key={r.id}>
                <td>{r.product_type}</td><td>{r.level_gap}</td>
                <td className="num">{pct(r.override_rate)}</td>
                <td className="muted">{r.valid_from}</td>
                <td className="muted">{r.valid_to ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <form className="card" onSubmit={(e: FormEvent) => { e.preventDefault(); createRule.mutate(); }}>
        <h2>Add / update rule</h2>
        {ruleErr && <div className="error">{ruleErr}</div>}
        <div className="row">
          <div><label>Product type</label>
            <select value={rule.product_type} onChange={(e) => setRule({ ...rule, product_type: e.target.value })}>
              {PRODUCT_TYPES.map((t) => <option key={t}>{t}</option>)}
            </select></div>
          <div><label>Level gap</label>
            <select value={rule.level_gap} onChange={(e) => setRule({ ...rule, level_gap: e.target.value })}>
              <option>1</option><option>2</option><option>3</option><option>4</option>
            </select></div>
          <div><label>Rate (e.g. 0.25 = 25%)</label>
            <input value={rule.override_rate} onChange={(e) => setRule({ ...rule, override_rate: e.target.value })} /></div>
        </div>
        <div className="row">
          <div><label>Valid from</label>
            <input type="date" value={rule.valid_from} onChange={(e) => setRule({ ...rule, valid_from: e.target.value })} /></div>
          <div><label>Valid to</label>
            <input type="date" value={rule.valid_to} onChange={(e) => setRule({ ...rule, valid_to: e.target.value })} /></div>
        </div>
        <div style={{ marginTop: 12 }}>
          <button className="primary" type="submit" disabled={createRule.isPending}>Save rule</button>
        </div>
      </form>
    </div>
  );
}
