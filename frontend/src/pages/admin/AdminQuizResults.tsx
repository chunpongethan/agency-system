import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import { useI18n } from "../../i18n/LanguageContext";
import { dateShort } from "../../lib/format";

const num = (n: number) => n.toLocaleString();

export default function AdminQuizResults() {
  const { t } = useI18n();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["quizResults"], queryFn: () => api.quizResults() });
  const d = q.data;

  const invalidate = () => qc.invalidateQueries({ queryKey: ["quizResults"] });
  const delOne = useMutation({ mutationFn: (id: number) => api.deleteQuizResult(id), onSuccess: invalidate });
  const clearAll = useMutation({ mutationFn: () => api.clearQuizResults(), onSuccess: invalidate });

  const passRate = d && d.total_attempts > 0 ? Math.round((d.pass_count * 100) / d.total_attempts) : 0;

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12, flexWrap: "wrap" }}>
        <div>
          <h1 className="page-title">{t("quizResults.title")}</h1>
          <p className="page-sub">{t("quizResults.subtitle")}</p>
        </div>
        {d && d.rows.length > 0 && (
          <button className="danger" style={{ marginTop: 4 }}
            disabled={clearAll.isPending}
            onClick={() => { if (window.confirm(t("quizResults.confirmClear"))) clearAll.mutate(); }}>
            {t("quizResults.clearAll")}
          </button>
        )}
      </div>

      {q.isLoading && <div className="spinner">{t("common.loading")}</div>}
      {d && (
        <>
          <div className="grid cols-3">
            <div className="stat"><div className="label">{t("quizResults.attempts")}</div><div className="value">{num(d.total_attempts)}</div></div>
            <div className="stat"><div className="label">{t("quizResults.passCount")}</div><div className="value">{num(d.pass_count)}</div></div>
            <div className="stat"><div className="label">{t("quizResults.passRate")}</div><div className="value">{passRate}%</div></div>
          </div>

          <div className="card">
            <table>
              <thead><tr>
                <th>{t("quizResults.agent")}</th>
                <th>{t("quizResults.quiz")}</th>
                <th>{t("quizResults.course")}</th>
                <th className="num">{t("quizResults.score")}</th>
                <th className="num">{t("quizResults.pct")}</th>
                <th>{t("quizResults.result")}</th>
                <th className="num">{t("quizResults.attemptsCol")}</th>
                <th>{t("quizResults.submitted")}</th>
                <th></th>
              </tr></thead>
              <tbody>
                {d.rows.map((r) => (
                  <tr key={r.id}>
                    <td>{r.agent_name} <span className="muted" style={{ fontSize: 12 }}>({r.agent_code})</span></td>
                    <td>{r.quiz_title}</td>
                    <td className="muted" style={{ fontSize: 13 }}>{r.material_title}</td>
                    <td className="num">{r.score}/{r.total}</td>
                    <td className="num">{r.pct}%</td>
                    <td><span className={`badge ${r.passed ? "settled" : "cancelled"}`}>{r.passed ? t("quiz.pass") : t("quiz.fail")}</span></td>
                    <td className="num">{num(r.attempt_count)}</td>
                    <td className="muted" style={{ fontSize: 13 }}>{dateShort(r.submitted_at)}</td>
                    <td className="num">
                      <button type="button" title={t("common.delete")}
                        disabled={delOne.isPending}
                        onClick={() => { if (window.confirm(t("quizResults.confirmDelete"))) delOne.mutate(r.id); }}
                        style={{ background: "none", border: "none", cursor: "pointer", color: "var(--danger, #dc2626)", fontSize: 15 }}>
                        ✕
                      </button>
                    </td>
                  </tr>
                ))}
                {d.rows.length === 0 && <tr><td colSpan={9} className="muted">{t("quizResults.noData")}</td></tr>}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
