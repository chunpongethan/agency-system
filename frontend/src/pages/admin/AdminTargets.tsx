import { useEffect, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, errorText } from "../../api/client";
import { useI18n } from "../../i18n/LanguageContext";
import { titleLabel, TITLE_VALUES } from "../../lib/titles";

export default function AdminTargets() {
  const { t } = useI18n();
  const qc = useQueryClient();
  const targets = useQuery({ queryKey: ["titleTargets"], queryFn: () => api.titleTargets() });

  const [edits, setEdits] = useState<Record<string, string>>({});
  const [savedTitle, setSavedTitle] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Seed local inputs from the fetched targets.
  useEffect(() => {
    if (targets.data) {
      const m: Record<string, string> = {};
      targets.data.forEach((tt) => { m[tt.title] = String(tt.target_afyp ?? 0); });
      setEdits(m);
    }
  }, [targets.data]);

  const save = useMutation({
    mutationFn: (title: string) => api.setTitleTarget(title, Number(edits[title] || 0)),
    onSuccess: (_r, title) => {
      qc.invalidateQueries({ queryKey: ["titleTargets"] });
      setSavedTitle(title); setError(null);
      setTimeout(() => setSavedTitle((s) => (s === title ? null : s)), 2000);
    },
    onError: (e) => setError(errorText(e, t) || t("admin.targets.failed")),
  });

  return (
    <div>
      <h1 className="page-title">{t("admin.targets.title")}</h1>
      <p className="page-sub">{t("admin.targets.subtitle")}</p>

      <div className="card">
        {error && <div className="error">{error}</div>}
        <table>
          <thead>
            <tr>
              <th>{t("admin.targets.thRank")}</th>
              <th>{t("admin.targets.thTarget")}</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {TITLE_VALUES.map((title) => (
              <tr key={title}>
                <td>{titleLabel(title)}</td>
                <td>
                  <input type="number" min="0" step="100000" style={{ maxWidth: 220 }}
                    value={edits[title] ?? ""}
                    onChange={(e) => setEdits({ ...edits, [title]: e.target.value })} />
                </td>
                <td className="num" style={{ whiteSpace: "nowrap" }}>
                  <button className="primary" disabled={save.isPending} onClick={() => save.mutate(title)}>
                    {t("admin.targets.save")}
                  </button>
                  {savedTitle === title && (
                    <span className="muted" style={{ marginLeft: 8 }}>{t("admin.targets.saved")}</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
