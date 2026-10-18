import { BrowserRouter, Navigate, Route, Routes, Outlet } from "react-router-dom";
import AppShell from "./components/AppShell";
import { Spinner } from "./components/ui";
import ContentPage from "./pages/ContentPage";
import DashboardPage from "./pages/DashboardPage";
import EvidencePage from "./pages/EvidencePage";
import ExportsPage from "./pages/ExportsPage";
import LoginPage from "./pages/LoginPage";
import PowerPointPage from "./pages/PowerPointPage";
import ProjectPage from "./pages/ProjectPage";
import ProjectsPage from "./pages/ProjectsPage";
import PublishingPage from "./pages/PublishingPage";
import ReviewPage from "./pages/ReviewPage";
import SettingsPage from "./pages/SettingsPage";
import { AuthProvider, useAuth } from "./state/auth";

function RequireAuth() {
  const { user, loading } = useAuth();
  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <Spinner label="Checking session…" />
      </div>
    );
  }
  if (!user) return <Navigate to="/login" replace />;
  return <Outlet />;
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route element={<RequireAuth />}>
            <Route element={<AppShell />}>
              <Route path="/" element={<DashboardPage />} />
              <Route path="/projects" element={<ProjectsPage />} />
              <Route path="/projects/:projectId" element={<ProjectPage />} />
              <Route path="/projects/:projectId/evidence" element={<EvidencePage />} />
              <Route path="/projects/:projectId/content" element={<ContentPage />} />
              <Route path="/projects/:projectId/powerpoint" element={<PowerPointPage />} />
              <Route path="/projects/:projectId/exports" element={<ExportsPage />} />
              <Route path="/review" element={<ReviewPage />} />
              <Route path="/publishing" element={<PublishingPage />} />
              <Route path="/settings" element={<SettingsPage />} />
            </Route>
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
