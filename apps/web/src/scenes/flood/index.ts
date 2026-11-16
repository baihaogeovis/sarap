import type { FeatureCollection, LayerSpec } from "../../features/map/layers";
import { registerScene } from "../registry";

/**
 * Flood is a registered scene package. The one-map loads published product
 * vectors from the platform; this module no longer synthesizes an extent.
 * Official class codes: 0 nodata, 1 non_water, 2 permanent_or_baseline_water,
 * 3 flood_event, 4 water_lowconf. No water-depth layer is registered.
 */
export const floodScene = {
  code: "flood",
  name: "洪水应急",
  description: "Sentinel-1 IW GRD 淹没范围。第一版不提供水深。",
  mapLayers(_aoi?: FeatureCollection): LayerSpec[] {
    return [];
  },
};

registerScene(floodScene);
