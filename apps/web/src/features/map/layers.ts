
export type GeoFeature = {
  type: "Feature";
  properties: Record<string, unknown>;
  geometry: { type: string; coordinates: unknown };
};

export type FeatureCollection = {
  type: "FeatureCollection";
  features: GeoFeature[];
};

export type LayerSpec = {
  id: string;
  title: string;
  kind: "water" | "event" | "baseline" | "qc" | "other";
  color: string;
  visible: boolean;
  geojson?: FeatureCollection;
};

export const COLORS = {
  water: "#2A6F7A",
  event: "#C45C26",
  baseline: "#4F8EA0",
  qc: "#C9A227",
  other: "#8AA0AC",
};

/** Build a rectangle feature from a project/area bbox. Not a named basin. */
export function bboxPolygon(bbox: { minx: number; miny: number; maxx: number; maxy: number }): GeoFeature {
  const { minx, miny, maxx, maxy } = bbox;
  return {
    type: "Feature",
    properties: { name: "试点区", class_code: 0 },
    geometry: {
      type: "Polygon",
      coordinates: [[[minx, miny], [maxx, miny], [maxx, maxy], [minx, maxy], [minx, miny]]],
    },
  };
}
