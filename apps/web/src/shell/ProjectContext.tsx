
import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, type Area, type Project } from "../api/client";
import { useAuth } from "../auth/AuthContext";

type ProjectState = {
  projects: Project[];
  project: Project | null;
  areas: Area[];
  setProjectId: (id: string) => void;
  reload: () => void;
};

const Ctx = createContext<ProjectState | null>(null);
const KEY = "sarap.project_id";

export function ProjectProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const [projects, setProjects] = useState<Project[]>([]);
  const [areas, setAreas] = useState<Area[]>([]);
  const [projectId, setProjectId] = useState<string>(localStorage.getItem(KEY) ?? "");

  const reload = () => {
    if (!user) return;
    api.projects().then((rows) => {
      setProjects(rows);
      const next = rows.find((p) => p.id === projectId)?.id ?? rows[0]?.id ?? "";
      if (next && next !== projectId) setProjectId(next);
    }).catch(() => setProjects([]));
  };

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user]);

  useEffect(() => {
    if (projectId) localStorage.setItem(KEY, projectId);
    if (!projectId) {
      setAreas([]);
      return;
    }
    api.areas(projectId).then(setAreas).catch(() => setAreas([]));
  }, [projectId]);

  const value = useMemo<ProjectState>(
    () => ({
      projects,
      project: projects.find((p) => p.id === projectId) ?? null,
      areas,
      setProjectId,
      reload,
    }),
    [projects, projectId, areas],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useProject(): ProjectState {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useProject must be used within ProjectProvider");
  return ctx;
}
