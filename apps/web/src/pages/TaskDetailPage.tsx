
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError, api, type Task } from "../api/client";
import { useAuth } from "../auth/AuthContext";

export function TaskDetailPage() {
  const { id = "" } = useParams();
  const { has } = useAuth();
  const [task, setTask] = useState<Task | null>(null);
  const [error, setError] = useState("");

  function reload() {
    api.task(id).then(setTask).catch((err) => setError(err.message));
  }
  useEffect(reload, [id]);

  async function act(kind: "retry" | "cancel") {
    setError("");
    try {
      const next = kind === "retry" ? await api.retryTask(id) : await api.cancelTask(id);
      setTask(next);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "操作失败");
    }
  }

  if (!task && !error) return <p className="empty">加载任务…</p>;
  if (!task) return <p className="error">{error}</p>;

  return (
    <>
      <p className="page-lead">
        <Link to="/tasks">返回任务列表</Link>
      </p>
      <div className="card">
        <h3>{task.title}</h3>
        <p>
          编号 {task.code} · 场景 {task.scene_code} · 类型 {task.task_type}
        </p>
        <p>
          状态 <span className={`status ${task.status}`}>{task.status}</span> · 进度 {task.progress}% · 步骤 {task.step || "—"}
        </p>
        {task.engine_job_id && <p className="hint">引擎作业 {task.engine_job_id}</p>}
        {task.error_message && <p className="error">{task.error_message}</p>}
        <div className="btn-row">
          <button className="btn" type="button" disabled={!has("task.retry")} onClick={() => act("retry")}>
            重跑
          </button>
          <button className="btn ghost" type="button" disabled={!has("task.cancel")} onClick={() => act("cancel")}>
            取消
          </button>
        </div>
        {(!has("task.retry") || !has("task.cancel")) && <p className="warn">当前角色无权执行部分操作。</p>}
        {error && <p className="error">{error}</p>}
      </div>
    </>
  );
}
