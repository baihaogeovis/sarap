
import { FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, api, type Task } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { useProject } from "../shell/ProjectContext";

export function TasksPage() {
  const { project } = useProject();
  const { has, isReadonly } = useAuth();
  const [tasks, setTasks] = useState<Task[]>([]);
  const [title, setTitle] = useState("洪水应急处理");
  const [taskType, setTaskType] = useState("flood_pipeline");
  const [emergency, setEmergency] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  function reload() {
    if (!project) return;
    api.tasks(project.id).then(setTasks).catch((err) => setError(err.message));
  }

  useEffect(reload, [project]);

  async function onCreate(event: FormEvent) {
    event.preventDefault();
    if (!project) return;
    if (!has("task.create")) {
      setError("当前角色无权执行该操作");
      return;
    }
    setError("");
    setNotice("");
    try {
      const created = await api.createTask({
        project_id: project.id,
        scene_code: "flood",
        task_type: taskType,
        title,
        emergency,
      });
      setNotice(`任务已创建：${created.code}`);
      reload();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "创建失败");
    }
  }

  return (
    <>
      <p className="page-lead">任务中心处理所有已开通场景的作业。洪水是当前已注册的第一条场景。</p>
      <div className="grid cols-2">
        <form className="card" onSubmit={onCreate}>
          <h3>新建任务</h3>
          <div className="field">
            <label>标题</label>
            <input value={title} onChange={(e) => setTitle(e.target.value)} required />
          </div>
          <div className="field">
            <label>任务类型</label>
            <select value={taskType} onChange={(e) => setTaskType(e.target.value)}>
              <option value="flood_pipeline">洪水全流程</option>
              <option value="water_extract">水体提取</option>
              <option value="change_detect">变化检测</option>
            </select>
          </div>
          <label className="hint">
            <input type="checkbox" checked={emergency} onChange={(e) => setEmergency(e.target.checked)} /> 应急插队
          </label>
          <div className="btn-row">
            <button className="btn" type="submit" disabled={isReadonly || !has("task.create")}>
              创建并下发
            </button>
          </div>
          {(isReadonly || !has("task.create")) && <p className="warn">当前角色无权执行该操作。</p>}
          {error && <p className="error">{error}</p>}
          {notice && <p className="hint">{notice}</p>}
        </form>
        <div className="card">
          <h3>任务列表</h3>
          {tasks.length === 0 && <p className="empty">还没有任务。</p>}
          {tasks.length > 0 && (
            <table className="table">
              <thead>
                <tr>
                  <th>标题</th>
                  <th>状态</th>
                  <th>进度</th>
                </tr>
              </thead>
              <tbody>
                {tasks.map((task) => (
                  <tr key={task.id}>
                    <td>
                      <Link to={`/tasks/${task.id}`}>{task.title}</Link>
                    </td>
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
      </div>
    </>
  );
}
