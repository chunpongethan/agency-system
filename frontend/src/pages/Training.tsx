import { useState, useEffect, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, downloadFile, fetchBlobUrl, errorText } from "../api/client";
import { useI18n } from "../i18n/LanguageContext";
import { dateShort } from "../lib/format";
import type { TrainingMaterial, TrainingFile } from "../api/types";

const PREVIEWABLE = ["application/pdf", "image/png", "image/jpeg", "image/jpg",
                     "image/gif", "image/webp", "text/plain",
                     "video/mp4", "video/webm", "video/ogg", "video/quicktime"];
const isNative = (ctype: string) => PREVIEWABLE.includes((ctype || "").toLowerCase());
// A file previews on screen if it's a natively-viewable type, or the server has
// a rendered PDF preview for it (e.g. from an uploaded PPTX/DOCX).
const canPreview = (f: TrainingFile) => isNative(f.content_type) || !!f.preview_content_type;
// The content type of the bytes the preview endpoint will serve.
const previewType = (f: TrainingFile) => f.preview_content_type || f.content_type;

// Render the preview bytes by kind: image, video player, or an iframe (PDF —
// which also covers PPTX/DOCX rendered to PDF — and plain text).
function embed(url: string, type: string, name: string) {
  const t = (type || "").toLowerCase();
  if (t.startsWith("image/"))
    return <img src={url} alt={name} style={{ maxWidth: "100%", maxHeight: 480, display: "block", margin: "0 auto" }} />;
  if (t.startsWith("video/"))
    return <video src={url} controls preload="metadata"
      style={{ width: "100%", maxHeight: 480, background: "#000", display: "block" }} />;
  return <iframe title={name} src={url} style={{ width: "100%", height: 600, border: "none", display: "block", background: "#fff" }} />;
}

// A file rendered inline as a ready-to-view preview, so the agent doesn't have to
// click anything first (video, PDF, PPTX→PDF, image, text). The file endpoint is
// auth-gated, so we fetch it as an object URL and revoke it on unmount. Fetching
// is deferred until the card scrolls near the viewport — otherwise every file on
// the page would download its full bytes on load.
function InlinePreview({ previewPath, name, type, onDownload }:
  { previewPath: string; name: string; type: string; onDownload: () => void }) {
  const { t } = useI18n();
  const wrapRef = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(false);
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const el = wrapRef.current;
    if (!el || typeof IntersectionObserver === "undefined") { setVisible(true); return; }
    const io = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting)) { setVisible(true); io.disconnect(); }
    }, { rootMargin: "300px" });
    io.observe(el);
    return () => io.disconnect();
  }, []);

  useEffect(() => {
    if (!visible) return;
    let cancelled = false;
    let objectUrl: string | null = null;
    fetchBlobUrl(previewPath)
      .then((u) => {
        if (cancelled) { URL.revokeObjectURL(u); return; }
        objectUrl = u;
        setUrl(u);
      })
      .catch(() => { if (!cancelled) setFailed(true); });
    return () => { cancelled = true; if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [visible, previewPath]);

  return (
    <div ref={wrapRef} style={{ marginTop: 10 }}>
      <div className="muted" style={{ fontSize: 12, marginBottom: 4, display: "flex",
        justifyContent: "space-between", gap: 8, alignItems: "center" }}>
        <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={name}>{name}</span>
        <button type="button" onClick={onDownload} style={{ background: "none", border: "none",
          color: "var(--brand, #2563eb)", cursor: "pointer", padding: 0, fontSize: 12, whiteSpace: "nowrap" }}>
          ↓ {t("training.download")}
        </button>
      </div>
      {!failed && (url
        ? <div style={{ border: "1px solid var(--line)", borderRadius: 8, overflow: "hidden", background: "#f3f4f6" }}>
            {embed(url, type, name)}
          </div>
        : <div className="muted" style={{ fontSize: 12 }}>…</div>)}
    </div>
  );
}

// Agent-facing training portal: browse materials grouped by category, filter by
// category, search by title/description, open links, and preview files on screen
// (videos, PDFs, PPTX/Office rendered to PDF, and images render inline).
export default function Training() {
  const { t } = useI18n();
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState<string>("");
  const [dlError, setDlError] = useState<string | null>(null);

  async function onDownloadFile(m: TrainingMaterial, f: TrainingFile) {
    setDlError(null);
    try {
      await downloadFile(api.trainingFilePath(m.id, f.id, true), f.file_name);
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
                    <div className="training-remark" style={{ fontSize: 13, margin: "6px 0 0" }}
                      dangerouslySetInnerHTML={{ __html: m.description }} />
                  )}
                  {(m.link_url || m.files.some((f) => !canPreview(f))) && (
                    <div style={{ display: "flex", gap: 8, marginTop: 10, flexWrap: "wrap" }}>
                      {m.link_url && (
                        <a className="badge role" style={{ textDecoration: "none", padding: "4px 10px" }}
                          href={m.link_url} target="_blank" rel="noopener noreferrer">
                          {t("training.openLink")} ↗
                        </a>
                      )}
                      {/* Non-previewable files can only be downloaded. */}
                      {m.files.filter((f) => !canPreview(f)).map((f) => (
                        <button key={f.id} className="ghost" style={{ padding: "3px 10px" }}
                          onClick={() => onDownloadFile(m, f)} title={f.file_name}>
                          ↓ {f.file_name}
                        </button>
                      ))}
                    </div>
                  )}
                  {/* Previewable files (video, PDF, PPTX→PDF, image) render in place. */}
                  {m.files.filter(canPreview).map((f) => (
                    <InlinePreview key={f.id} previewPath={api.trainingFilePath(m.id, f.id)}
                      name={f.file_name} type={previewType(f)} onDownload={() => onDownloadFile(m, f)} />
                  ))}
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
