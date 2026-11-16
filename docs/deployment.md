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

本地最近一次复跑结果（2026-11-16）：API 43 passed，引擎 54 passed。Web `npm run typecheck` 与 `npm run build` 通过。本环境没有 Docker 守护进程，镜像未在这里实际 build。

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
