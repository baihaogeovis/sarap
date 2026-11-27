
import { useEffect, useRef, useState } from "react";
import Map from "ol/Map";
import View from "ol/View";
import TileLayer from "ol/layer/Tile";
import VectorLayer from "ol/layer/Vector";
import VectorSource from "ol/source/Vector";
import OSM from "ol/source/OSM";
import XYZ from "ol/source/XYZ";
import ImageTile from "ol/ImageTile";
import type Tile from "ol/Tile";
import GeoJSON from "ol/format/GeoJSON";
import { fromLonLat, toLonLat, transformExtent } from "ol/proj";
import { createEmpty, extend, isEmpty, type Extent } from "ol/extent";
import { Fill, Stroke, Style } from "ol/style";
import type { FeatureLike } from "ol/Feature";
import type { LayerSpec } from "./layers";
import { attachSwipe } from "./swipe";
import { exportMapPng } from "./exportPng";
import { getToken } from "../../api/client";

export type RasterSpec = {
  id: string;
  title: string;
  visible: boolean;
  /** XYZ template. `{z}`, `{x}` and `{y}` are filled by OpenLayers. */
  url: string;
  bounds: [number, number, number, number];
};

type Props = {
  layers: LayerSpec[];
  rasters?: RasterSpec[];
  center?: [number, number];
  zoom?: number;
  fitToken?: string;
  notice?: string;
  compact?: boolean;
  sampleAt?: (lon: number, lat: number) => Promise<string[]>;
};

function loadAuthTile(tile: Tile, src: string) {
  if (!(tile instanceof ImageTile)) return;
  const image = tile.getImage();
  if (!(image instanceof HTMLImageElement)) return;
  const headers = new Headers();
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  fetch(src, { headers })
    .then((response) => (response.ok ? response.blob() : Promise.reject(new Error("tile"))))
    .then((blob) => {
      const url = URL.createObjectURL(blob);
      image.onload = () => URL.revokeObjectURL(url);
      image.src = url;
    })
    .catch(() => {
      image.src = "";
    });
}

function styleFor(spec: LayerSpec) {
  return (feature: FeatureLike) => {
    const affected = feature.get("affected");
    const muted = affected === false;
    const color = muted ? "#5c6b73" : spec.color;
    const fill = spec.fill !== false && !muted;
    const width = spec.strokeWidth ?? (spec.kind === "road" ? 3 : spec.fill === false ? 2 : 1.5);
    return new Style({
      fill: fill ? new Fill({ color: `${color}66` }) : undefined,
      stroke: new Stroke({
        color,
        width,
        lineDash: muted ? [5, 4] : undefined,
      }),
    });
  };
}

export function MapView({
  layers,
  rasters = [],
  center = [116.5, 39.85],
  zoom = 9,
  fitToken = "",
  notice,
  compact = false,
  sampleAt,
}: Props) {
  const host = useRef<HTMLDivElement>(null);
  const mapRef = useRef<Map | null>(null);
  const [swipe, setSwipe] = useState(false);
  const [ratio, setRatio] = useState(0.5);
  const [identify, setIdentify] = useState<Record<string, unknown> | null>(null);
  const ratioRef = useRef(ratio);
  const fittedToken = useRef("");
  const pendingFit = useRef<{ token: string; extent: Extent } | null>(null);
  const sampleRef = useRef(sampleAt);
  sampleRef.current = sampleAt;
  ratioRef.current = ratio;

  const fitPending = () => {
    const map = mapRef.current;
    const pending = pendingFit.current;
    if (!map || !pending) return false;
    if (fittedToken.current === pending.token) return true;
    map.updateSize();
    const size = map.getSize();
    if (!size || size[0] < 2 || size[1] < 2 || isEmpty(pending.extent)) return false;
    fittedToken.current = pending.token;
    map.getView().fit(pending.extent, { padding: [36, 36, 36, 36], maxZoom: 16, duration: 0 });
    return true;
  };

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
      const [lon, lat] = toLonLat(event.coordinate);
      const sample = sampleRef.current;
      if (!sample) {
        setIdentify(found);
        return;
      }
      sample(lon, lat)
        .then((titles) => {
          const next: Record<string, unknown> = { ...(found ?? {}) };
          if (titles.length) next["范围"] = titles.join("、");
          setIdentify(Object.keys(next).length ? next : null);
        })
        .catch(() => setIdentify(found));
    });
    mapRef.current = map;
    const observer = new ResizeObserver(() => {
      fitPending();
    });
    observer.observe(host.current);
    return () => {
      observer.disconnect();
      map.setTarget(undefined);
      mapRef.current = null;
    };
    // The view is created once. Later area changes refit from `fitToken`.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const existing = map.getLayers().getArray().slice(1);
    existing.forEach((layer) => map.removeLayer(layer));
    const format = new GeoJSON();
    const created: VectorLayer<VectorSource>[] = [];
    const rasterBounds: Array<[number, number, number, number]> = [];
    rasters
      .filter((spec) => spec.visible && spec.url)
      .forEach((spec) => {
        rasterBounds.push(spec.bounds);
        map.addLayer(
          new TileLayer({
            source: new XYZ({
              url: spec.url,
              wrapX: false,
              maxZoom: 19,
              tileLoadFunction: loadAuthTile,
            }),
            properties: { id: spec.id },
          }),
        );
      });
    const visible = layers.filter((spec) => spec.visible && spec.geojson);
    visible.forEach((spec) => {
      const source = new VectorSource({
        features: format.readFeatures(spec.geojson, {
          dataProjection: "EPSG:4326",
          featureProjection: "EPSG:3857",
        }),
      });
      const layer = new VectorLayer({
        source,
        style: styleFor(spec),
        properties: { id: spec.id },
      });
      map.addLayer(layer);
      created.push(layer);
    });
    if (fitToken && fitToken !== fittedToken.current && (created.length || rasterBounds.length)) {
      const productLayers = created.filter((_, index) => visible[index]?.kind !== "other");
      const extent = createEmpty();
      productLayers.forEach((layer) => extend(extent, layer.getSource()?.getExtent() ?? createEmpty()));
      rasterBounds.forEach((bounds) => extend(extent, transformExtent(bounds, "EPSG:4326", "EPSG:3857")));
      if (isEmpty(extent)) {
        created.forEach((layer) => extend(extent, layer.getSource()?.getExtent() ?? createEmpty()));
      }
      pendingFit.current = { token: fitToken, extent };
      fittedToken.current = "";
      fitPending();
    }
    const eventLayer = created.find((_, index) => visible[index]?.kind === "event");
    if (swipe && eventLayer) {
      return attachSwipe(map, eventLayer, () => ratioRef.current);
    }
    return undefined;
  }, [layers, rasters, swipe, ratio, fitToken]);

  return (
    <div className={compact ? "map-wrap compact" : "map-wrap"}>
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
      {notice && <div className="map-empty">{notice}</div>}
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
