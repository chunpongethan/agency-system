import { useMemo, useState, type FormEvent, type DragEvent } from "react";
import { Link } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, errorText } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { useI18n } from "../i18n/LanguageContext";
import { stageLabel, outcomeLabel, caseTypeLabel, LEAD_STAGES, CASE_TYPES } from "../i18n/labels";
import { moneyFixed } from "../lib/format";
import StageBadge from "../components/StageBadge";
import type { CaseRow } from "../api/types";

const BLANK = {
  prospect_name: "", email: "", phone: "", follow_up: "", notes: "",
  client_id: "", lead_agent_id: "", sdr_agent_id: "", closer_agent_id: "", stage: "lead",
  case_types: [] as string[], expected_afyp: "",
};

export default function Leads() {
  const { me } = useAuth();
  const { t } = useI18n();
  const qc = useQueryClient();

  const [mineOnly, setMineOnly] = useState(false);
  const [showClosed, setShowClosed] = useState(false);
  const [q, setQ] = useState("");
  const [view, setView] = useState<"board" | "table">("board");
  const [error, setError] = useState<string | null>(null);
  const [draggingId, setDraggingId] = useState<number | null>(null);
  const [dragOver, setDragOver] = useState<string | null>(null);

  const cases = useQuery({
    queryKey: ["cases", showClosed, mineOnly],
    queryFn: () => api.listCases({
      outcome: showClosed ? undefined : "open",
      agent_id: mineOnly ? me!.id : undefined,
    }),
  });
  const directory = useQuery({ queryKey: ["agentDirectory"], queryFn: () => api.agentDirectory() });
  const clients = useQuery({ queryKey: ["clients"], queryFn: () => api.clients() });

  const invalidate = () => qc.invalidateQueries({ queryKey: ["cases"] });
  const onErr = (e: unknown) => setError(errorText(e, t) || t("leads.actionFailed"));

  const update = useMutation({
    mutationFn: ({ id, patch }: { id: number; patch: Record<string, unknown> }) => api.updateCase(id, patch),
    onSuccess: () => { invalidate(); setError(null); }, onError: onErr,
  });
  const remove = useMutation({
    mutationFn: (id: number) => api.deleteCase(id),
    onSuccess: () => { invalidate(); setError(null); }, onError: onErr,
  });

  // --- Create / edit ---
  const [showForm, setShowForm] = useState(false);
  const [editId, setEditId] = useState<number | null>(null);
  const [form, setForm] = useState({ ...BLANK });

  const save = useMutation({
    mutationFn: () => {
      const payload: Record<string, unknown> = {
        prospect_name: form.prospect_name,
        email: form.email || undefined,
        phone: form.phone || undefined,
        follow_up: form.follow_up || null,
        notes: form.notes || undefined,
        client_id: form.client_id ? Number(form.client_id) : null,
        case_types: form.case_types,
        expected_afyp: form.expected_afyp ? Number(form.expected_afyp) : null,
        lead_agent_id: Number(form.lead_agent_id),
        sdr_agent_id: form.sdr_agent_id ? Number(form.sdr_agent_id) : null,
        closer_agent_id: form.closer_agent_id ? Number(form.closer_agent_id) : null,
        stage: form.stage,
      };
      return editId ? api.updateCase(editId, payload) : api.createCase(payload);
    },
    onSuccess: () => { invalidate(); closeForm(); setError(null); },
    onError: (e) => setError(errorText(e, t) || t("leads.createFailed")),
  });

  function openCreate() {
    setEditId(null);
    setForm({ ...BLANK, lead_agent_id: me ? String(me.id) : "" });
    setShowForm(true);
  }
  function openEdit(c: CaseRow) {
    setEditId(c.id);
    setForm({
      prospect_name: c.prospect_name, email: c.email ?? "", phone: c.phone ?? "",
      follow_up: c.follow_up ?? "", notes: c.notes ?? "",
      client_id: c.client_id ? String(c.client_id) : "",
      case_types: c.case_types ?? [],
      expected_afyp: c.expected_afyp != null ? String(c.expected_afyp) : "",
      lead_agent_id: String(c.lead_agent_id),
      sdr_agent_id: c.sdr_agent_id ? String(c.sdr_agent_id) : "",
      closer_agent_id: c.closer_agent_id ? String(c.closer_agent_id) : "",
      stage: c.stage,
    });
    setShowForm(true);
  }
  function closeForm() { setShowForm(false); setEditId(null); }

  // Admins and managers may edit any case they can see (the list endpoint only
  // returns a manager's own downline); plain agents edit cases they're assigned to.
  const canEdit = (c: CaseRow) =>
    me?.role === "admin" || me?.role === "manager" ||
    [c.lead_agent_id, c.sdr_agent_id, c.closer_agent_id].includes(me?.id ?? -1);

  // Filter by free-text q client-side, then bucket by stage.
  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return (cases.data ?? []).filter((c) =>
      !needle || [c.ref, c.prospect_name, c.email, c.lead_name, c.lead_code,
                  c.sdr_name, c.closer_name, c.client_name]
        .some((v) => (v ?? "").toLowerCase().includes(needle)));
  }, [cases.data, q]);

  const byStage = (stage: string) => filtered.filter((c) => c.stage === stage);

  function onDrop(e: DragEvent, stage: string) {
    e.preventDefault();
    setDragOver(null);
    const id = Number(e.dataTransfer.getData("text/plain"));
    const c = (cases.data ?? []).find((x) => x.id === id);
    setDraggingId(null);
    if (!c || !canEdit(c) || c.stage === stage) return;
    update.mutate({ id, patch: { stage } });
  }

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12, flexWrap: "wrap" }}>
        <div>
          <h1 className="page-title">{t("leads.title")}</h1>
          <p className="page-sub">{t("leads.subtitle")}</p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <div style={{ display: "flex", gap: 2 }}>
            <button className={view === "board" ? "primary" : "ghost"} style={{ padding: "4px 12px" }}
              onClick={() => setView("board")}>{t("leads.viewBoard")}</button>
            <button className={view === "table" ? "primary" : "ghost"} style={{ padding: "4px 12px" }}
              onClick={() => setView("table")}>{t("leads.viewTable")}</button>
          </div>
          <button className="primary" onClick={openCreate}>{t("leads.new")}</button>
        </div>
      </div>

      <div className="card">
        <div className="row" style={{ alignItems: "center", flexWrap: "wrap" }}>
          <div style={{ flex: 2, minWidth: 200 }}>
            <input type="search" value={q} onChange={(e) => setQ(e.target.value)}
              placeholder={t("leads.searchPlaceholder")} />
          </div>
          <label style={{ display: "flex", alignItems: "center", gap: 6, margin: 0 }}>
            <input type="checkbox" checked={mineOnly} style={{ width: "auto" }}
              onChange={(e) => setMineOnly(e.target.checked)} /> {t("leads.mineOnly")}
          </label>
          <label style={{ display: "flex", alignItems: "center", gap: 6, margin: 0 }}>
            <input type="checkbox" checked={showClosed} style={{ width: "auto" }}
              onChange={(e) => setShowClosed(e.target.checked)} /> {t("leads.showClosed")}
          </label>
          <span className="muted" style={{ fontSize: 12 }}>
            {cases.isLoading ? t("common.loading") : t("leads.count", { count: filtered.length })}
          </span>
        </div>
        {error && <div className="error" style={{ marginTop: 10 }}>{error}</div>}
      </div>

      {view === "board" && (
      <div className="board">
        {LEAD_STAGES.map((stage) => (
          <div key={stage}
            className={`col card ${dragOver === stage ? "drag-over" : ""}`}
            onDragOver={(e) => { e.preventDefault(); setDragOver(stage); }}
            onDragLeave={() => setDragOver((s) => (s === stage ? null : s))}
            onDrop={(e) => onDrop(e, stage)}>
            <div className="col-head">
              <StageBadge stage={stage} />
              <span className="muted" style={{ fontSize: 12 }}>{byStage(stage).length}</span>
            </div>
            {byStage(stage).length === 0 && (
              <p className="muted" style={{ fontSize: 12 }}>{t("leads.emptyColumn")}</p>
            )}
            {byStage(stage).map((c) => {
              const editable = canEdit(c);
              return (
                <div key={c.id} className={`lead-card ${draggingId === c.id ? "dragging" : ""}`}
                  draggable={editable}
                  onDragStart={(e) => { e.dataTransfer.setData("text/plain", String(c.id)); setDraggingId(c.id); }}
                  onDragEnd={() => setDraggingId(null)}>
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 6 }}>
                    <strong>{c.prospect_name}</strong>
                    <span className="muted" style={{ fontSize: 11 }}>{c.ref}</span>
                  </div>
                  {c.client_name && (
                    <div style={{ fontSize: 12 }}>
                      <Link to={`/clients/${c.client_id}`}>{c.client_name}</Link>
                    </div>
                  )}
                  {c.expected_afyp != null && (
                    <div style={{ fontSize: 12 }}>
                      <span className="muted">{t("leads.expectedAfyp")}：</span>{moneyFixed(c.expected_afyp, "HKD")}
                    </div>
                  )}
                  {c.case_types && c.case_types.length > 0 && (
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginTop: 4 }}>
                      {c.case_types.map((ct) => <span key={ct} className="badge dc">{caseTypeLabel(ct)}</span>)}
                    </div>
                  )}
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginTop: 4 }}>
                    <span className="badge role">{t("leads.leadAgent")}: {c.lead_name}</span>
                    {c.sdr_name && <span className="badge unit">{t("leads.sdrAgent")}: {c.sdr_name}</span>}
                    {c.closer_name && <span className="badge title">{t("leads.closerAgent")}: {c.closer_name}</span>}
                    {c.outcome !== "open" && (
                      <span className={`badge ${c.outcome === "won" ? "settled" : "cancelled"}`}>{outcomeLabel(c.outcome)}</span>
                    )}
                  </div>
                  {c.follow_up && (
                    <div style={{ fontSize: 12, marginTop: 6, whiteSpace: "pre-wrap" }}>
                      <span className="muted">{t("leads.followUp")}：</span>{c.follow_up}
                    </div>
                  )}
                  {editable && (
                    <>
                      <div style={{ marginTop: 8 }}>
                        <select value={c.stage} title={t("leads.moveTo")} style={{ width: "auto", fontSize: 12, padding: "2px 6px" }}
                          onChange={(e) => update.mutate({ id: c.id, patch: { stage: e.target.value } })}>
                          {LEAD_STAGES.map((s) => <option key={s} value={s}>{stageLabel(s)}</option>)}
                        </select>
                      </div>
                      <div style={{ display: "flex", gap: 6, marginTop: 6 }}>
                        {c.outcome === "open" ? (
                          <>
                            <button className="ghost" style={{ padding: "2px 8px" }}
                              onClick={() => update.mutate({ id: c.id, patch: { outcome: "won" } })}>{t("leads.markWon")}</button>
                            <button className="ghost" style={{ padding: "2px 8px", color: "var(--bad)" }}
                              onClick={() => update.mutate({ id: c.id, patch: { outcome: "lost" } })}>{t("leads.markLost")}</button>
                          </>
                        ) : (
                          <button className="ghost" style={{ padding: "2px 8px" }}
                            onClick={() => update.mutate({ id: c.id, patch: { outcome: "open" } })}>{t("leads.reopen")}</button>
                        )}
                      </div>
                      <div style={{ display: "flex", gap: 6, marginTop: 6 }}>
                        <button className="ghost" style={{ padding: "2px 8px" }} onClick={() => openEdit(c)}>{t("common.edit")}</button>
                        <button className="ghost" style={{ padding: "2px 8px", color: "var(--bad)" }}
                          onClick={() => { if (window.confirm(t("leads.confirmDelete", { ref: c.ref }))) remove.mutate(c.id); }}>
                          {t("common.delete")}
                        </button>
                      </div>
                    </>
                  )}
                </div>
              );
            })}
          </div>
        ))}
      </div>
      )}

      {view === "table" && (
        <div className="card" style={{ overflowX: "auto" }}>
          <table>
            <thead>
              <tr>
                <th>{t("common.ref")}</th>
                <th>{t("leads.thProspect")}</th>
                <th>{t("leads.thTypes")}</th>
                <th>{t("leads.thStage")}</th>
                <th>{t("leads.followUp")}</th>
                <th>{t("leads.thAgents")}</th>
                <th>{t("leads.thOutcome")}</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((c) => {
                const editable = canEdit(c);
                return (
                  <tr key={c.id}>
                    <td>{c.ref}</td>
                    <td>{c.prospect_name}{c.client_name && (<><br /><Link to={`/clients/${c.client_id}`} className="muted" style={{ fontSize: 12 }}>{c.client_name}</Link></>)}</td>
                    <td>{(c.case_types ?? []).map((ct) => <span key={ct} className="badge dc" style={{ marginRight: 4 }}>{caseTypeLabel(ct)}</span>)}</td>
                    <td>{editable ? (
                      <select value={c.stage} style={{ width: "auto", fontSize: 12, padding: "2px 6px" }}
                        onChange={(e) => update.mutate({ id: c.id, patch: { stage: e.target.value } })}>
                        {LEAD_STAGES.map((s) => <option key={s} value={s}>{stageLabel(s)}</option>)}
                      </select>
                    ) : <StageBadge stage={c.stage} />}</td>
                    <td style={{ whiteSpace: "pre-wrap", maxWidth: 240, fontSize: 13 }}>{c.follow_up}</td>
                    <td style={{ fontSize: 12 }}>{[c.lead_name, c.sdr_name, c.closer_name].filter(Boolean).join(" / ")}</td>
                    <td>{c.outcome !== "open"
                      ? <span className={`badge ${c.outcome === "won" ? "settled" : "cancelled"}`}>{outcomeLabel(c.outcome)}</span>
                      : <span className="muted">{outcomeLabel("open")}</span>}</td>
                    <td className="num" style={{ whiteSpace: "nowrap" }}>
                      {editable && (
                        <>
                          {c.outcome === "open" ? (
                            <>
                              <button className="ghost" style={{ padding: "2px 8px" }} onClick={() => update.mutate({ id: c.id, patch: { outcome: "won" } })}>{t("leads.markWon")}</button>{" "}
                              <button className="ghost" style={{ padding: "2px 8px", color: "var(--bad)" }} onClick={() => update.mutate({ id: c.id, patch: { outcome: "lost" } })}>{t("leads.markLost")}</button>
                            </>
                          ) : (
                            <button className="ghost" style={{ padding: "2px 8px" }} onClick={() => update.mutate({ id: c.id, patch: { outcome: "open" } })}>{t("leads.reopen")}</button>
                          )}{" "}
                          <button className="ghost" style={{ padding: "2px 8px" }} onClick={() => openEdit(c)}>{t("common.edit")}</button>{" "}
                          <button className="ghost" style={{ padding: "2px 8px", color: "var(--bad)" }}
                            onClick={() => { if (window.confirm(t("leads.confirmDelete", { ref: c.ref }))) remove.mutate(c.id); }}>{t("common.delete")}</button>
                        </>
                      )}
                    </td>
                  </tr>
                );
              })}
              {filtered.length === 0 && (
                <tr><td colSpan={8} className="muted">{t("leads.empty")}</td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {showForm && (
        <form className="card" onSubmit={(e: FormEvent) => { e.preventDefault(); save.mutate(); }}>
          <h2>{editId ? t("leads.editTitle", { ref: (cases.data ?? []).find((c) => c.id === editId)?.ref ?? "" }) : t("leads.new")}</h2>
          <div className="row">
            <div><label>{t("leads.prospectName")}</label>
              <input value={form.prospect_name} required
                onChange={(e) => setForm({ ...form, prospect_name: e.target.value })} /></div>
            <div><label>{t("common.email")}</label>
              <input value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></div>
            <div><label>{t("common.phone")}</label>
              <input value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} /></div>
          </div>
          <div className="row">
            <div><label>{t("leads.leadAgent")}</label>
              <select value={form.lead_agent_id} required
                onChange={(e) => setForm({ ...form, lead_agent_id: e.target.value })}>
                <option value="">{t("leads.selectAgent")}</option>
                {(directory.data ?? []).map((a) => <option key={a.id} value={a.id}>{a.name} ({a.code}) · L{a.level}</option>)}
              </select></div>
            <div><label>{t("leads.sdrAgent")}</label>
              <select value={form.sdr_agent_id} onChange={(e) => setForm({ ...form, sdr_agent_id: e.target.value })}>
                <option value="">—</option>
                {(directory.data ?? []).map((a) => <option key={a.id} value={a.id}>{a.name} ({a.code}) · L{a.level}</option>)}
              </select></div>
            <div><label>{t("leads.closerAgent")}</label>
              <select value={form.closer_agent_id} onChange={(e) => setForm({ ...form, closer_agent_id: e.target.value })}>
                <option value="">—</option>
                {(directory.data ?? []).map((a) => <option key={a.id} value={a.id}>{a.name} ({a.code}) · L{a.level}</option>)}
              </select></div>
          </div>
          <div className="row">
            <div><label>{t("common.status")}</label>
              <select value={form.stage} onChange={(e) => setForm({ ...form, stage: e.target.value })}>
                {LEAD_STAGES.map((s) => <option key={s} value={s}>{stageLabel(s)}</option>)}
              </select></div>
            <div><label>{t("leads.linkClient")}</label>
              <select value={form.client_id} onChange={(e) => setForm({ ...form, client_id: e.target.value })}>
                <option value="">{t("leads.noClient")}</option>
                {(clients.data ?? []).map((c) => <option key={c.id} value={c.id}>{c.name} ({c.ref})</option>)}
              </select></div>
          </div>
          <label>{t("leads.caseTypes")}</label>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 12, marginBottom: 8 }}>
            {CASE_TYPES.map((ct) => (
              <label key={ct} style={{ display: "flex", alignItems: "center", gap: 6, margin: 0, fontWeight: 400 }}>
                <input type="checkbox" style={{ width: "auto" }}
                  checked={form.case_types.includes(ct)}
                  onChange={(e) => setForm({
                    ...form,
                    case_types: e.target.checked
                      ? [...form.case_types, ct]
                      : form.case_types.filter((x) => x !== ct),
                  })} />
                {caseTypeLabel(ct)}
              </label>
            ))}
          </div>
          <label>{t("leads.expectedAfyp")}</label>
          <input type="number" min="0" step="1000" value={form.expected_afyp}
            onChange={(e) => setForm({ ...form, expected_afyp: e.target.value })} />
          <label>{t("leads.followUp")}</label>
          <textarea rows={2} value={form.follow_up} onChange={(e) => setForm({ ...form, follow_up: e.target.value })} />
          <label>{t("leads.notes")}</label>
          <textarea rows={2} value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
          <div style={{ marginTop: 12, display: "flex", gap: 8 }}>
            <button className="primary" type="submit" disabled={save.isPending}>
              {save.isPending ? t("common.saving") : t("common.save")}
            </button>
            <button className="ghost" type="button" onClick={closeForm}>{t("common.cancel")}</button>
          </div>
        </form>
      )}
    </div>
  );
}
