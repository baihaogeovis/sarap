import { FormEvent, useEffect, useState } from "react";
import { NavLink } from "react-router-dom";
import { ApiError, api, type Baseline, type DataAsset, type Dataset } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { useProject } from "../shell/ProjectContext";

function toIso(value: string): string | undefined {
  if (!value) return undefined;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return undefined;
  return parsed.toISOString();
}

export function CatalogPage() {
  const { project } = useProject();
  const { has } = useAuth();
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [source, setSource] = useState("staged");
  const [crs, setCrs] = useState("EPSG:4490");
  const [storageUri, setStorageUri] = useState("");
  const [s1ProductId, setS1ProductId] = useState("");
  const [timeStart, setTimeStart] = useState("");
  const [timeEnd, setTimeEnd] = useState("");

  function reload() {
    if (!project) return;
    api.datasets(project.id).then(setDatasets).catch((err) => setError(err.message));
  }

  useEffect(() => {
    reload();
  }, [project]);

  useEffect(() => {
    if (project?.default_crs) setCrs(project.default_crs);
  }, [project]);

  async function onCreate(event: FormEvent) {
    event.preventDefault();
    if (!project) return;
    setError("");
    setNotice("");
    try {
      const created = await api.createDataset({
        project_id: project.id,
        code,
        name,
        dataset_type: "raster",
        source,
        crs,
        storage_uri: storageUri,
        s1_product_id: s1ProductId,
        time_start: toIso(timeStart),
        time_end: toIso(timeEnd),
        metadata_json: { staged: true, mock_input: source === "mock" },
      });
      setNotice(`已登记 ${created.code}。值班员可在任务中心选用这景影像。`);
      setCode("");
      setName("");
      setStorageUri("");
      setS1ProductId("");
      reload();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "登记失败");
    }
  }

  return (
    <>
      <p className="page-lead">
        数据编目是平台资产。这里登记的是已经入仓的影像路径，引擎不会下载 Sentinel-1。坐标系按项目填写，不写死流域。
      </p>
      <div className="btn-row" style={{ marginBottom: 12 }}>
        <NavLink to="/catalog" className="btn">编目</NavLink>
        <NavLink to="/catalog/baseline" className="btn ghost">本底库</NavLink>
      </div>
      {error && <p className="error">{error}</p>}
      {notice && <p className="hint">{notice}</p>}
      <div className="grid cols-2">
        <div className="card">
          {datasets.length === 0 && <p className="empty">暂无编目数据。管理员可登记已入仓的 Sentinel-1 或 mock 路径。</p>}
          {datasets.length > 0 && (
            <table className="table">
              <thead>
                <tr>
                  <th>编码</th>
                  <th>名称</th>
                  <th>CRS</th>
                  <th>S1 产品号</th>
                  <th>路径</th>
                </tr>
              </thead>
              <tbody>
                {datasets.map((row) => (
                  <tr key={row.id}>
                    <td>{row.code}</td>
                    <td>{row.name}</td>
                    <td>{row.crs}</td>
                    <td>{row.s1_product_id || "—"}</td>
                    <td>{row.storage_uri || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
        <form className="card" onSubmit={onCreate}>
          <h3>登记已入仓影像</h3>
          {!has("dataset.write") && <p className="warn">当前角色不能登记编目。管理员登记后，值班员可以在任务里选用。</p>}
          <div className="field">
            <label>编码</label>
            <input value={code} onChange={(e) => setCode(e.target.value)} required disabled={!has("dataset.write")} />
          </div>
          <div className="field">
            <label>名称</label>
            <input value={name} onChange={(e) => setName(e.target.value)} required disabled={!has("dataset.write")} />
          </div>
          <div className="field">
            <label>来源</label>
            <select value={source} onChange={(e) => setSource(e.target.value)} disabled={!has("dataset.write")}>
              <option value="staged">已入仓</option>
              <option value="mock">mock 路径</option>
            </select>
          </div>
          <div className="field">
            <label>CRS</label>
            <input value={crs} onChange={(e) => setCrs(e.target.value)} disabled={!has("dataset.write")} />
          </div>
          <div className="field">
            <label>存储 URI</label>
            <input
              value={storageUri}
              onChange={(e) => setStorageUri(e.target.value)}
              placeholder="s3://sarap/staged/scene 或 file:///data/staged/scene"
              disabled={!has("dataset.write")}
            />
          </div>
          <div className="field">
            <label>Sentinel-1 PRODUCT-ID（可选）</label>
            <input value={s1ProductId} onChange={(e) => setS1ProductId(e.target.value)} disabled={!has("dataset.write")} />
          </div>
          <div className="field">
            <label>成像开始</label>
            <input type="datetime-local" value={timeStart} onChange={(e) => setTimeStart(e.target.value)} disabled={!has("dataset.write")} />
          </div>
          <div className="field">
            <label>成像结束</label>
            <input type="datetime-local" value={timeEnd} onChange={(e) => setTimeEnd(e.target.value)} disabled={!has("dataset.write")} />
          </div>
          <button className="btn" type="submit" disabled={!has("dataset.write")}>登记</button>
        </form>
      </div>
    </>
  );
}

export function BaselinesPage() {
  const { project, areas } = useProject();
  const { has } = useAuth();
  const [assets, setAssets] = useState<DataAsset[]>([]);
  const [legacy, setLegacy] = useState<Baseline[]>([]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [assetCode, setAssetCode] = useState("");
  const [name, setName] = useState("");
  const [assetType, setAssetType] = useState("permanent_water");
  const [areaId, setAreaId] = useState("");
  const [versionNo, setVersionNo] = useState("v1");
  const [storageUri, setStorageUri] = useState("");
  const [crs, setCrs] = useState("");

  const canWrite = has("baseline.write") && has("baseline.publish");

  function reload() {
    if (!project) return;
    Promise.all([api.dataAssets(project.id), api.baselines(project.id)])
      .then(([nextAssets, nextLegacy]) => {
        setAssets(nextAssets);
        setLegacy(nextLegacy);
      })
      .catch((err) => setError(err.message));
  }

  useEffect(() => {
    reload();
  }, [project]);

  useEffect(() => {
    if (!areaId && areas[0]) setAreaId(areas[0].id);
  }, [areas, areaId]);

  const area = areas.find((item) => item.id === areaId) ?? null;

  useEffect(() => {
    if (area) setCrs(area.analysis_crs);
  }, [area]);

  async function onCreate(event: FormEvent) {
    event.preventDefault();
    if (!project || !area) return;
    setError("");
    setNotice("");
    try {
      const asset = await api.createDataAsset({
        project_id: project.id,
        area_id: area.id,
        asset_code: assetCode,
        name,
        asset_type: assetType,
        default_crs: crs || area.analysis_crs,
      });
      const version = await api.createDataAssetVersion(asset.id, {
        version_no: versionNo,
        crs: crs || area.analysis_crs,
        storage_uri: storageUri,
        applicable_area_name: area.name,
        applicable_area_geojson: area.aoi_geojson,
        source: storageUri ? "staged" : "mock",
      });
      await api.publishDataAssetVersion(version.id);
      setNotice(`已发布 ${asset.asset_code} ${version.version_no}。任务里可以选择这个版本；没有栅格文件时 mock 引擎用合成水体对比。`);
      setAssetCode("");
      setName("");
      reload();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "发布失败");
    }
  }

  const versions = assets.flatMap((asset) =>
    (asset.versions ?? []).map((version) => ({ asset, version })),
  );

  return (
    <>
      <p className="page-lead">
        正式本底是已发布的数据资产版本。任务只引用已发布版本；没有本底时仍可出提取水体，不能把当期水体写成「本次淹没」。区域和 CRS 在此选择，不写死流域。
      </p>
      <div className="btn-row" style={{ marginBottom: 12 }}>
        <NavLink to="/catalog" className="btn ghost">编目</NavLink>
        <NavLink to="/catalog/baseline" className="btn">本底库</NavLink>
      </div>
      {error && <p className="error">{error}</p>}
      {notice && <p className="hint">{notice}</p>}
      <div className="grid cols-2">
        <div className="card">
          {versions.length === 0 && (
            <p className="empty">暂无数据资产版本。管理员可发布一份常年水体；留空存储路径表示 mock 对比。</p>
          )}
          {versions.length > 0 && (
            <table className="table">
              <thead>
                <tr>
                  <th>资产</th>
                  <th>类型</th>
                  <th>版本</th>
                  <th>状态</th>
                  <th>CRS</th>
                  <th>适用区域</th>
                </tr>
              </thead>
              <tbody>
                {versions.map(({ asset, version }) => (
                  <tr key={version.id}>
                    <td>{asset.name}</td>
                    <td>{asset.asset_type}</td>
                    <td>{version.version_no}</td>
                    <td>
                      <span className={`status ${version.review_status}`}>{version.review_status}</span>
                    </td>
                    <td>{version.crs}</td>
                    <td>{version.applicable_area_name || asset.area_id || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {legacy.length > 0 && (
            <p className="hint">另有 {legacy.length} 条旧本底记录。洪水任务不使用它们，只使用上面已发布的数据资产版本。</p>
          )}
        </div>
        <form className="card" onSubmit={onCreate}>
          <h3>登记并发布本底版本</h3>
          {!canWrite && <p className="warn">发布本底需要管理员。值班员在任务中心选择已发布版本。</p>}
          <div className="field">
            <label>资产编码</label>
            <input value={assetCode} onChange={(e) => setAssetCode(e.target.value)} required disabled={!canWrite} />
          </div>
          <div className="field">
            <label>名称</label>
            <input value={name} onChange={(e) => setName(e.target.value)} required disabled={!canWrite} />
          </div>
          <div className="field">
            <label>类型</label>
            <select value={assetType} onChange={(e) => setAssetType(e.target.value)} disabled={!canWrite}>
              <option value="permanent_water">常年水体</option>
              <option value="seasonal_water">季节水体</option>
            </select>
          </div>
          <div className="field">
            <label>适用区域</label>
            <select value={areaId} onChange={(e) => setAreaId(e.target.value)} required disabled={!canWrite}>
              <option value="">选择区域</option>
              {areas.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}（{item.analysis_crs}）
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label>版本号</label>
            <input value={versionNo} onChange={(e) => setVersionNo(e.target.value)} required disabled={!canWrite} />
          </div>
          <div className="field">
            <label>分析 CRS</label>
            <input value={crs} onChange={(e) => setCrs(e.target.value)} disabled={!canWrite} />
          </div>
          <div className="field">
            <label>栅格 URI（可选）</label>
            <input
              value={storageUri}
              onChange={(e) => setStorageUri(e.target.value)}
              placeholder="留空则 mock 任务使用合成水体"
              disabled={!canWrite}
            />
          </div>
          <button className="btn" type="submit" disabled={!canWrite || !areaId}>发布</button>
        </form>
      </div>
    </>
  );
}
