import { useState, useEffect } from "react";
import { useSearchParams } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, errorText } from "../api/client";
import { useI18n } from "../i18n/LanguageContext";
import { chineseVariant } from "../lib/zh";
import type { QuizListItem, QuizResult } from "../api/types";

// 課程考核 — agent/student takes an MC quiz tied to a 商學院課程, submits, and sees
// the score, 合格/不合格, and the correct answer + explanation for each question.
export default function Quiz() {
  const { t } = useI18n();
  const list = useQuery({ queryKey: ["quizzes"], queryFn: () => api.quizzes() });
  const [params, setParams] = useSearchParams();
  // ?take=<id> (e.g. from a course's detail popup) auto-opens that quiz.
  const [openId, setOpenId] = useState<number | null>(() => {
    const t = params.get("take"); return t ? Number(t) : null;
  });
  const closeModal = () => {
    setOpenId(null);
    if (params.get("take")) { params.delete("take"); setParams(params, { replace: true }); }
  };
  const rows = list.data ?? [];

  const renderCard = (q: QuizListItem) => {
    const taken = q.my_attempt_count > 0;
    return (
      <div key={q.id} className="tm-card" role="button" tabIndex={0}
        onClick={() => setOpenId(q.id)}
        onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setOpenId(q.id); } }}>
        <div className="tm-body">
          <div className="tm-title-row">
            <strong lang={chineseVariant(q.title)}>{q.title}</strong>
            {taken && (
              <span className={`badge ${q.my_passed ? "settled" : "cancelled"}`} style={{ fontSize: 11 }}>
                {q.my_passed ? t("quiz.pass") : t("quiz.fail")} {q.my_pct}%
              </span>
            )}
          </div>
          {q.material_title && (
            <p className="tm-summary muted" lang={chineseVariant(q.material_title)}>
              {t("quiz.linkedCourse")}: {q.material_title}
            </p>
          )}
          <div className="tm-meta">
            <span className="badge unit" style={{ fontSize: 11 }}>{t("quiz.questionCount", { n: q.question_count })}</span>
            <span className="badge dc" style={{ fontSize: 11 }}>{t("quiz.passMark", { pct: q.pass_pct })}</span>
            <span className="tm-open">{taken ? t("quiz.retake") : t("quiz.take")} →</span>
          </div>
        </div>
      </div>
    );
  };

  return (
    <div>
      <h1 className="page-title">{t("quiz.title")}</h1>
      <p className="page-sub">{t("quiz.subtitle")}</p>

      <div className="card">
        {list.isLoading && <div className="spinner">{t("common.loading")}</div>}
        {!list.isLoading && rows.length === 0 && <p className="muted">{t("quiz.empty")}</p>}
        <div className="training-grid">{rows.map(renderCard)}</div>
      </div>

      {openId != null && <QuizModal quizId={openId} onClose={closeModal} />}
    </div>
  );
}

function QuizModal({ quizId, onClose }: { quizId: number; onClose: () => void }) {
  const { t } = useI18n();
  const qc = useQueryClient();
  const take = useQuery({ queryKey: ["quiz", quizId], queryFn: () => api.quiz(quizId) });
  const quiz = take.data;
  const [answers, setAnswers] = useState<number[]>([]);
  const [result, setResult] = useState<QuizResult | null>(null);
  const [error, setError] = useState("");

  useEffect(() => { if (quiz) setAnswers(quiz.questions.map(() => -1)); }, [quiz]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const submit = useMutation({
    mutationFn: () => api.submitQuiz(quizId, { answers }),
    onSuccess: (res) => { setResult(res); qc.invalidateQueries({ queryKey: ["quizzes"] }); },
    onError: (e) => setError(errorText(e, t) || t("quiz.submitFailed")),
  });

  const pick = (qi: number, oi: number) =>
    setAnswers((a) => a.map((v, i) => (i === qi ? oi : v)));
  const allAnswered = quiz != null && answers.length === quiz.questions.length && answers.every((a) => a >= 0);

  const retake = () => { setResult(null); setError(""); if (quiz) setAnswers(quiz.questions.map(() => -1)); };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-panel" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <div style={{ minWidth: 0 }}>
            <strong style={{ fontSize: 15 }} lang={chineseVariant(quiz?.title ?? "")}>{quiz?.title}</strong>
            {quiz?.material_title && (
              <div className="muted" style={{ fontSize: 12 }}>{t("quiz.linkedCourse")}: {quiz.material_title}</div>
            )}
          </div>
          <button className="ghost" style={{ padding: "3px 10px" }} onClick={onClose}>✕</button>
        </div>
        <div className="modal-body detail">
          {take.isLoading && <div className="preview-loading"><span className="spin" aria-hidden />{t("common.loading")}</div>}
          {error && <div className="error">{error}</div>}

          {/* Result view (after submit) */}
          {quiz && result && (
            <div>
              <div className="card" style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
                <span style={{ fontSize: 28, fontWeight: 700 }}>{result.pct}%</span>
                <span className="muted">{t("quiz.scoreOf", { score: result.score, total: result.total })}</span>
                <span className={`badge ${result.passed ? "settled" : "cancelled"}`}>
                  {result.passed ? t("quiz.pass") : t("quiz.fail")}
                </span>
                <span className="muted" style={{ fontSize: 12 }}>{t("quiz.passMark", { pct: result.pass_pct })}</span>
              </div>
              {result.questions.map((q, qi) => (
                <div key={qi} className="card" style={{ marginTop: 10 }}>
                  <div style={{ fontWeight: 600, marginBottom: 6 }}>
                    <span className={`badge ${q.is_correct ? "settled" : "cancelled"}`} style={{ marginRight: 6 }}>
                      {q.is_correct ? t("quiz.correct") : t("quiz.incorrect")}
                    </span>
                    {qi + 1}. <span lang={chineseVariant(q.text)}>{q.text}</span>
                  </div>
                  <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
                    {q.options.map((opt, oi) => {
                      const isCorrect = oi === q.correct_index;
                      const isYours = oi === q.your_index;
                      return (
                        <li key={oi} style={{ padding: "3px 0", color: isCorrect ? "var(--ok, #16a34a)" : isYours ? "var(--danger, #dc2626)" : undefined }}>
                          {isCorrect ? "✓ " : isYours ? "✗ " : "　"}
                          <span lang={chineseVariant(opt)}>{opt}</span>
                          {isYours && <span className="muted" style={{ fontSize: 12 }}> ({t("quiz.yourAnswer")})</span>}
                        </li>
                      );
                    })}
                  </ul>
                  {q.explanation && (
                    <p className="muted" style={{ fontSize: 13, marginBottom: 0 }} lang={chineseVariant(q.explanation)}>
                      {t("quiz.explanation")}: {q.explanation}
                    </p>
                  )}
                </div>
              ))}
              <div style={{ marginTop: 12, display: "flex", gap: 8 }}>
                <button onClick={retake}>{t("quiz.retake")}</button>
                <button className="ghost" onClick={onClose}>{t("common.close")}</button>
              </div>
            </div>
          )}

          {/* Question form (before submit) */}
          {quiz && !result && (
            <div>
              {quiz.description && (
                <p className="muted" style={{ fontSize: 14 }} lang={chineseVariant(quiz.description)}>{quiz.description}</p>
              )}
              {quiz.questions.map((q, qi) => (
                <div key={qi} className="card" style={{ marginTop: 10 }}>
                  <div style={{ fontWeight: 600, marginBottom: 6 }}>
                    {qi + 1}. <span lang={chineseVariant(q.text)}>{q.text}</span>
                  </div>
                  {q.options.map((opt, oi) => (
                    <label key={oi} style={{ display: "block", padding: "4px 0", cursor: "pointer" }}>
                      <input type="radio" name={`q${qi}`} checked={answers[qi] === oi}
                        onChange={() => pick(qi, oi)} style={{ marginRight: 8 }} />
                      <span lang={chineseVariant(opt)}>{opt}</span>
                    </label>
                  ))}
                </div>
              ))}
              <div style={{ marginTop: 12, display: "flex", gap: 8, alignItems: "center" }}>
                <button disabled={!allAnswered || submit.isPending} onClick={() => submit.mutate()}>
                  {t("quiz.submit")}
                </button>
                {!allAnswered && <span className="muted" style={{ fontSize: 12 }}>{t("quiz.answerAll")}</span>}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
