import { useQuery } from "@tanstack/react-query";
import { api } from "../../api/client";
import { useI18n } from "../../i18n/LanguageContext";
import { dateShort } from "../../lib/format";

const num = (n: number) => n.toLocaleString();

// Seconds → "1h 02m 03s" / "2m 03s" / "45s".
function hms(total: number): string {
  const s = Math.max(0, Math.round(total));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  if (h) return `${h}h ${String(m).padStart(2, "0")}m ${String(sec).padStart(2, "0")}s`;
  if (m) return `${m}m ${String(sec).padStart(2, "0")}s`;
  return `${sec}s`;
}

export default function AdminTrainingViews() {
  const { t } = useI18n();
  const q = useQuery({ queryKey: ["trainingVideoViews"], queryFn: () => api.trainingVideoViews() });
  const d = q.data;

  return (
    <div>
      <h1 className="page-title">{t("trainingViews.title")}</h1>
      <p className="page-sub">{t("trainingViews.subtitle")}</p>

      {q.isLoading && <div className="spinner">{t("common.loading")}</div>}
      {d && (
        <>
          <div className="grid cols-3">
            <div className="stat"><div className="label">{t("trainingViews.totalTime")}</div><div className="value">{hms(d.total_seconds)}</div></div>
            <div className="stat"><div className="label">{t("trainingViews.totalViews")}</div><div className="value">{num(d.total_views)}</div></div>
            <div className="stat"><div className="label">{t("trainingViews.rows")}</div><div className="value">{num(d.rows.length)}</div></div>
          </div>

          <div className="card">
            <table>
              <thead><tr>
                <th>{t("trainingViews.agent")}</th>
                <th>{t("trainingViews.material")}</th>
                <th>{t("trainingViews.file")}</th>
                <th className="num">{t("trainingViews.views")}</th>
                <th className="num">{t("trainingViews.watched")}</th>
                <th>{t("trainingViews.lastViewed")}</th>
              </tr></thead>
              <tbody>
                {d.rows.map((r) => (
                  <tr key={`${r.agent_id}-${r.material_id}-${r.file_name}`}>
                    <td>{r.agent_name} <span className="muted" style={{ fontSize: 12 }}>({r.agent_code})</span></td>
                    <td>{r.material_title}</td>
                    <td className="muted" style={{ fontSize: 13 }}>{r.file_name}</td>
                    <td className="num">{num(r.view_count)}</td>
                    <td className="num">{hms(r.watched_seconds)}</td>
                    <td className="muted" style={{ fontSize: 13 }}>{dateShort(r.last_viewed_at)}</td>
                  </tr>
                ))}
                {d.rows.length === 0 && <tr><td colSpan={6} className="muted">{t("trainingViews.noData")}</td></tr>}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
