# SARAP 架构说明（第一版）

本文说明第一版怎么拆、各层怎么协作。更细的表结构和权限码见 [data-model.md](data-model.md)，引擎内部约定见 [engine-design.md](engine-design.md)，洪水产品规范见 [docs/specs/](specs/)。功能清单见 [功能说明](features.md)。

## 总体结构

```
浏览器（React + OpenLayers 10）
  作业台壳：RBAC、一张图、导航
  场景包（flood，…）注册到壳上，而不是写死成唯一应用
        │  /api/v1  JWT
平台 API（apps/api，FastAPI）
  认证与权限、编目与本底、场景开通、任务中心、产品库、简报、审计、内部入库
        │                         │ 内部 HTTP + 共享令牌
 Postgres + PostGIS               引擎（engine/）
 Redis                            控制面 + 工人
 MinIO                            不写平台业务表
```

引擎是同一仓库里的独立 Python 包。平台只通过内部接口调度（创建作业、查状态、取消、提升优先级），产物由引擎回调 `POST /api/v1/internal/products` 入库。引擎不可达时，任务派发必须明确失败，不能假装已经开始。第一版假定影像已经在平台就绪，平台和引擎都不负责下载 Sentinel-1。

## 技术选型（已锁定）

- 平台 API：Python 3.12、FastAPI、SQLAlchemy 2、Alembic、JWT；对外路径前缀 `/api/v1`，响应信封为 `{data, error, meta}`。
- 前端：TypeScript、React、Vite、OpenLayers 10（不用 Leaflet）。
- 引擎：Python；Sentinel-1 IW GRD 走 SNAP GPT 图，另有可文档化的 mock 模式。官方模板在 `docs/specs/s1_grd_flood_v1.xml.j2` 与 `s1_grd_flood_v1.defaults.json`。
- 数据：PostgreSQL 16 + PostGIS、Redis、S3 兼容对象存储（本地用 MinIO）。
- 第一版不起 Java / Spring 进程。OpenAPI、JWT 声明和路径保持稳定，方便以后加网关。

## 租户与认证

业务表都带 `org_id`，即使第一版通常是单租户部署。业务唯一键是 `(org_id, code)`。`org_id` 只从登录身份取，请求体不能作为租户来源。

JWT 访问令牌包含 `sub`、`typ`（`user` 或 `service`）、`org_id`、`roles`、`permissions`、`jti`。服务账号是独立的 `SERVICE` 主体，不是用户表上的一个开关。

第一版 API 和界面只露出 `admin`、`duty_officer`、`readonly`。RBAC 表已预留更完整角色和权限码。值班员可以质检并发布；不能管成员、不能配置场景；撤回已发布产品第一版仅管理员可做。

## 场景模型

`Scene` 是带清单的已注册应用（任务类型、产品类型、简报模板、推荐本底、参数 schema）。项目「开通」场景后，试点 AOI 和场景配置放在 `SceneActivation.config_json`。洪水场景会随演示库开通到 `demo-pilot`。AOI 与 `analysis_crs` 可配置，不写死流域名。

试点配置对齐规范第 12 节：地理范围示例用 `EPSG:4490`；官方栅格/矢量用各试点的 `analysis_crs`（国内试点优先 CGCS2000 3° 高斯克吕格，演示为 `EPSG:4548`）；交换/预览可用 `EPSG:4490` 或 `EPSG:4326`；Web Mercator 只用于显示瓦片，绝不用作分析原数据；网格 10 m，原点写在试点配置里；算法配置档为 `s1_grd_flood_v1`。

产品和任务用通用表，用 `scene_id` / `scene_code` 加 `metadata_json` 承载场景字段，不把洪水字段做成这些表的一级列。没有水深产品类型。

## 任务与产品流

1. 有权限的用户在已开通场景上创建任务。
2. 平台记录任务，并在配置了引擎地址时调用引擎内部接口。
3. 引擎跑官方 SNAP 链，或文档化的 mock 通路。
4. 成功后引擎把产物送到平台入库接口，产品进入 `draft`。
5. 值班员或管理员可将产品提交质检（`pending_qc`），打回 `draft`（须填原因），或发布为 `published`。已发布记录不可原地改写：由管理员撤回（`withdrawn`）后，再发布必须出新版本并重新质检。状态迁移都要留审计。

需求说明、界面主路径和里程碑把「简单质检通过后再进入默认一张图和简报」写进了第一版；GIS 规范 v1.1.1 另有「处理成功后可最短发布、完整打回放后续」的表述。当前 API 实现仍保留了从 `draft` 直接发布的路径。这一条还没有由产品负责人最终钉死，后续只改状态机和测试，不在本次导入里擅自改代码。

失败或未发布任务可按原参数重跑：相同幂等键返回已有任务/产品；`force_rerun` 升版本并保留旧产品，已发布成果不得被重跑静默覆盖，失败现场要保留。区域停用或场景关闭后禁止新建任务，进行中的任务可以跑完并继续质检发布，历史和已发布成果仍可查看。

## 一张图与简报

地图在 `features/map`（底图、叠加、卷帘/对比桩、点击识别、PNG 导出桩）。场景包如 `scenes/flood` 向壳注册图层。本底/当期水体用 `#2A6F7A`，事件淹没用 `#C45C26`。简报是可引用已发布产品的结构化 JSON 文档。默认一张图和对外简报应只展示已发布、且对当前角色可见的产品。

## 第一版不做

- 精细水深和水深分级。
- 引擎侧 Sentinel-1 检索与下载。
- 再起一套 Java 后端。
- 把 `qc_reviewer` 拆到第一版登录界面（权限码已预留；第一版由值班员和管理员做质检）。

以下为英文详细稿，与上文一致，并补充了若干实现注释。

# SARAP architecture (phase 1)

## Purpose

SARAP is a platform for SAR monitoring scenes. Phase 1 delivers a reusable platform skeleton and a flood-emergency scene on top of it. Later scenes (subsidence, and others) should register into the same organization, project, catalog, task, product, map, and permission model rather than becoming a second system.

Flood product rules, SNAP defaults, and the official GPT template are in `docs/specs/` (copied from the GIS v1 specification). Do not invent a competing CRS, class map, or processing order.

## Building blocks

```
                    ┌─────────────────────────────────────────────┐
  Browser (React    │  App shell + RBAC guards + one-map           │
  + OpenLayers 10)  │  Nav: 工作台 / 任务 / 一张图 / 简报 / 资源 / 管理
                    │  Registered scene packages (flood, …)        │
                    └──────────────────┬──────────────────────────┘
                                       │  /api/v1  (JWT)
                    ┌──────────────────▼──────────────────────────┐
                    │  Platform API  (apps/api, FastAPI)           │
                    │  Auth, RBAC, catalog, baselines, scenes,     │
                    │  task center, product library, briefings,    │
                    │  audit, internal ingest                      │
                    └──────────┬───────────────────┬──────────────┘
                               │                   │
                    Postgres   │                   │  internal HTTP
                    + PostGIS  │                   │  + shared token
                    Redis      │                   │
                    MinIO      │                   │
                               │         ┌─────────▼──────────────┐
                               │         │  Engine (engine/)      │
                               │         │  Control plane + worker│
                               │         │  Developed in parallel │
                               │         │  No platform table I/O │
                               │         └────────────────────────┘
```

The engine is an independent Python package in the same monorepo and is being written separately under `engine/`. The platform talks to it only through a thin internal HTTP client (`POST /internal/engine/jobs`, status, cancel, priority bump) and receives artifacts at `POST /api/v1/internal/products`. The engine never writes organization, project, task, or product rows. If the engine is unreachable, dispatch fails with a clear error; the platform does not pretend the job started. Imagery is assumed already staged; neither layer downloads Sentinel-1 in v1.

## Locked technology choices

- Platform API: Python 3.12, FastAPI, SQLAlchemy 2, Alembic, JWT.
- Frontend: TypeScript, React, Vite, OpenLayers 10 (not Leaflet). Workbench visual: deep navy canvas `#0F1A22`, primary `#0E4D6B`, accent `#C45C26`, water/success `#2A6F7A`.
- Engine: Python, SNAP GPT graphs for Sentinel-1 IW GRD, optional mock mode. Official template: `docs/specs/s1_grd_flood_v1.xml.j2` and `s1_grd_flood_v1.defaults.json`.
- Datastore: PostgreSQL 16 + PostGIS, Redis, S3-compatible object storage (MinIO locally).
- No Java/Spring process in v1. Contracts (OpenAPI, JWT claims, `/api/v1` paths) are kept stable so a later gateway can sit in front.

## Tenancy and auth

Every business table carries `org_id`, even though v1 is typically a single-tenant deployment. Unique business keys are `(org_id, code)`. `org_id` is taken only from the authenticated principal; request bodies are not a trusted source of tenancy.

JWT access-token claims include `sub`, `typ` (`user` or `service`), `org_id`, `roles`, `permissions`, and `jti`. Service accounts are a separate `SERVICE` principal, not a flag on the user table.

V1 exposes three roles in the API and UI: `admin`, `duty_officer`, `readonly`. The RBAC tables already hold the fuller set (`platform_admin`, `org_admin`, `project_admin`, `qc_reviewer`, `analyst`) and permission codes so those roles can be enabled later without a model rewrite.

V1 grants that differ from an earlier draft: a **duty officer can QC and publish**. Duty officers still cannot manage members or activate scenes. Withdrawal of a published product remains an `admin` action in v1.

## Scene model

A `Scene` is a registered application with a manifest (task types, product types, briefing template, recommended baselines, and parameter schema). A project *activates* a scene and stores scene-specific configuration, including the pilot AOI, in `SceneActivation.config_json`. The flood scene is seeded and activated on the demo project. The AOI and `analysis_crs` are configurable and are not hardcoded to a named basin.

Pilot configuration follows `docs/specs/SARAP-v1-flood-product-spec.md` section 12:

- AOI geography: `EPSG:4490` (example)
- Analysis and official rasters/vectors: per-pilot `analysis_crs` (China pilots prefer a CGCS2000 3° Gauss-Kruger zone, e.g. `EPSG:4548` in the demo seed)
- Exchange/preview copies may use `EPSG:4490` or `EPSG:4326`
- Web Mercator is display tiles only, never the analysis original
- Grid: 10 m, origin locked in the pilot config
- Algorithm profile: `s1_grd_flood_v1`

Generic product and task tables store `scene_id` / `scene_code` plus `metadata_json`. Flood-specific attributes never become first-class columns on those tables. There is no water-depth product type.

## Task and product flow

1. An authorized user creates a task against an activated scene.
2. The platform records the task and calls the engine internal API when an engine URL is configured.
3. The engine runs the official SNAP chain (see `docs/engine-design.md`) or a documented mock path.
4. On success the engine posts artifacts to the platform ingest endpoint. Products enter `draft`.
5. `duty_officer` or `admin` may submit to QC (`pending_qc`), reject back to `draft`, or publish (`published`). A published row is never edited in place: `admin` withdraws it, then a new version is created. Every transition is audited.

## One-map and briefings

The web map lives in `features/map` (base map, overlay layers, swipe/compare, click identify, PNG export stub). Scene packages such as `scenes/flood` register their layers with the shell; the shell does not treat flood as the only application. Flood layer styling should use water `#2A6F7A` for baseline/current water and accent `#C45C26` for event inundation (not a red/green-only pair). Briefings are structured JSON documents that can reference published products.

## Out of scope for phase 1

- Fine water depth and depth classification.
- Engine-side Sentinel-1 search and download.
- A second (Java) backend.
- Splitting `qc_reviewer` onto the v1 login surface (the permission is reserved; duty officers and admins perform QC in v1).
