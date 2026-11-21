import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError, api, type Briefing, type BriefingDocument } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { BriefingSheet } from "../features/briefing/BriefingSheet";

export function BriefingPage() {
  const { id = "" } = useParams();
  const { has } = useAuth();
  const [item, setItem] = useState<Briefing | null>(null);
  const [document, setDocument] = useState<BriefingDocument | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    api
      .briefing(id)
      .then((row) => {
        if (!cancelled) setItem(row);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      });
    api
      .briefingDocument(id)
      .then((doc) => {
        if (!cancelled) setDocument(doc);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      });
    return () => {
      cancelled = true;
    };
  }, [id]);

  async function publish() {
    try {
      const next = await api.publishBriefing(id);
      setItem(next);
      setDocument(await api.briefingDocument(id));
      setError("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "发布失败");
    }
  }

  if (!item && !document && !error) return <p className="empty">加载简报…</p>;
  if (!item && !document) return <p className="error">{error}</p>;

  return (
    <>
      <p className="page-lead">
        <Link to="/briefings">返回简报列表</Link>
        {item && (
          <>
            {" "}
            · <span className={`status ${item.status}`}>{item.status}</span>
          </>
        )}
      </p>
      {document && <BriefingSheet document={document} />}
      {item?.status === "draft" && (
        <div className="btn-row">
          <button className="btn accent" type="button" disabled={!has("briefing.publish")} onClick={publish}>
            发布简报
          </button>
          {!has("briefing.publish") && <p className="warn">当前角色无权执行该操作。</p>}
        </div>
      )}
      {error && <p className="error">{error}</p>}
    </>
  );
}
