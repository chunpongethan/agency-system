import {
  createContext, useContext, useEffect, useState, type ReactNode,
} from "react";
import { api, setToken, clearToken, getToken } from "../api/client";
import type { Me } from "../api/types";

interface AuthState {
  me: Me | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<Me>;
  logout: () => void;
}

const AuthCtx = createContext<AuthState | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!getToken()) {
      setLoading(false);
      return;
    }
    api
      .me()
      .then(setMe)
      .catch(() => clearToken())
      .finally(() => setLoading(false));
  }, []);

  async function login(username: string, password: string): Promise<Me> {
    const { access_token } = await api.login(username, password);
    setToken(access_token);
    const profile = await api.me();
    setMe(profile);
    return profile;
  }

  function logout() {
    clearToken();
    setMe(null);
    window.location.hash = "#/login";
  }

  return (
    <AuthCtx.Provider value={{ me, loading, login, logout }}>
      {children}
    </AuthCtx.Provider>
  );
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthCtx);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
