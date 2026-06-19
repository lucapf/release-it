import { createContext, useContext, useState, useEffect, ReactNode } from "react";
import { notifications } from "@mantine/notifications";
import {
  login as apiLogin,
  setToken,
  getToken,
  currentUser,
  CurrentUser,
  SESSION_EXPIRED_EVENT,
} from "../api/client";

interface AuthState {
  authenticated: boolean;
  user: CurrentUser | null;
  hasRole: (...roles: string[]) => boolean;
  signIn: (username: string, password: string) => Promise<void>;
  signOut: () => void;
}

const AuthCtx = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [authenticated, setAuthenticated] = useState<boolean>(!!getToken());
  const [user, setUser] = useState<CurrentUser | null>(() => currentUser());

  const signIn = async (username: string, password: string) => {
    const token = await apiLogin(username, password);
    setToken(token);
    setUser(currentUser());
    setAuthenticated(true);
  };

  const signOut = () => {
    setToken(null);
    setUser(null);
    setAuthenticated(false);
  };

  // The API layer fires this when a request is rejected with 401 (expired or
  // invalid token). Drop the session and tell the user plainly; <Protected>
  // then redirects to /login.
  useEffect(() => {
    const onExpired = () => {
      setUser(null);
      setAuthenticated(false);
      notifications.show({
        title: "Session expired",
        message: "Please sign in again to continue.",
        color: "yellow",
      });
    };
    window.addEventListener(SESSION_EXPIRED_EVENT, onExpired);
    return () => window.removeEventListener(SESSION_EXPIRED_EVENT, onExpired);
  }, []);

  // True if the user holds at least one of the given roles. Used to gate UI
  // controls; the backend independently enforces the same rules.
  const hasRole = (...roles: string[]) =>
    !!user && roles.some((r) => user.roles.includes(r));

  return (
    <AuthCtx.Provider value={{ authenticated, user, hasRole, signIn, signOut }}>
      {children}
    </AuthCtx.Provider>
  );
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthCtx);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
