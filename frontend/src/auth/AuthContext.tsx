import { createContext, useContext, useState, ReactNode } from "react";
import { login as apiLogin, setToken, getToken } from "../api/client";

interface AuthState {
  authenticated: boolean;
  signIn: (username: string, password: string) => Promise<void>;
  signOut: () => void;
}

const AuthCtx = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [authenticated, setAuthenticated] = useState<boolean>(!!getToken());

  const signIn = async (username: string, password: string) => {
    const token = await apiLogin(username, password);
    setToken(token);
    setAuthenticated(true);
  };

  const signOut = () => {
    setToken(null);
    setAuthenticated(false);
  };

  return <AuthCtx.Provider value={{ authenticated, signIn, signOut }}>{children}</AuthCtx.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthCtx);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
