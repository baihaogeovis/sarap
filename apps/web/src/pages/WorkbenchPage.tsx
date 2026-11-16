
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type Product, type Task } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { useProject } from "../shell/ProjectContext";

export function WorkbenchPage() {
  const { project, areas } = useProject();
  const { canQc, isReadonly } = useAuth();
  const [tasks, setTasks] = useState<Task[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!project) return;
    setError("");
    Promise.all([api.tasks(project.id), api.products(project.id)])
      .then(([t, p]) => {
        setTasks(t);
        setProducts(p);
      })
      .catch((err) => setError(err.message));
  }, [project]);

  const pendingQc = products.filter((p) => p.status === "pending_qc").length;
  const published = products.filter((p) => p.status === "published").length;
  const running = tasks.filter((t) => t.status === "running" || t.status === "queued").length;
  const area = areas.find((a) => a.is_pilot) ?? areas[0];

  return (
    <>
      <p className="page-lead">
        当前项目：{project?.name ?? "未选择"}。分析坐标系{" "}
        {area?.analysis_crs ?? project?.default_crs ?? "（待配置）"}，AOI 可在管理中调整，未写死流域。
      </p>
      {error && <p className="error">{error}</p>}
      <div className="grid cols-3">
        <div className="card">
          <h3>进行中任务</h3>
          <div className="metric">{running}</div>
          <Link to="/tasks">进入任务中心</Link>
        </div>
        <div className="card">
          <h3>待质检产品</h3>
          <div className="metric accent">{pendingQc}</div>
          {canQc ? <Link to="/qc">去质检 / 发布</Link> : <span className="hint">只读角色不能质检</span>}
        </div>
        <div className="card">
          <h3>已发布产品</h3>
          <div className="metric water">{published}</div>
          <Link to="/map">在一张图中查看</Link>
        </div>
      </div>
      <div className="card" style={{ marginTop: 16 }}>
        <h3>接下来</h3>
        {tasks.slice(0, 5).length === 0 && <p className="empty">暂无任务。{isReadonly ? "当前角色不能创建任务。" : "可在任务中心创建洪水处理任务。"}</p>}
        {tasks.slice(0, 5).length > 0 && (
          <table className="table">
            <thead>
              <tr>
                <th>标题</th>
                <th>场景</th>
                <th>状态</th>
                <th>进度</th>
              </tr>
            </thead>
            <tbody>
              {tasks.slice(0, 5).map((task) => (
                <tr key={task.id}>
                  <td>
                    <Link to={`/tasks/${task.id}`}>{task.title}</Link>
                  </td>
                  <td>{task.scene_code}</td>
                  <td>
                    <span className={`status ${task.status}`}>{task.status}</span>
                  </td>
                  <td>{task.progress}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}
