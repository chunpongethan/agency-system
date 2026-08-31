import { useState, useEffect } from "react";
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

// --- Thumbnail: a cheap type tile (no file fetch), so the list never preloads
// the actual (possibly large) file bytes. -----------------------------------
type Kind = "video" | "doc" | "image" | "link" | "none";
const THUMB: Record<Kind, { bg: string; glyph: string }> = {
  video: { bg: "linear-gradient(135deg,#7c3aed,#4f46e5)", glyph: "🎬" },
  doc: { bg: "linear-gradient(135deg,#ef4444,#b91c1c)", glyph: "📄" },
  image: { bg: "linear-gradient(135deg,#10b981,#059669)", glyph: "🖼️" },
  link: { bg: "linear-gradient(135deg,#0ea5e9,#2563eb)", glyph: "🔗" },
  none: { bg: "linear-gradient(135deg,#64748b,#334155)", glyph: "📚" },
};
function materialKind(m: TrainingMaterial): Kind {
  const files = m.files ?? [];
  if (files.some((f) => previewType(f).toLowerCase().startsWith("video/"))) return "video";
  if (files.some((f) => previewType(f).toLowerCase() === "application/pdf")) return "doc";
  if (files.some((f) => previewType(f).toLowerCase().startsWith("image/"))) return "image";
  if (files.length) return "doc";
  if (m.link_url) return "link";
  return "none";
}
function primaryExt(m: TrainingMaterial): string | null {
  const f = (m.files ?? [])[0];
  if (f) {
    const dot = f.file_name.lastIndexOf(".");
    if (dot >= 0 && dot < f.file_name.length - 1) return f.file_name.slice(dot + 1).toUpperCase();
    return "FILE";
  }
  return m.link_url ? "LINK" : null;
}

// The material's thumbnail file: the first previewable file (image/PDF/video/
// Office-as-PDF), which is what the server can render a thumbnail from.
const thumbFile = (m: TrainingMaterial): TrainingFile | undefined => (m.files ?? []).find(canPreview);

// A real thumbnail tile: fetch the server-generated JPEG for the primary file
// (a tiny image, ~10-40 KB — not the full file). Falls back to the type glyph
// tile if there's no thumbnailable file or it 404s (e.g. video with no ffmpeg).
function ThumbTile({ material, kind, ext }: { material: TrainingMaterial; kind: Kind; ext: string | null }) {
  const file = thumbFile(material);
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!file) return;
    let cancelled = false;
    let objectUrl: string | null = null;
    fetchBlobUrl(api.trainingThumbPath(material.id, file.id))
      .then((u) => { if (cancelled) { URL.revokeObjectURL(u); return; } objectUrl = u; setUrl(u); })
      .catch(() => { if (!cancelled) setFailed(true); });
    return () => { cancelled = true; if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [file, material.id]);

  return (
    <div className="tm-thumb" style={{ background: THUMB[kind].bg }}>
      {url && !failed
        ? <img className="tm-thumb-img" src={url} alt="" />
        : <span aria-hidden>{THUMB[kind].glyph}</span>}
      {ext && <span className="tm-kind">{ext}</span>}
    </div>
  );
}

// Strip the sanitised HTML remark down to a short plain-text summary. DOMParser
// does not run scripts or fetch images, so this touches nothing on the network.
function plainSummary(html: string | null | undefined, n = 160): string {
  if (!html) return "";
  const doc = new DOMParser().parseFromString(html, "text/html");
  const text = (doc.body.textContent || "").replace(/\s+/g, " ").trim();
  return text.length > n ? text.slice(0, n).trimEnd() + "…" : text;
}

// Render preview bytes by kind: image, video player, or an iframe (PDF — which
// also covers PPTX/DOCX rendered to PDF — and plain text).
function embed(url: string, type: string, name: string) {
  const t = (type || "").toLowerCase();
  if (t.startsWith("image/"))
    return <img src={url} alt={name} style={{ maxWidth: "100%", maxHeight: 480, display: "block", margin: "0 auto" }} />;
  if (t.startsWith("video/"))
    return <video src={url} controls autoPlay preload="metadata"
      style={{ width: "100%", maxHeight: 520, background: "#000", display: "block" }} />;
  return <iframe title={name} src={url} style={{ width: "100%", height: 600, border: "none", display: "block", background: "#fff" }} />;
}

// One file's preview inside the detail modal. Fetched eagerly (the user opened
// the item on purpose), and the object URL is revoked on unmount.
function FilePreview({ previewPath, name, type, onDownload }:
  { previewPath: string; name: string; type: string; onDownload: () => void }) {
  const { t } = useI18n();
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let cancelled = false;
    let objectUrl: string | null = null;
    fetchBlobUrl(previewPath)
      .then((u) => { if (cancelled) { URL.revokeObjectURL(u); return; } objectUrl = u; setUrl(u); })
      .catch(() => { if (!cancelled) setFailed(true); });
    return () => { cancelled = true; if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [previewPath]);
  return (
    <div style={{ marginTop: 12 }}>
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

// Agent-facing training portal: a light thumbnail+summary grid; clicking an item
// opens the full remark and its file previews (loaded only then).
export default function Training() {
  const { t } = useI18n();
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState<string>("");
  const [dlError, setDlError] = useState<string | null>(null);
  const [open, setOpen] = useState<TrainingMaterial | null>(null);

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

  // Keep the open material in sync if the list refetches.
  useEffect(() => {
    if (open) {
      const fresh = rows.find((m) => m.id === open.id);
      if (fresh && fresh !== open) setOpen(fresh);
    }
  }, [rows]); // eslint-disable-line react-hooks/exhaustive-deps

  // Close the modal on Escape.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(null); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

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
            <div className="training-grid">
              {groups.get(cat)!.map((m) => {
                const kind = materialKind(m);
                const ext = primaryExt(m);
                const summary = plainSummary(m.description);
                const fileCount = (m.files ?? []).length;
                return (
                  <button key={m.id} type="button" className="tm-card" onClick={() => setOpen(m)}>
                    <ThumbTile material={m} kind={kind} ext={ext} />
                    <div className="tm-body">
                      <div className="tm-title-row">
                        <strong>{m.title}</strong>
                        <span className="muted" style={{ fontSize: 11, whiteSpace: "nowrap" }}>{dateShort(m.created_at)}</span>
                      </div>
                      {summary
                        ? <p className="tm-summary">{summary}</p>
                        : <p className="tm-summary muted" style={{ fontStyle: "italic" }}>{t("training.noSummary")}</p>}
                      <div className="tm-meta">
                        {fileCount > 0 && <span className="badge unit" style={{ fontSize: 11 }}>{t("training.fileCount", { n: fileCount })}</span>}
                        {m.link_url && <span className="badge role" style={{ fontSize: 11 }}>{t("training.hasLink")}</span>}
                        <span className="tm-open">{t("training.openItem")} →</span>
                      </div>
                    </div>
                  </button>
                );
              })}
            </div>
          </div>
        ))}
      </div>

      {open && (
        <div className="modal-backdrop" onClick={() => setOpen(null)}>
          <div className="modal-panel" onClick={(e) => e.stopPropagation()}>
            <div className="modal-head">
              <div style={{ minWidth: 0 }}>
                <strong style={{ fontSize: 15 }}>{open.title}</strong>
                <div className="muted" style={{ fontSize: 12 }}>
                  <span className="badge dc" style={{ marginRight: 6 }}>{open.category || t("training.uncategorized")}</span>
                  {dateShort(open.created_at)}
                </div>
              </div>
              <button className="ghost" style={{ padding: "3px 10px" }} onClick={() => setOpen(null)}>✕</button>
            </div>
            <div className="modal-body detail">
              {open.description && (
                <div className="training-remark" style={{ fontSize: 14 }}
                  dangerouslySetInnerHTML={{ __html: open.description }} />
              )}
              {open.link_url && (
                <div style={{ marginTop: 10 }}>
                  <a className="badge role" style={{ textDecoration: "none", padding: "5px 12px" }}
                    href={open.link_url} target="_blank" rel="noopener noreferrer">
                    {t("training.openLink")} ↗
                  </a>
                </div>
              )}
              {/* Non-previewable files → download buttons. */}
              {(open.files ?? []).some((f) => !canPreview(f)) && (
                <div style={{ display: "flex", gap: 8, marginTop: 12, flexWrap: "wrap" }}>
                  {(open.files ?? []).filter((f) => !canPreview(f)).map((f) => (
                    <button key={f.id} className="ghost" style={{ padding: "3px 10px" }}
                      onClick={() => onDownloadFile(open, f)} title={f.file_name}>
                      ↓ {f.file_name}
                    </button>
                  ))}
                </div>
              )}
              {/* Previewable files render in place, loaded now. */}
              {(open.files ?? []).filter(canPreview).map((f) => (
                <FilePreview key={f.id} previewPath={api.trainingFilePath(open.id, f.id)}
                  name={f.file_name} type={previewType(f)} onDownload={() => onDownloadFile(open, f)} />
              ))}
              {(open.files ?? []).length === 0 && !open.link_url && !open.description && (
                <p className="muted">{t("training.noSummary")}</p>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
