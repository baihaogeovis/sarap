# SARAP engine design (phase 1)

This document records the platform-facing engine contract and the GIS-locked processing defaults. The `engine/` package itself is implemented in parallel; do not treat this file as a second copy of that code.

Authoritative sources (copied into this repo):

- `docs/specs/SARAP-v1-flood-product-spec.md`
- `docs/specs/s1_grd_flood_v1.defaults.json`
- `docs/specs/s1_grd_flood_v1.xml.j2`

## Role

The engine is an independent Python service. It is not a library that the platform imports into its request path. It accepts jobs, runs plugin workflows, exports artifacts, and posts them back to the platform ingest API. It may keep its own job state and working directory. It does **not** write platform business tables and it does **not** download Sentinel-1 imagery in v1. Inputs are local or object-storage URIs that the platform has already staged.

The control plane is internal-only. It is not exposed through the public `/api/v1` surface.

## Control-plane API

Authenticated with the shared internal token.

- `POST /internal/engine/jobs` — accept a job, return `job_id` and state `accepted`.
- `GET /internal/engine/jobs/{job_id}` — status, progress, step, error, result URIs.
- `POST /internal/engine/jobs/{job_id}/cancel` — request cancel; honoured at the next step boundary.
- `POST /internal/engine/jobs/{job_id}/priority` — bump to emergency / raise priority. Queued jobs jump the normal queue. A running SNAP graph is not preempted mid-step.

The platform client lives in `apps/api/app/services/engine_client.py`. If the engine is down or misconfigured, task dispatch fails clearly (HTTP 503), and the task is marked failed rather than left looking as if it is running.

## Job state machine (engine-side)

```
accepted → queued → running → ingesting → succeeded
                 ↘ retry_wait ↗
                 ↘ failed
                 ↘ cancelled
```

Emergency jobs are dequeued ahead of normal jobs. Preemption and cancel never terminate a SNAP GPT process in the middle of a graph step; the worker checks a cancel/preempt flag only between steps.

## SNAP flood workflow (locked)

Profile id: `s1_grd_flood_v1`. Preferred SNAP 10.x, one patch version locked across environments and written into product metadata. Data source: Sentinel-1 IW GRD. VV is the primary extract channel; VH is preprocessed as an assist.

Graph order in `s1_grd_flood_v1.xml.j2` (do not reorder without bumping the profile):

1. Read
2. Subset (pilot AOI, default 2 km buffer; early crop is required)
3. Apply-Orbit-File (precise orbit, `continueOnFail=true`)
4. Remove-GRD-Border-Noise (required when IPF &lt; 3.10, or when forced)
5. ThermalNoiseRemoval
6. Calibration → Sigma0, **linear** (not dB yet)
7. Speckle-Filter, Refined Lee, 7×7
8. Terrain-Correction, 10 m, `mapProjection` = the pilot **analysis CRS**, Copernicus DEM 30 m, align to the pilot grid origin
9. LinearToFromdB
10. Write (GeoTIFF-BigTIFF; post-process to COG)

Thresholding, morphology / MMU (default 0.3 ha), QC flags, and change detection against a versioned baseline run after the graph, in the analysis CRS, on σ⁰(dB). Default VV threshold is −18 dB, clamped to [−23, −14] dB; incidence 30–45°; slope 15°. See the defaults JSON for the full set.

Analysis CRS is **not** a global constant and is **not** Web Mercator. It comes from the pilot configuration (`analysis_crs`, demo example `EPSG:4548`). AOI geography uses `EPSG:4490` in the demo. `EPSG:4326` / `EPSG:4490` copies are exchange or preview only.

## Official class codes

Do not invent a parallel legend.

| Value | Name |
|------:|------|
| 0 | `nodata` |
| 1 | `non_water` |
| 2 | `permanent_or_baseline_water` |
| 3 | `flood_event` |
| 4 | `water_lowconf` |

`flood_event = water_current_hard AND NOT water_baseline_effective`. Baseline selection: seasonal water if the acquisition falls in a published version’s validity window, otherwise published permanent water; optional pre-event union. Conflicting published versions must fail or use `preferred_version_id` — never pick silently.

QC flag bits (0–8) are defined in the defaults JSON (`URBAN`, `SHADOW`, `LAYOVER`, `INCIDENCE`, `EDGE_MIXED`, `THIN_OR_SOIL`, `BASELINE_GAP`, `MMU_REMOVED`, `ORBIT_DEGRADED`).

## Products the engine may deliver

Layers listed in the GIS spec section 9.3 (`class_map`, `flood_event`, `water_current`, `qc_flags`, polygons, optional `sigma0_vv_db`, `thematic_map`, `impact_stats`, `metadata`). Product type `SARAP_FLOOD_V1`. **No water-depth raster or depth class.**

Impact objects, when the corresponding baseline/assets are published: `admin_county`, `admin_township`, `cropland`, `road`, `settlement`.

## Plugins and modes

A plugin implements `name`, `validate(job)`, `steps(job)`, `run_step(...)`. SNAP is the v1 implementation and must use the official graph template and defaults above. PIE-SAR should be registered as a stub whose `validate()` fails with a clear “not implemented in phase 1” error, with no silent fallback to SNAP.

`SARAP_ENGINE_MODE=mock` is for tests and local demos without `gpt`. Mock artifacts must be explicitly marked (`metadata.mock = true`). In `real` mode a missing `gpt` binary fails clearly and must not write a fake product.

## Platform ingest

On entering `ingesting`, the engine `POST`s artifact descriptors to `SARAP_ENGINE_PLATFORM_INGEST_URL` (default `http://api:8000/api/v1/internal/products`). The platform creates `draft` products with lineage (task, imagery URI, baseline version, engine name, parameters, `algo_profile_id`).

## Hour-scale target

“Hour-scale” is a suggested target after data is ready on the platform (`suggested_target_minutes=240`, i.e. within 4 hours to extent and area). It is not a contractual SLA, and it is not a Sentinel-1 revisit promise. The 10+40+10 minute and 60-minute figures are internal design and timing budgets only. The engine assumes staged inputs, cached orbit/DEM where possible, and early AOI subsetting. Prefer `suggested_target_minutes` in metadata; do not treat `sla_minutes` as a committed SLA.
