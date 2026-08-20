import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { isOperatorAuthorizationError } from "../core/api/client";
import { loadShellBootstrap } from "../core/api/shell";
import type { DataSource, KernelMeta, WorldSummary } from "../core/api/types";
import { useAuth } from "../features/auth/AuthContext";

const ACTIVE_WORLD_KEY = "ttdm.v2.active-world";

type AppContextValue = {
  meta: KernelMeta | null;
  worlds: WorldSummary[];
  activeWorldId: string;
  setActiveWorldId: (worldId: string) => void;
  source: DataSource;
  sourceReason: string;
  loading: boolean;
  error: string;
  authorizationRequired: boolean;
  refresh: () => void;
};

const AppContext = createContext<AppContextValue | null>(null);

export function AppProvider({ children }: { children: ReactNode }) {
  const { signOut } = useAuth();
  const [meta, setMeta] = useState<KernelMeta | null>(null);
  const [worlds, setWorlds] = useState<WorldSummary[]>([]);
  const [activeWorldId, setActiveWorldState] = useState(() => sessionStorage.getItem(ACTIVE_WORLD_KEY) ?? "");
  const [source, setSource] = useState<DataSource>("live");
  const [sourceReason, setSourceReason] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [authorizationRequired, setAuthorizationRequired] = useState(false);
  const [nonce, setNonce] = useState(0);

  const refresh = useCallback(() => {
    setLoading(true);
    setError("");
    setNonce((value) => value + 1);
  }, []);
  const setActiveWorldId = useCallback((worldId: string) => {
    setActiveWorldState(worldId);
    sessionStorage.setItem(ACTIVE_WORLD_KEY, worldId);
  }, []);

  useEffect(() => {
    let active = true;
    loadShellBootstrap().then(
      (result) => {
        if (!active) return;
        setMeta(result.data.meta);
        setWorlds(result.data.worlds);
        setSource(result.source);
        setSourceReason(result.reason ?? "");
        setAuthorizationRequired(false);
        setError("");
        const stored = sessionStorage.getItem(ACTIVE_WORLD_KEY);
        const next = result.data.worlds.some((world) => world.world_id === stored)
          ? stored!
          : result.data.worlds[0]?.world_id ?? "";
        setActiveWorldState(next);
        if (next) sessionStorage.setItem(ACTIVE_WORLD_KEY, next);
        setLoading(false);
      },
      (reason: unknown) => {
        if (!active) return;
        setMeta(null);
        setWorlds([]);
        setActiveWorldState("");
        setSourceReason("");
        const authenticationExpired = isOperatorAuthorizationError(reason);
        setAuthorizationRequired(authenticationExpired);
        setError(reason instanceof Error ? reason.message : "Unable to load the simulation kernel");
        setLoading(false);
        if (authenticationExpired) void signOut();
      },
    );
    return () => {
      active = false;
    };
  }, [nonce, signOut]);

  const value = useMemo<AppContextValue>(
    () => ({ meta, worlds, activeWorldId, setActiveWorldId, source, sourceReason, loading, error, authorizationRequired, refresh }),
    [meta, worlds, activeWorldId, setActiveWorldId, source, sourceReason, loading, error, authorizationRequired, refresh],
  );

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}

// Context hooks intentionally live beside their provider so the public contract stays atomic.
// eslint-disable-next-line react-refresh/only-export-components
export function useAppContext(): AppContextValue {
  const context = useContext(AppContext);
  if (!context) throw new Error("useAppContext must be used inside AppProvider");
  return context;
}
