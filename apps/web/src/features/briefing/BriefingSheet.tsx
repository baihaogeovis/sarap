import { useMemo, useState } from "react";
import { api, apiBase, type BriefingDocument, type MapLayerKind, type MapRasterLayer } from "../../api/client";
import { MapView, type RasterSpec } from "../map/MapView";
import { COLORS, collectionCenter, type FeatureCollection, type LayerSpec } from "../map/layers";

function colorFor(kind: MapLayerKind): string {
  if (kind === "event") return COLORS.event;
  if (kind === "baseline") return COLORS.baseline;
  if (kind === "admin") return COLORS.admin;
  if (kind === "road") return COLORS.road;
  if (kind === "settlement") return COLORS.settlement;
  if (kind === "cropland") return COLORS.cropland;
  if (kind === "water") return COLORS.water;
  return COLORS.other;
}

function formatHa(value: number | null | undefined): string {
  if (value == null || Number.isNaN(Number(value))) return "—";
  return `${value} ha`;
}

function rasterBounds(raster: MapRasterLayer): [number, number, number, number] | null {
  const [minx, miny, maxx, maxy] = raster.bounds ?? [];
  if (![minx, miny, maxx, maxy].every((value) => Number.isFinite(value))) return null;
  if (Math.abs(minx) > 180 || Math.abs(maxx) > 180 || Math.abs(miny) > 90 || Math.abs(maxy) > 90) return null;
  return [minx, miny, maxx, maxy];
}

export function BriefingSheet({ document }: { document: BriefingDocument }) {
  const [downloadError, setDownloadError] = useState("");
  const rasterKinds = useMemo(() => new Set((document.rasters ?? []).map((raster) => raster.kind)), [document]);
  const rasters = useMemo<RasterSpec[]>(() => {
    return (document.rasters ?? []).flatMap((raster) => {
      const bounds = rasterBounds(raster);
      if (!bounds) return [];
      return [
        {
          id: `raster:${raster.layer_key}`,
          title: raster.title,
          visible: true,
          url: `${apiBase()}${raster.tile_template}`,
          bounds,
        },
      ];
    });
  }, [document]);
  const layers = useMemo<LayerSpec[]>(() => {
    const specs: LayerSpec[] = [];
    if (document.area.aoi?.features?.length) {
      specs.push({
        id: "area-aoi",
        title: "区域范围",
        kind: "other",
        color: COLORS.other,
        visible: true,
        fill: false,
        geojson: document.area.aoi as FeatureCollection,
      });
    }
    for (const layer of document.layers) {
      if (rasterKinds.has(layer.kind) && (layer.kind === "water" || layer.kind === "event" || layer.kind === "baseline")) {
        continue;
      }
      specs.push({
        id: `${layer.layer_key}:${layer.kind}`,
        title: layer.title,
        kind: layer.kind,
        color: colorFor(layer.kind),
        visible: true,
        fill: layer.fill !== false && layer.kind !== "admin" && layer.kind !== "road",
        strokeWidth: layer.kind === "road" ? 3 : undefined,
        geojson: layer.geojson as FeatureCollection,
      });
    }
    return specs;
  }, [document, rasterKinds]);

  const center = useMemo<[number, number]>(() => {
    const raster = (document.rasters ?? []).map(rasterBounds).find((bounds) => bounds != null);
    if (raster) return [(raster[0] + raster[2]) / 2, (raster[1] + raster[3]) / 2];
    const focus =
      document.layers.find((layer) => layer.kind === "event" || layer.kind === "water") ?? document.layers[0];
    return (
      collectionCenter((focus?.geojson ?? null) as FeatureCollection | null) ??
      collectionCenter((document.area.aoi ?? null) as FeatureCollection | null) ??
      [0, 20]
    );
  }, [document]);

  const stats = document.stats;
  const fitToken = `${document.product?.id ?? "empty"}:${layers.map((layer) => layer.id).join(",")}:${rasters.map((raster) => raster.id).join(",")}`;

  return (
    <article className="briefing-sheet">
      <p className="sheet-kicker">SARAP · 应急简报</p>
      <h3>{document.title}</h3>
      <p className="sheet-meta">
        {document.area.name || "未选区域"}
        {document.area.analysis_crs ? ` · 分析坐标系 ${document.area.analysis_crs}` : ""}
        {document.product ? ` · ${document.product.title} · v${document.product.version}` : ""}
        {document.product?.acquisition_start ? ` · 成像 ${document.product.acquisition_start}` : ""}
        {document.basis_label ? ` · ${document.basis_label}` : ""}
        {document.product?.baseline_version ? ` · 本底 ${document.product.baseline_version}` : ""}
      </p>
      <MapView
        layers={layers}
        rasters={rasters}
        center={center}
        zoom={15}
        fitToken={fitToken}
        compact
        notice={document.empty ? document.notice : ""}
        sampleAt={
          document.product
            ? async (lon, lat) => {
                const found = await api.identify(document.product?.id || "", lon, lat);
                return found.hits.map((hit) => hit.title);
              }
            : undefined
        }
      />
      <div className="sheet-stats">
        <div>
          <span>{stats.inundation_label || "范围面积"}</span>
          <strong>{formatHa(stats.inundation_ha)}</strong>
        </div>
        {document.flood_event_status === "computed" && (
          <div>
            <span>当期水体</span>
            <strong>{formatHa(stats.water_current_ha)}</strong>
          </div>
        )}
        {stats.impact_configured && (
          <>
            <div>
              <span>受影响道路</span>
              <strong>
                {stats.affected_road_count ?? 0} 条 / {stats.affected_road_length_m ?? 0} m
              </strong>
            </div>
            <div>
              <span>受影响居民点</span>
              <strong>
                {stats.affected_settlement_count ?? 0} 个 / {formatHa(stats.affected_settlement_area_ha)}
              </strong>
            </div>
            <div>
              <span>受影响行政区</span>
              <strong>
                {stats.affected_admin_count ?? 0} 个 / {formatHa(stats.affected_admin_area_ha)}
              </strong>
            </div>
          </>
        )}
      </div>
      <div className="briefing-conclusion">
        <strong>结论</strong>
        <p>{document.conclusion}</p>
      </div>
      {document.omitted_product_ids.length > 0 && (
        <p className="sheet-note">有引用产品未发布或已撤回，未画入本简报。</p>
      )}
      <p className="sheet-note">{document.source_note}</p>
      {document.geopdf_path && (
        <button
          className="btn"
          type="button"
          onClick={() => {
            setDownloadError("");
            api.download(document.geopdf_path || "", "emergency-map.pdf").catch(() => setDownloadError("GeoPDF 下载失败"));
          }}
        >
          下载 GeoPDF
        </button>
      )}
      {downloadError && <p className="error">{downloadError}</p>}
      <ul className="sheet-notes">
        {document.footnotes.map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>
    </article>
  );
}
