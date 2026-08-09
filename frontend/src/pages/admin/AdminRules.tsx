import { useState, type FormEvent } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, errorText } from "../../api/client";
import { useI18n } from "../../i18n/LanguageContext";
import { pct } from "../../lib/format";
import { productTypeLabel, PRODUCT_TYPES } from "../../i18n/labels";
import type { OverrideRule } from "../../api/types";

export default function AdminRules() {
  const { t } = useI18n();
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
    onError: (e) => setRuleErr(errorText(e, t) || t("admin.rules.failed")),
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
    onError: (e) => setEditErr(errorText(e, t) || t("admin.rules.failed")),
  });

  // --- Delete ---
  const [rowMsg, setRowMsg] = useState<string | null>(null);
  const removeRule = useMutation({
    mutationFn: (id: number) => api.deleteOverrideRule(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["overrideRules"] }); },
    onError: (e) => setRowMsg(errorText(e, t) || t("admin.rules.deleteFailed")),
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
    if (window.confirm(t("admin.rules.confirmDelete", { type: productTypeLabel(r.product_type), gap: r.level_gap, rate: pct(r.override_rate) }))) {
      removeRule.mutate(r.id);
    }
  }

  const editingRule = rules.data?.find((r) => r.id === editId);

  return (
    <div>
      <h1 className="page-title">{t("admin.rules.title")}</h1>
      <p className="page-sub">{t("admin.rules.subtitle")}</p>

      <div className="card">
        <h2>{t("admin.rules.current")}</h2>
        {rowMsg && <div className="error">{rowMsg}</div>}
        <table>
          <thead>
            <tr>
              <th>{t("admin.rules.thProductType")}</th><th>{t("admin.rules.thGap")}</th><th className="num">{t("admin.rules.thRate")}</th>
              <th>{t("admin.rules.thValidFrom")}</th><th>{t("admin.rules.thValidTo")}</th><th></th>
            </tr>
          </thead>
          <tbody>
            {rules.data?.map((r) => (
              <tr key={r.id}>
                <td>{productTypeLabel(r.product_type)}</td><td>{r.level_gap}</td>
                <td className="num">{pct(r.override_rate)}</td>
                <td className="muted">{r.valid_from}</td>
                <td className="muted">{r.valid_to ?? "—"}</td>
                <td className="num" style={{ whiteSpace: "nowrap" }}>
                  <button className="ghost" onClick={() => startEdit(r)}>{t("common.edit")}</button>{" "}
                  <button className="ghost" style={{ color: "var(--bad)" }}
                    onClick={() => confirmDelete(r)}>{t("common.delete")}</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {editId != null && editingRule && (
        <form className="card" onSubmit={(e: FormEvent) => { e.preventDefault(); updateRule.mutate(); }}>
          <h2>{t("admin.rules.editTitle", { type: productTypeLabel(editingRule.product_type), gap: editingRule.level_gap })}</h2>
          {editErr && <div className="error">{editErr}</div>}
          <div className="row">
            <div><label>{t("admin.rules.rateHint")}</label>
              <input value={editForm.override_rate}
                onChange={(e) => setEditForm({ ...editForm, override_rate: e.target.value })} /></div>
            <div><label>{t("admin.rules.validFrom")}</label>
              <input type="date" value={editForm.valid_from}
                onChange={(e) => setEditForm({ ...editForm, valid_from: e.target.value })} /></div>
            <div><label>{t("admin.rules.validToBlank")}</label>
              <input type="date" value={editForm.valid_to}
                onChange={(e) => setEditForm({ ...editForm, valid_to: e.target.value })} /></div>
          </div>
          <div style={{ marginTop: 12, display: "flex", gap: 8 }}>
            <button className="primary" type="submit" disabled={updateRule.isPending}>
              {updateRule.isPending ? t("common.saving") : t("admin.agents.saveChanges")}
            </button>
            <button className="ghost" type="button" onClick={() => setEditId(null)}>{t("common.cancel")}</button>
          </div>
        </form>
      )}

      <form className="card" onSubmit={(e: FormEvent) => { e.preventDefault(); createRule.mutate(); }}>
        <h2>{t("admin.rules.add")}</h2>
        {ruleErr && <div className="error">{ruleErr}</div>}
        <div className="row">
          <div><label>{t("admin.rules.thProductType")}</label>
            <select value={rule.product_type} onChange={(e) => setRule({ ...rule, product_type: e.target.value })}>
              {PRODUCT_TYPES.map((pt) => <option key={pt} value={pt}>{productTypeLabel(pt)}</option>)}
            </select></div>
          <div><label>{t("admin.rules.levelGap")}</label>
            <select value={rule.level_gap} onChange={(e) => setRule({ ...rule, level_gap: e.target.value })}>
              <option>1</option><option>2</option><option>3</option><option>4</option>
            </select></div>
          <div><label>{t("admin.rules.rateHint")}</label>
            <input value={rule.override_rate} onChange={(e) => setRule({ ...rule, override_rate: e.target.value })} /></div>
        </div>
        <div className="row">
          <div><label>{t("admin.rules.validFrom")}</label>
            <input type="date" value={rule.valid_from} onChange={(e) => setRule({ ...rule, valid_from: e.target.value })} /></div>
          <div><label>{t("admin.rules.validTo")}</label>
            <input type="date" value={rule.valid_to} onChange={(e) => setRule({ ...rule, valid_to: e.target.value })} /></div>
        </div>
        <div style={{ marginTop: 12 }}>
          <button className="primary" type="submit" disabled={createRule.isPending}>{t("admin.rules.add")}</button>
        </div>
      </form>
    </div>
  );
}
