# SARAP 部署说明

本文说明如何在本机把第一版骨架跑起来。生产部署尚未定稿，下面的默认口令和密钥只用于本地演示，上线前必须全部更换。

更完整的启动摘录也写在仓库根目录 [README.md](../README.md)。

## 环境要求

- Docker 与 Docker Compose（用于 Postgres 16 + PostGIS、Redis、MinIO；也可用来起 API 和 Web）
- 若在主机上跑应用：Python 3.12+（本地 3.13 也可以）、Node 20+
- 可选：SNAP `gpt`（只有跑真实处理链才需要；mock 模式不需要）

## 1. 取代码并准备环境变量

```bash
git clone https://github.com/baihaogeovis/sarap.git
cd sarap
cp .env.example .env
```

按需要编辑 `.env`。不要把 `.env` 提交进仓库。本地默认值见 `.env.example`，包括数据库、MinIO 和内部令牌。

## 2. 启动依赖

```bash
docker compose up -d postgres redis minio
```

等 Postgres 健康后再启动应用。MinIO 控制台默认是 [http://localhost:9001](http://localhost:9001)，账号口令来自 `.env` / `.env.example`。

## 3. 启动平台 API 和前端

### 方式 A：Compose 构建 API 和 Web

```bash
docker compose up --build api web
```

- 平台 API：[http://localhost:8000](http://localhost:8000)，文档在 `/docs`，OpenAPI 在 `/openapi.json`
- 前端：[http://localhost:5173](http://localhost:5173)

API 首次启动会跑 Alembic 迁移，并在 `SARAP_SEED_ON_STARTUP=true` 时写入演示组织、项目和账号。

### 方式 B：依赖走 Compose，应用跑在主机

```bash
# API
cd apps/api
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
export SARAP_DATABASE_URL=postgresql+psycopg://sarap:sarap@localhost:5432/sarap
export SARAP_ENGINE_URL=http://localhost:8081
alembic upgrade head
uvicorn app.main:app --reload --port 8000

# Web（另开终端）
cd apps/web
npm install
npm run dev
```

Vite 开发服务器会把 `/api` 代理到 `http://localhost:8000`。引擎没启动时，创建处理任务会得到明确的「引擎不可用」错误；编目、权限、质检和发布接口仍可调用。

## 4. 引擎（mock 可随 Compose 启动）

引擎是内部服务（默认 [http://localhost:8081](http://localhost:8081)），不写平台业务表，第一版也不下载 Sentinel-1。镜像默认 `SARAP_ENGINE_MODE=mock`。和 API、Web 一起构建：

```bash
docker compose --profile engine up --build
```

只起引擎和它依赖的 API / Redis：

```bash
docker compose --profile engine up --build engine
```

健康检查：`GET /health` 或 `GET /internal/engine/health`。进程会在后台消费队列，所以值班员创建的任务会被 mock 跑完，并把产品回传到平台 `POST /api/v1/internal/products`。产品保持 draft，由平台决定发布。

也可以在主机上用 mock 模式启动（同样会拉起后台 worker，除非 `SARAP_ENGINE_WORKER=false` 或 `SARAP_ENGINE_RUN_INLINE=true`）：

```bash
cd engine
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
SARAP_ENGINE_MODE=mock SARAP_ENGINE_INGEST_MODE=http \
  SARAP_ENGINE_PLATFORM_INGEST_URL=http://localhost:8000/api/v1/internal/products \
  SARAP_ENGINE_TOKEN=dev-internal-token SARAP_INTERNAL_TOKEN=dev-internal-token \
  python -m sarap_engine.main --port 8081
```

没有平台、只想本地空跑时，把 `SARAP_ENGINE_INGEST_MODE` 设为 `mock`。单次演示：

```bash
python -m sarap_engine.demo_mock
python -m sarap_engine.demo_mock --with-baseline
```

真实 SNAP 模式需要环境里有 `gpt`。找不到时引擎返回 `GPT_NOT_FOUND` 并失败，不得自动改走 mock。当前镜像不安装 SNAP。

### 在一张图里看淹没范围

引擎跑完后产品仍是 `draft`，默认一张图不会画它。用值班员或管理员账号到「质检 / 发布」把产品发布，然后打开「一张图」，选刚才的区域。

有已发布常年水体本底时，图上是「本次淹没」（强调色）和「本底水体」（水色）。没有本底时，图层标题是「提取水体（未扣本底）」，不会被改名叫本次淹没。分析坐标系用区域上保存的 `analysis_crs`，统计在这个 10 m 网格上做，不在 Web Mercator 里算。草稿、待质检和已撤回的产品不会出现在这张默认图上。该区域没有任何已发布产品时，地图只留区域范围，并提示空状态，右侧也不编造面积或影响数字。

种子里的示例区域会带上 `impact_assets`，指向引擎里的小夹具 `fixture:public_validation_window`。这是一块 800 m 的公开验证式窗口（西侧开阔水体，类似 Sen1Floods11 里湄公河开阔水面验证得比较好的情形），坐标是相对分析窗口西北角的米，不是国内试点，也不包含 Sen1Floods11 的栅格或人工标注。已有数据库如果示例区域还没有这条配置，API 启动种子会补上，不会覆盖你已经填过的道路引用。

发布之后在一张图上应能看到：水体或本次淹没、行政区、道路、居民点，以及右侧的面积和影响统计（受影响道路条数和长度、居民点个数和面积、行政区个数和面积）。点选要素可以看名称和是否受影响。不受影响的对象用虚线，避免把干地也涂成淹没。

简报页用同一批已发布产品。选中示例区域后，默认简报直接画出应急图和结论，不必先保存。可以把这一页存成草稿；把简报记录本身标成已发布需要 `briefing.publish`（种子里的管理员有这个权限，值班员可以起草和查看）。只读账号看得到已发布产品和这张默认简报，看不到草稿产品或未发布的简报记录。撤回后，默认图和简报主图都会拿掉该产品。

只读账号 `readonly@sarap.local` / `readonly123` 可以打开同一张图，看不到未发布产品。

建议走一遍「发布本底 → 引用本底的洪水任务 → 发布产品 → 看本次淹没」。不下载 Sentinel-1，也不需要 SNAP。国内实景和 `gpt` 正射链不在这次增量里。

1. 用管理员 `admin@sarap.local` / `admin123` 打开「资源 → 本底库」。值班员没有 `baseline.write` / `baseline.publish`，不能在这里发布。
2. 登记一份常年水体：适用区域选「示例区域」，版本号例如 `v1`，分析 CRS 保持区域上的 `EPSG:4548`，栅格 URI 留空。留空表示 mock 用合成水体做差，不会去读一个不存在的文件。发布后版本状态是 `published`。
3. 换值班员 `duty@sarap.local` / `duty123`，打开「任务」。区域仍选示例区域，已发布本底选刚才的 `v1`，已入仓影像可以不选。创建洪水全流程任务。下拉里的「不指定」不是强制无本底：若该区域当时只有一份适用的已发布本底，平台会自动绑定它。多份已发布本底且没有 `preferred_version_id` 时，不指定会失败。
4. 等任务变成 `succeeded`。产品先是 `draft`。草稿不进默认一张图和简报。
5. 在「质检 / 发布」直接发布该产品。第一版仍允许 `draft` 直接发布，不必先提交到 `pending_qc`。
6. 打开「一张图」和「简报」，选示例区域。默认视图应是「本次淹没」，不是「提取水体（未扣本底）」。

这一步的 mock 结果来自仓内 `fixture:public_validation_window`：800 m、10 m 网格、西侧开阔水体，坐标相对窗口西北角，放在示例区域分析网格的中部。它不是国内标注场景，也不含 Sen1Floods11 栅格。变化检测口径是当期确定水体减去有效已发布本底（`flood_event = water_current_hard AND NOT water_baseline_effective`）。本底缺测的像元不算本次淹没。

对照已发布本底时，引擎回传并在默认图、默认简报上显示：

| 项 | 值 |
| --- | --- |
| `flood_event_status` | `computed` |
| 本次淹没 `flood_event_ha` | 6.75 ha |
| 当期水体 `water_current_ha` | 17.75 ha |
| 低置信 `lowconf_ha` | 4.75 ha |
| 受影响道路 | 1 条（穿水道路），301 m |
| 受影响居民点 | 1 个（临水居民点），0.79 ha |
| 受影响行政区 | 2 个（开阔水体县 6.75 ha，沿水乡镇 3.15 ha），合计 9.9 ha |
| 含低置信 | 穿水道路约 603 m；另有建成区居民点。干地道路、干地居民点、干地县、干地乡镇不进默认统计 |

分析坐标系仍是区域上的 `EPSG:4548`，统计在 10 m 网格上做。地图只把矢量转到 `EPSG:4326` 显示。右侧和简报会写出本底版本号。

在还没有任何适用的已发布本底时建任务，发布后是对照：`flood_event_status=baseline_missing`，图层标题「提取水体（未扣本底）」，提取水体 18.95 ha，穿水道路 451 m，临水居民点 1.28 ha。不得把这张图叫成本次淹没。本底一旦发布，同一区域上再跑的洪水任务会用上它（显式选择，或在只有一份时自动绑定）。

默认一张图和默认简报用的是该区域**最新一份已发布产品**。想让默认视图停在本次淹没上，最后发布的应是引用了本底的那份产品。草稿、待质检、已撤回仍然不出现。同一区域、同一成像时刻有多份已发布本底、任务又没指定版本时，创建任务会返回 `BASELINE_VERSION_CONFLICT`，要用区域 `config_json.baselines.preferred_version_id` 指定，不能静默任选。未发布版本是 `BASELINE_NOT_PUBLISHED`。

## 5. 演示账号

仅用于本地，上线前必须改掉或关闭种子数据。

| 角色 | 邮箱 | 密码 |
|------|------|------|
| 管理员 | admin@sarap.local | admin123 |
| 值班员 | duty@sarap.local | duty123 |
| 只读 | readonly@sarap.local | readonly123 |

种子还会创建组织 `demo-org`、项目 `demo-pilot`（占位 AOI），并开通 `flood` 场景。

## 6. 测试

```bash
# API
cd apps/api && pip install -e ".[dev]" && pytest -q

# Web
cd apps/web && npm install && npm run typecheck && npm run build

# 引擎（mock）
cd engine && pip install -e ".[dev]" && SARAP_ENGINE_MODE=mock pytest -q
```

推到 `main` 或开 Pull Request 时，GitHub Actions（`.github/workflows/ci.yml`）会跑上述 API lint/测试、引擎 mock 测试和前端 typecheck/build。

本地复跑：API pytest、引擎 `SARAP_ENGINE_MODE=mock` pytest、Web `npm run typecheck` 与 `npm run build` 需要通过。本环境通常没有 Docker 守护进程，镜像不一定在这里实际 build。

## 7. 端口一览

| 服务 | 地址 |
|------|------|
| Web | http://localhost:5173 |
| 平台 API | http://localhost:8000 |
| 引擎（内部） | http://localhost:8081 |
| Postgres | localhost:5432 |
| Redis | localhost:6379 |
| MinIO API | http://localhost:9000 |
| MinIO 控制台 | http://localhost:9001 |

## 8. 生产注意事项

- 更换所有默认密钥和口令，关闭或改写启动种子，不要使用上面的演示账号。
- `docker compose --profile engine` 适合本地 mock。生产若要跑真实 SNAP，镜像里必须有 `gpt`，缺了会以 `GPT_NOT_FOUND` 失败，不会改走 mock。
- 对象存储、数据库和控制面令牌按环境隔离；`SARAP_INTERNAL_TOKEN` 与 `SARAP_ENGINE_TOKEN` 必须一致且足够长。
- 分析坐标系按试点配置，不要把 Web Mercator 当作分析原数据。
