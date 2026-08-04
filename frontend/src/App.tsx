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
import Admin from "./pages/Admin";
import type { ReactElement } from "react";

function RequireAuth({ children }: { children: ReactElement }) {
  const { me, loading } = useAuth();
  if (loading) return <div className="spinner" style={{ padding: 40 }}>Loading…</div>;
  if (!me) return <Navigate to="/login" replace />;
  return children;
}

function RequireRole({ roles, children }: { roles: string[]; children: ReactElement }) {
  const { me } = useAuth();
  if (me && !roles.includes(me.role)) return <Navigate to="/" replace />;
  return children;
}

export default function App() {
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
        <Route path="/" element={<Dashboard />} />
        <Route path="/clients" element={<Clients />} />
        <Route path="/clients/:id" element={<ClientDetail />} />
        <Route path="/transactions/new" element={<NewTransaction />} />
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
          path="/admin"
          element={
            <RequireRole roles={["admin"]}>
              <Admin />
            </RequireRole>
          }
        />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
