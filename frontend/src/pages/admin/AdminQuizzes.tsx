import { useState, type FormEvent } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, errorText } from "../../api/client";
import { useI18n } from "../../i18n/LanguageContext";
import { companyLabel } from "../../i18n/labels";

type QForm = {
  text: string; options: string[]; correct_index: number; explanation: string;
};
type Form = {
  title: string; material_id: number | ""; description: string;
  pass_pct: number; is_active: boolean; companies: string[]; questions: QForm[];
};
const COMPANIES = ["heritree", "cpm", "bschool"];
const BLANK_Q: QForm = { text: "", options: ["", ""], correct_index: 0, explanation: "" };
const BLANK: Form = { title: "", material_id: "", description: "", pass_pct: 60, is_active: true,
                      companies: [...COMPANIES], questions: [{ ...BLANK_Q, options: ["", ""] }] };

export default function AdminQuizzes() {
  const { t } = useI18n();
  const qc = useQueryClient();
  const quizzes = useQuery({ queryKey: ["quizzes-admin"], queryFn: () => api.adminQuizzes() });
  const courses = useQuery({ queryKey: ["training"], queryFn: () => api.listTraining() });
  const rows = quizzes.data ?? [];
  const courseRows = courses.data ?? [];

  const [showForm, setShowForm] = useState(false);
  const [editId, setEditId] = useState<number | null>(null);
  const [form, setForm] = useState<Form>({ ...BLANK });
  const [error, setError] = useState<string | null>(null);

  const invalidate = () => qc.invalidateQueries({ queryKey: ["quizzes-admin"] });
  const onErr = (e: unknown) => setError(errorText(e, t) || t("quiz.saveFailed"));

  function openCreate() {
    setEditId(null); setForm({ ...BLANK, questions: [{ ...BLANK_Q, options: ["", ""] }] });
    setError(null); setShowForm(true);
  }
  async function openEdit(id: number) {
    setError(null); setShowForm(true); setEditId(id);
    try {
      const q = await api.adminQuiz(id);
      setForm({
        title: q.title, material_id: q.material_id, description: q.description ?? "",
        pass_pct: q.pass_pct, is_active: q.is_active,
        companies: q.companies && q.companies.length ? q.companies : [...COMPANIES],
        questions: q.questions.map((x) => ({
          text: x.text, options: [...x.options], correct_index: x.correct_index,
          explanation: x.explanation ?? "",
        })),
      });
    } catch (e) { onErr(e); }
  }
  function closeForm() { setShowForm(false); setEditId(null); }

  // --- dynamic question/option editing ---
  const toggleCompany = (c: string) =>
    setForm((f) => ({ ...f, companies: f.companies.includes(c)
      ? f.companies.filter((x) => x !== c) : [...f.companies, c] }));
  const setQ = (qi: number, patch: Partial<QForm>) =>
    setForm((f) => ({ ...f, questions: f.questions.map((q, i) => (i === qi ? { ...q, ...patch } : q)) }));
  const addQuestion = () => setForm((f) => ({ ...f, questions: [...f.questions, { ...BLANK_Q, options: ["", ""] }] }));
  const removeQuestion = (qi: number) =>
    setForm((f) => ({ ...f, questions: f.questions.filter((_, i) => i !== qi) }));
  const setOption = (qi: number, oi: number, val: string) =>
    setQ(qi, { options: form.questions[qi].options.map((o, i) => (i === oi ? val : o)) });
  const addOption = (qi: number) => setQ(qi, { options: [...form.questions[qi].options, ""] });
  const removeOption = (qi: number, oi: number) => {
    const q = form.questions[qi];
    const options = q.options.filter((_, i) => i !== oi);
    const correct_index = q.correct_index === oi ? 0 : q.correct_index > oi ? q.correct_index - 1 : q.correct_index;
    setQ(qi, { options, correct_index });
  };

  const save = useMutation({
    mutationFn: async () => {
      const payload = {
        title: form.title.trim(),
        material_id: form.material_id,
        description: form.description.trim() || null,
        pass_pct: Number(form.pass_pct) || 0,
        is_active: form.is_active,
        // All companies selected → null (visible to everyone, incl. future tenants).
        companies: form.companies.length === COMPANIES.length ? null : form.companies,
        questions: form.questions.map((q) => ({
          text: q.text.trim(),
          options: q.options.map((o) => o.trim()),
          correct_index: q.correct_index,
          explanation: q.explanation.trim() || null,
        })),
      };
      return editId ? api.updateQuiz(editId, payload) : api.createQuiz(payload);
    },
    onSuccess: () => { invalidate(); closeForm(); setError(null); },
    onError: onErr,
  });

  const remove = useMutation({
    mutationFn: (id: number) => api.deleteQuiz(id),
    onSuccess: invalidate, onError: onErr,
  });

  function validate(): string | null {
    if (!form.title.trim()) return t("quiz.errTitle");
    if (!form.material_id) return t("quiz.errCourse");
    if (form.companies.length === 0) return t("quiz.errCompanies");
    if (form.questions.length === 0) return t("quiz.errNoQuestions");
    for (const q of form.questions) {
      if (!q.text.trim()) return t("quiz.errQuestionText");
      const filled = q.options.filter((o) => o.trim());
      if (filled.length < 2) return t("quiz.errOptions");
      if (!q.options[q.correct_index]?.trim()) return t("quiz.errCorrect");
    }
    return null;
  }
  function onSubmit(e: FormEvent) {
    e.preventDefault();
    const v = validate();
    if (v) { setError(v); return; }
    save.mutate();
  }

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        <div>
          <h1 className="page-title">{t("quiz.adminTitle")}</h1>
          <p className="page-sub">{t("quiz.adminSubtitle")}</p>
        </div>
        {!showForm && <button onClick={openCreate}>{t("quiz.new")}</button>}
      </div>

      {showForm && (
        <form className="card" onSubmit={onSubmit}>
          {error && <div className="error">{error}</div>}
          <div className="form-row">
            <label>{t("quiz.fTitle")}
              <input value={form.title} required
                onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))} />
            </label>
            <label>{t("quiz.fCourse")}
              <select value={form.material_id}
                onChange={(e) => setForm((f) => ({ ...f, material_id: e.target.value ? Number(e.target.value) : "" }))}>
                <option value="">—</option>
                {courseRows.map((c) => <option key={c.id} value={c.id}>{c.title}</option>)}
              </select>
            </label>
          </div>
          <div className="form-row">
            <label>{t("quiz.fPassPct")}
              <input type="number" min={0} max={100} value={form.pass_pct}
                onChange={(e) => setForm((f) => ({ ...f, pass_pct: Number(e.target.value) }))} />
            </label>
            <label style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <input type="checkbox" checked={form.is_active}
                onChange={(e) => setForm((f) => ({ ...f, is_active: e.target.checked }))} />
              {t("quiz.fActive")}
            </label>
          </div>
          <div style={{ margin: "4px 0" }}>
            <div className="muted" style={{ fontSize: 12, marginBottom: 2 }}>{t("quiz.fCompanies")}</div>
            <div style={{ display: "flex", gap: 14, flexWrap: "wrap" }}>
              {COMPANIES.map((c) => (
                <label key={c} style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <input type="checkbox" checked={form.companies.includes(c)} onChange={() => toggleCompany(c)} />
                  {companyLabel(c)}
                </label>
              ))}
            </div>
          </div>
          <label>{t("quiz.fDescription")}
            <textarea rows={2} value={form.description}
              onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))} />
          </label>

          <h3 style={{ marginBottom: 4 }}>{t("quiz.questions")}</h3>
          {form.questions.map((q, qi) => (
            <div key={qi} className="card" style={{ background: "var(--surface-2, #f8fafc)" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
                <strong>{t("quiz.question")} {qi + 1}</strong>
                <button type="button" className="ghost" onClick={() => removeQuestion(qi)}
                  disabled={form.questions.length <= 1}>{t("quiz.removeQuestion")}</button>
              </div>
              <label>{t("quiz.questionText")}
                <input value={q.text} onChange={(e) => setQ(qi, { text: e.target.value })} />
              </label>
              <div className="muted" style={{ fontSize: 12, margin: "6px 0 2px" }}>{t("quiz.optionsHint")}</div>
              {q.options.map((opt, oi) => (
                <div key={oi} style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
                  <input type="radio" name={`correct-${qi}`} checked={q.correct_index === oi}
                    onChange={() => setQ(qi, { correct_index: oi })} title={t("quiz.markCorrect")} />
                  <input style={{ flex: 1 }} value={opt} placeholder={`${t("quiz.option")} ${oi + 1}`}
                    onChange={(e) => setOption(qi, oi, e.target.value)} />
                  <button type="button" className="ghost" onClick={() => removeOption(qi, oi)}
                    disabled={q.options.length <= 2}>✕</button>
                </div>
              ))}
              <button type="button" className="ghost" onClick={() => addOption(qi)}>+ {t("quiz.addOption")}</button>
              <label style={{ marginTop: 6 }}>{t("quiz.fExplanation")}
                <textarea rows={2} value={q.explanation}
                  onChange={(e) => setQ(qi, { explanation: e.target.value })} />
              </label>
            </div>
          ))}
          <button type="button" className="ghost" onClick={addQuestion}>+ {t("quiz.addQuestion")}</button>

          <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
            <button type="submit" disabled={save.isPending}>{t("common.save")}</button>
            <button type="button" className="ghost" onClick={closeForm}>{t("common.cancel")}</button>
          </div>
        </form>
      )}

      <div className="card">
        {quizzes.isLoading && <div className="spinner">{t("common.loading")}</div>}
        <table>
          <thead><tr>
            <th>{t("quiz.colTitle")}</th>
            <th>{t("quiz.colCourse")}</th>
            <th className="num">{t("quiz.colQuestions")}</th>
            <th className="num">{t("quiz.colPassPct")}</th>
            <th className="num">{t("quiz.colAttempts")}</th>
            <th>{t("quiz.colActive")}</th>
            <th></th>
          </tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <td>{r.title}</td>
                <td className="muted" style={{ fontSize: 13 }}>{r.material_title}</td>
                <td className="num">{r.question_count}</td>
                <td className="num">{r.pass_pct}%</td>
                <td className="num">{r.attempt_count}</td>
                <td>{r.is_active ? "✓" : <span className="muted">—</span>}</td>
                <td className="num" style={{ whiteSpace: "nowrap" }}>
                  <button className="ghost" onClick={() => openEdit(r.id)}>{t("common.edit")}</button>
                  <button className="ghost" style={{ color: "var(--danger, #dc2626)" }}
                    onClick={() => { if (window.confirm(t("quiz.confirmDelete", { title: r.title }))) remove.mutate(r.id); }}>
                    {t("common.delete")}
                  </button>
                </td>
              </tr>
            ))}
            {!quizzes.isLoading && rows.length === 0 && <tr><td colSpan={7} className="muted">{t("quiz.adminEmpty")}</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  );
}
