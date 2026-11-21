# SARAP 处理引擎（第一版）

同仓独立 Python 包，负责 Sentinel-1 水体提取、变化检测、质控旗标、面积统计与任务编排。平台与仓库名均为 SARAP。

产品与算法口径对齐：

- `/workspace/SARAP/specs/SARAP-v1-flood-product-spec.md`（SARAP-SPEC-FLOOD-V1 **v1.1.0**）
- `/workspace/SARAP/specs/SARAP-M0-engine-test-freeze.md`（测试 / 引擎冻结口径）
- 默认参数：`/workspace/SARAP/specs/s1_grd_flood_v1.defaults.json`（包内有副本）
- SNAP 图模板：`/workspace/SARAP/specs/s1_grd_flood_v1.xml.j2`（包内副本已改为 `${orbitType}` / `${pixelSpacing}` 变量）

**第一版不提供水深**，也不会在产品或接口里把淹没范围表述成水深。

## 职责边界

引擎做的事：

- 通过内部 HTTP 从平台接任务、回状态、在质控与打包完成后把产品文件 URI + metadata + qc_summary 交给平台入库接口。
- 假设 Sentinel-1 输入路径 / URI 已由平台准备就绪，**首版不做下载**。
- 生产路径用 SNAP `gpt` + 预置 Graph；后处理（阈值、MMU、变化检测、质控、面积）是纯 Python，可单测、不依赖 SNAP。
- `review` / `published` 属于平台产品生命周期。引擎质控通过后走 `ingesting`，平台确认入库后任务才 `succeeded`。引擎不自己发布，也不直接写平台业务库。

引擎不做的事：水深产品、光学融合、其它雷达卫星、在 Web Mercator 上提水或算面积、把一般质控警告当成 P0 发布阻断。

P0 / P1 口径（v1.1.0）：

- **P0 允许无本底出准范围**。无本底时 `class_map` 用 `5=extracted_water` 表示确定水体，不写 2/3；可出空的「本次淹没」层并在元数据写 `flood_event_status=baseline_missing`。面积字段用 `extracted_water_ha`，文案为「提取水体面积（未扣本底）」，不得写成「本次淹没」。
- **有本底**时官方口径：`flood_event = water_current_hard AND NOT water_baseline_effective`。`class_map` 写 2/3，不写 5；同时给出 `water_current_ha` 与 `flood_event_ha`。本底 nodata 不得算本次淹没。
- 面积是 P0 必出。交叉统计（县/乡镇、道路相交长度、居民点）是 P1，且仅在已配置影响对象时才出；未配置只给面积并说明「未配置影响对象，不出交叉结论」。耕地为扩展，不是 P1 必选。禁止空壳指标。
- 质控旗标 P0 就要写（建成区默认降为低置信等）。一般警告不阻断最短发布。硬错误才失败：SNAP 失败、网格不对齐、有效覆盖过低。
- 对外时效：数据就绪后建议 ≤ **4 小时** 出准范围与面积，验证前不作合同承诺。必须记录 `data_ready_at`、`submitted_at`、`processed_at`。内部 10+40+10 分钟只写入任务日志 / `internal_budget_minutes`，不是对外 SLA，也不再使用「对外 SLA=60 分钟」。

## 安装

需要 Python 3.11+（当前盒子为 3.13）。在本目录创建虚拟环境并安装：

```bash
cd /workspace/sarap/engine
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

可选地理依赖（写 GeoTIFF/COG、矢量库；安装失败不阻塞核心算法与 mock 空跑）：

```bash
pip install -e ".[geo]"
# 即 rasterio / geopandas / shapely / scikit-image（需要系统 GDAL 时可能失败）
```

没有 rasterio 时，栅格以 `npy` + `*.grid.json` 侧车写出，算法单测仍用纯 numpy，不依赖 SNAP / GDAL。有 rasterio 则写 GeoTIFF。应急图 PNG 使用 Pillow，旁路写 `emergency_map.json`（标题、面积、影响统计和限制说明）。完整 GeoPDF 仍未做。

## 启动 API

```bash
cd engine
source .venv/bin/activate
export SARAP_ENGINE_MODE=mock
export SARAP_ENGINE_WORK_DIR=./data/engine-work
export SARAP_ENGINE_DB_URL=sqlite:///./data/engine-jobs.sqlite
export SARAP_ENGINE_INGEST_MODE=mock   # 无平台时用本地回执；对接平台时用 http
python -m sarap_engine.main --host 0.0.0.0 --port 8081
# 或：sarap-engine --mode mock
```

`python -m sarap_engine.main` 会启动后台 worker 消费队列（`SARAP_ENGINE_WORKER=false` 可关）。`SARAP_ENGINE_RUN_INLINE=true` 则在提交请求里同步跑完，不再另起线程。

Compose（仓库根目录，默认 mock，不下载 Sentinel-1）：

```bash
docker compose --profile engine up --build
```

内部 HTTP 前缀 `/internal/engine`（字段稳定，不必套平台 `{data,error,meta}`）：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/internal/engine/jobs` | 提交任务 |
| `GET` | `/internal/engine/jobs/{id}` | 查询 |
| `POST` | `/internal/engine/jobs/{id}/cancel` | 取消 |
| `POST` | `/internal/engine/jobs/{id}/priority` | 提升为 emergency 插队 |
| `GET` | `/internal/engine/health` | 健康检查（含是否找到 gpt） |

设置了 `SARAP_ENGINE_TOKEN`（平台调用引擎的令牌）时，请求需带 `X-Internal-Token` 或 `Authorization: Bearer`（平台目前会同时带上这两个头）。

同步跑完（测试 / 演示）：`SARAP_ENGINE_RUN_INLINE=true`。

## mock 空跑（无 SNAP / 无 gpt）

硬性要求：`execution_mode=mock` 或 `SARAP_ENGINE_MODE=mock` 时使用 `mock` 插件，**不得调用 gpt**。合成小型 numpy 栅格，走真实的 extract / change / qc / package 算法，写出 `metadata.json`、`qc_summary.json` 以及 `class_map` / `water_current` 等。

```bash
cd /workspace/sarap/engine
source .venv/bin/activate
python -m sarap_engine.demo_mock
# 有本底合成对比：
python -m sarap_engine.demo_mock --with-baseline
```

成功时打印任务状态 `succeeded`、产品 ID、图层清单和面积字段。入库默认 mock 成功（不访问外网）。

也可以用 pytest 端到端用例：`tests/test_api_mock_e2e.py`。

生产模式 `snap` 且系统找不到 `gpt` 时，任务失败并给出明确错误（`GPT_NOT_FOUND`），**不会偷偷改走 mock**。`pie_sar` 在 validate / run 即声明未实现（`PLUGIN_NOT_IMPLEMENTED`）。

## 测试

```bash
cd /workspace/sarap/engine
source .venv/bin/activate
pytest
```

覆盖：状态机合法/非法迁移、阈值夹逼与双峰失败回退、本底相减（含本底 nodata 不得算本次淹没）、MMU、建成区降为低置信、网格不对齐必须失败、应急插队与步骤边界抢占、幂等提交、API + mock 空跑、pie_sar 拒绝、snap 无 gpt 时的明确错误。算法测试在没有 rasterio / SNAP 时也能跑。

## 任务状态

```
accepted → queued → preparing → snap_running → extracting
→ change_detecting → impact_mapping → qc → ingesting → succeeded
```

另有：`retry_wait`、`failed`、`cancelled`、`preempted`（应急任务在步骤边界让出后回到 `queued`，优先级低于 emergency）。

- 瞬时错误（gpt 崩溃、超时、磁盘、入库 5xx）：指数退避，默认最多 3 次。SNAP 崩溃先立即重试 1 次，仍失败再进入上述通用重试。
- 业务错误（输入缺失、无 VV、参数非法、网格不对齐、pie_sar 未实现、有效覆盖过低、找不到 gpt）：不重试，直接 `failed`，写 `error_code` 和原因。
- 应急插队：`priority=emergency` 排在 normal 之前。不 SIGKILL 正在跑的 gpt；在 preparing 之后、snap_running 完成之后、各后处理步骤之间检查。普通任务标记 `preempted` 并带检查点回到 `queued`。
- 幂等键：`(scene_id, area_id, s1_product_id, baseline_version_id, algo_profile_id, param_hash)`。`scene_id` 是平台场景（如 flood），`s1_product_id` 才是 Sentinel-1 景标识，二者不要混名。区域主键是 `area_id`，`pilot_id` 不是必填。相同键重复提交返回已有任务，除非 `force_rerun=true`。

## 配置项

均可通过环境变量 `SARAP_ENGINE_*` 覆盖（见 `sarap_engine/config.py`）：

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `SARAP_ENGINE_MODE` | `mock` | 默认插件：`mock` / `snap` / `pie_sar` |
| `SARAP_ENGINE_HOST` / `PORT` | `0.0.0.0` / `8081` | API 监听 |
| `SARAP_ENGINE_WORK_DIR` | `./data/engine-work` | 任务工作目录 |
| `SARAP_ENGINE_DB_URL` | `sqlite:///./data/engine-jobs.sqlite` | 任务库 |
| `SARAP_ENGINE_PLATFORM_BASE_URL` | `http://localhost:8000` | 平台 API 根地址 |
| `SARAP_ENGINE_PLATFORM_INGEST_URL` | `http://localhost:8000/api/v1/internal/products` | 入库完整 URL（可由此解析 internal 根路径） |
| `SARAP_ENGINE_INGEST_MODE` | `http` | `http` 或 `mock` |
| `SARAP_ENGINE_PLATFORM_TOKEN` | 空 | 服务账号明文 API Key（回传只放 `X-API-Key`，不要放进 Bearer） |
| `SARAP_INTERNAL_TOKEN` | 空 | 引擎回传平台时的 `X-Internal-Token`，与平台同名变量对齐 |
| `SARAP_ENGINE_TOKEN` | 空 | 平台调用引擎时的令牌（`X-Internal-Token` 或 Bearer） |
| `SARAP_ENGINE_INTERNAL_TOKEN` | 空 | 旧名回退；优先使用上面两个平台同名变量 |
| `SARAP_ENGINE_DEFAULT_CRS` | `EPSG:4548` | 默认可被试点 `analysis_crs` 覆盖，不写死流域 |
| `SARAP_ENGINE_MAX_RETRIES` | `3` | 通用重试次数 |
| `SARAP_ENGINE_MIN_VALID_COVERAGE_RATIO` | `0.05` | 低于此视为有效覆盖过低（硬错误） |
| `SARAP_ENGINE_RUN_INLINE` | `false` | 提交后同步执行 |
| `SARAP_ENGINE_GPT_BINARY` | `gpt` | SNAP 可执行文件 |

试点 CRS、10 m 网格原点、阈值、MMU、建成区策略等均可在任务的 `pilot` / `param_overrides` 中覆盖，对应规范第 12 节。

## 与平台入库接口的约定

引擎只通过内部 HTTP 回传，平台 API 不要 import 引擎业务库。引擎回传平台时：`X-Internal-Token` 对齐平台的 `SARAP_INTERNAL_TOKEN`；服务账号则用 `X-API-Key` 传明文 API Key。`Authorization: Bearer` 只接受 JWT access token，不要把原始 API Key 放到 Bearer 里。平台调用引擎时使用 `SARAP_ENGINE_TOKEN`，目前会同时带 `Authorization: Bearer` 和 `X-Internal-Token`。

提交任务时请带上平台 `task_id`（UUID），以及 `scene_id` / `scene_code`（平台场景，如 flood）、`area_id`、`s1_product_id`、`acquisition_start` / `acquisition_end`。`scene_id` 不是 Sentinel-1 PRODUCT-ID；区域用 `area_id`，不要把 `pilot_id` 当作必填，试点最多带 `is_pilot`。引擎在处理过程中回传：

- `POST /api/v1/internal/tasks/{id}/progress`
- `POST /api/v1/internal/tasks/{id}/events`（`status` 映射为 queued/running/succeeded/failed/cancelled，`step` 为引擎细状态）
- `POST /api/v1/internal/products`（质控打包完成后；产品保持 draft，由平台决定发布）

产品回传字段对齐平台 `InternalProductIn`：`class_map` 编码 0–5；洪水任务出结果后 `flood_event_status` 只保留 `computed` 或 `baseline_missing`，`none` 仅用于未出结果或非洪水产品。时间戳 `data_ready_at` / `submitted_at` / `processed_at`（UTC，`Z` 后缀），并回传 `s1_product_id` 与成像起止时间。无本底只给 `extracted_water_ha`，不回传对外「本次淹没」图层和任何 `flood_event*` 面积字段；有本底同时给 `water_current_ha` / `flood_event_ha`。时效用 `suggested_target_minutes`（默认 240），`contract_commitment=false`，不把 sla 写成合同承诺。不带水深字段。缺已发布常年水体本底时不把成果标成「本次淹没」，但不阻断准范围回传。

- 2xx：任务 `succeeded`。
- 5xx 或网络错误：瞬时失败，进入重试。
- 4xx：不重试，任务 `failed`。
- `SARAP_ENGINE_INGEST_MODE=mock` 时不发 HTTP，直接视为入库成功，便于本地空跑。

## SNAP 生产路径

顺序固定：Read → Subset（AOI 外扩 2 km）→ Apply-Orbit-File → Remove-GRD-Border-Noise（仅 IPF < 3.10 或 `force_border_noise_removal`）→ ThermalNoiseRemoval → Calibration（线性 σ⁰，此步不转 dB）→ Refined Lee 7×7 → Terrain-Correction（10 m，对齐网格）→ LinearToFromdB → Write。

模板变量包括 `${input}` `${aoiWkt}` `${orbitType}` `${demName}` `${mapProjection}` `${pixelSpacing}` `${output}` 等，不把绝对路径写死在图里。

## 已知限制与未做完的部分

- 道路、居民点、行政区的交叉统计在分析网格上计算。任务的 `impact_assets` 指向 `fixture:public_validation_window` 或一份带 CRS 的 GeoJSON 时才会出数；未配置、几何读不到、或分析坐标系是 Web Mercator / 地理坐标时不出交叉结论，也不补空壳指标。应急图是 PNG 预览加 `emergency_map.json`，完整 GeoPDF 仍未做。
- 矢量化在无 shapely 时用连通域外接矩形写出 GeoJSON，便于测试，不是生产级拓扑修复。
- SNAP 多波段输出（VH、入射角、DEM）的完整波段名适配，需在已安装 SNAP + rasterio 的环境继续完善；无 gpt 时生产路径会明确失败。
- 引擎不发布产品，不输出水深。
