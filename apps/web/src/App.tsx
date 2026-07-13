import { Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { PlaceholderPage } from "./pages/PlaceholderPage";
import { StoryPlanningPage } from "./pages/StoryPlanningPage";
import { StoryWorkspaceProvider } from "./context/StoryWorkspaceContext";
import { ProjectOverviewPage } from "./pages/ProjectOverviewPage";
import { ChapterWritingPage } from "./pages/ChapterWritingPage";
import { QualityCenterPage } from "./pages/QualityCenterPage";
import { SettingsHubPage } from "./pages/SettingsHubPage";
import { CanonPage } from "./pages/CanonPage";
import { AutomationPage } from "./pages/AutomationPage";

export function App() {
  return (
    <StoryWorkspaceProvider><Routes>
      <Route element={<AppShell />}>
        <Route index element={<Navigate to="/planning" replace />} />
        <Route path="overview" element={<ProjectOverviewPage />} />
        <Route path="canon" element={<CanonPage />} />
        <Route path="planning" element={<StoryPlanningPage />} />
        <Route path="writing" element={<ChapterWritingPage />} />
        <Route path="quality" element={<QualityCenterPage />} />
        <Route path="state" element={<PlaceholderPage page="state" />} />
        <Route path="automation" element={<AutomationPage />} />
        <Route path="settings" element={<SettingsHubPage />} />
        <Route path="drama" element={<PlaceholderPage page="drama" />} />
      </Route>
      <Route path="*" element={<Navigate to="/planning" replace />} />
    </Routes></StoryWorkspaceProvider>
  );
}
