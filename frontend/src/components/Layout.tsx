import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { useI18n } from "../i18n/LanguageContext";
import { titleLabel } from "../lib/titles";
import { roleLabel } from "../i18n/labels";
import LanguageToggle from "./LanguageToggle";
import CurrencyToggle from "./CurrencyToggle";

export default function Layout() {
  const { me, logout } = useAuth();
  const { t } = useI18n();
  const isAdmin = me?.role === "admin";
  const isManager = me?.role === "manager";
  const isSeller = me?.role === "agent" || isManager; // admins don't sell

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">{t("app.brand")}</div>
        <nav>
          {isSeller && <NavLink to="/" end>{t("nav.dashboard")}</NavLink>}
          {(isSeller || isAdmin) && <NavLink to="/clients">{t("nav.clients")}</NavLink>}
          {(isSeller || isAdmin) && <NavLink to="/leads">{t("nav.leads")}</NavLink>}
          {isAdmin && <NavLink to="/transactions/new">{t("nav.newTransaction")}</NavLink>}
          {(isManager || isAdmin) && <NavLink to="/hierarchy">{t("nav.hierarchy")}</NavLink>}
          <NavLink to="/reports">{t("nav.reports")}</NavLink>
          {isAdmin && (
            <>
              <div className="nav-section">{t("nav.admin")}</div>
              <NavLink to="/admin/agents">{t("nav.agents")}</NavLink>
              <NavLink to="/admin/transactions">{t("nav.transactions")}</NavLink>
              <NavLink to="/admin/products">{t("nav.products")}</NavLink>
              <NavLink to="/admin/rules">{t("nav.rules")}</NavLink>
              <NavLink to="/admin/targets">{t("nav.targets")}</NavLink>
              <NavLink to="/admin/payouts">{t("nav.payouts")}</NavLink>
            </>
          )}
        </nav>
        <div className="spacer" />
        <div className="whoami">
          {me?.name}
          <br />
          <span className="badge role">{roleLabel(me?.role)}</span> · L{me?.level}
          {me?.title && <><br />{titleLabel(me.title)}</>}
          <br />
          <NavLink to="/account" style={{ fontSize: 12 }}>{t("nav.account")}</NavLink>
        </div>
        <CurrencyToggle className="sidebar-lang" />
        <LanguageToggle className="sidebar-lang" />
        <button className="logout" onClick={logout}>{t("nav.logout")}</button>
      </aside>
      <main className="main">
        <Outlet />
      </main>
    </div>
  );
}
