import { useMemo, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import type { QaLearner } from "../../api/types";
import { useI18n } from "../../i18n/LanguageContext";
import { dateTime } from "../../lib/format";

const num = (n: number) => n.toLocaleString();

// 問答特訓紀錄: progress learners report from the public /training/*.html pages.
export default function AdminQaTraining() {
  const { t } = useI18n();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["qaTraining"], queryFn: () => api.qaTraining(), refetchInterval: 30000 });
  const d = q.data;

  const [search, setSearch] = useState("");
  const [course, setCourse] = useState("");
  const [kind, setKind] = useState<"" | "qa" | "video">("");
  const [focus, setFocus] = useState<QaLearner | null>(null);   // history filtered to one learner × course

  const invalidate = () => qc.invalidateQueries({ queryKey: ["qaTraining"] });
  const delLearner = useMutation({
    mutationFn: (l: QaLearner) => api.deleteQaLearner(l.visitor_id, l.page),
    onSuccess: () => { setFocus(null); invalidate(); },
  });
  const clearAll = useMutation({ mutationFn: () => api.clearQaTraining(), onSuccess: () => { setFocus(null); invalidate(); } });

  const courses = useMemo(() => {
    const m = new Map<string, string>();
    (d?.learners || []).filter((l) => !kind || l.kind === kind).forEach((l) => m.set(l.page, l.page_title));
    return [...m.entries()].sort((a, b) => a[1].localeCompare(b[1]));
  }, [d, kind]);
  const pageKind = (page: string) => (page.endsWith("-video") ? "video" : "qa");

  const s = search.trim().toLowerCase();
  const learners = (d?.learners || []).filter((l) =>
    (!kind || l.kind === kind) && (!course || l.page === course) && (!s || l.learner_name.toLowerCase().includes(s)));
  const events = (d?.events || []).filter((e) => focus
    ? e.visitor_id === focus.visitor_id && e.page === focus.page
    : (!kind || pageKind(e.page) === kind) && (!course || e.page === course) && (!s || e.learner_name.toLowerCase().includes(s)));
  const completions = (d?.learners || []).reduce((n, l) => n + l.finished.length, 0);

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12, flexWrap: "wrap" }}>
        <div>
          <h1 className="page-title">{t("qaTraining.title")}</h1>
          <p className="page-sub">{t("qaTraining.subtitle")}</p>
        </div>
        {d && d.total_events > 0 && (
          <button className="danger" style={{ marginTop: 4 }} disabled={clearAll.isPending}
            onClick={() => { if (window.confirm(t("qaTraining.confirmClear"))) clearAll.mutate(); }}>
            {t("qaTraining.clearAll")}
          </button>
        )}
      </div>

      {q.isLoading && <div className="spinner">{t("common.loading")}</div>}
      {d && (
        <>
          <div className="grid cols-3">
            <div className="stat"><div className="label">{t("qaTraining.learners")}</div><div className="value">{num(new Set(d.learners.map((l) => l.visitor_id)).size)}</div></div>
            <div className="stat"><div className="label">{t("qaTraining.completions")}</div><div className="value">{num(completions)}</div></div>
            <div className="stat"><div className="label">{t("qaTraining.events")}</div><div className="value">{num(d.total_events)}</div></div>
          </div>

          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", margin: "12px 0" }}>
            <input value={search} onChange={(e) => { setSearch(e.target.value); setFocus(null); }}
              placeholder={t("qaTraining.search")} style={{ flex: "1 1 200px", maxWidth: 280 }} />
            <select value={kind} onChange={(e) => { setKind(e.target.value as "" | "qa" | "video"); setCourse(""); setFocus(null); }} style={{ flex: "0 1 160px" }}>
              <option value="">{t("qaTraining.kindAll")}</option>
              <option value="qa">{t("qaTraining.kindQa")}</option>
              <option value="video">{t("qaTraining.kindVideo")}</option>
            </select>
            <select value={course} onChange={(e) => { setCourse(e.target.value); setFocus(null); }} style={{ flex: "1 1 200px", maxWidth: 320 }}>
              <option value="">{t("qaTraining.allCourses")}</option>
              {courses.map(([page, title]) => <option key={page} value={page}>{title}</option>)}
            </select>
          </div>

          <div className="card">
            <h3 style={{ marginTop: 0 }}>{t("qaTraining.progress")}</h3>
            <div style={{ overflowX: "auto" }}>
              <table>
                <thead><tr>
                  <th>{t("qaTraining.learner")}</th>
                  <th>{t("qaTraining.course")}</th>
                  <th>{t("qaTraining.finished")}</th>
                  <th className="num">{t("qaTraining.exam")}</th>
                  <th>{t("qaTraining.lastActive")}</th>
                  <th></th>
                </tr></thead>
                <tbody>
                  {learners.map((l) => {
                    const sel = focus?.visitor_id === l.visitor_id && focus?.page === l.page;
                    return (
                      <tr key={l.visitor_id + l.page} onClick={() => setFocus(sel ? null : l)}
                        style={{ cursor: "pointer", background: sel ? "var(--row-selected, rgba(201,134,46,.12))" : undefined }}>
                        <td>{l.learner_name}</td>
                        <td>
                          {l.page_title}
                          {l.kind === "video" && <span style={{ marginLeft: 6, fontSize: 11, padding: "1px 6px", borderRadius: 8,
                            background: "rgba(106,44,107,.12)", color: "#6A2C6B", whiteSpace: "nowrap" }}>▶ {t("qaTraining.video")}</span>}
                        </td>
                        <td>
                          <strong>{l.finished.length}{l.module_total ? ` / ${l.module_total}` : ""}</strong>
                          {l.finished.length > 0 && <div className="muted" style={{ fontSize: 12 }}>{l.finished.join("、")}</div>}
                        </td>
                        <td className="num">
                          {l.kind === "video" ? (l.quiz_right != null
                            ? <>{l.quiz_right} / {l.quiz_total}
                              <div className="muted" style={{ fontSize: 12 }}>{t("qaTraining.quiz")} · {l.quiz_chapters} {t("qaTraining.quizChapters")}</div></>
                            : "—") : l.last_score != null ? <>{l.last_score}{l.exam_total ? ` / ${l.exam_total}` : ""}
                            {l.best_score != null && l.best_score !== l.last_score &&
                              <div className="muted" style={{ fontSize: 12 }}>{t("qaTraining.best")} {l.best_score}</div>}</> : "—"}
                        </td>
                        <td className="muted" style={{ fontSize: 13 }}>{dateTime(l.last_at)}</td>
                        <td className="num">
                          <button type="button" title={t("common.delete")} disabled={delLearner.isPending}
                            onClick={(e) => { e.stopPropagation(); if (window.confirm(t("qaTraining.confirmDelete"))) delLearner.mutate(l); }}
                            style={{ background: "none", border: "none", cursor: "pointer", color: "var(--danger, #dc2626)", fontSize: 15 }}>
                            ✕
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                  {learners.length === 0 && <tr><td colSpan={6} className="muted">{t("qaTraining.noData")}</td></tr>}
                </tbody>
              </table>
            </div>
            <p className="muted" style={{ fontSize: 12, marginBottom: 0 }}>{t("qaTraining.note")}</p>
          </div>

          <div className="card">
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
              <h3 style={{ margin: 0 }}>{t("qaTraining.history")}</h3>
              {focus && (
                <span className="muted" style={{ fontSize: 13 }}>
                  {t("qaTraining.showing")}{focus.learner_name} · {focus.page_title}{" "}
                  <button type="button" className="link" onClick={() => setFocus(null)}
                    style={{ background: "none", border: "none", cursor: "pointer", textDecoration: "underline", color: "inherit" }}>
                    {t("qaTraining.clearFilter")}
                  </button>
                </span>
              )}
            </div>
            <div style={{ overflowX: "auto" }}>
              <table>
                <thead><tr>
                  <th>{t("qaTraining.time")}</th>
                  <th>{t("qaTraining.learner")}</th>
                  <th>{t("qaTraining.course")}</th>
                  <th>{t("qaTraining.action")}</th>
                  <th>{t("qaTraining.chapter")}</th>
                </tr></thead>
                <tbody>
                  {events.slice(0, 500).map((e) => (
                    <tr key={e.id}>
                      <td className="muted" style={{ fontSize: 13, whiteSpace: "nowrap" }}>{dateTime(e.created_at)}</td>
                      <td>{e.learner_name}</td>
                      <td>{e.page_title}</td>
                      <td>{t(`qaTraining.ev.${e.event}`)}</td>
                      <td>{e.event === "exam" ? `${e.score ?? "—"}${e.total ? ` / ${e.total}` : ""}`
                        : e.event === "quiz" ? `${e.module_name || e.module_id} · ${e.score ?? "—"}${e.total ? ` / ${e.total}` : ""}`
                        : (e.module_name || e.module_id)}</td>
                    </tr>
                  ))}
                  {events.length === 0 && <tr><td colSpan={5} className="muted">{t("qaTraining.noData")}</td></tr>}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
