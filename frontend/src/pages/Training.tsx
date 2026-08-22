import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, downloadFile, errorText } from "../api/client";
import { useI18n } from "../i18n/LanguageContext";
import { dateShort } from "../lib/format";
import type { TrainingMaterial } from "../api/types";

// Agent-facing training portal: browse materials grouped by category, filter by
// category, search by title/description, open external links or download files.
export default function Training() {
  const { t } = useI18n();
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState<string>("");
  const [dlError, setDlError] = useState<string | null>(null);

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

  async function onDownload(m: TrainingMaterial) {
    setDlError(null);
    try {
      await downloadFile(`/training-materials/${m.id}/file`, m.file_name || "file");
    } catch (e) {
      setDlError(errorText(e, t));
    }
  }

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
                    {m.has_file && (
                      <button className="ghost" style={{ padding: "3px 10px" }} onClick={() => onDownload(m)}>
                        {t("training.download")}{m.file_name ? ` · ${m.file_name}` : ""}
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
