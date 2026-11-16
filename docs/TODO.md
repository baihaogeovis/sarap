# SARAP TODO

按第一版里程碑排列（Asia/Shanghai，编码与 M1 起算日 2026-11-14）。编目本底、场景开通、质检发布、简报留在第一版必做；通知、多期对比、自动入库不进第一版必做。

## 进行中 / 马上要做

- [x] 补 `engine/Dockerfile`，让 `docker compose --profile engine up --build` 能以 mock 拉起引擎并后台跑任务。缺 `gpt` 的真实模式仍以 `GPT_NOT_FOUND` 失败。
- [x] mock 值班主路径：按项目区域（analysis_crs / AOI 可配）创建洪水任务，可选已入仓影像和已发布本底；mock 引擎跑完后，任务列表、任务详情和质检页能看到 succeeded 与 draft 产品。不下载 Sentinel-1，不需要 SNAP。
- [ ] 钉死第一版产品发布路径，并改 `apps/api` 的状态机、测试和 `apps/api/README.md` 使之与口径一致。需求与里程碑要求 `draft → submit → pending_qc → publish`（或 reject 回 `draft`），未质检不得进入默认一张图和简报；GIS v1.1.1 则允许 P0 最短发布。当前代码仍允许 `draft` 直接发布。撤回仅管理员、再发布必须新版本且 `re_qc_required`、时效用 `suggested_target_minutes=240` 这些保持不变。
- [x] 一张图默认视图展示所选区域已发布产品的淹没/水体矢量。mock 把 GeoJSON 随入库回传，API 按该区域 `analysis_crs` 转到 `EPSG:4326` 给 OpenLayers。草稿、待质检、已撤回不进默认图；没有已发布产品时显示空状态。
- [ ] 一张图 COG 瓦片，以及识别与 PNG 导出的进一步完善。
- [ ] 按 OpenAPI 生成 `packages/api-client`，替换占位包，给前端正式类型和调用。
- [ ] 继续完成 M1（至 2026-11-27）：登录三角色、项目/区域、场景开通、编目与本底库的可演示闭环。
- [ ] M2（2026-11-28 至 12-11）：任务中心 + SNAP 真链 + 简单质检发布闭环。
- [ ] M3（2026-12-12 至 12-18）：一张图与简报收口，第一版验收。

## 引擎与处理

- [ ] 在有 SNAP `gpt` 的环境中跑通真实处理链；缺 `gpt` 时必须报 `GPT_NOT_FOUND`，不得偷跑 mock。
- [ ] 正式引用本底时只认已发布的 `baseline_version_id`；多版本冲突按 `preferred_version_id` 解析，否则失败，禁止静默任选。
- [ ] 产品和任务稳定返回成像时间与 `s1_product_id`。
- [ ] 工作目录、对象存储和失败现场的保留策略按规范落地，避免已发布成果被覆盖。

## 平台与前端

- [ ] 生产环境关闭 `SARAP_SEED_ON_STARTUP`，更换 `SARAP_SECRET_KEY`、数据库密码、MinIO 密钥和内部令牌；JWT 测试密钥过短的警告一并处理。
- [ ] 管理端完善成员、区域停用、场景关闭后的任务规则（禁止新建，进行中可跑完，历史可查）。
- [ ] 简报模板与已发布产品引用、只读可见性。
- [ ] 高保真效果图如已出，对照补齐前端细节。

## 文档与发布

- [x] 本地第一版骨架（API、Web、引擎 mock）。
- [x] 本仓库的功能说明、架构说明、TODO、部署说明。
- [ ] 如需仓库改为私有：当前 GitHub 仓库是公开的，README 中的演示账号对所有人可见，确认是否要在 GitHub 上改为 Private。
- [ ] 试点区、目标用户（应急 / 水利）、单租户还是多租户，待产品确认后再写进配置，不在代码里写死承诺。

## 明确不进第一版必做

- 通知、多期对比、自动入库（需求 P1）。
- 精细水深。
- 引擎内下载 Sentinel-1。
- 并行 Java 后端。
