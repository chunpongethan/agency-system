import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useAuth } from "../auth/AuthContext";
import { useI18n } from "../i18n/LanguageContext";
import { titleLabel } from "../lib/titles";
import { roleLabel, companyLabel } from "../i18n/labels";
import { api } from "../api/client";
import { buildMenu, type Role } from "../lib/menu";
import LanguageToggle from "./LanguageToggle";
import CurrencyToggle from "./CurrencyToggle";

export default function Layout() {
  const { me, logout } = useAuth();
  const { t } = useI18n();

  // Global left-menu config (admin-controlled). Resilient: on error/empty we fall
  // back to the registry defaults inside buildMenu.
  const menuSettings = useQuery({
    queryKey: ["menuSettings"], queryFn: () => api.menuSettings(),
    staleTime: 60_000, retry: false,
  });
  const { main, admin } = buildMenu(me?.role as Role | undefined, menuSettings.data);

  // Mobile nav drawer (desktop ignores this — the sidebar is always visible there).
  const [navOpen, setNavOpen] = useState(false);
  const location = useLocation();
  useEffect(() => { setNavOpen(false); }, [location.pathname]);

  return (
    <div className="app">
      <div className="topbar">
        <button className="hamburger" aria-label="menu" onClick={() => setNavOpen((v) => !v)}>☰</button>
        <div className="brand">{t("app.brand")}</div>
      </div>
      {navOpen && <div className="backdrop" onClick={() => setNavOpen(false)} />}
      <aside className={`sidebar ${navOpen ? "open" : ""}`}>
        <div className="brand">{t("app.brand")}</div>
        <nav onClick={() => setNavOpen(false)}>
          {main.map((m) => (
            <NavLink key={m.key} to={m.to} end={m.end}>{t(m.labelKey)}</NavLink>
          ))}
          {admin.length > 0 && (
            <>
              <div className="nav-section">{t("nav.admin")}</div>
              {admin.map((m) => (
                <NavLink key={m.key} to={m.to} end={m.end}>{t(m.labelKey)}</NavLink>
              ))}
            </>
          )}
        </nav>
        <div className="spacer" />
        <div className="whoami">
          {me?.company && <><span className="badge unit">{companyLabel(me.company)}</span><br /></>}
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
