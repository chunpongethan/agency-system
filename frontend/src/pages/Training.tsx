import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, downloadFile, fetchBlobUrl, errorText } from "../api/client";
import { useI18n } from "../i18n/LanguageContext";
import { dateShort } from "../lib/format";
import type { TrainingMaterial, TrainingFile } from "../api/types";

const PREVIEWABLE = ["application/pdf", "image/png", "image/jpeg", "image/jpg",
                     "image/gif", "image/webp", "text/plain"];
const canPreview = (ctype: string) => PREVIEWABLE.includes((ctype || "").toLowerCase());

// Agent-facing training portal: browse materials grouped by category, filter by
// category, search by title/description, open links, and preview files on screen.
export default function Training() {
  const { t } = useI18n();
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState<string>("");
  const [dlError, setDlError] = useState<string | null>(null);
  const [preview, setPreview] = useState<{ url: string; name: string; type: string } | null>(null);

  function closePreview() {
    if (preview) URL.revokeObjectURL(preview.url);
    setPreview(null);
  }
  async function onPreview(mid: number, f: TrainingFile) {
    setDlError(null);
    try {
      if (!canPreview(f.content_type)) {
        await downloadFile(api.trainingFilePath(mid, f.id, true), f.file_name);
        return;
      }
      const url = await fetchBlobUrl(api.trainingFilePath(mid, f.id));
      closePreview();
      setPreview({ url, name: f.file_name, type: f.content_type });
    } catch (e) {
      setDlError(errorText(e, t));
    }
  }

  const materials = useQuery({ queryKey: ["training"], queryFn: () => api.listTraining() });
  const rows = materials.data ?? [];

  const categories = Array.from(new Set(rows.map((m) => m.category).filter(Boolean))).sort();
  const q = search.trim().toLowerCase();
  const filtered = rows.filter((m) => {
    if (category && m.category !== category) return false;
    if (!q) return true;
    return [m.title, m.description].some((v) => v && v.toLowerCase().includes(q));
  });

  // Group filtered materials by category.
  const groups = new Map<string, TrainingMaterial[]>();
  for (const m of filtered) {
    const key = m.category || t("training.uncategorized");
    const arr = groups.get(key);
    if (arr) arr.push(m);
    else groups.set(key, [m]);
  }
  const groupKeys = Array.from(groups.keys()).sort();

  return (
    <div>
      <h1 className="page-title">{t("training.title")}</h1>
      <p className="page-sub">{t("training.subtitle")}</p>

      <div className="card">
        {materials.isLoading && <div className="spinner">{t("common.loading")}</div>}
        {dlError && <div className="error">{dlError}</div>}

        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center", marginBottom: 14 }}>
          <input type="search" style={{ maxWidth: 320 }} placeholder={t("training.search")}
            value={search} onChange={(e) => setSearch(e.target.value)} />
          <div className="seg">
            <button className={category === "" ? "active" : ""} onClick={() => setCategory("")}>
              {t("training.allCategories")}
            </button>
            {categories.map((c) => (
              <button key={c} className={category === c ? "active" : ""} onClick={() => setCategory(c)}>{c}</button>
            ))}
          </div>
          <span className="muted" style={{ fontSize: 13, marginLeft: "auto" }}>
            {t("training.count", { count: filtered.length })}
          </span>
        </div>

        {!materials.isLoading && rows.length === 0 && <p className="muted">{t("training.empty")}</p>}
        {!materials.isLoading && rows.length > 0 && filtered.length === 0 && (
          <p className="muted">{t("training.noMatch")}</p>
        )}

        {groupKeys.map((cat) => (
          <div key={cat} style={{ marginBottom: 20 }}>
            <h2 style={{ fontSize: 15, margin: "0 0 10px", display: "flex", alignItems: "center", gap: 8 }}>
              <span className="badge dc">{cat}</span>
              <span className="muted" style={{ fontSize: 12, fontWeight: 400 }}>
                {t("training.count", { count: groups.get(cat)!.length })}
              </span>
            </h2>
            <div className="grid cols-2">
              {groups.get(cat)!.map((m) => (
                <div key={m.id} className="card" style={{ margin: 0 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "baseline" }}>
                    <strong>{m.title}</strong>
                    <span className="muted" style={{ fontSize: 12, whiteSpace: "nowrap" }}>{dateShort(m.created_at)}</span>
                  </div>
                  {m.description && (
                    <p className="muted" style={{ fontSize: 13, margin: "6px 0 0", whiteSpace: "pre-wrap" }}>{m.description}</p>
                  )}
                  <div style={{ display: "flex", gap: 8, marginTop: 10, flexWrap: "wrap" }}>
                    {m.link_url && (
                      <a className="badge role" style={{ textDecoration: "none", padding: "4px 10px" }}
                        href={m.link_url} target="_blank" rel="noopener noreferrer">
                        {t("training.openLink")} ↗
                      </a>
                    )}
                    {m.files.map((f) => (
                      <button key={f.id} className="ghost" style={{ padding: "3px 10px" }}
                        onClick={() => onPreview(m.id, f)}
                        title={f.file_name}>
                        {canPreview(f.content_type) ? "👁 " : "↓ "}{f.file_name}
                      </button>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>

      {preview && (
        <div className="modal-backdrop" onClick={closePreview}>
          <div className="modal-panel" onClick={(e) => e.stopPropagation()}>
            <div className="modal-head">
              <strong style={{ fontSize: 14 }}>{preview.name}</strong>
              <div style={{ display: "flex", gap: 8 }}>
                <a className="ghost" style={{ padding: "3px 10px" }} href={preview.url}
                  download={preview.name}>{t("training.download")}</a>
                <button className="ghost" style={{ padding: "3px 10px" }} onClick={closePreview}>✕</button>
              </div>
            </div>
            <div className="modal-body">
              {preview.type.startsWith("image/")
                ? <img src={preview.url} alt={preview.name} style={{ maxWidth: "100%", maxHeight: "100%", objectFit: "contain" }} />
                : <iframe title={preview.name} src={preview.url} style={{ width: "100%", height: "100%", border: "none" }} />}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
