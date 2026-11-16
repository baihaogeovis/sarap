
import { useEffect, useState } from "react";
import { api, type Scene, type SceneActivation } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { useProject } from "../shell/ProjectContext";

export function AdminPage() {
  const { project, areas } = useProject();
  const { canManage } = useAuth();
  const [scenes, setScenes] = useState<Scene[]>([]);
  const [activations, setActivations] = useState<SceneActivation[]>([]);
  const [members, setMembers] = useState<{ id: string; user_id: string; role_code: string }[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!project) return;
    Promise.all([api.scenes(), api.activations(project.id), api.members(project.id)])
      .then(([s, a, m]) => {
        setScenes(s);
        setActivations(a);
        setMembers(m);
      })
      .catch((err) => setError(err.message));
  }, [project]);

  if (!canManage) {
    return <div className="card empty">当前角色无权访问管理页。只有管理员可以配置项目、区域、成员和场景开通。</div>;
  }

  return (
    <>
      <p className="page-lead">项目管理、试点区域、场景开通与成员。试点 AOI 与 analysis_crs 在此配置，禁止把流域名称写进代码。</p>
      {error && <p className="error">{error}</p>}
      <div className="grid cols-2">
        <div className="card">
          <h3>项目与区域</h3>
          <p>
            {project?.name} · 默认分析 CRS {project?.default_crs}
          </p>
          {areas.length === 0 && <p className="empty">尚未登记区域。</p>}
          <table className="table">
            <thead>
              <tr>
                <th>区域</th>
                <th>分析 CRS</th>
                <th>交换 CRS</th>
                <th>试点</th>
              </tr>
            </thead>
            <tbody>
              {areas.map((area) => (
                <tr key={area.id}>
                  <td>{area.name}</td>
                  <td>{area.analysis_crs}</td>
                  <td>{area.exchange_crs}</td>
                  <td>{area.is_pilot ? "是" : "否"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="card">
          <h3>已注册场景</h3>
          {scenes.map((scene) => {
            const active = activations.find((a) => a.scene_id === scene.id);
            return (
              <p key={scene.id}>
                <strong>{scene.name}</strong> ({scene.code} {scene.version}) — {active?.status ?? "未开通"}
                <br />
                <span className="hint">{scene.description}</span>
              </p>
            );
          })}
        </div>
        <div className="card">
          <h3>项目成员</h3>
          {members.length === 0 && <p className="empty">无法列出成员或尚无成员。</p>}
          <ul>
            {members.map((member) => (
              <li key={member.id}>
                {member.user_id} · {member.role_code}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </>
  );
}
