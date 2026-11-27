# SARAP

SARAP is a reusable SAR application platform. Phase 1 ships two things together:

1. A **platform skeleton** — organizations, projects, RBAC, catalog and versioned baseline library, scene registry, task center, product library with QC/publish, one-map, and briefings.
2. A **flood-emergency scene** plugged into that platform — Sentinel-1 IW GRD + SNAP, inundation extent, simple impact stats, and an emergency map. The target is hour-scale production after imagery is already staged. Fine water depth is **not** in scope.

Flood is a registered scene, not a hardcoded application. Pilot AOI and `analysis_crs` are configured per project (see `docs/specs/`), not baked in as a named basin.

GitHub 仓库：[https://github.com/baihaogeovis/sarap](https://github.com/baihaogeovis/sarap)。

说明文档：

- [功能说明](docs/features.md)
- [架构说明](docs/architecture.md)
- [TODO](docs/TODO.md)
- [部署说明](docs/deployment.md)
- 数据模型：[docs/data-model.md](docs/data-model.md)
- 引擎设计：[docs/engine-design.md](docs/engine-design.md)
- 洪水产品规范：[docs/specs/](docs/specs/)

## Layout

```
sarap/
  apps/api/             Python 3.12 FastAPI platform API (SQLAlchemy 2, Alembic, JWT)
  apps/web/             Vite + React + TypeScript + OpenLayers 10
  engine/               Independent processing engine (developed in parallel)
  packages/api-client/  OpenAPI-generated TypeScript types (`MapRasterOut` and the rest of the schema)
  docs/                 功能、架构、TODO、部署，以及数据模型和引擎约定
  docs/specs/           GIS v1 flood product spec, SNAP defaults, GPT template
  docker-compose.yml    Postgres 16 + PostGIS, Redis, MinIO, api, web
                        (engine service is behind --profile engine)
```

## Default local users

Seeded on API startup when `SARAP_SEED_ON_STARTUP=true` (the compose default). Change these before any shared deployment.

| Role           | Email                 | Password      |
|----------------|-----------------------|---------------|
| admin          | admin@sarap.local     | admin123      |
| duty_officer   | duty@sarap.local      | duty123       |
| readonly       | readonly@sarap.local  | readonly123   |

The seed also creates one organization (`demo-org`), one project (`demo-pilot` with a placeholder AOI you should replace), and activates the `flood` scene on that project. Demo analysis CRS is `EPSG:4548`; AOI geography is `EPSG:4490`. Algorithm profile: `s1_grd_flood_v1`.

V1 UI/API roles are only `admin`, `duty_officer`, and `readonly`. The data model already reserves `platform_admin`, `org_admin`, `project_admin`, `qc_reviewer`, `analyst`, and a separate `SERVICE` principal type for API accounts.

## Permissions (v1 surface)

- `admin` — manage org/project/members/scenes, run tasks, QC, publish and withdraw products, publish briefings.
- `duty_officer` — create and run tasks, draft products, submit to QC, **perform QC and publish products**, and draft briefings. The default briefing is visible once a product is published. Publishing the briefing record needs `briefing.publish`, which the seeded admin has. Cannot manage members, configure scenes, or withdraw a published product.
- `readonly` — published products and briefings, one-map, and task lists. Write actions are hidden or disabled with an explanation.

## Web workbench

Navigation: **工作台 / 任务 / 一张图 / 简报 / 资源 / 管理**.

Visual lock (deep navy workbench): canvas `#0F1A22`, primary `#0E4D6B`, accent `#C45C26`, water/success `#2A6F7A`.

## Run locally

中文步骤见 [部署说明](docs/deployment.md)。


Copy environment defaults and start dependencies:

```bash
cp .env.example .env
docker compose up -d postgres redis minio
```

Wait until Postgres is healthy, then either use compose for the apps or run them on the host.

### Option A — Compose for API and web

```bash
docker compose up --build api web
```

- Platform API: http://localhost:8000  (OpenAPI at `/docs`, raw schema at `/openapi.json`)
- Web: http://localhost:5173
- MinIO console: http://localhost:9001 (user/password from `.env.example`)

The first API start runs Alembic migrations and seeds the demo org, project, and users.

The engine is an internal service. The image runs in mock mode (no Sentinel-1 download, no platform table writes). Start it with the API:

```bash
docker compose --profile engine up --build
```

Engine control plane (internal): http://localhost:8081 (`/health`). A background worker drains the queue and posts draft products back to the platform. If `SARAP_ENGINE_MODE=snap` and `gpt` is missing, jobs fail with `GPT_NOT_FOUND` and do not fall back to mock.

To see 本次淹没 rather than extracted water, an administrator publishes a permanent-water baseline for the demo area with the raster URI left empty, then a duty officer creates a flood task that cites that published `baseline_version_id` and publishes the resulting draft. The default 一张图 and 简报 then show `flood_event` for that area: 6.75 ha of inundation, 17.75 ha of current water, one road (301 m), one settlement (0.79 ha), and two admin units (9.9 ha) on `fixture:public_validation_window`. A task that cites no baseline stays `flood_event_status=baseline_missing` (18.95 ha extracted water) and is not labeled 本次淹没. The default views use the latest published product only; draft, pending QC, and withdrawn products stay off both. Published flood, extracted-water, and baseline rasters are served as RGBA COGs and drawn as XYZ tiles, so zoom stays on the 10 m grid. The emergency-map button on 一张图 and 简报 downloads a one-page GeoPDF for that published product. The fixture is a compact 800 m open-water window inspired by the public Sen1Floods11 Mekong chips, stored as local metres, not a domestic labeled AOI and not the Sen1Floods11 rasters. See [部署说明](docs/deployment.md).

### Option B — Dependencies in Compose, apps on the host

Requires Python 3.12+ and Node 20+. Python 3.13 is fine for local use.

```bash
# API
cd apps/api
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
export SARAP_DATABASE_URL=postgresql+psycopg://sarap:sarap@localhost:5432/sarap
export SARAP_ENGINE_URL=http://localhost:8081
alembic upgrade head
uvicorn app.main:app --reload --port 8000

# Web
cd apps/web
npm install
npm run dev
```

The Vite dev server proxies `/api` to `http://localhost:8000`. If the engine is not running, creating a processing task fails with a clear “engine unavailable” error; catalog, RBAC, QC, and publish still work.

### Tests

```bash
# API (RBAC + product state machine)
cd apps/api && pip install -e ".[dev]" && pytest -q

# Web typecheck / build
cd apps/web && npm install && npm run typecheck && npm run build

# Engine tests, once that package is present
cd engine && pip install -e ".[dev]" && SARAP_ENGINE_MODE=mock pytest -q
```

## What v1 does not do

- No fine water-depth product, and no depth classes on the map or in APIs.
- No Sentinel-1 download inside the engine; imagery must already be staged.
- No Java / Spring service in this version. The data model is reviewed so a later gateway can sit in front of this API.
- 生产环境不要使用文档里的演示口令和默认密钥。
