import { useState, type FormEvent } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, ApiError } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { resolveUnit } from "../lib/agency";

export default function Clients() {
  const { me } = useAuth();
  const isAdmin = me!.role === "admin";
  const qc = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [search, setSearch] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState({
    ref: "",
    name: "",
    email: "",
    phone: "",
    risk_profile: "Balanced",
    agent_id: me!.id,
  });

  const clients = useQuery({ queryKey: ["clients"], queryFn: () => api.clients() });
  const agents = useQuery({ queryKey: ["agents"], queryFn: () => api.agents() });
  const agentsById = new Map((agents.data ?? []).map((a) => [a.id, a]));

  const create = useMutation({
    mutationFn: () =>
      api.createClient({
        ...form,
        email: form.email || undefined,
        phone: form.phone || undefined,
        agent_id: Number(form.agent_id),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["clients"] });
      setShowForm(false);
      setForm({ ...form, ref: "", name: "", email: "", phone: "" });
      setError(null);
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : "Failed to create client"),
  });

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    create.mutate();
  }

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div>
          <h1 className="page-title">Clients</h1>
          <p className="page-sub">{isAdmin ? "All clients (read-only)" : "Your clients"}</p>
        </div>
        {!isAdmin && (
          <button className="primary" onClick={() => setShowForm((s) => !s)}>
            {showForm ? "Cancel" : "+ New client"}
          </button>
        )}
      </div>

      {showForm && (
        <form className="card" onSubmit={onSubmit}>
          <h2>New client</h2>
          {error && <div className="error">{error}</div>}
          <div className="row">
            <div>
              <label>Reference</label>
              <input value={form.ref} required
                onChange={(e) => setForm({ ...form, ref: e.target.value })} />
            </div>
            <div>
              <label>Name</label>
              <input value={form.name} required
                onChange={(e) => setForm({ ...form, name: e.target.value })} />
            </div>
          </div>
          <div className="row">
            <div>
              <label>Email</label>
              <input value={form.email}
                onChange={(e) => setForm({ ...form, email: e.target.value })} />
            </div>
            <div>
              <label>Phone</label>
              <input value={form.phone}
                onChange={(e) => setForm({ ...form, phone: e.target.value })} />
            </div>
            <div>
              <label>Risk profile</label>
              <select value={form.risk_profile}
                onChange={(e) => setForm({ ...form, risk_profile: e.target.value })}>
                <option>Conservative</option>
                <option>Balanced</option>
                <option>Growth</option>
                <option>Aggressive</option>
              </select>
            </div>
          </div>
          <div style={{ marginTop: 14 }}>
            <button className="primary" type="submit" disabled={create.isPending}>
              {create.isPending ? "Saving…" : "Create client"}
            </button>
          </div>
        </form>
      )}

      <div className="card">
        {clients.isLoading && <div className="spinner">Loading…</div>}
        {clients.error && <div className="error">Failed to load clients.</div>}
        {(() => {
          const rows = (clients.data ?? []).map((c) => {
            const owner = agentsById.get(c.agent_id);
            const unit = resolveUnit(owner, agentsById);
            return { c, owner, unit };
          });
          const q = search.trim().toLowerCase();
          const filtered = q
            ? rows.filter(({ c, owner, unit }) =>
                [c.name, c.ref, c.email, c.risk_profile, owner?.name, owner?.code, unit]
                  .some((v) => v && v.toLowerCase().includes(q)),
              )
            : rows;
          return (
            <>
              <div style={{ marginBottom: 14, maxWidth: 340 }}>
                <input
                  type="search"
                  placeholder="Search name, ref, email, owner, unit…"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                />
              </div>
              <table>
                <thead>
                  <tr>
                    <th>Name</th><th>Ref</th><th>Risk</th><th>Email</th><th>Owner</th><th>Unit</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map(({ c, owner, unit }) => (
                    <tr key={c.id}>
                      <td><Link to={`/clients/${c.id}`}>{c.name}</Link></td>
                      <td className="muted">{c.ref}</td>
                      <td>{c.risk_profile ?? "—"}</td>
                      <td className="muted">{c.email ?? "—"}</td>
                      <td>
                        {owner ? owner.name : `#${c.agent_id}`}{" "}
                        {owner && <span className="muted">({owner.code})</span>}
                      </td>
                      <td>{unit ? <span className="badge unit">{unit}</span> : <span className="muted">—</span>}</td>
                    </tr>
                  ))}
                  {filtered.length === 0 && (
                    <tr>
                      <td colSpan={6} className="muted">
                        {rows.length === 0 ? "No clients in scope." : "No clients match your search."}
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </>
          );
        })()}
      </div>
    </div>
  );
}
