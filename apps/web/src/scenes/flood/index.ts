
import { COLORS, type FeatureCollection, type LayerSpec } from "../../features/map/layers";
import { registerScene } from "../registry";

/**
 * Flood is a registered scene package. Official class codes:
 * 0 nodata, 1 non_water, 2 permanent_or_baseline_water, 3 flood_event, 4 water_lowconf.
 * No water-depth layer is registered.
 */
function inset(collection: FeatureCollection | undefined, dx: number, dy: number): FeatureCollection | undefined {
  if (!collection) return undefined;
  const shift = (coords: unknown): unknown => {
    if (typeof coords === "number") return coords;
    if (Array.isArray(coords) && typeof coords[0] === "number") {
      return [Number(coords[0]) + dx, Number(coords[1]) + dy];
    }
    if (Array.isArray(coords)) return coords.map(shift);
    return coords;
  };
  return {
    type: "FeatureCollection",
    features: collection.features.map((feature) => ({
      ...feature,
      geometry: { ...feature.geometry, coordinates: shift(feature.geometry.coordinates) },
      properties: { ...feature.properties },
    })),
  };
}

export const floodScene = {
  code: "flood",
  name: "洪水应急",
  description: "Sentinel-1 IW GRD 淹没范围。第一版不提供水深。",
  mapLayers(aoi?: FeatureCollection): LayerSpec[] {
    const baseline = inset(aoi, 0, 0);
    if (baseline) {
      baseline.features = baseline.features.map((f) => ({
        ...f,
        properties: { ...f.properties, name: "本底水体", class_code: 2, class_name: "permanent_or_baseline_water" },
      }));
    }
    const event = inset(aoi, 0.04, 0.02);
    if (event) {
      event.features = event.features.map((f) => ({
        ...f,
        properties: { ...f.properties, name: "本次淹没", class_code: 3, class_name: "flood_event" },
      }));
    }
    return [
      { id: "flood-baseline", title: "本底水体", kind: "baseline", color: COLORS.water, visible: true, geojson: baseline },
      { id: "flood-event", title: "本次淹没", kind: "event", color: COLORS.event, visible: true, geojson: event },
      { id: "flood-lowconf", title: "低置信水体", kind: "qc", color: COLORS.qc, visible: false, geojson: aoi },
    ];
  },
};

registerScene(floodScene);
