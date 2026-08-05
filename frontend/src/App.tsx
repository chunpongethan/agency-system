import { Routes, Route, Navigate } from "react-router-dom";
import { useAuth } from "./auth/AuthContext";
import Layout from "./components/Layout";
import Login from "./pages/Login";
import Dashboard from "./pages/Dashboard";
import Clients from "./pages/Clients";
import ClientDetail from "./pages/ClientDetail";
import NewTransaction from "./pages/NewTransaction";
import Hierarchy from "./pages/Hierarchy";
import Reports from "./pages/Reports";
import AdminAgents from "./pages/admin/AdminAgents";
import AdminProducts from "./pages/admin/AdminProducts";
import AdminRules from "./pages/admin/AdminRules";
import AdminPayouts from "./pages/admin/AdminPayouts";
import type { ReactElement } from "react";

// Where each role lands by default. Admins are not sellers, so their home is the
// first admin section, not the seller dashboard.
function homeFor(role: string | undefined): string {
  return role === "admin" ? "/admin/agents" : "/";
}

function RequireAuth({ children }: { children: ReactElement }) {
  const { me, loading } = useAuth();
  if (loading) return <div className="spinner" style={{ padding: 40 }}>Loading…</div>;
  if (!me) return <Navigate to="/login" replace />;
  return children;
}

function RequireRole({ roles, children }: { roles: string[]; children: ReactElement }) {
  const { me } = useAuth();
  if (me && !roles.includes(me.role)) return <Navigate to={homeFor(me.role)} replace />;
  return children;
}

const SELLERS = ["agent", "manager"];

export default function App() {
  const { me } = useAuth();
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        element={
          <RequireAuth>
            <Layout />
          </RequireAuth>
        }
      >
        <Route
          path="/"
          element={
            <RequireRole roles={SELLERS}>
              <Dashboard />
            </RequireRole>
          }
        />
        <Route
          path="/clients"
          element={
            <RequireRole roles={SELLERS}>
              <Clients />
            </RequireRole>
          }
        />
        <Route
          path="/clients/:id"
          element={
            <RequireRole roles={SELLERS}>
              <ClientDetail />
            </RequireRole>
          }
        />
        <Route
          path="/transactions/new"
          element={
            <RequireRole roles={SELLERS}>
              <NewTransaction />
            </RequireRole>
          }
        />
        <Route
          path="/hierarchy"
          element={
            <RequireRole roles={["manager", "admin"]}>
              <Hierarchy />
            </RequireRole>
          }
        />
        <Route path="/reports" element={<Reports />} />
        <Route
          path="/admin/agents"
          element={<RequireRole roles={["admin"]}><AdminAgents /></RequireRole>}
        />
        <Route
          path="/admin/products"
          element={<RequireRole roles={["admin"]}><AdminProducts /></RequireRole>}
        />
        <Route
          path="/admin/rules"
          element={<RequireRole roles={["admin"]}><AdminRules /></RequireRole>}
        />
        <Route
          path="/admin/payouts"
          element={<RequireRole roles={["admin"]}><AdminPayouts /></RequireRole>}
        />
        <Route path="/admin" element={<Navigate to="/admin/agents" replace />} />
      </Route>
      <Route path="*" element={<Navigate to={homeFor(me?.role)} replace />} />
    </Routes>
  );
}
