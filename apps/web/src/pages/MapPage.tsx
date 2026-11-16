import { useEffect, useMemo, useState } from "react";
import { api, type Area, type MapPayload } from "../api/client";
import { MapView } from "../features/map/MapView";
import { COLORS, collectionCenter, type FeatureCollection, type LayerSpec } from "../features/map/layers";
import { listScenes } from "../scenes/registry";
import "../scenes/flood";
import { useProject } from "../shell/ProjectContext";

function geographicCenter(area: Area | undefined): [number, number] | null {
  const bbox = area?.bbox_json;
  if (!bbox) return null;
  if (Math.abs(bbox.minx) > 180 || Math.abs(bbox.maxx) > 180) return null;
  if (Math.abs(bbox.miny) > 90 || Math.abs(bbox.maxy) > 90) return null;
  return [(bbox.minx + bbox.maxx) / 2, (bbox.miny + bbox.maxy) / 2];
}

function colorFor(kind: LayerSpec["kind"]): string {
  if (kind === "event") return COLORS.event;
  if (kind === "qc") return COLORS.qc;
  return COLORS.water;
}

export function MapPage() {
  const { project, areas } = useProject();
  const registered = listScenes();
  const [sceneCode, setSceneCode] = useState(registered[0]?.code ?? "");
  const [areaId, setAreaId] = useState("");
  const [productId, setProductId] = useState("");
  const [hidden, setHidden] = useState<Record<string, boolean>>({});
  const [payload, setPayload] = useState<MapPayload | null>(null);
  const [phase, setPhase] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState("");

  useEffect(() => {
    if (!areas.length) {
      setAreaId("");
      return;
    }
    if (areas.some((area) => area.id === areaId)) return;
    setAreaId((areas.find((area) => area.is_pilot) ?? areas[0]).id);
  }, [areas, areaId]);

  useEffect(() => {
    if (!project || !areaId) {
      setPayload(null);
      setPhase(areas.length ? "loading" : "ready");
      return;
    }
    let cancelled = false;
    setPhase("loading");
    setError("");
    api
      .mapLayers(areaId, project.id, sceneCode || undefined)
      .then((next) => {
        if (cancelled) return;
        setPayload(next);
        setPhase("ready");
      })
      .catch((err: Error) => {
        if (cancelled) return;
        setPayload(null);
        setError(err.message || "地图产品加载失败");
        setPhase("error");
      });
    return () => {
      cancelled = true;
    };
  }, [project, areaId, sceneCode, areas.length]);

  useEffect(() => {
    const ids = payload?.products.map((product) => product.id) ?? [];
    if (!ids.length) {
      setProductId("");
      return;
    }
    if (!ids.includes(productId)) setProductId(ids[0]);
  }, [payload, productId]);

  const area = areas.find((item) => item.id === areaId);
  const product = payload?.products.find((item) => item.id === productId) ?? null;
  const analysisCrs = payload?.area.analysis_crs || area?.analysis_crs || "";

  const layers = useMemo<LayerSpec[]>(() => {
    const specs: LayerSpec[] = [];
    const aoi = payload?.area.aoi;
    if (aoi?.features?.length) {
      specs.push({
        id: "area-aoi",
        title: "区域范围",
        kind: "other",
        color: COLORS.other,
        visible: hidden["area-aoi"] !== true,
        fill: false,
        geojson: aoi as FeatureCollection,
      });
    }
    for (const layer of product?.layers ?? []) {
      const id = `${product?.id}:${layer.layer_key}:${layer.kind}`;
      specs.push({
        id,
        title: layer.title,
        kind: layer.kind,
        color: layer.kind === "other" ? COLORS.other : colorFor(layer.kind),
        visible: hidden[id] !== true,
        fill: true,
        geojson: layer.geojson as FeatureCollection,
      });
    }
    return specs;
  }, [payload, product, hidden]);

  const center = useMemo<[number, number]>(() => {
    return (
      collectionCenter((payload?.area.aoi ?? null) as FeatureCollection | null) ??
      geographicCenter(area) ?? [0, 20]
    );
  }, [payload, area]);

  let notice = "";
  if (!project) notice = "正在读取项目…";
  else if (!areas.length && phase !== "loading") notice = "当前项目还没有区域。";
  else if (phase === "loading") notice = "正在读取已发布产品…";
  else if (phase === "error") notice = error;
  else if (!payload?.products.length) notice = "该区域没有已发布产品。默认一张图只显示已发布范围。";
  else if (product && product.layers.length === 0) notice = "这份已发布产品没有可显示的范围图层。";

  const fitToken = `${areaId}:${productId}:${layers.map((layer) => layer.id).join(",")}`;

  return (
    <>
      <p className="page-lead">
        一张图显示所选区域，以及该区域已发布的洪水产品范围。草稿、待质检和已撤回的产品不会出现在默认图上。没有已发布产品时只保留区域范围，不编造淹没面。本底水体用水色，本次淹没用强调色。不展示水深。
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
        <label className="hint">
          场景{" "}
          <select value={sceneCode} onChange={(event) => setSceneCode(event.target.value)}>
            {registered.map((scene) => (
              <option key={scene.code} value={scene.code}>
                {scene.name}
              </option>
            ))}
          </select>
        </label>
        <label className="hint">
          已发布产品{" "}
          <select value={productId} onChange={(event) => setProductId(event.target.value)}>
            {payload?.products.length ? (
              payload.products.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.title} · v{item.version}
                </option>
              ))
            ) : (
              <option value="">无</option>
            )}
          </select>
        </label>
        {analysisCrs && <span className="hint">分析坐标系 {analysisCrs}</span>}
        {layers.map((layer) => (
          <label key={layer.id} className="hint">
            <input
              type="checkbox"
              checked={layer.visible}
              onChange={() => setHidden((curr) => ({ ...curr, [layer.id]: layer.visible }))}
            />{" "}
            {layer.title}
          </label>
        ))}
      </div>
      <MapView layers={layers} center={center} fitToken={fitToken} notice={notice} />
    </>
  );
}
