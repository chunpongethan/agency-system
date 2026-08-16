import { useState, type FormEvent } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, errorText } from "../../api/client";
import { useI18n } from "../../i18n/LanguageContext";
import type { TrainingMaterial } from "../../api/types";

// Seed category suggestions for the datalist (admins may type their own too).
const CATEGORY_SUGGESTIONS = ["新人入職", "產品知識", "銷售技巧", "合規法規", "系統操作"];
const BLANK = { title: "", category: "", description: "", link_url: "" };

export default function AdminTraining() {
  const { t } = useI18n();
  const qc = useQueryClient();
  const materials = useQuery({ queryKey: ["training"], queryFn: () => api.listTraining() });
  const rows = materials.data ?? [];

  const [showForm, setShowForm] = useState(false);
  const [editId, setEditId] = useState<number | null>(null);
  const [form, setForm] = useState({ ...BLANK });
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);

  const invalidate = () => qc.invalidateQueries({ queryKey: ["training"] });
  const onErr = (e: unknown) => setError(errorText(e, t) || t("training.saveFailed"));

  // Existing category values (for the datalist) merged with the seed suggestions.
  const categoryOptions = Array.from(
    new Set([...CATEGORY_SUGGESTIONS, ...rows.map((m) => m.category).filter(Boolean)]),
  );

  const save = useMutation({
    mutationFn: async () => {
      const payload = {
        title: form.title,
        category: form.category,
        description: form.description || null,
        link_url: form.link_url || null,
      };
      const saved = editId
        ? await api.updateTraining(editId, payload)
        : await api.createTraining(payload);
      if (file) await api.uploadTrainingFile(saved.id, file);
      return saved;
    },
    onSuccess: () => { invalidate(); closeForm(); },
    onError: onErr,
  });

  const remove = useMutation({
    mutationFn: (id: number) => api.deleteTraining(id),
    onSuccess: invalidate,
    onError: onErr,
  });

  const removeFile = useMutation({
    mutationFn: (id: number) => api.deleteTrainingFile(id),
    onSuccess: invalidate,
    onError: onErr,
  });

  function openCreate() {
    setEditId(null); setForm({ ...BLANK }); setFile(null); setError(null); setShowForm(true);
  }
  function openEdit(m: TrainingMaterial) {
    setEditId(m.id);
    setForm({ title: m.title, category: m.category, description: m.description ?? "", link_url: m.link_url ?? "" });
    setFile(null); setError(null); setShowForm(true);
  }
  function closeForm() { setShowForm(false); setEditId(null); setFile(null); }

  function onSubmit(e: FormEvent) { e.preventDefault(); save.mutate(); }

  const editing = editId != null ? rows.find((m) => m.id === editId) : undefined;

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div>
          <h1 className="page-title">{t("training.adminTitle")}</h1>
          <p className="page-sub">{t("training.adminSubtitle")}</p>
        </div>
        <button className="primary" onClick={() => (showForm ? closeForm() : openCreate())}>
          {showForm ? t("common.cancel") : t("training.new")}
        </button>
      </div>

      {showForm && (
        <form className="card" onSubmit={onSubmit}>
          <h2>{editId ? t("training.editTitle") : t("training.new")}</h2>
          {error && <div className="error">{error}</div>}
          <div className="row">
            <div>
              <label>{t("training.fTitle")}</label>
              <input value={form.title} required
                onChange={(e) => setForm({ ...form, title: e.target.value })} />
            </div>
            <div>
              <label>{t("training.fCategory")}</label>
              <input list="training-categories" value={form.category} required
                onChange={(e) => setForm({ ...form, category: e.target.value })} />
              <datalist id="training-categories">
                {categoryOptions.map((c) => <option key={c} value={c} />)}
              </datalist>
            </div>
          </div>
          <div>
            <label>{t("training.fDescription")}</label>
            <textarea rows={3} value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })} />
          </div>
          <div className="row">
            <div>
              <label>{t("training.fLink")}</label>
              <input type="url" placeholder="https://…" value={form.link_url}
                onChange={(e) => setForm({ ...form, link_url: e.target.value })} />
            </div>
            <div>
              <label>{t("training.fFile")}</label>
              <input type="file" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
              <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>{t("training.fileHint", { mb: 25 })}</div>
            </div>
          </div>
          {editing?.has_file && (
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 6 }}>
              <span className="muted" style={{ fontSize: 13 }}>
                {t("training.currentFile")}: {editing.file_name}
              </span>
              <button type="button" className="ghost" style={{ color: "var(--bad)", padding: "2px 8px" }}
                disabled={removeFile.isPending}
                onClick={() => removeFile.mutate(editing.id)}>{t("training.removeFile")}</button>
            </div>
          )}
          <div style={{ marginTop: 14 }}>
            <button className="primary" type="submit" disabled={save.isPending}>
              {save.isPending ? (file ? t("training.uploading") : t("training.saving")) : t("training.save")}
            </button>
          </div>
        </form>
      )}

      <div className="card">
        {materials.isLoading && <div className="spinner">{t("common.loading")}</div>}
        <table>
          <thead>
            <tr>
              <th>{t("training.thTitle")}</th>
              <th>{t("training.thCategory")}</th>
              <th>{t("training.thAttachments")}</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((m) => (
              <tr key={m.id}>
                <td>{m.title}</td>
                <td><span className="badge dc">{m.category}</span></td>
                <td>
                  {m.link_url && <span className="badge role" style={{ marginRight: 4 }}>{t("training.hasLink")}</span>}
                  {m.has_file && <span className="badge unit">{t("training.hasFile")}</span>}
                  {!m.link_url && !m.has_file && <span className="muted">—</span>}
                </td>
                <td className="num" style={{ whiteSpace: "nowrap" }}>
                  <button className="ghost" onClick={() => openEdit(m)}>{t("common.edit")}</button>{" "}
                  <button className="ghost" style={{ color: "var(--bad)" }}
                    onClick={() => { if (window.confirm(t("training.confirmDelete", { title: m.title }))) remove.mutate(m.id); }}>
                    {t("common.delete")}
                  </button>
                </td>
              </tr>
            ))}
            {!materials.isLoading && rows.length === 0 && (
              <tr><td colSpan={4} className="muted">{t("training.empty")}</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
