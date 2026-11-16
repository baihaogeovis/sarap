
import { FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, api, type Briefing } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { useProject } from "../shell/ProjectContext";

export function BriefingsPage() {
  const { project } = useProject();
  const { has, isReadonly } = useAuth();
  const [items, setItems] = useState<Briefing[]>([]);
  const [title, setTitle] = useState("洪水应急简报");
  const [summary, setSummary] = useState("成像时刻淹没范围见附图。第一版不提供水深，建成区可能低估。");
  const [error, setError] = useState("");

  function reload() {
    if (!project) return;
    api.briefings(project.id).then(setItems).catch((err) => setError(err.message));
  }
  useEffect(reload, [project]);

  async function onCreate(event: FormEvent) {
    event.preventDefault();
    if (!project) return;
    try {
      await api.createBriefing({
        project_id: project.id,
        scene_code: "flood",
        title,
        content_json: { summary, limitations: ["第一版不提供水深", "非小时级重访"] },
      });
      reload();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "创建失败");
    }
  }

  return (
    <>
      <p className="page-lead">简报引用已发布产品，面向会商与值班通报。</p>
      <div className="grid cols-2">
        <form className="card" onSubmit={onCreate}>
          <h3>起草简报</h3>
          <div className="field">
            <label>标题</label>
            <input value={title} onChange={(e) => setTitle(e.target.value)} />
          </div>
          <div className="field">
            <label>摘要</label>
            <textarea rows={4} value={summary} onChange={(e) => setSummary(e.target.value)} />
          </div>
          <button className="btn" type="submit" disabled={isReadonly || !has("briefing.write")}>
            保存草稿
          </button>
          {(isReadonly || !has("briefing.write")) && <p className="warn">当前角色无权执行该操作。</p>}
          {error && <p className="error">{error}</p>}
        </form>
        <div className="card">
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
    </>
  );
}
