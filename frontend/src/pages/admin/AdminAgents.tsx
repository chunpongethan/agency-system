import { useState, type FormEvent } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, errorText } from "../../api/client";
import { useI18n } from "../../i18n/LanguageContext";
import { TITLE_VALUES, titleLabel } from "../../lib/titles";
import { roleLabel, ROLES } from "../../i18n/labels";
import type { Agent, Role, Title } from "../../api/types";

export default function AdminAgents() {
  const { t } = useI18n();
  const qc = useQueryClient();
  const agents = useQuery({ queryKey: ["agents"], queryFn: () => api.agents() });

  // Roster filter: terminated agents are hidden unless the admin opts in.
  const [includeTerminated, setIncludeTerminated] = useState(false);
  const rosterAgents = (agents.data ?? []).filter((a) => includeTerminated || a.is_active);
  const terminatedCount = (agents.data ?? []).filter((a) => !a.is_active).length;

  // --- Create agent ---
  const [agentForm, setAgentForm] = useState({
    code: "", name: "", email: "", upline_id: "", unit_code: "",
    title: "business_manager" as Title, role: "agent" as Role, password: "demo1234",
    direct_client: false,
  });
  const [agentErr, setAgentErr] = useState<string | null>(null);
  const [agentMsg, setAgentMsg] = useState<string | null>(null);

  const selectedUpline = (agents.data ?? []).find((a) => a.id === Number(agentForm.upline_id));
  const derivedLevel = selectedUpline ? selectedUpline.level + 1 : 1;

  const createAgent = useMutation({
    mutationFn: () =>
      api.createAgent({
        code: agentForm.code, name: agentForm.name, email: agentForm.email,
        level: derivedLevel,
        upline_id: agentForm.upline_id ? Number(agentForm.upline_id) : null,
        role: agentForm.role, title: agentForm.title,
        unit_code: agentForm.unit_code || null,
        direct_client: agentForm.direct_client,
        password: agentForm.password || undefined,
      }),
    onSuccess: (a) => {
      qc.invalidateQueries({ queryKey: ["agents"] });
      setAgentMsg(t("admin.agents.created", { name: a.name, code: a.code, level: a.level }));
      setAgentErr(null);
      setAgentForm({ ...agentForm, code: "", name: "", email: "" });
      setTimeout(() => setAgentMsg(null), 3000);
    },
    onError: (e) => { setAgentErr(errorText(e, t) || t("admin.agents.createFailed")); setAgentMsg(null); },
  });

  // --- Edit agent (the 職級/title is changed here, not inline in the table) ---
  const [editId, setEditId] = useState<number | null>(null);
  const [editForm, setEditForm] = useState({ name: "", email: "", role: "agent" as Role, title: "", unit_code: "", password: "", direct_client: false });
  const [editErr, setEditErr] = useState<string | null>(null);
  const updateAgent = useMutation({
    mutationFn: () =>
      api.updateAgent(editId!, {
        name: editForm.name, email: editForm.email, role: editForm.role,
        title: (editForm.title || null) as Title | null,
        unit_code: editForm.unit_code || null,
        direct_client: editForm.direct_client,
        password: editForm.password || undefined,
      }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["agents"] }); setEditId(null); setEditErr(null); },
    onError: (e) => setEditErr(errorText(e, t) || t("admin.agents.saveFailed")),
  });

  // --- Terminate / reactivate ---
  const [rowMsg, setRowMsg] = useState<string | null>(null);
  const setActive = useMutation({
    mutationFn: ({ id, active }: { id: number; active: boolean }) =>
      api.updateAgent(id, { is_active: active }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["agents"] }),
    onError: (e) => setRowMsg(errorText(e, t) || t("admin.agents.actionFailed")),
  });

  function startEdit(a: Agent) {
    setEditId(a.id);
    setEditForm({ name: a.name, email: a.email, role: a.role, title: a.title ?? "", unit_code: a.unit_code ?? "", password: "", direct_client: a.direct_client });
    setEditErr(null);
  }
  function terminate(a: Agent) {
    if (window.confirm(t("admin.agents.confirmTerminate", { name: a.name, code: a.code }))) {
      setActive.mutate({ id: a.id, active: false });
    }
  }

  return (
    <div>
      <h1 className="page-title">{t("admin.agents.title")}</h1>
      <p className="page-sub">{t("admin.agents.subtitle")}</p>

      <div className="card">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8 }}>
          <h2 style={{ margin: 0 }}>{t("admin.agents.roster")}</h2>
          <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, fontWeight: 400, margin: 0, cursor: "pointer" }}>
            <input type="checkbox" style={{ width: "auto" }} checked={includeTerminated}
              onChange={(e) => setIncludeTerminated(e.target.checked)} />
            {t("admin.agents.includeTerminated", { count: terminatedCount })}
          </label>
        </div>
        {rowMsg && <div className="error">{rowMsg}</div>}
        <table>
          <thead>
            <tr>
              <th>{t("common.code")}</th><th>{t("common.name")}</th><th>{t("admin.agents.thDepth")}</th><th>{t("common.role")}</th><th>{t("common.title")}</th>
              <th>{t("common.unit")}</th><th>{t("admin.agents.thDirectClient")}</th><th>{t("admin.agents.thUpline")}</th><th>{t("common.status")}</th><th></th>
            </tr>
          </thead>
          <tbody>
            {rosterAgents.map((a) => {
              const upline = agents.data?.find((u) => u.id === a.upline_id);
              return (
                <tr key={a.id} style={a.is_active ? undefined : { opacity: 0.55 }}>
                  <td>{a.code}</td>
                  <td>{a.name}</td>
                  <td>L{a.level}</td>
                  <td><span className="badge role">{roleLabel(a.role)}</span></td>
                  <td>
                    {a.title
                      ? <span className="badge title">{titleLabel(a.title)}</span>
                      : <span className="muted">—</span>}
                  </td>
                  <td className="muted">{a.unit_code ?? "—"}</td>
                  <td>{a.direct_client ? <span className="badge unit">直客</span> : <span className="muted">—</span>}</td>
                  <td className="muted">{upline ? `${upline.name} (${upline.code})` : "—"}</td>
                  <td>
                    <span className={`badge ${a.is_active ? "settled" : "cancelled"}`}>
                      {a.is_active ? t("admin.agents.active") : t("admin.agents.terminated")}
                    </span>
                  </td>
                  <td className="num" style={{ whiteSpace: "nowrap" }}>
                    <button className="ghost" onClick={() => startEdit(a)}>{t("common.edit")}</button>{" "}
                    {a.is_active ? (
                      <button className="ghost" style={{ color: "var(--bad)" }}
                        onClick={() => terminate(a)}>{t("admin.agents.terminate")}</button>
                    ) : (
                      <button className="ghost" style={{ color: "var(--good)" }}
                        onClick={() => setActive.mutate({ id: a.id, active: true })}>{t("admin.agents.reactivate")}</button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {editId != null && (
        <form className="card" onSubmit={(e: FormEvent) => { e.preventDefault(); updateAgent.mutate(); }}>
          <h2>{t("admin.agents.editTitle", { code: agents.data?.find((a) => a.id === editId)?.code ?? "" })}</h2>
          {editErr && <div className="error">{editErr}</div>}
          <div className="row">
            <div><label>{t("common.name")}</label>
              <input value={editForm.name} required
                onChange={(e) => setEditForm({ ...editForm, name: e.target.value })} /></div>
            <div><label>{t("common.email")}</label>
              <input type="email" value={editForm.email} required
                onChange={(e) => setEditForm({ ...editForm, email: e.target.value })} /></div>
          </div>
          <div className="row">
            <div><label>{t("admin.agents.roleScope")}</label>
              <select value={editForm.role}
                onChange={(e) => setEditForm({ ...editForm, role: e.target.value as Role })}>
                {ROLES.map((r) => <option key={r} value={r}>{roleLabel(r)}</option>)}
              </select></div>
            <div><label>{t("common.title")}</label>
              <select value={editForm.title}
                onChange={(e) => setEditForm({ ...editForm, title: e.target.value })}>
                <option value="">{t("admin.agents.titleNone")}</option>
                {TITLE_VALUES.map((tv) => <option key={tv} value={tv}>{titleLabel(tv)}</option>)}
              </select></div>
            <div><label>{t("admin.agents.unitCode")}</label>
              <input value={editForm.unit_code} placeholder="e.g. U-LEO"
                onChange={(e) => setEditForm({ ...editForm, unit_code: e.target.value })} /></div>
            <div><label>{t("admin.agents.newPassword")}</label>
              <input type="text" value={editForm.password} autoComplete="new-password"
                onChange={(e) => setEditForm({ ...editForm, password: e.target.value })} /></div>
            <div><label>{t("admin.agents.directClient")}</label>
              <input type="checkbox" checked={editForm.direct_client} style={{ width: "auto" }}
                onChange={(e) => setEditForm({ ...editForm, direct_client: e.target.checked })} /></div>
          </div>
          <p className="muted" style={{ fontSize: 12, marginTop: 8 }}>
            {t("admin.agents.editNote")}
          </p>
          <div style={{ marginTop: 10, display: "flex", gap: 8 }}>
            <button className="primary" type="submit" disabled={updateAgent.isPending}>
              {updateAgent.isPending ? t("common.saving") : t("admin.agents.saveChanges")}
            </button>
            <button className="ghost" type="button" onClick={() => setEditId(null)}>{t("common.cancel")}</button>
          </div>
        </form>
      )}

      <form className="card" onSubmit={(e: FormEvent) => { e.preventDefault(); createAgent.mutate(); }}>
        <h2>{t("admin.agents.add")}</h2>
        {agentErr && <div className="error">{agentErr}</div>}
        {agentMsg && <div className="success">{agentMsg}</div>}
        <div className="row">
          <div><label>{t("common.code")}</label>
            <input value={agentForm.code} required placeholder="e.g. A009"
              onChange={(e) => setAgentForm({ ...agentForm, code: e.target.value })} /></div>
          <div><label>{t("common.name")}</label>
            <input value={agentForm.name} required
              onChange={(e) => setAgentForm({ ...agentForm, name: e.target.value })} /></div>
          <div><label>{t("common.email")}</label>
            <input type="email" value={agentForm.email} required
              onChange={(e) => setAgentForm({ ...agentForm, email: e.target.value })} /></div>
        </div>
        <div className="row">
          <div>
            <label>{t("admin.agents.thUpline")}</label>
            <select value={agentForm.upline_id}
              onChange={(e) => setAgentForm({ ...agentForm, upline_id: e.target.value })}>
              <option value="">{t("admin.agents.uplineNone")}</option>
              {(agents.data ?? []).filter((u) => u.role !== "admin" && u.is_active).map((u) => (
                <option key={u.id} value={u.id}>{u.name} ({u.code}) · L{u.level}</option>
              ))}
            </select>
          </div>
          <div><label>{t("admin.agents.thDepth")}</label>
            <input value={`L${derivedLevel}`} disabled readOnly /></div>
          <div>
            <label>{t("common.title")}</label>
            <select value={agentForm.title}
              onChange={(e) => setAgentForm({ ...agentForm, title: e.target.value as Title })}>
              {TITLE_VALUES.map((tv) => <option key={tv} value={tv}>{titleLabel(tv)}</option>)}
            </select>
          </div>
        </div>
        <div className="row">
          <div><label>{t("admin.agents.roleScope")}</label>
            <select value={agentForm.role}
              onChange={(e) => setAgentForm({ ...agentForm, role: e.target.value as Role })}>
              {ROLES.map((r) => <option key={r} value={r}>{roleLabel(r)}</option>)}
            </select></div>
          <div><label>{t("admin.agents.unitCode")}</label>
            <input value={agentForm.unit_code} placeholder="e.g. U-LEO"
              onChange={(e) => setAgentForm({ ...agentForm, unit_code: e.target.value })} /></div>
          <div><label>{t("admin.agents.password")}</label>
            <input type="text" value={agentForm.password}
              onChange={(e) => setAgentForm({ ...agentForm, password: e.target.value })} /></div>
          <div><label>{t("admin.agents.directClient")}</label>
            <input type="checkbox" checked={agentForm.direct_client} style={{ width: "auto" }}
              onChange={(e) => setAgentForm({ ...agentForm, direct_client: e.target.checked })} /></div>
          <div className="shrink" style={{ alignSelf: "flex-end" }}>
            <button className="primary" type="submit" disabled={createAgent.isPending}>
              {createAgent.isPending ? t("admin.agents.creating") : t("admin.agents.create")}
            </button>
          </div>
        </div>
        <p className="muted" style={{ fontSize: 12, marginTop: 8 }}>
          {t("admin.agents.addNote", { level: derivedLevel })}
        </p>
      </form>
    </div>
  );
}
