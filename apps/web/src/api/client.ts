
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
  code: string;
  name: string;
  dataset_type: string;
  crs: string;
  status: string;
  source: string;
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
  engine_job_id: string;
  created_at: string;
};

export type Product = {
  id: string;
  project_id: string;
  scene_code: string;
  code: string;
  title: string;
  product_type: string;
  version: number;
  status: string;
  metadata_json: Record<string, unknown>;
  review_comment: string;
  withdraw_reason: string;
  published_at: string | null;
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
  areas: (projectId: string) => request<Area[]>(`/areas?project_id=${projectId}`),
  scenes: () => request<Scene[]>("/scenes"),
  activations: (projectId: string) => request<SceneActivation[]>(`/projects/${projectId}/scenes`),
  datasets: (projectId: string) => request<Dataset[]>(`/datasets?project_id=${projectId}`),
  baselines: (projectId: string) => request<Baseline[]>(`/baselines?project_id=${projectId}`),
  tasks: (projectId: string) => request<Task[]>(`/tasks?project_id=${projectId}`),
  task: (id: string) => request<Task>(`/tasks/${id}`),
  createTask: (body: Record<string, unknown>) =>
    request<Task>("/tasks", { method: "POST", body: JSON.stringify(body) }),
  retryTask: (id: string) => request<Task>(`/tasks/${id}/retry`, { method: "POST" }),
  cancelTask: (id: string) => request<Task>(`/tasks/${id}/cancel`, { method: "POST" }),
  products: (projectId: string) => request<Product[]>(`/products?project_id=${projectId}`),
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
  createBriefing: (body: Record<string, unknown>) =>
    request<Briefing>("/briefings", { method: "POST", body: JSON.stringify(body) }),
  publishBriefing: (id: string) => request<Briefing>(`/briefings/${id}/publish`, { method: "POST" }),
  members: (projectId: string) =>
    request<{ id: string; user_id: string; role_code: string }[]>(`/projects/${projectId}/members`),
};
