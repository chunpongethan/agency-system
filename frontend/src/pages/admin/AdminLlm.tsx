import { useQuery } from "@tanstack/react-query";
import { api } from "../../api/client";
import { useI18n } from "../../i18n/LanguageContext";

const usd = (n: number) => `$${n.toFixed(n < 1 ? 4 : 2)}`;
const num = (n: number) => n.toLocaleString();

export default function AdminLlm() {
  const { t } = useI18n();
  const usage = useQuery({ queryKey: ["kbUsage"], queryFn: () => api.kbUsage() });
  const d = usage.data;

  return (
    <div>
      <h1 className="page-title">{t("llm.title")}</h1>
      <p className="page-sub">{t("llm.subtitle")}</p>

      {usage.isLoading && <div className="spinner">{t("common.loading")}</div>}
      {d && (
        <>
          <div className="card" style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            <span className="muted">{t("llm.currentModel")}:</span>
            <span className="badge unit">{d.model}</span>
            {d.ai_enabled
              ? <span className="badge settled">{t("llm.enabled")}</span>
              : <span className="badge cancelled">{t("llm.notConfigured")}</span>}
          </div>

          <div className="grid cols-3">
            <div className="stat"><div className="label">{t("llm.totalCost")}</div><div className="value">{usd(d.total.cost_usd)}</div></div>
            <div className="stat"><div className="label">{t("llm.requests")}</div><div className="value">{num(d.total.requests)}</div></div>
            <div className="stat"><div className="label">{t("llm.tokens")}</div><div className="value" style={{ fontSize: 20 }}>
              {num(d.total.input_tokens + d.total.output_tokens)}
              <span className="muted" style={{ fontSize: 12, fontWeight: 400 }}> ({num(d.total.input_tokens)} / {num(d.total.output_tokens)})</span>
            </div></div>
          </div>

          <div className="card">
            <h2 style={{ marginTop: 0 }}>{t("llm.byMonth")}</h2>
            <table>
              <thead><tr><th>{t("llm.month")}</th><th className="num">{t("llm.requests")}</th><th className="num">{t("llm.inTokens")}</th><th className="num">{t("llm.outTokens")}</th><th className="num">{t("llm.cost")}</th></tr></thead>
              <tbody>
                {d.by_month.map((m) => (
                  <tr key={m.month}><td>{m.month}</td><td className="num">{num(m.requests)}</td><td className="num">{num(m.input_tokens)}</td><td className="num">{num(m.output_tokens)}</td><td className="num">{usd(m.cost_usd)}</td></tr>
                ))}
                {d.by_month.length === 0 && <tr><td colSpan={5} className="muted">{t("llm.noData")}</td></tr>}
              </tbody>
            </table>
          </div>

          <div className="grid cols-2" style={{ alignItems: "start" }}>
            <div className="card">
              <h2 style={{ marginTop: 0 }}>{t("llm.byModel")}</h2>
              <table>
                <thead><tr><th>{t("llm.model")}</th><th className="num">{t("llm.requests")}</th><th className="num">{t("llm.cost")}</th></tr></thead>
                <tbody>
                  {d.by_model.map((m) => (
                    <tr key={m.model}><td>{m.model}</td><td className="num">{num(m.requests)}</td><td className="num">{usd(m.cost_usd)}</td></tr>
                  ))}
                  {d.by_model.length === 0 && <tr><td colSpan={3} className="muted">{t("llm.noData")}</td></tr>}
                </tbody>
              </table>
            </div>
            <div className="card">
              <h2 style={{ marginTop: 0 }}>{t("llm.topAgents")}</h2>
              <table>
                <thead><tr><th>{t("common.name")}</th><th className="num">{t("llm.requests")}</th><th className="num">{t("llm.cost")}</th></tr></thead>
                <tbody>
                  {d.by_agent.map((a) => (
                    <tr key={a.agent_id ?? 0}><td>{a.name} <span className="muted" style={{ fontSize: 12 }}>({a.code})</span></td><td className="num">{num(a.requests)}</td><td className="num">{usd(a.cost_usd)}</td></tr>
                  ))}
                  {d.by_agent.length === 0 && <tr><td colSpan={3} className="muted">{t("llm.noData")}</td></tr>}
                </tbody>
              </table>
            </div>
          </div>

          <div className="card">
            <h2 style={{ marginTop: 0 }}>{t("llm.priceTable")}</h2>
            <p className="muted" style={{ fontSize: 13, marginTop: 0 }}>{t("llm.priceNote")}</p>
            <table>
              <thead><tr><th>{t("llm.tier")}</th><th className="num">{t("llm.priceIn")}</th><th className="num">{t("llm.priceOut")}</th></tr></thead>
              <tbody>
                {Object.entries(d.prices).map(([tier, p]) => (
                  <tr key={tier}><td>{tier}</td><td className="num">${p.in.toFixed(2)}</td><td className="num">${p.out.toFixed(2)}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
