
import { useEffect, useState } from "react";
import { ApiError, api, type Product } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { useProject } from "../shell/ProjectContext";

export function QcPage() {
  const { project } = useProject();
  const { has, canQc } = useAuth();
  const [products, setProducts] = useState<Product[]>([]);
  const [comment, setComment] = useState("");
  const [error, setError] = useState("");

  function reload() {
    if (!project) return;
    api.products(project.id).then(setProducts).catch((err) => setError(err.message));
  }
  useEffect(reload, [project]);

  async function act(id: string, kind: "submit" | "reject" | "publish" | "withdraw") {
    setError("");
    try {
      if (kind === "submit") await api.submitProduct(id);
      if (kind === "reject") await api.rejectProduct(id, comment || "请补充说明");
      if (kind === "publish") await api.publishProduct(id, comment);
      if (kind === "withdraw") await api.withdrawProduct(id, comment || "撤回");
      reload();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "操作失败");
    }
  }

  const queue = products.filter((p) => p.status === "pending_qc" || p.status === "draft" || p.status === "published");

  return (
    <>
      <p className="page-lead">值班员和管理员可以对产品进行质检并发布。撤回已发布产品仅管理员可执行。第一版产品不含水深。</p>
      <div className="field" style={{ maxWidth: 420 }}>
        <label>质检意见 / 撤回原因</label>
        <input value={comment} onChange={(e) => setComment(e.target.value)} placeholder="打回时必须填写原因" />
      </div>
      {error && <p className="error">{error}</p>}
      {!canQc && <p className="warn">当前角色无权执行质检或发布。</p>}
      <div className="card">
        {queue.length === 0 && <p className="empty">暂无待处理产品。</p>}
        <table className="table">
          <thead>
            <tr>
              <th>标题</th>
              <th>类型</th>
              <th>版本</th>
              <th>状态</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {queue.map((product) => (
              <tr key={product.id}>
                <td>{product.title}</td>
                <td>{product.product_type}</td>
                <td>v{product.version}</td>
                <td>
                  <span className={`status ${product.status}`}>{product.status}</span>
                </td>
                <td>
                  <div className="btn-row">
                    {product.status === "draft" && (
                      <button className="btn" type="button" disabled={!has("product.submit")} onClick={() => act(product.id, "submit")}>
                        提交质检
                      </button>
                    )}
                    {product.status === "pending_qc" && (
                      <>
                        <button className="btn accent" type="button" disabled={!has("product.publish")} onClick={() => act(product.id, "publish")}>
                          发布
                        </button>
                        <button className="btn ghost" type="button" disabled={!has("product.qc")} onClick={() => act(product.id, "reject")}>
                          打回
                        </button>
                      </>
                    )}
                    {product.status === "published" && (
                      <button className="btn danger" type="button" disabled={!has("product.withdraw")} onClick={() => act(product.id, "withdraw")}>
                        撤回
                      </button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
