import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { useI18n } from "../i18n/LanguageContext";
import { money } from "../lib/format";
import { productTypeLabel, productDetails } from "../lib/agency";
import StatusBadge from "../components/StatusBadge";
import LockedRate from "../components/LockedRate";

const STATUSES = ["pending", "approved", "cancelled"];

// Read-only transaction review list for sellers: their own (closing) deals, with
// the locked commission rate. Transactions are created/maintained by an admin.
export default function Transactions() {
  const { me } = useAuth();
  const { t } = useI18n();
  const isManager = me!.role === "manager";

  // Scoped to the caller's visible line: own deals for an agent, whole subtree
  // for a manager.
  const txns = useQuery({ queryKey: ["reviewTxns"], queryFn: () => api.reviewTransactions() });
  const products = useQuery({ queryKey: ["products"], queryFn: () => api.products() });
  const productsById = useMemo(() => new Map((products.data ?? []).map((p) => [p.id, p])), [products.data]);

  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return (txns.data ?? []).filter((tx) => {
      if (status && tx.status !== status) return false;
      if (!needle) return true;
      return [tx.ref, tx.policy_no, tx.product_name, tx.client_name, tx.client_ref,
              tx.agent_name, tx.agent_code]
        .some((v) => (v ?? "").toString().toLowerCase().includes(needle));
    });
  }, [txns.data, q, status]);
  const colCount = isManager ? 8 : 7;

  return (
    <div>
      <h1 className="page-title">{t("myTxns.title")}</h1>
      <p className="page-sub">{t("myTxns.subtitle")}</p>
      <div className="card">
        {txns.isLoading && <div className="spinner">{t("common.loading")}</div>}
        <div className="product-filters">
          <input className="filter-search" type="search" value={q} placeholder={t("myTxns.searchPlaceholder")}
            onChange={(e) => setQ(e.target.value)} />
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">{t("adminTxn.all")}</option>
            {STATUSES.map((s) => <option key={s} value={s}>{t(`enum.status.${s}`)}</option>)}
          </select>
          <span className="muted filter-count">{t("myTxns.count", { n: rows.length, total: txns.data?.length ?? 0 })}</span>
        </div>
        <div className="table-scroll">
        <table className="cards-on-mobile">
          <thead>
            <tr>
              <th>{t("common.ref")}</th><th>{t("common.date")}</th>
              {isManager && <th>{t("common.agent")}</th>}
              <th>{t("common.client")}</th>
              <th>{t("common.product")}</th><th className="num">{t("common.notional")}</th>
              <th className="num">{t("txn.lockedRate")}</th><th>{t("common.status")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && !txns.isLoading && (
              <tr><td colSpan={colCount} className="muted" style={{ textAlign: "center", padding: "18px 0" }}>{t("myTxns.empty")}</td></tr>
            )}
            {rows.map((tx) => {
              const p = productsById.get(tx.product_id);
              return (
                <tr key={tx.id}>
                  <td data-label={t("common.ref")}>{tx.ref}</td>
                  <td className="muted" data-label={t("common.date")}>{tx.trade_date}</td>
                  {isManager && (
                    <td data-label={t("common.agent")}>
                      {tx.agent_name}
                      <span className="muted" style={{ fontSize: 11, marginLeft: 4 }}>{tx.agent_code}</span>
                    </td>
                  )}
                  <td data-label={t("common.client")}>{tx.client_name ?? `#${tx.client_id}`}</td>
                  <td data-label={t("common.product")}>
                    <div>{tx.product_name ?? (p ? p.name : `#${tx.product_id}`)}</div>
                    <div className="muted" style={{ fontSize: 11 }}>
                      {tx.product_type && <span className="badge role" style={{ marginRight: 6 }}>{productTypeLabel(tx.product_type)}</span>}
                      {productDetails(p)}
                    </div>
                  </td>
                  <td className="num" data-label={t("common.notional")}>{money(tx.notional, tx.currency)}</td>
                  <td className="num" data-label={t("txn.lockedRate")}>
                    <LockedRate base={tx.locked_base_rate} years={tx.locked_year_commissions} />
                  </td>
                  <td data-label={t("common.status")}><StatusBadge status={tx.status} /></td>
                </tr>
              );
            })}
          </tbody>
        </table>
        </div>
      </div>
    </div>
  );
}
