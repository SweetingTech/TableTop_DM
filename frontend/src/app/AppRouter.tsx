import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "../components/AppShell";
import { LoadingState } from "../components/ui/States";

const GameConsolePage = lazy(() => import("../features/game-console/GameConsolePage"));
const ControlPlanePage = lazy(() => import("../features/control-plane/ControlPlanePage"));
const PersonaStudioPage = lazy(() => import("../features/persona-studio/PersonaStudioPage"));
const PopulationStudioPage = lazy(() => import("../features/population-studio/PopulationStudioPage"));
const ScenarioLabPage = lazy(() => import("../features/scenario-lab/ScenarioLabPage"));
const RunInspectorPage = lazy(() => import("../features/run-inspector/RunInspectorPage"));
const CalibrationPage = lazy(() => import("../features/calibration/CalibrationPage"));
const SettingsPage = lazy(() => import("../features/settings/SettingsPage"));

export function AppRouter() {
  return (
    <AppShell>
      <Suspense fallback={<LoadingState label="Opening workspace" />}>
        <Routes>
          <Route path="/" element={<Navigate replace to="/game" />} />
          <Route path="/game" element={<GameConsolePage />} />
          <Route path="/control" element={<ControlPlanePage />} />
          <Route path="/personas" element={<PersonaStudioPage />} />
          <Route path="/populations" element={<PopulationStudioPage />} />
          <Route path="/scenarios" element={<ScenarioLabPage />} />
          <Route path="/runs" element={<RunInspectorPage />} />
          <Route path="/calibration" element={<CalibrationPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="*" element={<Navigate replace to="/game" />} />
        </Routes>
      </Suspense>
    </AppShell>
  );
}
