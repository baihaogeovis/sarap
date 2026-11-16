
import { useEffect, useRef, useState } from "react";
import Map from "ol/Map";
import View from "ol/View";
import TileLayer from "ol/layer/Tile";
import VectorLayer from "ol/layer/Vector";
import VectorSource from "ol/source/Vector";
import OSM from "ol/source/OSM";
import GeoJSON from "ol/format/GeoJSON";
import { fromLonLat } from "ol/proj";
import { Fill, Stroke, Style } from "ol/style";
import type { LayerSpec } from "./layers";
import { attachSwipe } from "./swipe";
import { exportMapPng } from "./exportPng";

type Props = {
  layers: LayerSpec[];
  center?: [number, number];
  zoom?: number;
};

function styleFor(color: string) {
  return new Style({
    fill: new Fill({ color: `${color}99` }),
    stroke: new Stroke({ color, width: 2 }),
  });
}

export function MapView({ layers, center = [116.5, 39.85], zoom = 9 }: Props) {
  const host = useRef<HTMLDivElement>(null);
  const mapRef = useRef<Map | null>(null);
  const [swipe, setSwipe] = useState(false);
  const [ratio, setRatio] = useState(0.5);
  const [identify, setIdentify] = useState<Record<string, unknown> | null>(null);
  const ratioRef = useRef(ratio);
  ratioRef.current = ratio;

  useEffect(() => {
    if (!host.current) return;
    const map = new Map({
      target: host.current,
      layers: [new TileLayer({ source: new OSM() })],
      view: new View({ center: fromLonLat(center), zoom }),
    });
    map.on("singleclick", (event) => {
      let found: Record<string, unknown> | null = null;
      map.forEachFeatureAtPixel(event.pixel, (feature) => {
        found = { ...(feature.getProperties() as Record<string, unknown>) };
        delete found.geometry;
        return true;
      });
      setIdentify(found);
    });
    mapRef.current = map;
    return () => {
      map.setTarget(undefined);
      mapRef.current = null;
    };
  }, [center, zoom]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const existing = map.getLayers().getArray().slice(1);
    existing.forEach((layer) => map.removeLayer(layer));
    const format = new GeoJSON();
    const created: VectorLayer<VectorSource>[] = [];
    layers.forEach((spec) => {
      if (!spec.visible || !spec.geojson) return;
      const source = new VectorSource({
        features: format.readFeatures(spec.geojson, {
          dataProjection: "EPSG:4326",
          featureProjection: "EPSG:3857",
        }),
      });
      const layer = new VectorLayer({ source, style: styleFor(spec.color), properties: { id: spec.id } });
      map.addLayer(layer);
      created.push(layer);
    });
    const eventLayer = created.find((_, i) => layers.filter((l) => l.visible && l.geojson)[i]?.kind === "event");
    if (swipe && eventLayer) {
      return attachSwipe(map, eventLayer, () => ratioRef.current);
    }
    return undefined;
  }, [layers, swipe, ratio]);

  return (
    <div className="map-wrap">
      <div className="map-toolbar">
        <button className={`btn ${swipe ? "accent" : "ghost"}`} onClick={() => setSwipe((v) => !v)} type="button">
          {swipe ? "关闭卷帘" : "卷帘对比"}
        </button>
        {swipe && (
          <input
            type="range"
            min={0}
            max={1}
            step={0.01}
            value={ratio}
            onChange={(e) => {
              setRatio(Number(e.target.value));
              mapRef.current?.render();
            }}
            aria-label="卷帘位置"
          />
        )}
        <button className="btn ghost" type="button" onClick={() => mapRef.current && exportMapPng(mapRef.current)}>
          导出 PNG
        </button>
      </div>
      {identify && (
        <div className="identify-pop">
          <strong>识别结果</strong>
          {Object.keys(identify).length === 0 && <p className="hint">无属性</p>}
          {Object.entries(identify).map(([key, value]) => (
            <div key={key}>
              <span className="hint">{key}：</span>
              {String(value)}
            </div>
          ))}
        </div>
      )}
      <div ref={host} style={{ width: "100%", height: "100%" }} />
    </div>
  );
}
