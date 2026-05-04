import { Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "./AppShell";
import { ResearchLivePage } from "../pages/ResearchLivePage";
import { ResearchReplayPage } from "../pages/ResearchReplayPage";
import { PlaceholderPage } from "../pages/PlaceholderPage";

export function App() {
  return (
    <AppShell>
      <Routes>
        <Route path="/" element={<Navigate to="/research/live" replace />} />
        <Route path="/research" element={<Navigate to="/research/live" replace />} />
        <Route path="/research/live" element={<ResearchLivePage />} />
        <Route path="/research/replay" element={<ResearchReplayPage />} />
        <Route
          path="/portfolio"
          element={
            <PlaceholderPage
              title="Portfolio Workspace"
              description="Portfolio / positions / exposures will move here after the research dashboard migration is stable."
            />
          }
        />
        <Route
          path="/reports/:reportId"
          element={
            <PlaceholderPage
              title="Backtest Report"
              description="Backtest report JSON is now part of the backend output bundle. The interactive report page is the next UI slice."
            />
          }
        />
      </Routes>
    </AppShell>
  );
}
