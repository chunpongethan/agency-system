import { useEffect, useState, type FormEvent } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, errorText, downloadFile } from "../../api/client";
import { useI18n } from "../../i18n/LanguageContext";
import { dateShort } from "../../lib/format";
import { companyLabel } from "../../i18n/labels";
import type { TrainingMaterial } from "../../api/types";

const COMPANIES = ["heritree", "cpm"];
const BLANK = { title: "", category: "", description: "", link_url: "",
                companies: [...COMPANIES], inline_preview: false };

export default function AdminTraining() {
  const { t } = useI18n();
  const qc = useQueryClient();
  const materials = useQuery({ queryKey: ["training"], queryFn: () => api.listTraining() });
  const categories = useQuery({ queryKey: ["trainingCategories"], queryFn: () => api.trainingCategories() });
  const rows = materials.data ?? [];
  const cats = categories.data ?? [];

  const [showForm, setShowForm] = useState(false);
  const [editId, setEditId] = useState<number | null>(null);
  const [form, setForm] = useState<typeof BLANK>({ ...BLANK });
  const [files, setFiles] = useState<File[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [listError, setListError] = useState<string | null>(null);

  async function onDownload(mid: number, fileId: number, name: string) {
    setListError(null);
    try {
      await downloadFile(api.trainingFilePath(mid, fileId, true), name);
    } catch (e) {
      setListError(errorText(e, t));
    }
  }
  function toggleCompany(ckey: string) {
    setForm((f) => ({
      ...f,
      companies: f.companies.includes(ckey)
        ? f.companies.filter((x) => x !== ckey) : [...f.companies, ckey],
    }));
  }

  const invalidate = () => qc.invalidateQueries({ queryKey: ["training"] });
  const onErr = (e: unknown) => setError(errorText(e, t) || t("training.saveFailed"));

  // --- Training types (培訓類別) management ---------------------------------
  const invalidateCats = () => qc.invalidateQueries({ queryKey: ["trainingCategories"] });
  const [catEdits, setCatEdits] = useState<Record<number, string>>({});
  const [newCat, setNewCat] = useState("");
  const [catError, setCatError] = useState<string | null>(null);
  const onCatErr = (e: unknown) => setCatError(errorText(e, t) || t("training.saveFailed"));
  useEffect(() => {
    const m: Record<number, string> = {};
    cats.forEach((c) => { m[c.id] = c.name; });
    setCatEdits(m);
  }, [categories.data]);

  const addCat = useMutation({
    mutationFn: () => api.createTrainingCategory({ name: newCat.trim(), sort_order: cats.length }),
    onSuccess: () => { invalidateCats(); setNewCat(""); setCatError(null); },
    onError: onCatErr,
  });
  const renameCat = useMutation({
    mutationFn: (id: number) => api.updateTrainingCategory(id, { name: (catEdits[id] || "").trim() }),
    onSuccess: () => { invalidateCats(); setCatError(null); },
    onError: onCatErr,
  });
  const delCat = useMutation({
    mutationFn: (id: number) => api.deleteTrainingCategory(id),
    onSuccess: () => { invalidateCats(); setCatError(null); },
    onError: onCatErr,
  });

  // Options for the material form's type picker: managed types, plus the current
  // material's category if it's a legacy value not in the managed list.
  const catNames = cats.map((c) => c.name);
  const typeOptions = form.category && !catNames.includes(form.category)
    ? [form.category, ...catNames] : catNames;

  const save = useMutation({
    mutationFn: async () => {
      const payload = {
        title: form.title,
        category: form.category,
        description: form.description || null,
        link_url: form.link_url || null,
        companies: form.companies,
        inline_preview: form.inline_preview,
      };
      const saved = editId
        ? await api.updateTraining(editId, payload)
        : await api.createTraining(payload);
      if (files.length) await api.uploadTrainingFiles(saved.id, files);
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
    mutationFn: (v: { mid: number; fid: number }) => api.deleteTrainingFile(v.mid, v.fid),
    onSuccess: invalidate,
    onError: onErr,
  });

  function openCreate() {
    setEditId(null); setForm({ ...BLANK }); setFiles([]); setError(null); setShowForm(true);
  }
  function openEdit(m: TrainingMaterial) {
    setEditId(m.id);
    setForm({ title: m.title, category: m.category, description: m.description ?? "",
              link_url: m.link_url ?? "", companies: m.companies ?? [...COMPANIES],
              inline_preview: m.inline_preview });
    setFiles([]); setError(null); setShowForm(true);
  }
  function closeForm() { setShowForm(false); setEditId(null); setFiles([]); }

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
              <select value={form.category} required
                onChange={(e) => setForm({ ...form, category: e.target.value })}>
                <option value="" disabled>{t("training.selectType")}</option>
                {typeOptions.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
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
              <label>{t("training.fFiles")}</label>
              <input type="file" multiple onChange={(e) => setFiles(Array.from(e.target.files ?? []))} />
              <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>
                {t("training.fileHint", { mb: 25 })}{files.length ? ` · ${files.length}` : ""}
              </div>
            </div>
          </div>
          <div style={{ marginTop: 6 }}>
            <label>{t("training.fCompanies")}</label>
            <div style={{ display: "flex", gap: 16 }}>
              {COMPANIES.map((ckey) => (
                <label key={ckey} style={{ display: "flex", alignItems: "center", gap: 6, fontWeight: 400 }}>
                  <input type="checkbox" style={{ width: "auto" }} checked={form.companies.includes(ckey)}
                    onChange={() => toggleCompany(ckey)} />
                  {companyLabel(ckey)}
                </label>
              ))}
            </div>
            <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>{t("training.companiesHint")}</div>
          </div>
          <div style={{ marginTop: 8 }}>
            <label style={{ display: "flex", alignItems: "center", gap: 8, fontWeight: 400 }}>
              <input type="checkbox" style={{ width: "auto" }} checked={form.inline_preview}
                onChange={(e) => setForm({ ...form, inline_preview: e.target.checked })} />
              {t("training.fInlinePreview")}
            </label>
            <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>{t("training.inlinePreviewHint")}</div>
          </div>
          {editing && editing.files.length > 0 && (
            <div style={{ marginTop: 10 }}>
              <label>{t("training.currentFiles")}</label>
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                {editing.files.map((f) => (
                  <div key={f.id} style={{ display: "flex", alignItems: "center", gap: 10 }}>
                    <span className="muted" style={{ fontSize: 13 }}>{f.file_name}</span>
                    <button type="button" className="ghost" style={{ color: "var(--bad)", padding: "2px 8px" }}
                      disabled={removeFile.isPending}
                      onClick={() => removeFile.mutate({ mid: editing.id, fid: f.id })}>{t("training.removeFile")}</button>
                  </div>
                ))}
              </div>
            </div>
          )}
          <div style={{ marginTop: 14 }}>
            <button className="primary" type="submit" disabled={save.isPending || form.companies.length === 0}>
              {save.isPending ? (files.length ? t("training.uploading") : t("training.saving")) : t("training.save")}
            </button>
          </div>
        </form>
      )}

      <div className="card">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", flexWrap: "wrap", gap: 8 }}>
          <h2 style={{ margin: 0 }}>{t("training.types")}</h2>
          <span className="muted" style={{ fontSize: 13 }}>{t("training.typesHint")}</span>
        </div>
        {catError && <div className="error">{catError}</div>}
        <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 10 }}>
          {cats.map((c) => (
            <div key={c.id} style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
              <input style={{ maxWidth: 260 }} value={catEdits[c.id] ?? ""}
                onChange={(e) => setCatEdits({ ...catEdits, [c.id]: e.target.value })} />
              <button className="ghost" style={{ padding: "3px 10px" }}
                disabled={renameCat.isPending || !(catEdits[c.id] ?? "").trim() || catEdits[c.id] === c.name}
                onClick={() => renameCat.mutate(c.id)}>{t("training.save")}</button>
              <button className="ghost" style={{ padding: "3px 10px", color: "var(--bad)" }}
                disabled={delCat.isPending}
                onClick={() => { if (window.confirm(t("training.confirmDeleteType", { name: c.name }))) delCat.mutate(c.id); }}>
                {t("common.delete")}
              </button>
            </div>
          ))}
          {!categories.isLoading && cats.length === 0 && <p className="muted" style={{ margin: 0 }}>{t("training.noTypes")}</p>}
          <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 4 }}>
            <input style={{ maxWidth: 260 }} placeholder={t("training.typeName")} value={newCat}
              onChange={(e) => setNewCat(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && newCat.trim()) { e.preventDefault(); addCat.mutate(); } }} />
            <button className="primary" style={{ padding: "3px 12px" }}
              disabled={addCat.isPending || !newCat.trim()} onClick={() => addCat.mutate()}>
              {t("training.addType")}
            </button>
          </div>
        </div>
      </div>

      <div className="card">
        {materials.isLoading && <div className="spinner">{t("common.loading")}</div>}
        {listError && <div className="error">{listError}</div>}
        <table>
          <thead>
            <tr>
              <th>{t("training.thTitle")}</th>
              <th>{t("training.thCategory")}</th>
              <th>{t("training.thCompanies")}</th>
              <th>{t("training.thDate")}</th>
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
                  <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                    {(m.companies ?? COMPANIES).map((ckey) => (
                      <span key={ckey} className="badge unit" style={{ fontSize: 11 }}>{companyLabel(ckey)}</span>
                    ))}
                  </div>
                </td>
                <td className="muted" style={{ whiteSpace: "nowrap" }}>{dateShort(m.created_at)}</td>
                <td>
                  <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                    {m.link_url && (
                      <a className="badge role" href={m.link_url} target="_blank" rel="noopener noreferrer"
                        style={{ textDecoration: "none" }}>{t("training.hasLink")} ↗</a>
                    )}
                    {m.files.map((f) => (
                      <button key={f.id} type="button" onClick={() => onDownload(m.id, f.id, f.file_name)}
                        title={f.file_name}
                        style={{ width: "auto", padding: "2px 8px", cursor: "pointer", fontSize: 12 }}
                        className="ghost">↓ {f.file_name}</button>
                    ))}
                    {!m.link_url && m.files.length === 0 && <span className="muted">—</span>}
                  </div>
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
              <tr><td colSpan={6} className="muted">{t("training.empty")}</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
