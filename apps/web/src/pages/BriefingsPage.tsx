import { FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, api, type Briefing, type BriefingDocument } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { BriefingSheet } from "../features/briefing/BriefingSheet";
import { useProject } from "../shell/ProjectContext";

export function BriefingsPage() {
  const { project, areas } = useProject();
  const { has, isReadonly } = useAuth();
  const [items, setItems] = useState<Briefing[]>([]);
  const [areaId, setAreaId] = useState("");
  const [preview, setPreview] = useState<BriefingDocument | null>(null);
  const [title, setTitle] = useState("洪水应急简报");
  const [summary, setSummary] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    if (!areas.length) {
      setAreaId("");
      return;
    }
    if (areas.some((area) => area.id === areaId)) return;
    setAreaId((areas.find((area) => area.is_pilot) ?? areas[0]).id);
  }, [areas, areaId]);

  function reload() {
    if (!project) return;
    api.briefings(project.id).then(setItems).catch((err) => setError(err.message));
  }
  useEffect(reload, [project]);

  useEffect(() => {
    if (!project || !areaId) {
      setPreview(null);
      return;
    }
    let cancelled = false;
    api
      .briefingPreview(project.id, areaId, "flood")
      .then((doc) => {
        if (cancelled) return;
        setPreview(doc);
        setTitle(doc.title);
        setSummary(doc.conclusion);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      });
    return () => {
      cancelled = true;
    };
  }, [project, areaId]);

  async function onCreate(event: FormEvent) {
    event.preventDefault();
    if (!project) return;
    try {
      await api.createBriefing({
        project_id: project.id,
        scene_code: "flood",
        title,
        content_json: {
          summary,
          conclusion: summary,
          limitations: ["第一版不提供水深", "非小时级重访"],
        },
        product_ids: preview?.product ? [preview.product.id] : [],
      });
      reload();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "创建失败");
    }
  }

  return (
    <>
      <p className="page-lead">
        默认简报只采用已发布产品。草稿、待质检和已撤回的淹没范围不会出现在这张简报上。没有已发布产品时只保留区域范围。
      </p>
      <div className="btn-row" style={{ marginBottom: 12 }}>
        <label className="hint">
          区域{" "}
          <select value={areaId} onChange={(event) => setAreaId(event.target.value)}>
            {areas.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name}
              </option>
            ))}
          </select>
        </label>
      </div>
      <div className="grid cols-2">
        <div>{preview ? <BriefingSheet document={preview} /> : <p className="empty">正在读取已发布产品…</p>}</div>
        <div>
          <form className="card" onSubmit={onCreate}>
            <h3>保存为简报草稿</h3>
            <p className="hint">保存时引用当前已发布产品。发布简报时，引用的产品必须已经发布。</p>
            <div className="field">
              <label>标题</label>
              <input value={title} onChange={(e) => setTitle(e.target.value)} />
            </div>
            <div className="field">
              <label>结论</label>
              <textarea rows={5} value={summary} onChange={(e) => setSummary(e.target.value)} />
            </div>
            <button className="btn" type="submit" disabled={isReadonly || !has("briefing.write")}>
              保存草稿
            </button>
            {(isReadonly || !has("briefing.write")) && <p className="warn">当前角色无权执行该操作。</p>}
            {error && <p className="error">{error}</p>}
          </form>
          <div className="card" style={{ marginTop: 16 }}>
            <h3>简报列表</h3>
            {items.length === 0 && <p className="empty">还没有简报。</p>}
            <ul>
              {items.map((item) => (
                <li key={item.id}>
                  <Link to={`/briefing/${item.id}`}>{item.title}</Link>{" "}
                  <span className={`status ${item.status}`}>{item.status}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </div>
    </>
  );
}
