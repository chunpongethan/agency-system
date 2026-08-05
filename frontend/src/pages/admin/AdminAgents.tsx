import { useState, type FormEvent } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../../api/client";
import { TITLES } from "../../lib/titles";
import type { Role, Title } from "../../api/types";

export default function AdminAgents() {
  const qc = useQueryClient();
  const agents = useQuery({ queryKey: ["agents"], queryFn: () => api.agents() });

  // The new agent sits directly under the chosen upline; its depth (level) is
  // derived (upline.level + 1, or 1 for a root). Titles are assigned separately.
  const [agentForm, setAgentForm] = useState({
    code: "", name: "", email: "", upline_id: "",
    title: "business_manager" as Title, role: "agent" as Role, password: "demo1234",
  });
  const [agentErr, setAgentErr] = useState<string | null>(null);
  const [agentMsg, setAgentMsg] = useState<string | null>(null);

  const selectedUpline = (agents.data ?? []).find((a) => a.id === Number(agentForm.upline_id));
  const derivedLevel = selectedUpline ? selectedUpline.level + 1 : 1;

  const createAgent = useMutation({
    mutationFn: () =>
      api.createAgent({
        code: agentForm.code,
        name: agentForm.name,
        email: agentForm.email,
        level: derivedLevel,
        upline_id: agentForm.upline_id ? Number(agentForm.upline_id) : null,
        role: agentForm.role,
        title: agentForm.title,
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

  // Reassign a title to an existing agent.
  const assignTitle = useMutation({
    mutationFn: ({ id, title }: { id: number; title: Title }) => api.updateAgent(id, { title }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["agents"] }),
  });

  return (
    <div>
      <h1 className="page-title">Agents</h1>
      <p className="page-sub">Create agents, place them in the hierarchy, and assign titles</p>

      <div className="card">
        <h2>Roster</h2>
        <p className="muted" style={{ fontSize: 12, marginTop: -8 }}>
          Assign each agent a title from the dropdown. Depth (L#) is their position in the tree.
        </p>
        <table>
          <thead>
            <tr><th>Code</th><th>Name</th><th>Depth</th><th>Role</th><th>Title</th><th>Upline</th></tr>
          </thead>
          <tbody>
            {agents.data?.map((a) => {
              const upline = agents.data?.find((u) => u.id === a.upline_id);
              return (
                <tr key={a.id}>
                  <td>{a.code}</td>
                  <td>{a.name}</td>
                  <td>L{a.level}</td>
                  <td><span className="badge role">{a.role}</span></td>
                  <td>
                    <select
                      value={a.title ?? ""}
                      onChange={(e) => assignTitle.mutate({ id: a.id, title: e.target.value as Title })}
                      style={{ padding: "4px 6px", fontSize: 12 }}
                    >
                      <option value="" disabled>— assign —</option>
                      {TITLES.map((t) => (
                        <option key={t.value} value={t.value}>{t.label}</option>
                      ))}
                    </select>
                  </td>
                  <td className="muted">{upline ? `${upline.name} (${upline.code})` : "—"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

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
            <select
              value={agentForm.upline_id}
              onChange={(e) => setAgentForm({ ...agentForm, upline_id: e.target.value })}
            >
              <option value="">— none (new top-level root) —</option>
              {(agents.data ?? [])
                .filter((u) => u.role !== "admin")
                .map((u) => (
                  <option key={u.id} value={u.id}>{u.name} ({u.code}) · L{u.level}</option>
                ))}
            </select>
          </div>
          <div>
            <label>Depth</label>
            <input value={`L${derivedLevel}`} disabled readOnly />
          </div>
          <div>
            <label>Title</label>
            <select value={agentForm.title}
              onChange={(e) => setAgentForm({ ...agentForm, title: e.target.value as Title })}>
              {TITLES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
            </select>
          </div>
        </div>
        <div className="row">
          <div>
            <label>Role (access scope)</label>
            <select value={agentForm.role}
              onChange={(e) => setAgentForm({ ...agentForm, role: e.target.value as Role })}>
              <option value="admin">admin</option>
              <option value="manager">manager</option>
              <option value="agent">agent</option>
            </select>
          </div>
          <div>
            <label>Password</label>
            <input type="text" value={agentForm.password}
              onChange={(e) => setAgentForm({ ...agentForm, password: e.target.value })} />
          </div>
          <div className="shrink" style={{ alignSelf: "flex-end" }}>
            <button className="primary" type="submit" disabled={createAgent.isPending}>
              {createAgent.isPending ? "Creating…" : "Create agent"}
            </button>
          </div>
        </div>
        <p className="muted" style={{ fontSize: 12, marginTop: 8 }}>
          The new agent is placed directly under the chosen upline (depth L{derivedLevel}); cycles are rejected.
          Role controls data visibility (admin / manager / agent); title is the business rank.
        </p>
      </form>
    </div>
  );
}
