import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError, api, type Product, type Task } from "../api/client";
import { useAuth } from "../auth/AuthContext";

const ACTIVE = new Set(["queued", "running"]);

export function TaskDetailPage() {
  const { id = "" } = useParams();
  const { has } = useAuth();
  const [task, setTask] = useState<Task | null>(null);
  const [products, setProducts] = useState<Product[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    let stop = false;
    let timer = 0;

    async function tick() {
      try {
        const next = await api.task(id);
        if (stop) return;
        setTask(next);
        const rows = await api.products(next.project_id, next.id);
        if (stop) return;
        setProducts(rows);
        if (ACTIVE.has(next.status)) {
          timer = window.setTimeout(tick, 2000);
        }
      } catch (err) {
        if (!stop) setError(err instanceof ApiError ? err.message : "加载失败");
      }
    }

    tick();
    return () => {
      stop = true;
      window.clearTimeout(timer);
    };
  }, [id]);

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
        {task.s1_product_id && <p className="hint">Sentinel-1 {task.s1_product_id}</p>}
        {task.engine_job_id && <p className="hint">引擎作业 {task.engine_job_id}</p>}
        {task.error_code && <p className="error">{task.error_code}</p>}
        {task.error_message && <p className="error">{task.error_message}</p>}
        {ACTIVE.has(task.status) && <p className="hint">引擎处理中，页面会自动刷新。</p>}
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
      <div className="card" style={{ marginTop: 16 }}>
        <h3>本任务产品</h3>
        {products.length === 0 && <p className="empty">还没有产品。mock 引擎成功回传后会出现在这里和质检页，状态为 draft。</p>}
        {products.length > 0 && (
          <table className="table">
            <thead>
              <tr>
                <th>标题</th>
                <th>状态</th>
                <th>淹没口径</th>
                <th>面积</th>
              </tr>
            </thead>
            <tbody>
              {products.map((product) => (
                <tr key={product.id}>
                  <td>
                    <Link to="/qc">{product.title}</Link>
                    <div className="hint">{product.code}</div>
                  </td>
                  <td>
                    <span className={`status ${product.status}`}>{product.status}</span>
                  </td>
                  <td>{product.flood_event_status || "—"}</td>
                  <td>
                    {product.flood_event_ha != null
                      ? `${product.flood_event_ha} ha`
                      : product.extracted_water_ha != null
                        ? `${product.extracted_water_ha} ha`
                        : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}
