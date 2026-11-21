import { FormEvent, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, api, type DataAsset, type Dataset, type Product, type Task } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { useProject } from "../shell/ProjectContext";

const ACTIVE = new Set(["queued", "running"]);

export function TasksPage() {
  const { project, areas } = useProject();
  const { has, isReadonly } = useAuth();
  const [tasks, setTasks] = useState<Task[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [assets, setAssets] = useState<DataAsset[]>([]);
  const [title, setTitle] = useState("洪水应急处理");
  const [taskType, setTaskType] = useState("flood_pipeline");
  const [areaId, setAreaId] = useState("");
  const [datasetId, setDatasetId] = useState("");
  const [baselineVersionId, setBaselineVersionId] = useState("");
  const [emergency, setEmergency] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  function reload() {
    if (!project) return;
    Promise.all([api.tasks(project.id), api.products(project.id), api.datasets(project.id), api.dataAssets(project.id, "published")])
      .then(([nextTasks, nextProducts, nextDatasets, nextAssets]) => {
        setTasks(nextTasks);
        setProducts(nextProducts);
        setDatasets(nextDatasets);
        setAssets(nextAssets);
      })
      .catch((err) => setError(err.message));
  }

  useEffect(() => {
    reload();
  }, [project]);

  useEffect(() => {
    if (!areaId && areas[0]) setAreaId(areas[0].id);
  }, [areas, areaId]);

  useEffect(() => {
    if (!project) return;
    if (!tasks.some((task) => ACTIVE.has(task.status))) return;
    const timer = window.setInterval(reload, 3000);
    return () => window.clearInterval(timer);
  }, [project, tasks]);

  const area = areas.find((item) => item.id === areaId) ?? null;
  const publishedVersions = useMemo(() => {
    const rows: { id: string; label: string }[] = [];
    for (const asset of assets) {
      if (area && asset.area_id && asset.area_id !== area.id) continue;
      for (const version of asset.versions ?? []) {
        if (version.review_status !== "published") continue;
        rows.push({
          id: version.id,
          label: `${asset.name} ${version.version_no}（${asset.asset_type}）`,
        });
      }
    }
    return rows;
  }, [assets, area]);

  async function onCreate(event: FormEvent) {
    event.preventDefault();
    if (!project) return;
    if (!has("task.create")) {
      setError("当前角色无权执行该操作");
      return;
    }
    if (!areaId) {
      setError("请选择区域。分析坐标系和 AOI 来自该区域，不在这里写死。");
      return;
    }
    setError("");
    setNotice("");
    try {
      const body: Record<string, unknown> = {
        project_id: project.id,
        area_id: areaId,
        scene_code: "flood",
        task_type: taskType,
        title,
        emergency,
      };
      if (datasetId) body.imagery_dataset_id = datasetId;
      if (baselineVersionId) body.baseline_version_id = baselineVersionId;
      const created = await api.createTask(body);
      setNotice(
        created.status === "queued" || created.status === "running"
          ? `任务已下发：${created.code}。mock 引擎跑完后，状态会变成 succeeded，并在下方和质检页出现产品。`
          : `任务已创建：${created.code}（${created.status}）`,
      );
      reload();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "创建失败");
    }
  }

  return (
    <>
      <p className="page-lead">
        任务中心处理已开通场景的作业。洪水是当前已注册的场景。创建后由 mock 引擎处理已入仓的数据，不下载 Sentinel-1，也不需要 SNAP。
      </p>
      <div className="grid cols-2">
        <form className="card" onSubmit={onCreate}>
          <h3>新建洪水处理任务</h3>
          <div className="field">
            <label>标题</label>
            <input value={title} onChange={(e) => setTitle(e.target.value)} required />
          </div>
          <div className="field">
            <label>区域</label>
            <select value={areaId} onChange={(e) => setAreaId(e.target.value)} required>
              <option value="">选择区域</option>
              {areas.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}（{item.analysis_crs}）
                </option>
              ))}
            </select>
          </div>
          {area && (
            <p className="hint">
              分析坐标系 {area.analysis_crs}，交换坐标系 {area.exchange_crs}，网格 {area.grid_res_m} m。AOI 与 CRS 按区域配置。
            </p>
          )}
          <div className="field">
            <label>已入仓影像（可选）</label>
            <select value={datasetId} onChange={(e) => setDatasetId(e.target.value)}>
              <option value="">不指定，mock 使用合成栅格</option>
              {datasets.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                  {item.s1_product_id ? ` · ${item.s1_product_id}` : ""}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label>已发布本底版本（可选）</label>
            <select value={baselineVersionId} onChange={(e) => setBaselineVersionId(e.target.value)}>
              <option value="">不指定。平台只绑定唯一的已发布本底；没有适用本底时只出提取水体</option>
              {publishedVersions.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.label}
                </option>
              ))}
            </select>
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
          {areas.length === 0 && <p className="warn">当前项目还没有区域。请管理员先在管理页配置区域和 analysis_crs。</p>}
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
                  <th>产品</th>
                </tr>
              </thead>
              <tbody>
                {tasks.map((task) => {
                  const linked = products.filter((product) => product.task_id === task.id);
                  return (
                    <tr key={task.id}>
                      <td>
                        <Link to={`/tasks/${task.id}`}>{task.title}</Link>
                      </td>
                      <td>
                        <span className={`status ${task.status}`}>{task.status}</span>
                      </td>
                      <td>{task.progress}%</td>
                      <td>
                        {linked.length === 0 && "—"}
                        {linked.map((product) => (
                          <div key={product.id}>
                            <Link to="/qc">{product.code}</Link>
                            <span className="hint"> {product.status}</span>
                          </div>
                        ))}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </>
  );
}
