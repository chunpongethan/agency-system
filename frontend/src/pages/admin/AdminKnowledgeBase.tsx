import { useRef, useState, type FormEvent, type ChangeEvent } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, errorText } from "../../api/client";
import { useI18n } from "../../i18n/LanguageContext";
import { dateShort } from "../../lib/format";
import HtmlEditor from "../../components/HtmlEditor";
import type { KbArticle } from "../../api/types";

const BLANK = { title: "", category: "", body: "", is_active: true };

export default function AdminKnowledgeBase() {
  const { t } = useI18n();
  const qc = useQueryClient();
  const articles = useQuery({ queryKey: ["kbArticles"], queryFn: () => api.listKbArticles() });
  const documents = useQuery({ queryKey: ["kbDocuments"], queryFn: () => api.listKbDocuments() });

  const [showForm, setShowForm] = useState(false);
  const [editId, setEditId] = useState<number | null>(null);
  const [form, setForm] = useState<typeof BLANK>({ ...BLANK });
  const [error, setError] = useState<string | null>(null);
  const [docTitle, setDocTitle] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  const invalidate = () => qc.invalidateQueries({ queryKey: ["kbArticles"] });
  const invalidateDocs = () => qc.invalidateQueries({ queryKey: ["kbDocuments"] });
  const onErr = (e: unknown) => setError(errorText(e, t) || t("kb.saveFailed"));

  const save = useMutation({
    mutationFn: () => {
      const payload = { title: form.title, category: form.category || null, body: form.body || "", is_active: form.is_active };
      return editId ? api.updateKbArticle(editId, payload) : api.createKbArticle(payload);
    },
    onSuccess: () => { invalidate(); closeForm(); setError(null); },
    onError: onErr,
  });
  const remove = useMutation({
    mutationFn: (id: number) => api.deleteKbArticle(id),
    onSuccess: () => { invalidate(); setError(null); }, onError: onErr,
  });
  const upload = useMutation({
    mutationFn: (file: File) => api.uploadKbDocument(file, docTitle.trim() || file.name),
    onSuccess: () => { invalidateDocs(); setDocTitle(""); setError(null); }, onError: onErr,
  });
  const removeDoc = useMutation({
    mutationFn: (id: number) => api.deleteKbDocument(id),
    onSuccess: () => { invalidateDocs(); setError(null); }, onError: onErr,
  });

  function openCreate() { setEditId(null); setForm({ ...BLANK }); setError(null); setShowForm(true); }
  function openEdit(a: KbArticle) {
    setEditId(a.id);
    setForm({ title: a.title, category: a.category ?? "", body: a.body ?? "", is_active: a.is_active });
    setError(null); setShowForm(true);
  }
  function closeForm() { setShowForm(false); setEditId(null); }
  function onFile(e: ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    e.target.value = "";
    if (f) upload.mutate(f);
  }

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div>
          <h1 className="page-title">{t("kb.adminTitle")}</h1>
          <p className="page-sub">{t("kb.adminSubtitle")}</p>
        </div>
        <button className="primary" onClick={() => (showForm ? closeForm() : openCreate())}>
          {showForm ? t("common.cancel") : t("kb.newArticle")}
        </button>
      </div>

      {showForm && (
        <form className="card" onSubmit={(e: FormEvent) => { e.preventDefault(); save.mutate(); }}>
          <h2>{editId ? t("common.edit") : t("kb.newArticle")}</h2>
          {error && <div className="error">{error}</div>}
          <div className="row">
            <div>
              <label>{t("kb.fTitle")}</label>
              <input value={form.title} required onChange={(e) => setForm({ ...form, title: e.target.value })} />
            </div>
            <div>
              <label>{t("kb.fCategory")}</label>
              <input value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })} />
            </div>
          </div>
          <label>{t("kb.fBody")}</label>
          <HtmlEditor value={form.body} onChange={(html) => setForm({ ...form, body: html })} />
          <label style={{ display: "flex", alignItems: "center", gap: 8, fontWeight: 400, marginTop: 10 }}>
            <input type="checkbox" style={{ width: "auto" }} checked={form.is_active}
              onChange={(e) => setForm({ ...form, is_active: e.target.checked })} />
            {t("kb.fActive")}
          </label>
          <div style={{ marginTop: 14 }}>
            <button className="primary" type="submit" disabled={save.isPending}>
              {save.isPending ? t("common.saving") : t("common.save")}
            </button>
          </div>
        </form>
      )}

      <div className="card">
        <h2 style={{ marginTop: 0 }}>{t("kb.articles")}</h2>
        {articles.isLoading && <div className="spinner">{t("common.loading")}</div>}
        <table>
          <thead>
            <tr><th>{t("kb.fTitle")}</th><th>{t("kb.fCategory")}</th><th>{t("common.status")}</th><th></th></tr>
          </thead>
          <tbody>
            {(articles.data ?? []).map((a) => (
              <tr key={a.id}>
                <td>{a.title}</td>
                <td>{a.category ? <span className="badge dc">{a.category}</span> : <span className="muted">—</span>}</td>
                <td>{a.is_active ? <span className="badge settled">✓</span> : <span className="badge cancelled">停用</span>}</td>
                <td className="num" style={{ whiteSpace: "nowrap" }}>
                  <button className="ghost" onClick={() => openEdit(a)}>{t("common.edit")}</button>{" "}
                  <button className="ghost" style={{ color: "var(--bad)" }}
                    onClick={() => { if (window.confirm(t("kb.confirmDeleteArticle", { title: a.title }))) remove.mutate(a.id); }}>
                    {t("common.delete")}
                  </button>
                </td>
              </tr>
            ))}
            {!articles.isLoading && (articles.data ?? []).length === 0 && (
              <tr><td colSpan={4} className="muted">—</td></tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="card">
        <h2 style={{ marginTop: 0 }}>{t("kb.documents")}</h2>
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", marginBottom: 12 }}>
          <input style={{ maxWidth: 260 }} placeholder={t("kb.docTitle")} value={docTitle}
            onChange={(e) => setDocTitle(e.target.value)} />
          <button className="primary" disabled={upload.isPending} onClick={() => fileRef.current?.click()}>
            {upload.isPending ? t("kb.uploading") : t("kb.chooseFile")}
          </button>
          <input ref={fileRef} type="file" style={{ display: "none" }} accept=".pdf,application/pdf" onChange={onFile} />
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {(documents.data ?? []).map((d) => (
            <div key={d.id} style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "center" }}>
              <span>📄 {d.title} <span className="muted" style={{ fontSize: 12 }}>· {d.file_name} · {dateShort(d.created_at)}</span></span>
              <button className="ghost" style={{ color: "var(--bad)", padding: "2px 10px" }}
                onClick={() => { if (window.confirm(t("kb.confirmDeleteDoc", { title: d.title }))) removeDoc.mutate(d.id); }}>
                {t("common.delete")}
              </button>
            </div>
          ))}
          {(documents.data ?? []).length === 0 && <p className="muted" style={{ margin: 0 }}>—</p>}
        </div>
      </div>
    </div>
  );
}
