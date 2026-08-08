import { useState, type FormEvent } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../../api/client";
import { pct } from "../../lib/format";
import type { OverrideRule } from "../../api/types";

const PRODUCT_TYPES = ["insurance", "fund", "eam_account", "other"];

export default function AdminRules() {
  const qc = useQueryClient();
  const rules = useQuery({ queryKey: ["overrideRules"], queryFn: () => api.overrideRules() });

  // --- Create ---
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
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["overrideRules"] }); setRuleErr(null); },
    onError: (e) => setRuleErr(e instanceof ApiError ? e.message : "Failed"),
  });

  // --- Edit ---
  const [editId, setEditId] = useState<number | null>(null);
  const [editForm, setEditForm] = useState({ override_rate: "", valid_from: "", valid_to: "" });
  const [editErr, setEditErr] = useState<string | null>(null);
  const updateRule = useMutation({
    mutationFn: () =>
      api.updateOverrideRule(editId!, {
        override_rate: editForm.override_rate,
        valid_from: editForm.valid_from || undefined,
        valid_to: editForm.valid_to || null,
      }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["overrideRules"] }); setEditId(null); setEditErr(null); },
    onError: (e) => setEditErr(e instanceof ApiError ? e.message : "Failed"),
  });

  // --- Delete ---
  const [rowMsg, setRowMsg] = useState<string | null>(null);
  const removeRule = useMutation({
    mutationFn: (id: number) => api.deleteOverrideRule(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["overrideRules"] }); },
    onError: (e) => setRowMsg(e instanceof ApiError ? e.message : "Delete failed"),
  });

  function startEdit(r: OverrideRule) {
    setEditId(r.id);
    setEditForm({
      override_rate: r.override_rate,
      valid_from: r.valid_from,
      valid_to: r.valid_to ?? "",
    });
    setEditErr(null);
  }
  function confirmDelete(r: OverrideRule) {
    if (window.confirm(`Delete the ${r.product_type} gap-${r.level_gap} rule (${pct(r.override_rate)})?`)) {
      removeRule.mutate(r.id);
    }
  }

  const editingRule = rules.data?.find((r) => r.id === editId);

  return (
    <div>
      <h1 className="page-title">Override rules</h1>
      <p className="page-sub">
        An upline earns this percentage of the closing agent's commission, by level gap (1st–4th upline).
      </p>

      <div className="card">
        <h2>Current rules</h2>
        {rowMsg && <div className="error">{rowMsg}</div>}
        <table>
          <thead>
            <tr>
              <th>Product type</th><th>Gap</th><th className="num">Rate (of commission)</th>
              <th>Valid from</th><th>Valid to</th><th></th>
            </tr>
          </thead>
          <tbody>
            {rules.data?.map((r) => (
              <tr key={r.id}>
                <td>{r.product_type}</td><td>{r.level_gap}</td>
                <td className="num">{pct(r.override_rate)}</td>
                <td className="muted">{r.valid_from}</td>
                <td className="muted">{r.valid_to ?? "—"}</td>
                <td className="num" style={{ whiteSpace: "nowrap" }}>
                  <button className="ghost" onClick={() => startEdit(r)}>Edit</button>{" "}
                  <button className="ghost" style={{ color: "var(--bad)" }}
                    onClick={() => confirmDelete(r)}>Delete</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {editId != null && editingRule && (
        <form className="card" onSubmit={(e: FormEvent) => { e.preventDefault(); updateRule.mutate(); }}>
          <h2>Edit rule — {editingRule.product_type} · gap {editingRule.level_gap}</h2>
          {editErr && <div className="error">{editErr}</div>}
          <div className="row">
            <div><label>Rate (e.g. 0.25 = 25%)</label>
              <input value={editForm.override_rate}
                onChange={(e) => setEditForm({ ...editForm, override_rate: e.target.value })} /></div>
            <div><label>Valid from</label>
              <input type="date" value={editForm.valid_from}
                onChange={(e) => setEditForm({ ...editForm, valid_from: e.target.value })} /></div>
            <div><label>Valid to (blank = open)</label>
              <input type="date" value={editForm.valid_to}
                onChange={(e) => setEditForm({ ...editForm, valid_to: e.target.value })} /></div>
          </div>
          <div style={{ marginTop: 12, display: "flex", gap: 8 }}>
            <button className="primary" type="submit" disabled={updateRule.isPending}>
              {updateRule.isPending ? "Saving…" : "Save changes"}
            </button>
            <button className="ghost" type="button" onClick={() => setEditId(null)}>Cancel</button>
          </div>
        </form>
      )}

      <form className="card" onSubmit={(e: FormEvent) => { e.preventDefault(); createRule.mutate(); }}>
        <h2>Add rule</h2>
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
          <button className="primary" type="submit" disabled={createRule.isPending}>Add rule</button>
        </div>
      </form>
    </div>
  );
}
