
export type Envelope<T> = {
  data: T;
  error: { code: string; message: string; details?: unknown } | null;
  meta: Record<string, unknown>;
};

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

const TOKEN_KEY = "sarap.access_token";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string | null): void {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

export function apiBase(): string {
  return import.meta.env.VITE_API_BASE_URL ?? "/api/v1";
}

export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (!headers.has("Content-Type") && init.body) {
    headers.set("Content-Type", "application/json");
  }
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(`${apiBase()}${path}`, { ...init, headers });
  const body = (await response.json()) as Envelope<T>;
  if (!response.ok || body.error) {
    throw new ApiError(
      response.status,
      body.error?.code ?? "http_error",
      body.error?.message ?? response.statusText,
    );
  }
  return body.data;
}

export type User = {
  id: string;
  email: string;
  name: string;
  status: string;
  roles: string[];
  permissions: string[];
  org_id: string | null;
};

export type Project = {
  id: string;
  org_id: string;
  code: string;
  name: string;
  status: string;
  default_crs: string;
  bbox_json: { crs?: string; minx: number; miny: number; maxx: number; maxy: number } | null;
  aoi_wkt: string | null;
};

export type Area = {
  id: string;
  project_id: string;
  code: string;
  name: string;
  is_pilot: boolean;
  analysis_crs: string;
  exchange_crs: string;
  grid_res_m: number;
  grid_origin_x: number;
  grid_origin_y: number;
  aoi_geojson: Record<string, unknown> | null;
  bbox_json: Project["bbox_json"];
  config_json: Record<string, unknown>;
};

export type Scene = {
  id: string;
  code: string;
  name: string;
  description: string;
  version: string;
  status: string;
  manifest_json: Record<string, unknown>;
};

export type SceneActivation = {
  id: string;
  project_id: string;
  scene_id: string;
  status: string;
  config_json: Record<string, unknown>;
};

export type Dataset = {
  id: string;
  project_id: string | null;
  code: string;
  name: string;
  dataset_type: string;
  crs: string;
  status: string;
  source: string;
  storage_uri: string;
  s1_product_id: string;
  time_start: string | null;
  time_end: string | null;
};

export type Baseline = {
  id: string;
  code: string;
  name: string;
  category: string;
  version: string;
  review_status: string;
  applicable_area_name: string;
};

export type Task = {
  id: string;
  project_id: string;
  area_id: string | null;
  scene_code: string;
  code: string;
  title: string;
  task_type: string;
  status: string;
  priority: string;
  emergency: boolean;
  progress: number;
  step: string;
  error_message: string;
  error_code: string;
  engine_job_id: string;
  s1_product_id: string;
  baseline_version_id: string | null;
  created_at: string;
};

export type Product = {
  id: string;
  project_id: string;
  task_id: string | null;
  scene_code: string;
  code: string;
  title: string;
  product_type: string;
  version: number;
  status: string;
  flood_event_status: string;
  extracted_water_ha: number | null;
  water_current_ha: number | null;
  flood_event_ha: number | null;
  s1_product_id: string;
  metadata_json: Record<string, unknown>;
  review_comment: string;
  withdraw_reason: string;
  published_at: string | null;
};

export type DataAssetVersion = {
  id: string;
  asset_id: string;
  version_no: string;
  review_status: string;
  storage_uri: string;
  crs: string;
  applicable_area_name: string;
  valid_from: string | null;
  valid_to: string | null;
};

export type DataAsset = {
  id: string;
  project_id: string | null;
  area_id: string | null;
  asset_code: string;
  name: string;
  asset_type: string;
  default_crs: string;
  versions?: DataAssetVersion[];
};

export type MapGeoJson = {
  type: "FeatureCollection";
  features: {
    type: "Feature";
    properties: Record<string, unknown>;
    geometry: { type: string; coordinates: unknown };
  }[];
};

export type MapLayerKind = "water" | "event" | "baseline" | "qc" | "admin" | "road" | "settlement" | "cropland" | "other";

export type ImpactSummary = {
  impact_configured?: boolean;
  scope?: string;
  affected_road_count?: number;
  affected_road_length_m?: number;
  affected_settlement_count?: number;
  affected_settlement_area_ha?: number;
  affected_admin_count?: number;
  affected_admin_area_ha?: number;
};

export type MapProductLayer = {
  layer_key: string;
  title: string;
  kind: MapLayerKind;
  fill?: boolean;
  geojson: MapGeoJson;
};

export type MapPayload = {
  area: {
    id: string;
    name: string;
    analysis_crs: string;
    exchange_crs: string;
    aoi: MapGeoJson | null;
  };
  products: {
    id: string;
    title: string;
    status: string;
    flood_event_status: string;
    baseline_version?: string;
    baseline_version_id?: string | null;
    version: number;
    scene_code: string;
    extracted_water_ha?: number | null;
    water_current_ha?: number | null;
    flood_event_ha?: number | null;
    acquisition_start?: string | null;
    s1_product_id?: string;
    layers: MapProductLayer[];
    impact?: ImpactSummary;
    impact_including_lowconf?: ImpactSummary;
    emergency_map?: Record<string, unknown> | null;
  }[];
};

export type BriefingDocument = {
  title: string;
  status: string;
  briefing_id: string | null;
  empty: boolean;
  notice: string;
  summary: string;
  conclusion: string;
  basis_label: string;
  flood_event_status: string | null;
  product: {
    id: string;
    title: string;
    version: number;
    status: string;
    published_at: string | null;
    acquisition_start: string | null;
    s1_product_id: string;
    baseline_version?: string;
    baseline_version_id?: string | null;
  } | null;
  omitted_product_ids: string[];
  stats: ImpactSummary & {
    inundation_ha?: number | null;
    inundation_label?: string;
    water_current_ha?: number | null;
    extracted_water_ha?: number | null;
    flood_event_ha?: number | null;
    including_lowconf?: ImpactSummary;
  };
  limitation: string;
  footnotes: string[];
  area: {
    id: string | null;
    name: string;
    analysis_crs: string;
    aoi: MapGeoJson | null;
  };
  layers: MapProductLayer[];
  emergency_map: Record<string, unknown> | null;
  source_note: string;
};

export type Briefing = {
  id: string;
  project_id: string;
  scene_code: string;
  code: string;
  title: string;
  status: string;
  content_json: Record<string, unknown>;
  product_ids: string[];
  published_at: string | null;
};

export const api = {
  login: (email: string, password: string) =>
    request<{ tokens: { access_token: string; refresh_token: string }; user: User }>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),
  me: () => request<User>("/auth/me"),
  projects: () => request<Project[]>("/projects"),
  areas: (projectId: string) => request<Area[]>(`/projects/${projectId}/areas`),
  scenes: () => request<Scene[]>("/scenes"),
  activations: (projectId: string) => request<SceneActivation[]>(`/projects/${projectId}/scenes`),
  datasets: (projectId: string) => request<Dataset[]>(`/datasets?project_id=${projectId}`),
  createDataset: (body: Record<string, unknown>) =>
    request<Dataset>("/datasets", { method: "POST", body: JSON.stringify(body) }),
  baselines: (projectId: string) => request<Baseline[]>(`/baselines?project_id=${projectId}`),
  dataAssets: (projectId: string, reviewStatus?: string) => {
    const query = new URLSearchParams({ project_id: projectId });
    if (reviewStatus) query.set("review_status", reviewStatus);
    return request<DataAsset[]>(`/data-assets?${query}`);
  },
  createDataAsset: (body: Record<string, unknown>) =>
    request<DataAsset>("/data-assets", { method: "POST", body: JSON.stringify(body) }),
  createDataAssetVersion: (assetId: string, body: Record<string, unknown>) =>
    request<DataAssetVersion>(`/data-assets/${assetId}/versions`, { method: "POST", body: JSON.stringify(body) }),
  publishDataAssetVersion: (versionId: string) =>
    request<DataAssetVersion>(`/data-asset-versions/${versionId}/publish`, {
      method: "POST",
      body: JSON.stringify({ comment: "发布供处理任务引用" }),
    }),
  tasks: (projectId: string) => request<Task[]>(`/tasks?project_id=${projectId}`),
  task: (id: string) => request<Task>(`/tasks/${id}`),
  createTask: (body: Record<string, unknown>) =>
    request<Task>("/tasks", { method: "POST", body: JSON.stringify(body) }),
  retryTask: (id: string) => request<Task>(`/tasks/${id}/retry`, { method: "POST" }),
  cancelTask: (id: string) => request<Task>(`/tasks/${id}/cancel`, { method: "POST" }),
  products: (projectId: string, taskId?: string) => {
    const query = new URLSearchParams({ project_id: projectId });
    if (taskId) query.set("task_id", taskId);
    return request<Product[]>(`/products?${query}`);
  },
  mapLayers: (areaId: string, projectId?: string, sceneCode?: string) => {
    const query = new URLSearchParams({ area_id: areaId });
    if (projectId) query.set("project_id", projectId);
    if (sceneCode) query.set("scene_code", sceneCode);
    return request<MapPayload>(`/products/map?${query}`);
  },
  layerGeojson: (productId: string, layerKey: string) =>
    request<MapGeoJson>(`/products/${productId}/layers/${layerKey}`),
  product: (id: string) => request<Product>(`/products/${id}`),
  submitProduct: (id: string) => request<Product>(`/products/${id}/submit`, { method: "POST", body: "{}" }),
  rejectProduct: (id: string, comment: string) =>
    request<Product>(`/products/${id}/reject`, { method: "POST", body: JSON.stringify({ comment }) }),
  publishProduct: (id: string, comment = "") =>
    request<Product>(`/products/${id}/publish`, { method: "POST", body: JSON.stringify({ comment }) }),
  withdrawProduct: (id: string, reason: string) =>
    request<Product>(`/products/${id}/withdraw`, { method: "POST", body: JSON.stringify({ reason }) }),
  briefings: (projectId: string) => request<Briefing[]>(`/briefings?project_id=${projectId}`),
  briefing: (id: string) => request<Briefing>(`/briefings/${id}`),
  briefingPreview: (projectId: string, areaId: string, sceneCode?: string) => {
    const query = new URLSearchParams({ project_id: projectId, area_id: areaId });
    if (sceneCode) query.set("scene_code", sceneCode);
    return request<BriefingDocument>(`/briefings/preview?${query}`);
  },
  briefingDocument: (id: string) => request<BriefingDocument>(`/briefings/${id}/document`),
  createBriefing: (body: Record<string, unknown>) =>
    request<Briefing>("/briefings", { method: "POST", body: JSON.stringify(body) }),
  publishBriefing: (id: string) => request<Briefing>(`/briefings/${id}/publish`, { method: "POST" }),
  members: (projectId: string) =>
    request<{ id: string; user_id: string; role_code: string }[]>(`/projects/${projectId}/members`),
};
