
import { Navigate, Route, Routes } from "react-router-dom";
import { RequireAuth } from "./auth/guards";
import { AppShell } from "./shell/AppShell";
import { ProjectProvider } from "./shell/ProjectContext";
import { LoginPage } from "./pages/LoginPage";
import { WorkbenchPage } from "./pages/WorkbenchPage";
import { TasksPage } from "./pages/TasksPage";
import { TaskDetailPage } from "./pages/TaskDetailPage";
import { QcPage } from "./pages/QcPage";
import { MapPage } from "./pages/MapPage";
import { BriefingsPage } from "./pages/BriefingsPage";
import { BriefingPage } from "./pages/BriefingPage";
import { BaselinesPage, CatalogPage } from "./pages/CatalogPage";
import { AdminPage } from "./pages/AdminPage";
import { ProjectsPage } from "./pages/ProjectsPage";
import { ScenesPage } from "./pages/ScenesPage";
import "./scenes/flood";

function ProtectedShell() {
  return (
    <RequireAuth>
      <ProjectProvider>
        <AppShell />
      </ProjectProvider>
    </RequireAuth>
  );
}

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<ProtectedShell />}>
        <Route path="/" element={<WorkbenchPage />} />
        <Route path="/tasks" element={<TasksPage />} />
        <Route path="/tasks/:id" element={<TaskDetailPage />} />
        <Route path="/qc" element={<QcPage />} />
        <Route path="/map" element={<MapPage />} />
        <Route path="/briefings" element={<BriefingsPage />} />
        <Route path="/briefing/:id" element={<BriefingPage />} />
        <Route path="/catalog" element={<CatalogPage />} />
        <Route path="/catalog/baseline" element={<BaselinesPage />} />
        <Route path="/projects" element={<ProjectsPage />} />
        <Route path="/scenes" element={<ScenesPage />} />
        <Route path="/admin" element={<AdminPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
