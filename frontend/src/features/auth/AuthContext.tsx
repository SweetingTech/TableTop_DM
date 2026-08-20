import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { ApiError } from "../../core/api/client";
import * as authApi from "./api";
import type { CurrentUser } from "./types";

type AuthValue = {
  user: CurrentUser | null;
  loading: boolean;
  error: string;
  signIn: (username: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
  changePassword: (currentPassword: string, newPassword: string) => Promise<void>;
  setUser: (user: CurrentUser) => void;
};

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    authApi.loadSession().then(
      (account) => {
        if (active) setUser(account);
      },
      (reason: unknown) => {
        if (active && !(reason instanceof ApiError && reason.status === 401)) {
          setError(reason instanceof Error ? reason.message : "Unable to verify your account");
        }
      },
    ).finally(() => {
      if (active) setLoading(false);
    });
    return () => {
      active = false;
    };
  }, []);

  const signIn = useCallback(async (username: string, password: string) => {
    setError("");
    try {
      setUser(await authApi.login(username, password));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Sign in failed");
      throw reason;
    }
  }, []);

  const signOut = useCallback(async () => {
    await authApi.logout();
    setUser(null);
  }, []);

  const changePassword = useCallback(async (currentPassword: string, newPassword: string) => {
    setError("");
    try {
      setUser(await authApi.changePassword(currentPassword, newPassword));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Password change failed");
      throw reason;
    }
  }, []);

  const value = useMemo(
    () => ({ user, loading, error, signIn, signOut, changePassword, setUser }),
    [user, loading, error, signIn, signOut, changePassword],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth(): AuthValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside AuthProvider");
  return context;
}
