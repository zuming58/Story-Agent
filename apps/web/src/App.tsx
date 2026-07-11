import { Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { PlaceholderPage } from "./pages/PlaceholderPage";
import { StoryPlanningPage } from "./pages/StoryPlanningPage";

export function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<Navigate to="/planning" replace />} />
        <Route path="overview" element={<PlaceholderPage page="overview" />} />
        <Route path="canon" element={<PlaceholderPage page="canon" />} />
        <Route path="planning" element={<StoryPlanningPage />} />
        <Route path="writing" element={<PlaceholderPage page="writing" />} />
        <Route path="quality" element={<PlaceholderPage page="quality" />} />
        <Route path="state" element={<PlaceholderPage page="state" />} />
        <Route path="automation" element={<PlaceholderPage page="automation" />} />
        <Route path="drama" element={<PlaceholderPage page="drama" />} />
      </Route>
      <Route path="*" element={<Navigate to="/planning" replace />} />
    </Routes>
  );
}
