
import { useMemo, useState } from "react";
import { MapView } from "../features/map/MapView";
import { bboxPolygon, type FeatureCollection, type LayerSpec } from "../features/map/layers";
import { getScene, listScenes } from "../scenes/registry";
import "../scenes/flood";
import { useProject } from "../shell/ProjectContext";

export function MapPage() {
  const { project, areas } = useProject();
  const area = areas.find((a) => a.is_pilot) ?? areas[0];
  const bbox = area?.bbox_json ?? project?.bbox_json;
  const aoi = useMemo<FeatureCollection | undefined>(
    () => (bbox ? { type: "FeatureCollection", features: [bboxPolygon(bbox)] } : undefined),
    [bbox],
  );
  const center: [number, number] = bbox ? [(bbox.minx + bbox.maxx) / 2, (bbox.miny + bbox.maxy) / 2] : [116.5, 39.85];
  const registered = listScenes();
  const [sceneCode, setSceneCode] = useState(registered[0]?.code ?? "flood");
  const [hidden, setHidden] = useState<Record<string, boolean>>({});

  const layers: LayerSpec[] = useMemo(() => {
    const scene = getScene(sceneCode);
    return (scene?.mapLayers(aoi) ?? []).map((layer) => ({
      ...layer,
      visible: hidden[layer.id] === undefined ? layer.visible : !hidden[layer.id],
    }));
  }, [sceneCode, aoi, hidden]);

  return (
    <>
      <p className="page-lead">
        一张图由平台提供底图、卷帘、点选识别和 PNG 导出。图层由已注册场景包挂入，当前场景可切换，洪水不是写死的唯一应用。
        本底水体使用水色，本次淹没使用强调色，避免只用红绿区分。不展示水深。
      </p>
      <div className="btn-row" style={{ marginBottom: 12 }}>
        <label className="hint">
          场景{" "}
          <select value={sceneCode} onChange={(e) => setSceneCode(e.target.value)}>
            {registered.map((scene) => (
              <option key={scene.code} value={scene.code}>
                {scene.name}
              </option>
            ))}
          </select>
        </label>
        {layers.map((layer) => (
          <label key={layer.id} className="hint">
            <input
              type="checkbox"
              checked={!hidden[layer.id] && layer.visible}
              onChange={() => setHidden((curr) => ({ ...curr, [layer.id]: !curr[layer.id] }))}
            />{" "}
            {layer.title}
          </label>
        ))}
      </div>
      <MapView layers={layers} center={center} />
    </>
  );
}
