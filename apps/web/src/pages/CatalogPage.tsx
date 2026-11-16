
import { useEffect, useState } from "react";
import { NavLink } from "react-router-dom";
import { api, type Baseline, type Dataset } from "../api/client";
import { useProject } from "../shell/ProjectContext";

export function CatalogPage() {
  const { project } = useProject();
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!project) return;
    api.datasets(project.id).then(setDatasets).catch((err) => setError(err.message));
  }, [project]);

  return (
    <>
      <p className="page-lead">数据编目是平台资产，洪水与后续场景共用同一套目录。</p>
      <div className="btn-row" style={{ marginBottom: 12 }}>
        <NavLink to="/catalog" className="btn">编目</NavLink>
        <NavLink to="/catalog/baseline" className="btn ghost">本底库</NavLink>
      </div>
      {error && <p className="error">{error}</p>}
      <div className="card">
        {datasets.length === 0 && <p className="empty">暂无编目数据。管理员可在接入引擎后登记已入仓的 Sentinel-1 与专题数据。</p>}
        {datasets.length > 0 && (
          <table className="table">
            <thead>
              <tr>
                <th>编码</th>
                <th>名称</th>
                <th>类型</th>
                <th>CRS</th>
                <th>状态</th>
              </tr>
            </thead>
            <tbody>
              {datasets.map((row) => (
                <tr key={row.id}>
                  <td>{row.code}</td>
                  <td>{row.name}</td>
                  <td>{row.dataset_type}</td>
                  <td>{row.crs}</td>
                  <td>{row.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}

export function BaselinesPage() {
  const { project } = useProject();
  const [rows, setRows] = useState<Baseline[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!project) return;
    api.baselines(project.id).then(setRows).catch((err) => setError(err.message));
  }, [project]);

  return (
    <>
      <p className="page-lead">
        本底是带版本、生效时段、适用区域和审核状态的正式数据资产，不是任务临时文件。只有已发布版本可被正式产品引用。
      </p>
      <div className="btn-row" style={{ marginBottom: 12 }}>
        <NavLink to="/catalog" className="btn ghost">编目</NavLink>
        <NavLink to="/catalog/baseline" className="btn">本底库</NavLink>
      </div>
      {error && <p className="error">{error}</p>}
      <div className="card">
        {rows.length === 0 && (
          <p className="empty">暂无本底版本。每个试点区至少需要一份已发布的常年水体（permanent_water）才能产出「本次淹没」。</p>
        )}
        {rows.length > 0 && (
          <table className="table">
            <thead>
              <tr>
                <th>编码</th>
                <th>名称</th>
                <th>类型</th>
                <th>版本</th>
                <th>审核状态</th>
                <th>适用区域</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id}>
                  <td>{row.code}</td>
                  <td>{row.name}</td>
                  <td>{row.category}</td>
                  <td>{row.version}</td>
                  <td>
                    <span className={`status ${row.review_status}`}>{row.review_status}</span>
                  </td>
                  <td>{row.applicable_area_name || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}
