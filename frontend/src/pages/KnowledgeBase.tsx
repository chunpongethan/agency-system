import { useState, useRef, useEffect, type FormEvent, type MouseEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, downloadFile, errorText } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { useI18n } from "../i18n/LanguageContext";
import { chineseVariant } from "../lib/zh";
import type { KbArticle, KbSource, KbChatTurn } from "../api/types";

type ChatMsg = { role: "user" | "assistant"; content: string; sources?: KbSource[] };

const SRC_KEY: Record<string, string> = {
  article: "kb.srcArticle", document: "kb.srcDocument",
  training: "kb.srcTraining", product: "kb.srcProduct",
};

// Deep-link a source to the specific item on a page the viewer can reach.
// Products live on a seller page (/products) and a separate admin page
// (/admin/products); the target page reads `?focus=`/`?material=` and opens that
// item. Articles/documents are handled in-page (modal / download) via onClick.
function kbHref(sourceType: string, refId: number, role: string | undefined): string {
  if (sourceType === "product")
    return `#${role === "admin" ? "/admin/products" : "/products"}?focus=${refId}`;
  if (sourceType === "training") return `#/training?material=${refId}`;
  return "#/knowledge-base";       // article, document
}

export default function KnowledgeBase() {
  const { t } = useI18n();
  const [tab, setTab] = useState<"ask" | "browse">("ask");

  const status = useQuery({ queryKey: ["kbStatus"], queryFn: () => api.kbStatus() });
  const aiEnabled = status.data?.ai_enabled ?? false;

  // If the AI is off, default to the Browse tab.
  useEffect(() => { if (status.data && !aiEnabled) setTab("browse"); }, [status.data, aiEnabled]);

  return (
    <div>
      <h1 className="page-title">{t("kb.title")}</h1>
      <p className="page-sub">{t("kb.subtitle")}</p>

      <div className="seg" style={{ marginBottom: 14 }}>
        <button className={tab === "ask" ? "active" : ""} onClick={() => setTab("ask")}>{t("kb.tabAsk")}</button>
        <button className={tab === "browse" ? "active" : ""} onClick={() => setTab("browse")}>{t("kb.tabBrowse")}</button>
      </div>

      {tab === "ask" ? <AskPanel aiEnabled={aiEnabled} /> : <BrowsePanel />}
    </div>
  );
}

// --- Ask (chat) --------------------------------------------------------------
function AskPanel({ aiEnabled }: { aiEnabled: boolean }) {
  const { t } = useI18n();
  const { me } = useAuth();
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, sending]);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    const q = input.trim();
    if (!q || sending) return;
    setError(null);
    const history: KbChatTurn[] = messages.map((m) => ({ role: m.role, content: m.content }));
    setMessages((prev) => [...prev, { role: "user", content: q }]);
    setInput("");
    setSending(true);
    try {
      const res = await api.kbAsk(q, history);
      setMessages((prev) => [...prev, { role: "assistant", content: res.answer, sources: res.sources }]);
    } catch (err) {
      setError(errorText(err, t));
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="card">
      {!aiEnabled && <div className="error" style={{ marginBottom: 12 }}>{t("kb.aiDisabled")}</div>}
      <div ref={scrollRef} className="kb-chat">
        {messages.length === 0 && <p className="muted" style={{ textAlign: "center", margin: "24px 0" }}>{t("kb.emptyChat")}</p>}
        {messages.map((m, i) => (
          <div key={i} className={`kb-msg ${m.role}`}>
            <div className="kb-bubble">
              <div style={{ whiteSpace: "pre-wrap" }} lang={chineseVariant(m.content)}>{m.content}</div>
              {m.sources && m.sources.length > 0 && (
                <div className="kb-sources">
                  <span className="muted" style={{ fontSize: 11 }}>{t("kb.sources")}：</span>
                  {m.sources.map((s) => (
                    <a key={s.n} href={kbHref(s.source_type, s.ref_id, me?.role)} className="badge role kb-src" title={s.title}>
                      [{s.n}] {t(SRC_KEY[s.source_type] || "kb.srcArticle")}: {s.title}
                    </a>
                  ))}
                </div>
              )}
            </div>
          </div>
        ))}
        {sending && <div className="kb-msg assistant"><div className="kb-bubble muted">{t("kb.thinking")}</div></div>}
      </div>

      {error && <div className="error" style={{ marginTop: 10 }}>{error}</div>}

      <form onSubmit={onSubmit} style={{ display: "flex", gap: 8, marginTop: 12, alignItems: "flex-end" }}>
        <textarea rows={2} style={{ flex: 1, resize: "vertical" }} value={input}
          placeholder={t("kb.askPlaceholder")} disabled={!aiEnabled || sending}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); onSubmit(e); } }} />
        <button className="primary" type="submit" disabled={!aiEnabled || sending || !input.trim()}>
          {sending ? t("kb.thinking") : t("kb.send")}
        </button>
        {messages.length > 0 && (
          <button type="button" className="ghost" onClick={() => { setMessages([]); setError(null); }}>{t("kb.clear")}</button>
        )}
      </form>
    </div>
  );
}

// --- Browse / search ---------------------------------------------------------
function BrowsePanel() {
  const { t } = useI18n();
  const { me } = useAuth();
  const [q, setQ] = useState("");
  const [openArticle, setOpenArticle] = useState<KbArticle | null>(null);
  const [dlError, setDlError] = useState<string | null>(null);

  const search = useQuery({
    queryKey: ["kbSearch", q.trim()],
    queryFn: () => api.kbSearch(q.trim()),
    enabled: q.trim().length > 0,
  });
  const articles = useQuery({ queryKey: ["kbArticles"], queryFn: () => api.listKbArticles() });
  const documents = useQuery({ queryKey: ["kbDocuments"], queryFn: () => api.listKbDocuments() });

  async function onDownloadDoc(id: number, name: string) {
    setDlError(null);
    try { await downloadFile(api.kbDocumentPath(id, true), name); }
    catch (e) { setDlError(errorText(e, t)); }
  }

  const searching = q.trim().length > 0;

  return (
    <div className="card">
      <input type="search" style={{ maxWidth: 420, marginBottom: 14 }} placeholder={t("kb.searchPlaceholder")}
        value={q} onChange={(e) => setQ(e.target.value)} />
      {dlError && <div className="error" style={{ marginBottom: 10 }}>{dlError}</div>}

      {searching ? (
        <>
          {search.isLoading && <div className="spinner">{t("common.loading")}</div>}
          {search.data && search.data.length === 0 && <p className="muted">{t("kb.noResults")}</p>}
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {(search.data ?? []).map((r) => {
              // Articles open in the modal, documents download; training/products
              // navigate to a page the viewer can access.
              const onClick = (e: MouseEvent) => {
                if (r.source_type === "article") {
                  e.preventDefault();
                  const a = (articles.data ?? []).find((x) => x.id === r.ref_id);
                  if (a) setOpenArticle(a);
                } else if (r.source_type === "document") {
                  e.preventDefault();
                  onDownloadDoc(r.ref_id, r.title);
                }
              };
              return (
                <a key={`${r.source_type}-${r.ref_id}`} href={kbHref(r.source_type, r.ref_id, me?.role)}
                  className="kb-result" onClick={onClick}>
                  <div style={{ display: "flex", gap: 8, alignItems: "baseline" }}>
                    <span className="badge unit" style={{ fontSize: 11 }}>{t(SRC_KEY[r.source_type] || "kb.srcArticle")}</span>
                    <strong lang={chineseVariant(r.title)}>{r.title}</strong>
                  </div>
                  <div className="muted" style={{ fontSize: 12, marginTop: 3 }} lang={chineseVariant(r.snippet)}>{r.snippet}</div>
                </a>
              );
            })}
          </div>
        </>
      ) : (
        <div className="grid cols-2" style={{ alignItems: "start" }}>
          <div>
            <h3 style={{ margin: "0 0 8px" }}>{t("kb.articles")}</h3>
            {(articles.data ?? []).length === 0 && <p className="muted">—</p>}
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {(articles.data ?? []).map((a) => (
                <button key={a.id} className="kb-result" style={{ textAlign: "left" }} onClick={() => setOpenArticle(a)}>
                  <strong lang={chineseVariant(a.title)}>{a.title}</strong>
                  {a.category && <span className="badge dc" style={{ marginLeft: 8, fontSize: 11 }}>{a.category}</span>}
                  {!a.is_active && <span className="badge cancelled" style={{ marginLeft: 8, fontSize: 11 }}>停用</span>}
                </button>
              ))}
            </div>
          </div>
          <div>
            <h3 style={{ margin: "0 0 8px" }}>{t("kb.documents")}</h3>
            {(documents.data ?? []).length === 0 && <p className="muted">—</p>}
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {(documents.data ?? []).map((d) => (
                <div key={d.id} className="kb-result" style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "center" }}>
                  <span>📄 {d.title}</span>
                  <button className="ghost" style={{ padding: "2px 10px" }} onClick={() => onDownloadDoc(d.id, d.file_name)}>↓ {t("kb.download")}</button>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {openArticle && (
        <div className="modal-backdrop" onClick={() => setOpenArticle(null)}>
          <div className="modal-panel" onClick={(e) => e.stopPropagation()}>
            <div className="modal-head">
              <strong style={{ fontSize: 15 }} lang={chineseVariant(openArticle.title)}>{openArticle.title}</strong>
              <button className="ghost" style={{ padding: "3px 10px" }} onClick={() => setOpenArticle(null)}>✕</button>
            </div>
            <div className="modal-body detail">
              <div className="training-remark" lang={chineseVariant(openArticle.body)} dangerouslySetInnerHTML={{ __html: openArticle.body }} />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
