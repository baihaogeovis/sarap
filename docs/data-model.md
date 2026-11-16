# SARAP data model (phase 1)

All identifiers are UUIDs. Common columns: `id`, `created_at`, `updated_at`, and a soft-delete `deleted_at` where noted. Business tables include `org_id`. Unique business codes are scoped as `(org_id, code)`.

`org_id` is always taken from the authentication context, never from a trusted client-supplied body field.

Baseline types, review states, flood class codes, and pilot-config keys follow `docs/specs/SARAP-v1-flood-product-spec.md`. Do not invent a parallel vocabulary.

## Identity

| Entity | Notes |
|--------|--------|
| `Organization` | `code` (slug) is globally unique. Status `active` / `disabled`. |
| `Project` | Belongs to an org. `code` unique per org. `default_crs` is the analysis CRS (demo seed uses `EPSG:4548`). `bbox_json` stores a project-level AOI as `{crs,minx,miny,maxx,maxy}` (AOI geography example: `EPSG:4490`), plus optional WKT. |
| `Area` | The primary spatial object under a project (unique `(org_id, code)`). Holds `analysis_crs`, `exchange_crs`, 10 m grid origin, AOI, `is_pilot`, timezone, and `config_json` (algo profile, baselines, publish flags). A pilot is a flag and config on an area, not a separate hardcoded basin table. |
| `User` | Email, name, password hash, status. No “is_service” flag. |
| `ServiceAccount` | Separate `SERVICE` principal: `client_id`, secret hash, scopes, optional project binding, expiry, rate-limit fields. |
| `Membership` | `scope_type` is `organization` or `project`, plus `scope_id` and a role code. |

## RBAC

| Entity | Notes |
|--------|--------|
| `Role` | Seeded codes include v1 surface roles `admin`, `duty_officer`, `readonly` and reserved roles `platform_admin`, `org_admin`, `project_admin`, `qc_reviewer`, `analyst`. |
| `Permission` | Stable codes listed below. |
| `RolePermission` | Many-to-many. |

Permission codes:

- `product.submit`, `product.qc`, `product.publish`, `product.withdraw`, `product.draft`, `product.read`
- `task.create`, `task.cancel`, `task.retry`, `task.read`
- `dataset.read`, `dataset.write`
- `baseline.write`, `baseline.review`
- `scene.configure`, `scene.read`
- `api.invoke`
- `org.manage`, `project.manage`, `member.manage`
- `briefing.write`, `briefing.publish`, `briefing.read`

V1 grants:

- `admin` — all of the above except that `api.invoke` is intended for service accounts.
- `duty_officer` — `task.*`, `dataset.read`, `product.draft`, `product.submit`, `product.qc`, `product.publish`, `product.read`, `briefing.write`, `briefing.publish`, `briefing.read`, `scene.read`. Not member/org/project management, not `scene.configure`, not `product.withdraw`, not baseline write/review.
- `readonly` — `product.read`, `briefing.read`, `task.read`, `dataset.read`, `scene.read`. The API still filters product and briefing lists to published records for this role.

## Scenes

| Entity | Notes |
|--------|--------|
| `Scene` | Platform catalog. `code` is globally unique (`flood`). `manifest_json` declares task types, product types, briefing template, recommended baselines, and parameter schema. Status `registered` / `deprecated`. |
| `SceneActivation` | Unique `(project_id, scene_id)`. Status `enabled` / `disabled`. `config_json` holds the pilot AOI, `analysis_crs`, 10 m grid origin, and `algo_profile_id=s1_grd_flood_v1`. |

## Catalog and baselines

| Entity | Notes |
|--------|--------|
| `Dataset` | Imagery, DEM, admin boundaries, hydrology, thematic layers, or services. `dataset_type`: `vector` / `raster` / `tabular` / `service`. Optional `project_id` (null = org-shared). Time range, CRS, bbox, URI, checksum, `metadata_json`. |
| `BaselineAsset` | First-class, versioned asset, not a task temp file. Points at a `Dataset`. `version`, validity window (`valid_from`, `valid_to`), applicable area, `review_status` (`draft` / `pending_review` / `published` / `rejected` / `deprecated`). Category follows the GIS asset types: `permanent_water`, `seasonal_water`, `preevent_water`, `ref_dem`, `ref_landcover`, `ref_admin`, `ref_road`, `ref_cropland`, `ref_settlement`. Only `published` versions may be cited by official products. Tasks bind a specific version. |

## Runtime and products

| Entity | Notes |
|--------|--------|
| `Task` | `scene_id` optional in the schema but required for flood work. Platform statuses: `queued`, `running`, `succeeded`, `failed`, `cancelled`. Priority includes an emergency flag. `params_json`, progress, error, `engine_job_id`, timestamps. Retry starts a new engine job and does not overwrite an already-successful product. |
| `Product` | Lineage: `task_id`, imagery dataset id, baseline asset + version, engine name and params. Status machine: `draft → pending_qc → published → withdrawn`. QC reject returns to `draft`. A published row is immutable; withdraw, then a new version. Flood products use `product_type=SARAP_FLOOD_V1` and put official layers (`class_map`, `flood_event`, `water_current`, `qc_flags`, polygons, `thematic_map`, `impact_stats`) in `metadata_json` / artifact lists. No water-depth attributes. |
| `Briefing` | Structured `content_json`, optional linked product ids, status `draft` / `published` / `archived`. |
| `AuditLog` | `actor_type` (`user` / `service`), `actor_id`, `action`, resource type/id, `org_id`, `project_id`, `request_id`, before/after payload. At least product transitions, task dispatch, permission changes, and baseline review are recorded. |

## Product state machine

```
draft  --submit-->  pending_qc  --publish-->  published  --withdraw-->  withdrawn
                      │
                      └──reject-->  draft

withdrawn  --new version-->  draft (new row, version++)
```

Illegal transitions are rejected with a stable error. Every successful transition writes an audit row.

## Flood class codes (official, do not remap)

From `docs/specs/s1_grd_flood_v1.defaults.json`:

| Value | Name | Meaning |
|------:|------|---------|
| 0 | `nodata` | No data / outside mask |
| 1 | `non_water` | Determined non-water |
| 2 | `permanent_or_baseline_water` | Current water that matches the baseline |
| 3 | `flood_event` | New inundation (official “this event” class) |
| 4 | `water_lowconf` | Low-confidence water; excluded from default event stats |

Official event formula: `flood_event = water_current_hard AND NOT water_baseline_effective`. First version does not emit a water-depth band.

## Spatial types

Compose provisions PostGIS. The v1 schema stores AOI and footprints as `bbox_json` plus optional WKT so the same models can be exercised in SQLite during unit tests. A later migration can promote these to geometry columns without changing the API contract. Analysis rasters themselves must be produced in the pilot `analysis_crs` at 10 m, aligned to the configured grid origin.
