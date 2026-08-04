import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";

export default function Layout() {
  const { me, logout } = useAuth();
  const isManagerOrAdmin = me?.role === "manager" || me?.role === "admin";
  const isAdmin = me?.role === "admin";

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">Agency System</div>
        <nav>
          <NavLink to="/" end>Dashboard</NavLink>
          <NavLink to="/clients">Clients</NavLink>
          <NavLink to="/transactions/new">New transaction</NavLink>
          {isManagerOrAdmin && <NavLink to="/hierarchy">Hierarchy</NavLink>}
          <NavLink to="/reports">Reports</NavLink>
          {isAdmin && <NavLink to="/admin">Admin</NavLink>}
        </nav>
        <div className="spacer" />
        <div className="whoami">
          {me?.name}
          <br />
          <span className="badge role">{me?.role}</span> · L{me?.level}
        </div>
        <button className="logout" onClick={logout}>Log out</button>
      </aside>
      <main className="main">
        <Outlet />
      </main>
    </div>
  );
}
