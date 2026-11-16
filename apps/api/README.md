# SARAP Platform API（`apps/api`）

第一版平台接口。对象命名与需求说明一致：项目、**区域**、场景、数据资产、本底、任务、产品。洪水是可注册场景，不是根实体（不要使用 `FloodProject` / `FloodTask`）。区域是主对象；`pilot_config` 只是区域上的 `config_json` 配置项，不是单独的区域模型。

时间一律 **UTC 存储**，接口输出 ISO-8601。展示请转 **Asia/Shanghai**。小时级是建议目标（`suggested_target_minutes=240`，数据就绪后 4 小时内出准范围），**不是合同 SLA**；不要把 `sla_minutes` 理解成已承诺时效。禁止任何水深字段或入口。

引擎是独立服务，本包只通过内部 HTTP 调用（`SARAP_ENGINE_URL` + `SARAP_ENGINE_TOKEN`），**禁止 import `engine` 业务库**。

## P0 / P1 切分

| 批次 | 平台行为 |
| --- | --- |
| **P0 值班员出图** | 无本底也可开通洪水场景（返回 `meta.warnings`，**不** 403/400 阻断）。任务成功后 **duty_officer 与 admin** 都可把 `draft` 直接发布到一张图，不必先走 `pending_qc`。无本底面积字段为 `extracted_water_ha`，文案「提取水体面积（未扣本底）」；不产出对外名为「本次淹没」的图层（`flood_event_status=baseline_missing`）。有本底同时给 `water_current_ha` 与 `flood_event_ha`。缺已发布 `permanent_water` 时不允许「启用自动本次淹没发布」，但不阻断准范围任务与最短发布。一般质控警告不阻断 P0 发布；硬错误（`PROCESSING_FAILED` / `GRID_MISALIGNED` / `COVERAGE_TOO_LOW`）才失败。 |
| **P1（模型与接口已落，不挡 P0）** | `data_asset` + `data_asset_version`（仅 `review_status=published` 可被「本次淹没」引用）。完整质检打回：`pending_qc` → `draft`，**必须填原因**，不要把 `withdrawn` 当打回。交叉统计（县/乡镇、道路、居民点）仅当已挂已发布资产时才返回；未挂资产不返回空壳、不虚报。P0 的 `impact_stat` 只出面积。 |
| **权限（已锁定）** | 值班员可质检（`product.qc`）并发布（`product.publish`），**不能撤回**。仅 admin 可 `product.withdraw`。撤回后只读与默认一张图（`?for_map=true`）不可见。再发布必须新版本且 `re_qc_required`（禁止最短发布，须重新提交质检）。禁止就地改已发布记录。readonly 默认只见 `published`。 |

产品 `status`：`draft` / `pending_qc` / `published` / `withdrawn`（`pending_qc` 对应此前的 pending_review）。本底版本用独立的 `review_status`：`draft` / `pending_review` / `published` / `rejected` / `deprecated`，不要和产品状态混用。

## 如何运行

Python 3.12+（本地 3.13 也可）。依赖 Postgres 时先在仓库根目录启动 `postgres`（见根 README / compose）。单元测试使用 SQLite，不必起 PostGIS。

```bash
cd apps/api
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# 测试
pytest -q

# 本地开发（默认 SQLite + 种子账号；或 export SARAP_DATABASE_URL=postgresql+psycopg://sarap:sarap@localhost:5432/sarap）
export SARAP_SEED_ON_STARTUP=true
uvicorn app.main:app --reload --port 8000
```

OpenAPI：`http://localhost:8000/openapi.json`，文档：`/docs`。

默认种子（`SARAP_SEED_ON_STARTUP=true`）：

| 角色 | Email | 密码 |
| --- | --- | --- |
| admin | admin@sarap.local | admin123 |
| duty_officer | duty@sarap.local | duty123 |
| readonly | readonly@sarap.local | readonly123 |

同时种子组织 `demo-org`、项目 `demo-pilot`、区域 `demo-area`（可配置 AOI / 10 m 网格原点，**不是写死流域名**）。演示 AOI 在 116°E 附近，分析坐标用示例 `EPSG:4548`（CGCS2000 3° 带、中央经线 117E）。**这不是全国默认**：新区域若不传 `analysis_crs`，平台按 AOI 质心经度选带（`EPSG = 4534 + (CM-75)/3`，`CM = 3*round(lon/3)`）。

Postgres 部署：`alembic upgrade head` 后启动；上线需加载 0002 迁移中的 `audit_logs` 不可变触发器。

## 鉴权与角色

- 人：邮箱 + 密码 + JWT（access + refresh）。Claims 含 `sub`、`ptype`、`org_id`、`roles`、`permissions`、`jti`。
- 服务账号：独立 `ServiceAccount` 表（不是 User 上的 flag）。创建时明文 API Key **只返回一次**，之后用 `X-API-Key` 调用（内部回调还可用 `X-Internal-Token`）。不能用密码登录。
- 权限码为点号形式，如 `product.publish`、`product.qc`。完整角色会种子，但 **V1 接口只允许绑定** `admin`、`duty_officer`、`readonly`。
- `duty_officer`：**没有** `product.withdraw`、`member.manage`、`org.manage`、`scene.configure`、`baseline.write/review/publish`。
- 越权 403，只靠依赖注入，不靠前端。

## 与引擎的 HTTP 约定

平台 → 引擎（`SARAP_ENGINE_URL`，共享 token）：

- `POST /internal/engine/jobs`
- `GET /internal/engine/jobs/{job_id}`
- `POST /internal/engine/jobs/{job_id}/cancel`
- `POST /internal/engine/jobs/{job_id}/priority`

`POST /internal/engine/jobs` 顶层字段：`task_id`（平台任务 UUID）、`scene_id`（**平台场景 UUID**，如 flood，不要和 Sentinel-1 PRODUCT-ID 混名）、`scene_code`、`area_id`（区域是空间主对象）。有值再带：`s1_product_id`、`acquisition_start` / `acquisition_end`（成像时间，UTC）、`baseline_version_id`、`algo_profile_id`。区域 `is_pilot=true` 时额外带顶层（及 params）`is_pilot` 作为配置标记。**不要**把 `pilot_id` 当作必填或唯一区域标识。

引擎 → 平台：

- `POST /api/v1/internal/products`（入库存为 `draft`）
- `POST /api/v1/internal/tasks/{id}/events`（更新状态/进度/时间字段）

测试用进程内 `RecordingEngineClient`，不编造产品。单元测试里由内部回传接口写入草稿产品。

## 主要接口（均 `/api/v1`）

统一信封 `{ "data", "error", "meta" }`。

- 认证：`POST /auth/login`、`POST /auth/refresh`、`GET /auth/me`
- 组织/项目/成员：`/orgs`、`/projects`、`/projects/{id}/members`（仅三角色）
- 服务账号：`POST /service-accounts`（返回一次 key）、`POST /service-accounts/{id}/revoke`
- 场景：`GET /scenes`；`POST/PATCH /projects/{id}/scenes`（无本底开通返回 warning）
- 区域：`/projects/{id}/areas`、`/areas/{id}`
- 编目：`/datasets`；本底资产 `/data-assets`、`/data-asset-versions/{id}/submit|publish|reject|deprecate`
- 任务：`POST /tasks`（可传 `idempotency_key`；未传时平台按 `(scene_id, area_id, s1_product_id, baseline_version_id, algo_profile_id, param_hash)` 生成（`scene_id` 为平台场景 UUID，与引擎调度载荷一致；无 `s1_product_id` 时不自动生成））、`force_rerun`、列表/详情、取消、`/rerun`
- 产品：草稿、P0 `POST /{id}/publish`、`/submit`、`/reject`（必填原因）、`/withdraw`（admin）、`/new-version`、`/layers`、`/stats`
- 简报：草稿 CRUD、发布、归档
- 内部：`/internal/products`、`/internal/tasks/{id}/events`

## 字段表（供 GIS 核对）

### 区域 Area

| 字段 | 说明 |
| --- | --- |
| id, org_id, project_id, code, name, status | 主键与归属。code 在组织内唯一。 |
| is_pilot | 是否试点。试点是区域上的配置，不是另一类实体。 |
| timezone | 默认 `Asia/Shanghai`（展示用；库内时间仍是 UTC）。 |
| aoi_geojson | 区域边界 GeoJSON。与本底 `applicable_area_geojson` 一样，按本区域 `exchange_crs`（默认 `EPSG:4490`）存储与解释；不要存成 `analysis_crs` / 高斯克吕格。 |
| bbox_json | 可选包围盒。 |
| analysis_crs | 分析与面积统计 CRS。未传时按 AOI 中央经线选 CGCS2000 3° 带。`EPSG:4548`（CM 117E）只是 116°E 附近示例区的默认，不是全国默认。 |
| exchange_crs | 交换/地理坐标，默认 `EPSG:4490`。本底适用几何与区域 AOI 在做包含判断前必须是同一 CRS，建议都按此字段存储。未标明 crs 的 GeoJSON 按本字段解释，不得当成 `analysis_crs`。 |
| grid_res_m, grid_origin_x, grid_origin_y | 正式栅格网格，默认 10 m，原点锁定。 |
| config_json | 相当于 pilot_config：`algo_profile_id`、`baselines.permanent_water_asset_id`、`baselines.preferred_version_id`、impact_assets、`publish.auto_publish_flood_event`、`suggested_target_minutes`（不要用合同口径的 sla_minutes）。同一资产在同一区域、同一成像时刻若有多个已发布版本，必须用 `preferred_version_id` 选定，否则任务创建返回 `BASELINE_VERSION_CONFLICT`，禁止静默任选。 |

### 本底版本 DataAssetVersion（独立 review_status）

| 字段 | 说明 |
| --- | --- |
| id, org_id, asset_id, version_no | 同一资产内 version_no 唯一。 |
| valid_from / valid_to | 生效窗，from 含、to 不含；任一侧为空表示该侧未限制。UTC。缺有效时段字段时不要放宽成永远适用，除非该侧本身为空。 |
| applicable_area_geojson, applicable_area_name | 适用区域几何建议按对应区域 `exchange_crs`（默认 `EPSG:4490`）存储。自动解析与显式 `baseline_version_id` 都按下面规则校验。 |
| review_status | `draft` / `pending_review` / `published` / `rejected` / `deprecated`。仅 published 可被「本次淹没」引用。 |
| reviewer_id, reviewed_at, review_comment | 审核。 |
| source, algorithm_profile_id, spatial_res_m, crs, gsd_note | 来源与精度。 |
| checksum, byte_size, storage_uri, preview_uri, schema_json, lineage_json | 存储与谱系。禁止只放在任务工作目录。 |
| 主表 DataAsset | asset_code, name, asset_type（如 `permanent_water` / `ref_road`…）, default_crs, status, org_id, 可选 project_id / area_id。 |

本底适用判定（自动筛选与显式传入均适用；SQLite 测试与生产路径均用 shapely 做包含判断，不依赖 PostGIS）：

1. 必须 `review_status=published`。
2. 若有成像时间（`acquisition_start`，没有则退到 `data_ready_at`），必须落在 `valid_from`（含）/`valid_to`（不含）内。
3. 空间与 CRS：
   - `applicable_area_geojson` 与区域 `aoi_geojson` 在 shapely `covers` 前必须是同一 CRS。建议都按区域 `exchange_crs`（默认 `EPSG:4490`）存储。GeoJSON 未标明 crs 时，按该区域 `exchange_crs` 解释，不要当成 `analysis_crs` / 高斯克吕格。`EPSG:4490` 与 `EPSG:4326`（含 CRS84）视为同一经纬度交换约定，可直接 covers。
   - 若 GeoJSON 带了 crs（或能明确判定坐标系，例如一边是经纬度、一边是米制投影），两者不一致则不得 covers、不得静默重投影，请先对齐到 `exchange_crs`。**显式** `baseline_version_id` 或 `preferred_version_id` 指向该版本时，直接 409 `BASELINE_CRS_MISMATCH`，不跳过、不换版本。**自动解析**（没有显式/可用 preferred 时）先跳过 CRS 不一致的版本，继续看其他已发布版本：筛完仍有可用版本则用这些版本（1 个自动绑定，多个仍走 `BASELINE_VERSION_CONFLICT` / preferred）；若筛完没有可用版本，且被排除的版本里至少有一个本可通过时段/适用区、只是 CRS 不一致，则再返回 409 `BASELINE_CRS_MISMATCH`。若本来就没有空间/时段上都适用的版本（例如名称留空无几何、area_id 也不匹配，或该版本明显属于另一区域），保持「无本底 / 不自动绑定」的 P0 行为，不要因为旁边有个 CRS 乱七八糟的无关版本就报 `BASELINE_CRS_MISMATCH`。
   - 有 `applicable_area_geojson` 且区域已有 `aoi_geojson` 时，必须以几何包含为准（即使 `asset.area_id` 相同，几何不包含也不适用 / 显式 409）。
   - 本底已有适用几何，但任务区域还没有 `aoi_geojson` 时，不直接判不适用：回退到 `asset.area_id == task.area_id`；两者都对不上再判不适用 / 显式 409 `BASELINE_AREA_NOT_APPLICABLE`。
   - 无适用几何时：`asset.area_id == task.area_id`，或非空 `applicable_area_name` 与区域 name/code 相等，否则不适用。名称留空且没有可判定几何、也没有匹配的 `area_id` 时，不得把同组织已发布版本当成适用。
4. 显式传入的 `baseline_version_id` 必须通过同样的时段、CRS 与适用区校验，不合格返回 409，不静默换版本、也不忽略该 id。错误码：`BASELINE_NOT_PUBLISHED`、`BASELINE_NOT_IN_VALIDITY_PERIOD`、`BASELINE_AREA_NOT_APPLICABLE`、`BASELINE_CRS_MISMATCH`。
5. 多个已发布且适用的版本仍用 `config_json.baselines.preferred_version_id` 选定；该 preferred 版本也必须通过上述校验，否则 409 `BASELINE_VERSION_CONFLICT` 或更具体的错误码，禁止静默任选。

### 任务时间与幂等

| 字段 | 说明 |
| --- | --- |
| data_ready_at | 数据在平台就绪（UTC）。小时级起算点。 |
| submitted_at | 任务提交（UTC）。 |
| processed_at | 产品生成/处理完成（UTC）。 |
| started_at / finished_at | 运行起止。 |
| idempotency_key | 相同键重复提交返回已有任务；`force_rerun=true` 新建。客户端未传时由平台按 `(scene_id, area_id, s1_product_id, baseline_version_id, algo_profile_id, param_hash)` 生成，与引擎调度载荷对齐：`scene_id` 是平台场景 UUID（不是 `scene_code`，也不是 Sentinel-1 PRODUCT-ID）。无 `s1_product_id` 时不自动生成，避免探索任务互相碰撞。 |
| area_id, algo_profile_id, baseline_version_id | 可选关联。`baseline_version_id` 只认 `data_asset_versions` 且 `review_status=published`；旧 `/baselines` 不参与洪水本底判定。 |
| scene_id / scene_code | **平台场景**（如 `flood`），不要和 Sentinel-1 PRODUCT-ID 混名。 |
| acquisition_start / acquisition_end | 成像起止时间（UTC）。应急图和时效评估以成像时间为准，不能只靠 `processed_at`。可由 `imagery_dataset_id` 对应 Dataset.`time_start`/`time_end` 映射。 |
| s1_product_id | Sentinel-1 PRODUCT-ID。可由 Dataset.`s1_product_id`（或 `metadata_json.s1_product_id`，或 code 以 `S1` 开头）映射。 |
| status | `queued` / `running` / `succeeded` / `failed` / `cancelled`。子阶段放 `progress_json`。 |
| error_code, log_uri | 失败写硬错误码与日志。 |
| suggested_target_minutes | 建议目标，默认 240。不是合同 SLA。 |

### 产品 Product

| 字段 | 说明 |
| --- | --- |
| status | `draft` / `pending_qc` / `published` / `withdrawn`。 |
| version, supersedes_id, re_qc_required | 撤回后新建版本并强制重新质检。 |
| area_id, task_id, scene_id / scene_code | 归属。 |
| baseline_version_id / data_asset_id | 「有本底」**只**认 `data_asset_versions.baseline_version_id` 且 `review_status=published`。仅有旧 `/baselines` 或字符串 `baseline_version` 时按无本底处理，不产出 `flood_event` 图层。已被任务/产品引用的版本只允许 `deprecate`，禁止软删除。 |
| flood_event_status | 洪水任务出结果后只保留 `computed`（有已发布本底）或 `baseline_missing`。`none` 仅用于未出结果或非洪水产品。 |
| acquisition_start / acquisition_end / s1_product_id | 一等字段，含义同任务；与 `scene_id`/`scene_code`（平台场景）分开。应急图用成像时间。 |
| extracted_water_ha | 无本底：提取水体面积（未扣本底），公顷保留 2 位；同时给出 `extracted_water_m2` 整数。 |
| water_current_ha, flood_event_ha | 有本底：当期水体与本次淹没。 |
| lowconf_ha | 低置信，默认不计入对外面积。 |
| data_ready_at, submitted_at, processed_at, published_at, withdrawn_at | UTC。 |
| reject_reason | P1 打回原因（回到 draft）。 |
| withdraw_reason | 仅发布后撤回。 |
| suggested_target_minutes | 默认 240。 |
| metadata_json | 引擎元数据；水深字段会被拒绝/剥离；`sla_minutes` 会规范成 `suggested_target_minutes`。 |
| ProductLayer.layer_key | 按是否有本底返回：始终 `class_map`(0 nodata, 1 非水, 2 本底水仅有本底, 3 本次淹没仅有本底, 4 低置信, 5 extracted_water 无本底确定水)、`water_current`、`water_current_poly`、`qc_flags`、`qc_summary`、`metadata`；有本底才给 `flood_event` / `flood_event_poly`。 |

## 模块边界

- `apps/api`：本目录，平台 API。
- `apps/web`：前端（TypeScript + React + 地图），本包不实现页面。
- `engine/`：独立处理引擎，内部 HTTP。
