import { useState, type FormEvent } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../../api/client";
import { TITLES } from "../../lib/titles";
import type { Agent, Role, Title } from "../../api/types";

export default function AdminAgents() {
  const qc = useQueryClient();
  const agents = useQuery({ queryKey: ["agents"], queryFn: () => api.agents() });

  // --- Create agent ---
  const [agentForm, setAgentForm] = useState({
    code: "", name: "", email: "", upline_id: "", unit_code: "",
    title: "business_manager" as Title, role: "agent" as Role, password: "demo1234",
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
        password: agentForm.password || undefined,
      }),
    onSuccess: (a) => {
      qc.invalidateQueries({ queryKey: ["agents"] });
      setAgentMsg(`Created ${a.name} (${a.code}) at depth L${a.level}.`);
      setAgentErr(null);
      setAgentForm({ ...agentForm, code: "", name: "", email: "" });
      setTimeout(() => setAgentMsg(null), 3000);
    },
    onError: (e) => { setAgentErr(e instanceof ApiError ? e.message : "Failed to create agent"); setAgentMsg(null); },
  });

  // --- Inline title assignment ---
  const assignTitle = useMutation({
    mutationFn: ({ id, title }: { id: number; title: Title }) => api.updateAgent(id, { title }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["agents"] }),
  });

  // --- Edit agent ---
  const [editId, setEditId] = useState<number | null>(null);
  const [editForm, setEditForm] = useState({ name: "", email: "", role: "agent" as Role, title: "", unit_code: "" });
  const [editErr, setEditErr] = useState<string | null>(null);
  const updateAgent = useMutation({
    mutationFn: () =>
      api.updateAgent(editId!, {
        name: editForm.name, email: editForm.email, role: editForm.role,
        title: (editForm.title || null) as Title | null,
        unit_code: editForm.unit_code || null,
      }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["agents"] }); setEditId(null); setEditErr(null); },
    onError: (e) => setEditErr(e instanceof ApiError ? e.message : "Failed to save"),
  });

  // --- Terminate / reactivate ---
  const [rowMsg, setRowMsg] = useState<string | null>(null);
  const setActive = useMutation({
    mutationFn: ({ id, active }: { id: number; active: boolean }) =>
      api.updateAgent(id, { is_active: active }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["agents"] }),
    onError: (e) => setRowMsg(e instanceof ApiError ? e.message : "Action failed"),
  });

  function startEdit(a: Agent) {
    setEditId(a.id);
    setEditForm({ name: a.name, email: a.email, role: a.role, title: a.title ?? "", unit_code: a.unit_code ?? "" });
    setEditErr(null);
  }
  function terminate(a: Agent) {
    if (window.confirm(`Terminate ${a.name} (${a.code})? They will be deactivated and can no longer log in.`)) {
      setActive.mutate({ id: a.id, active: false });
    }
  }

  return (
    <div>
      <h1 className="page-title">Agents</h1>
      <p className="page-sub">Create, edit, and terminate agents; place them in the hierarchy and assign titles</p>

      <div className="card">
        <h2>Roster</h2>
        {rowMsg && <div className="error">{rowMsg}</div>}
        <table>
          <thead>
            <tr>
              <th>Code</th><th>Name</th><th>Depth</th><th>Role</th><th>Title</th>
              <th>Unit</th><th>Upline</th><th>Status</th><th></th>
            </tr>
          </thead>
          <tbody>
            {agents.data?.map((a) => {
              const upline = agents.data?.find((u) => u.id === a.upline_id);
              return (
                <tr key={a.id} style={a.is_active ? undefined : { opacity: 0.55 }}>
                  <td>{a.code}</td>
                  <td>{a.name}</td>
                  <td>L{a.level}</td>
                  <td><span className="badge role">{a.role}</span></td>
                  <td>
                    <select value={a.title ?? ""} disabled={!a.is_active}
                      onChange={(e) => assignTitle.mutate({ id: a.id, title: e.target.value as Title })}
                      style={{ padding: "4px 6px", fontSize: 12 }}>
                      <option value="" disabled>— assign —</option>
                      {TITLES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
                    </select>
                  </td>
                  <td className="muted">{a.unit_code ?? "—"}</td>
                  <td className="muted">{upline ? `${upline.name} (${upline.code})` : "—"}</td>
                  <td>
                    <span className={`badge ${a.is_active ? "settled" : "cancelled"}`}>
                      {a.is_active ? "active" : "terminated"}
                    </span>
                  </td>
                  <td className="num" style={{ whiteSpace: "nowrap" }}>
                    <button className="ghost" onClick={() => startEdit(a)}>Edit</button>{" "}
                    {a.is_active ? (
                      <button className="ghost" style={{ color: "var(--bad)" }}
                        onClick={() => terminate(a)}>Terminate</button>
                    ) : (
                      <button className="ghost" style={{ color: "var(--good)" }}
                        onClick={() => setActive.mutate({ id: a.id, active: true })}>Reactivate</button>
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
          <h2>Edit agent — {agents.data?.find((a) => a.id === editId)?.code}</h2>
          {editErr && <div className="error">{editErr}</div>}
          <div className="row">
            <div><label>Name</label>
              <input value={editForm.name} required
                onChange={(e) => setEditForm({ ...editForm, name: e.target.value })} /></div>
            <div><label>Email</label>
              <input type="email" value={editForm.email} required
                onChange={(e) => setEditForm({ ...editForm, email: e.target.value })} /></div>
          </div>
          <div className="row">
            <div><label>Role (access scope)</label>
              <select value={editForm.role}
                onChange={(e) => setEditForm({ ...editForm, role: e.target.value as Role })}>
                <option value="admin">admin</option>
                <option value="manager">manager</option>
                <option value="agent">agent</option>
              </select></div>
            <div><label>Title</label>
              <select value={editForm.title}
                onChange={(e) => setEditForm({ ...editForm, title: e.target.value })}>
                <option value="">— none —</option>
                {TITLES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
              </select></div>
            <div><label>Unit code (team)</label>
              <input value={editForm.unit_code} placeholder="e.g. U-LEO"
                onChange={(e) => setEditForm({ ...editForm, unit_code: e.target.value })} /></div>
          </div>
          <p className="muted" style={{ fontSize: 12, marginTop: 8 }}>
            Depth and upline are fixed here; a manager's unit code names their team. Use Terminate to deactivate.
          </p>
          <div style={{ marginTop: 10, display: "flex", gap: 8 }}>
            <button className="primary" type="submit" disabled={updateAgent.isPending}>
              {updateAgent.isPending ? "Saving…" : "Save changes"}
            </button>
            <button className="ghost" type="button" onClick={() => setEditId(null)}>Cancel</button>
          </div>
        </form>
      )}

      <form className="card" onSubmit={(e: FormEvent) => { e.preventDefault(); createAgent.mutate(); }}>
        <h2>Add agent</h2>
        {agentErr && <div className="error">{agentErr}</div>}
        {agentMsg && <div className="success">{agentMsg}</div>}
        <div className="row">
          <div><label>Code</label>
            <input value={agentForm.code} required placeholder="e.g. A009"
              onChange={(e) => setAgentForm({ ...agentForm, code: e.target.value })} /></div>
          <div><label>Name</label>
            <input value={agentForm.name} required
              onChange={(e) => setAgentForm({ ...agentForm, name: e.target.value })} /></div>
          <div><label>Email</label>
            <input type="email" value={agentForm.email} required
              onChange={(e) => setAgentForm({ ...agentForm, email: e.target.value })} /></div>
        </div>
        <div className="row">
          <div>
            <label>Upline</label>
            <select value={agentForm.upline_id}
              onChange={(e) => setAgentForm({ ...agentForm, upline_id: e.target.value })}>
              <option value="">— none (new top-level root) —</option>
              {(agents.data ?? []).filter((u) => u.role !== "admin" && u.is_active).map((u) => (
                <option key={u.id} value={u.id}>{u.name} ({u.code}) · L{u.level}</option>
              ))}
            </select>
          </div>
          <div><label>Depth</label>
            <input value={`L${derivedLevel}`} disabled readOnly /></div>
          <div>
            <label>Title</label>
            <select value={agentForm.title}
              onChange={(e) => setAgentForm({ ...agentForm, title: e.target.value as Title })}>
              {TITLES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
            </select>
          </div>
        </div>
        <div className="row">
          <div><label>Role (access scope)</label>
            <select value={agentForm.role}
              onChange={(e) => setAgentForm({ ...agentForm, role: e.target.value as Role })}>
              <option value="admin">admin</option>
              <option value="manager">manager</option>
              <option value="agent">agent</option>
            </select></div>
          <div><label>Unit code (team)</label>
            <input value={agentForm.unit_code} placeholder="e.g. U-LEO"
              onChange={(e) => setAgentForm({ ...agentForm, unit_code: e.target.value })} /></div>
          <div><label>Password</label>
            <input type="text" value={agentForm.password}
              onChange={(e) => setAgentForm({ ...agentForm, password: e.target.value })} /></div>
          <div className="shrink" style={{ alignSelf: "flex-end" }}>
            <button className="primary" type="submit" disabled={createAgent.isPending}>
              {createAgent.isPending ? "Creating…" : "Create agent"}
            </button>
          </div>
        </div>
        <p className="muted" style={{ fontSize: 12, marginTop: 8 }}>
          The new agent is placed directly under the chosen upline (depth L{derivedLevel}); cycles are rejected.
          Role controls data visibility; title is the business rank.
        </p>
      </form>
    </div>
  );
}
