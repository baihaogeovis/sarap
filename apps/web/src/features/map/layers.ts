
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
  /** False draws an outline only, used for the area boundary. */
  fill?: boolean;
  geojson?: FeatureCollection;
};

export const COLORS = {
  water: "#2A6F7A",
  event: "#C45C26",
  baseline: "#4F8EA0",
  qc: "#C9A227",
  other: "#8AA0AC",
};

/** Mean lon/lat of a feature collection already in EPSG:4326. */
export function collectionCenter(collection: FeatureCollection | null | undefined): [number, number] | null {
  if (!collection?.features?.length) return null;
  const points: number[][] = [];
  const walk = (coords: unknown) => {
    if (!Array.isArray(coords)) return;
    if (typeof coords[0] === "number" && typeof coords[1] === "number") {
      points.push([coords[0], coords[1]]);
      return;
    }
    coords.forEach(walk);
  };
  collection.features.forEach((feature) => walk(feature.geometry?.coordinates));
  if (!points.length) return null;
  const lon = points.reduce((sum, pair) => sum + pair[0], 0) / points.length;
  const lat = points.reduce((sum, pair) => sum + pair[1], 0) / points.length;
  if (!Number.isFinite(lon) || !Number.isFinite(lat)) return null;
  if (Math.abs(lon) > 180 || Math.abs(lat) > 90) return null;
  return [lon, lat];
}

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
