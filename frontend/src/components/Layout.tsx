import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { titleLabel } from "../lib/titles";

export default function Layout() {
  const { me, logout } = useAuth();
  const isAdmin = me?.role === "admin";
  const isManager = me?.role === "manager";
  const isSeller = me?.role === "agent" || isManager; // admins don't sell

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">Agency System</div>
        <nav>
          {isSeller && <NavLink to="/" end>Dashboard</NavLink>}
          {(isSeller || isAdmin) && <NavLink to="/clients">Clients</NavLink>}
          {isAdmin && <NavLink to="/transactions/new">New transaction</NavLink>}
          {(isManager || isAdmin) && <NavLink to="/hierarchy">Hierarchy</NavLink>}
          <NavLink to="/reports">Reports</NavLink>
          {isAdmin && (
            <>
              <div className="nav-section">Admin</div>
              <NavLink to="/admin/agents">Agents</NavLink>
              <NavLink to="/admin/products">Products</NavLink>
              <NavLink to="/admin/rules">Override rules</NavLink>
              <NavLink to="/admin/payouts">Periods &amp; payouts</NavLink>
            </>
          )}
        </nav>
        <div className="spacer" />
        <div className="whoami">
          {me?.name}
          <br />
          <span className="badge role">{me?.role}</span> · L{me?.level}
          {me?.title && <><br />{titleLabel(me.title)}</>}
        </div>
        <button className="logout" onClick={logout}>Log out</button>
      </aside>
      <main className="main">
        <Outlet />
      </main>
    </div>
  );
}
