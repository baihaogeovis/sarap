
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { useProject } from "./ProjectContext";

const NAV = [
  { to: "/", label: "工作台", end: true },
  { to: "/tasks", label: "任务" },
  { to: "/map", label: "一张图" },
  { to: "/briefings", label: "简报" },
  { to: "/catalog", label: "资源" },
  { to: "/admin", label: "管理", manageOnly: true },
];

const ROLE_LABEL: Record<string, string> = {
  admin: "管理员",
  duty_officer: "值班员",
  readonly: "只读",
};

export function AppShell() {
  const { user, logout, canManage } = useAuth();
  const { projects, project, setProjectId } = useProject();
  const navigate = useNavigate();
  const role = user?.roles[0] ?? "";

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <h1>SARAP</h1>
          <p>SAR 应用平台</p>
        </div>
        <nav className="nav-list">
          {NAV.filter((item) => !item.manageOnly || canManage).map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) => `nav-item${isActive ? " active" : ""}`}
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-user">
          <div>{user?.name}</div>
          <div>{user?.email}</div>
          <span className="role-badge">{ROLE_LABEL[role] ?? role}</span>
        </div>
      </aside>
      <div className="main">
        <header className="topbar">
          <h2>工作台</h2>
          <label className="project-switch">
            <select
              value={project?.id ?? ""}
              onChange={(e) => setProjectId(e.target.value)}
              aria-label="当前项目"
            >
              {projects.length === 0 && <option value="">暂无项目</option>}
              {projects.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
          </label>
          <button
            className="btn ghost"
            onClick={() => {
              logout();
              navigate("/login");
            }}
          >
            退出
          </button>
        </header>
        <div className="content">
          <Outlet />
        </div>
      </div>
    </div>
  );
}
