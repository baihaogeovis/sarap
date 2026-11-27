import { useMemo } from "react";
import type { BriefingDocument, MapLayerKind } from "../../api/client";
import { MapView } from "../map/MapView";
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

export function BriefingSheet({ document }: { document: BriefingDocument }) {
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
  }, [document]);

  const center = useMemo<[number, number]>(() => {
    const focus =
      document.layers.find((layer) => layer.kind === "event" || layer.kind === "water") ?? document.layers[0];
    return (
      collectionCenter((focus?.geojson ?? null) as FeatureCollection | null) ??
      collectionCenter((document.area.aoi ?? null) as FeatureCollection | null) ??
      [0, 20]
    );
  }, [document]);

  const stats = document.stats;
  const fitToken = `${document.product?.id ?? "empty"}:${layers.map((layer) => layer.id).join(",")}`;

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
        center={center}
        zoom={15}
        fitToken={fitToken}
        compact
        notice={document.empty ? document.notice : ""}
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
      <ul className="sheet-notes">
        {document.footnotes.map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>
    </article>
  );
}
