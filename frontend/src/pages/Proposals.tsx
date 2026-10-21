import { useEffect, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, downloadFile, errorText, fetchBlobUrl } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { useI18n } from "../i18n/LanguageContext";
import { dateShort } from "../lib/format";
import Markdown from "../components/Markdown";
import type { Proposal } from "../api/types";

const CURRENCIES = ["USD", "HKD", "RMB"];
const BLANK = { client_id: "", age: "", gender: "F", product: "", premium: "", term_years: "", currency: "USD" };
const ACTIVE = new Set(["queued", "claimed"]);

const STATUS_BADGE: Record<string, string> = {
  queued: "unit", claimed: "role", done: "settled", failed: "cancelled", cancelled: "cancelled",
};

// 建議書 — agents request a proposal; a WeChat worker generates the PDF and the
// backend adds an AI analysis. Polls while any request is still in progress.
export default function Proposals() {
  const { t } = useI18n();
  const { me } = useAuth();
  const qc = useQueryClient();
  const isAdmin = me?.role === "admin";
  const [form, setForm] = useState({ ...BLANK });
  const [error, setError] = useState<string | null>(null);
  const [openId, setOpenId] = useState<number | null>(null);

  const list = useQuery({
    queryKey: ["proposals"], queryFn: () => api.proposals(),
    refetchInterval: (q) => ((q.state.data ?? []).some((p) => ACTIVE.has(p.status) ||
      (p.status === "done" && p.analysis_status === "pending")) ? 5000 : false),
  });
  const worker = useQuery({ queryKey: ["proposalWorker"], queryFn: () => api.proposalWorkerStatus(),
                            refetchInterval: 30000 });
  const clients = useQuery({ queryKey: ["clients"], queryFn: () => api.clients() });
  const rows = list.data ?? [];
  const invalidate = () => qc.invalidateQueries({ queryKey: ["proposals"] });

  const create = useMutation({
    mutationFn: () => api.createProposal({
      age: Number(form.age), gender: form.gender, product: form.product.trim(),
      premium: Number(form.premium), term_years: Number(form.term_years), currency: form.currency,
      client_id: form.client_id ? Number(form.client_id) : null,
    }),
    onSuccess: () => { setForm({ ...BLANK }); setError(null); invalidate(); },
    onError: (e) => setError(errorText(e, t) || t("proposal.createFailed")),
  });

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!form.age || !form.product.trim() || !form.premium || !form.term_years) {
      setError(t("proposal.errRequired")); return;
    }
    create.mutate();
  }
  const set = (k: keyof typeof BLANK) => (e: { target: { value: string } }) =>
    setForm((f) => ({ ...f, [k]: e.target.value }));

  const open = rows.find((p) => p.id === openId) ?? null;

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        <div>
          <h1 className="page-title">{t("proposal.title")}</h1>
          <p className="page-sub">{t("proposal.subtitle")}</p>
        </div>
        {worker.data && (
          <span className={`badge ${worker.data.online ? "settled" : "cancelled"}`}
            title={worker.data.last_seen ? dateShort(worker.data.last_seen) : ""}>
            {worker.data.online ? t("proposal.workerOnline") : t("proposal.workerOffline")}
            {worker.data.queued > 0 && ` · ${t("proposal.queued", { n: worker.data.queued })}`}
          </span>
        )}
      </div>

      <form className="card" onSubmit={onSubmit}>
        {error && <div className="error">{error}</div>}
        <div className="form-row">
          <label>{t("proposal.fClient")}
            <select value={form.client_id} onChange={set("client_id")}>
              <option value="">—</option>
              {(clients.data ?? []).map((c) => <option key={c.id} value={c.id}>{c.name} ({c.ref})</option>)}
            </select>
          </label>
          <label>{t("proposal.fProduct")}
            <input value={form.product} onChange={set("product")} placeholder="飛揚·88" required />
          </label>
        </div>
        <div className="form-row">
          <label>{t("proposal.fAge")}
            <input type="number" min={0} max={100} value={form.age} onChange={set("age")} required />
          </label>
          <label>{t("proposal.fGender")}
            <select value={form.gender} onChange={set("gender")}>
              <option value="F">{t("proposal.female")}</option>
              <option value="M">{t("proposal.male")}</option>
            </select>
          </label>
          <label>{t("proposal.fCurrency")}
            <select value={form.currency} onChange={set("currency")}>
              {CURRENCIES.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
          </label>
        </div>
        <div className="form-row">
          <label>{t("proposal.fPremium")}
            <input type="number" min={1} step="any" value={form.premium} onChange={set("premium")} required />
          </label>
          <label>{t("proposal.fTerm")}
            <input type="number" min={1} max={50} value={form.term_years} onChange={set("term_years")} required />
          </label>
        </div>
        <div className="muted" style={{ fontSize: 12, margin: "4px 0 10px" }}>{t("proposal.privacyNote")}</div>
        <button className="primary" type="submit" disabled={create.isPending}>{t("proposal.submit")}</button>
      </form>

      <div className="card">
        {list.isLoading && <div className="spinner">{t("common.loading")}</div>}
        <table className="cards-on-mobile">
          <thead><tr>
            <th>{t("proposal.colCreated")}</th>
            {isAdmin && <th>{t("proposal.colAgent")}</th>}
            <th>{t("proposal.fProduct")}</th>
            <th>{t("proposal.colInsured")}</th>
            <th className="num">{t("proposal.fPremium")}</th>
            <th>{t("proposal.colStatus")}</th>
          </tr></thead>
          <tbody>
            {rows.map((p) => (
              <tr key={p.id} onClick={() => setOpenId(p.id)} style={{ cursor: "pointer" }}>
                <td className="muted" style={{ fontSize: 13 }}>{dateShort(p.created_at)}</td>
                {isAdmin && <td>{p.agent_name} <span className="muted" style={{ fontSize: 12 }}>({p.agent_code})</span></td>}
                <td>{p.inputs.product}{p.client_name && <span className="muted" style={{ fontSize: 12 }}> · {p.client_name}</span>}</td>
                <td>{p.inputs.age} {p.inputs.gender === "M" ? t("proposal.male") : t("proposal.female")}</td>
                <td className="num">{p.inputs.currency} {p.inputs.premium.toLocaleString()} × {p.inputs.term_years}</td>
                <td><StatusBadge p={p} /></td>
              </tr>
            ))}
            {!list.isLoading && rows.length === 0 && (
              <tr><td colSpan={isAdmin ? 6 : 5} className="muted">{t("proposal.empty")}</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {open && <ProposalModal p={open} isAdmin={isAdmin} onClose={() => setOpenId(null)} onChanged={invalidate} />}
    </div>
  );
}

function StatusBadge({ p }: { p: Proposal }) {
  const { t } = useI18n();
  let label = t(`proposal.status.${p.status}`);
  if (p.status === "queued" && p.queue_position) label += ` #${p.queue_position}`;
  if (p.status === "done" && p.analysis_status === "pending") label += ` · ${t("proposal.analyzing")}`;
  return <span className={`badge ${STATUS_BADGE[p.status] || "unit"}`}>{label}</span>;
}

function ProposalModal({ p, isAdmin, onClose, onChanged }:
  { p: Proposal; isAdmin: boolean; onClose: () => void; onChanged: () => void }) {
  const { t } = useI18n();
  const [pdfUrl, setPdfUrl] = useState<string | null>(null);
  const [shotUrl, setShotUrl] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!p.has_pdf) return;
    let cancelled = false; let url: string | null = null;
    fetchBlobUrl(api.proposalPdfPath(p.id))
      .then((u) => { if (cancelled) { URL.revokeObjectURL(u); return; } url = u; setPdfUrl(u); })
      .catch(() => {});
    return () => { cancelled = true; if (url) URL.revokeObjectURL(url); };
  }, [p.id, p.has_pdf]);

  useEffect(() => {
    if (!p.has_screenshot || p.status !== "failed") return;
    let cancelled = false; let url: string | null = null;
    fetchBlobUrl(api.proposalScreenshotPath(p.id))
      .then((u) => { if (cancelled) { URL.revokeObjectURL(u); return; } url = u; setShotUrl(u); })
      .catch(() => {});
    return () => { cancelled = true; if (url) URL.revokeObjectURL(url); };
  }, [p.id, p.has_screenshot, p.status]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const act = (fn: () => Promise<unknown>) => () => {
    setErr(null);
    fn().then(onChanged).catch((e) => setErr(errorText(e, t)));
  };
  const onUpload = (file: File | undefined) => {
    if (!file) return;
    act(() => api.uploadProposalPdf(p.id, file))();
  };
  const name = `建議書-${p.inputs.product}-${p.id}.pdf`;

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-panel" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 960 }}>
        <div className="modal-head">
          <div style={{ minWidth: 0 }}>
            <strong style={{ fontSize: 15 }}>{p.inputs.product}</strong>
            <div className="muted" style={{ fontSize: 12 }}>
              {p.inputs.age} {p.inputs.gender === "M" ? t("proposal.male") : t("proposal.female")} ·{" "}
              {p.inputs.currency} {p.inputs.premium.toLocaleString()} × {p.inputs.term_years} {t("proposal.years")}
              {p.client_name && ` · ${p.client_name}`}
            </div>
          </div>
          <button className="ghost" style={{ padding: "3px 10px" }} onClick={onClose}>✕</button>
        </div>
        <div className="modal-body detail">
          {err && <div className="error">{err}</div>}
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center", marginBottom: 10 }}>
            <StatusBadge p={p} />
            {p.has_pdf && (
              <button className="ghost" onClick={() => downloadFile(api.proposalPdfPath(p.id, true), name)
                .catch((e) => setErr(errorText(e, t)))}>↓ {t("proposal.download")}</button>
            )}
            {p.status === "queued" && <button className="ghost" onClick={act(() => api.cancelProposal(p.id))}>{t("proposal.cancel")}</button>}
            {(p.status === "failed" || p.status === "cancelled") &&
              <button className="ghost" onClick={act(() => api.retryProposal(p.id))}>{t("proposal.retry")}</button>}
            {p.has_pdf && p.analysis_status !== "pending" &&
              <button className="ghost" onClick={act(() => api.reanalyzeProposal(p.id))}>{t("proposal.reanalyze")}</button>}
            {isAdmin && p.status !== "done" && (
              <label className="ghost" style={{ cursor: "pointer", padding: "3px 10px", border: "1px solid var(--line)", borderRadius: 6 }}>
                ↑ {t("proposal.uploadManual")}
                <input type="file" accept=".pdf,application/pdf" style={{ display: "none" }}
                  onChange={(e) => onUpload(e.target.files?.[0])} />
              </label>
            )}
          </div>

          {p.status === "failed" && p.error && <div className="error">{t("proposal.failedWith")}: {p.error}</div>}
          {shotUrl && <img src={shotUrl} alt="screenshot" style={{ maxWidth: "100%", border: "1px solid var(--line)", borderRadius: 6 }} />}
          {ACTIVE.has(p.status) && (
            <div className="preview-loading"><span className="spin" aria-hidden />
              {p.status === "queued" ? t("proposal.waiting") : t("proposal.generating")}
            </div>
          )}

          {p.status === "done" && (
            <>
              <h3 style={{ marginTop: 6 }}>{t("proposal.analysis")}</h3>
              {p.analysis_status === "pending" && (
                <div className="preview-loading"><span className="spin" aria-hidden />{t("proposal.analyzing")}</div>
              )}
              {p.analysis_status === "skipped" && <p className="muted">{t("proposal.analysisSkipped")}</p>}
              {(p.analysis_status === "done" || p.analysis_status === "failed") && p.analysis && (
                <div className="card" style={{ background: "var(--surface-2, #f8fafc)" }}>
                  <Markdown text={p.analysis} />
                  <p className="muted" style={{ fontSize: 12, marginBottom: 0 }}>{t("proposal.aiDisclaimer")}</p>
                </div>
              )}
              {pdfUrl && (
                <iframe title="proposal" src={pdfUrl}
                  style={{ width: "100%", height: 640, border: "1px solid var(--line)", borderRadius: 6, marginTop: 10 }} />
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
