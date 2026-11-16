
import type { FeatureCollection, LayerSpec } from "../features/map/layers";

export type SceneModule = {
  code: string;
  name: string;
  description: string;
  mapLayers: (aoi?: FeatureCollection) => LayerSpec[];
};

const modules = new Map<string, SceneModule>();

export function registerScene(mod: SceneModule): void {
  modules.set(mod.code, mod);
}

export function getScene(code: string): SceneModule | undefined {
  return modules.get(code);
}

export function listScenes(): SceneModule[] {
  return [...modules.values()];
}
