
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError, api, type Briefing } from "../api/client";
import { useAuth } from "../auth/AuthContext";

export function BriefingPage() {
  const { id = "" } = useParams();
  const { has } = useAuth();
  const [item, setItem] = useState<Briefing | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.briefing(id).then(setItem).catch((err) => setError(err.message));
  }, [id]);

  async function publish() {
    try {
      setItem(await api.publishBriefing(id));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "发布失败");
    }
  }

  if (!item && !error) return <p className="empty">加载简报…</p>;
  if (!item) return <p className="error">{error}</p>;
  const summary = String(item.content_json.summary ?? "");

  return (
    <>
      <p className="page-lead">
        <Link to="/briefings">返回简报列表</Link>
      </p>
      <div className="card">
        <h3>{item.title}</h3>
        <p>
          <span className={`status ${item.status}`}>{item.status}</span> · 场景 {item.scene_code || "—"}
        </p>
        <p>{summary}</p>
        {item.status === "draft" && (
          <button className="btn accent" type="button" disabled={!has("briefing.publish")} onClick={publish}>
            发布简报
          </button>
        )}
        {!has("briefing.publish") && item.status === "draft" && <p className="warn">当前角色无权执行该操作。</p>}
        {error && <p className="error">{error}</p>}
      </div>
    </>
  );
}
