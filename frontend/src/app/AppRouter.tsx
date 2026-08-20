import { lazy, Suspense, type ReactNode } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "../components/AppShell";
import { LoadingState } from "../components/ui/States";
import { useAuth } from "../features/auth/AuthContext";

const GameConsolePage = lazy(() => import("../features/game-console/GameConsolePage"));
const ControlPlanePage = lazy(() => import("../features/control-plane/ControlPlanePage"));
const PersonaStudioPage = lazy(() => import("../features/persona-studio/PersonaStudioPage"));
const PopulationStudioPage = lazy(() => import("../features/population-studio/PopulationStudioPage"));
const ScenarioLabPage = lazy(() => import("../features/scenario-lab/ScenarioLabPage"));
const RunInspectorPage = lazy(() => import("../features/run-inspector/RunInspectorPage"));
const CalibrationPage = lazy(() => import("../features/calibration/CalibrationPage"));
const SettingsPage = lazy(() => import("../features/settings/SettingsPage"));
const AdminDashboardPage = lazy(() => import("../features/admin/AdminDashboardPage"));
const DungeonMasterPage = lazy(() => import("../features/dm/DungeonMasterPage"));
const PlayerDashboardPage = lazy(() => import("../features/player/PlayerDashboardPage"));

function RoleRoute({ access, children }: { access: "admin" | "dm" | "player"; children: ReactNode }) {
  const { user } = useAuth();
  const allowed = access === "admin" ? user?.is_admin : access === "dm" ? user?.is_admin || user?.has_dm_role : user?.is_admin || user?.has_player_role;
  return allowed ? children : <Navigate replace to="/settings" />;
}

export function AppRouter() {
  return (
    <AppShell>
      <Suspense fallback={<LoadingState label="Opening workspace" />}>
        <Routes>
          <Route path="/" element={<Navigate replace to="/game" />} />
          <Route path="/game" element={<GameConsolePage />} />
          <Route path="/player" element={<RoleRoute access="player"><PlayerDashboardPage /></RoleRoute>} />
          <Route path="/dm" element={<RoleRoute access="dm"><DungeonMasterPage /></RoleRoute>} />
          <Route path="/admin" element={<RoleRoute access="admin"><AdminDashboardPage /></RoleRoute>} />
          <Route path="/control" element={<RoleRoute access="admin"><ControlPlanePage /></RoleRoute>} />
          <Route path="/personas" element={<RoleRoute access="admin"><PersonaStudioPage /></RoleRoute>} />
          <Route path="/populations" element={<RoleRoute access="admin"><PopulationStudioPage /></RoleRoute>} />
          <Route path="/scenarios" element={<RoleRoute access="admin"><ScenarioLabPage /></RoleRoute>} />
          <Route path="/runs" element={<RoleRoute access="admin"><RunInspectorPage /></RoleRoute>} />
          <Route path="/calibration" element={<RoleRoute access="admin"><CalibrationPage /></RoleRoute>} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="*" element={<Navigate replace to="/game" />} />
        </Routes>
      </Suspense>
    </AppShell>
  );
}
