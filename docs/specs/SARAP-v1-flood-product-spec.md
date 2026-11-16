# SARAP 第一版洪水场景产品规范与工作流

| 项 | 内容 |
| --- | --- |
| 文档编号 | SARAP-SPEC-FLOOD-V1 |
| 版本 | v1.0.0（第一版冻结稿，供研发按此实现） |
| 日期 | 2026-11-14 |
| 状态 | 可供开发 |
| 适用产品 | SARAP 洪水淹没监测（Sentinel-1 + SNAP） |
| 编写 | GIS行业专家 |

---

## 1. 目标、范围与明确不做的事

### 1.1 目标

第一版在可配置试点区内，基于 **Sentinel-1 GRD** 和 **SNAP**，在影像可用后尽快产出应急可用的洪水产品，核心是 **把范围做准、把影响对象对上**，支撑值班研判和简单统计出图。

交付四类结果：

1. **淹没范围**：当期水体范围（栅格 + 矢量）。
2. **本次淹没**：与本底库对比后的新增/本次淹没范围（栅格 + 矢量）。
3. **简单影响统计**：与第一版可落地的专题对象叠加后的面积、长度、落在区内的对象数量。
4. **应急专题图**：固定版式的出图（PNG/GeoPDF），含图例、采集时间、本底版本、置信说明。

### 1.2 范围（第一版必须做）

- 数据源只接 Sentinel-1 IW GRD（VV 必选，VH 同步处理作辅助）。
- 处理引擎先挂 SNAP（生产路径用 `gpt` 图，不把 snappy 作为主路径）。
- 本底库按 **平台数据资产** 管理，不是任务临时文件。
- 试点区、阈值策略、统计对象集、出图模板均可配置。
- 流程按 **小时级出图时效** 设计（从「影像对任务可见」到「产品可发布」的时限，不是 Sentinel-1 每小时一景）。

### 1.3 明确不做（第一版禁止对外承诺）

- **不承诺精细水深**。不得输出以米为单位的水深产品，不得在专题图或接口里把范围当成水深。若后续要做水深，另开版本，且须有 DEM、水力或实测约束。
- 不承诺林下/建筑物内部积水的完整探测（SAR 在这些场景以漏提为主，只做低置信标注）。
- 不承诺小时级重访。Sentinel-1 重访通常是数天级（双星约 6 天量级，还受轨道和覆盖限制）。产品元数据必须同时给出 **成像时间** 和 **产品生成时间**，避免被理解成「每小时实况」。
- 第一版不做多源光学融合、不接其他雷达卫星、不做三维淹没推演。

### 1.4 精度定位（对外口径）

- 几何：精轨 + 距离多普勒正射后，平面定位精度按 **1～2 个像元（约 10～20 m）** 管理，不以亚像元精度验收。
- 专题：开放水体和洪泛平原上的连片淹没是主场景；建成区、雷达阴影、薄水/湿土是主要不确定区，必须有质控标记，不能 silently 当成确定淹没。
- 面积：统计值应带最小制图单元和栅格分辨率引起的约定量级说明（见第 10 节），避免把像元计数当成测绘面积。

---

## 2. 术语

| 术语 | 定义 |
| --- | --- |
| 当期水体 `water_current` | 本景（或本景拼幅）提取出的全部水体，含常年水体和本次淹没。 |
| 本底水体 `water_baseline` | 本底资产在生效版本、生效时段、适用区域内的参考水体。 |
| 本次淹没 `flood_event` | `water_current` 减去本底水体（及可选的「事件前水体」）后的新增淹没。常年水体不是本次淹没。 |
| 疑似水体 `water_lowconf` | 通过提取规则但落在质控风险区（建成区、阴影/叠掩、陡坡、薄水边缘等）的像元。 |
| 本底资产 | 平台级、可版本化、可审核、可被多任务引用的参考数据集，不是某次作业的中间文件。 |
| 算法配置档 `algo_profile` | 一套预置的 SNAP 参数 + 提取/质控阈值，与试点区绑定，可覆盖。 |
| 最小制图单元 MMU | 小于该面积的图斑予以剔除或降为低置信。第一版默认 **0.3 ha（3×10³ m²，约 30 个 10 m 像元）**，试点区可改。 |
| 小时级出图 | 生产时限目标，不是观测频率。 |

类别编码（栅格统一用 8-bit）：

| 值 | 名称 | 含义 |
| --- | --- | --- |
| 0 | nodata | 无数据、处理失败、轨道外、已被质量掩膜剔除且不参与统计 |
| 1 | non_water | 确定非水 |
| 2 | permanent_or_baseline_water | 当期为水且与本底一致（常年/本底水体） |
| 3 | flood_event | 本次淹没（确定级） |
| 4 | water_lowconf | 疑似水体/低置信，不进入默认「本次淹没」统计，但保留供复核 |

另输出独立的 `qc_flags` 位掩膜（见第 9 节），不要把质控信息只藏在分类值里。

---

## 3. 总体数据流与小时级时效设计

### 3.1 数据流

```
Sentinel-1 IW GRD 到达（CDSE/ASF 等）
    → 入库与元数据解析（scene_id、轨道、极化、IPF、起止时间、footprint）
    → 与试点 AOI 空间相交？否：忽略或只建档
    → 是：创建处理任务（幂等键见 13.3）
    → 按 AOI 裁剪/选片，降低计算量
    → SNAP gpt 预处理（轨道→热噪声→定标→滤波→地形校正→dB）
    → 水体提取（自适应阈值，失败则回退预置阈值）
    → 叠加质控掩膜（叠掩/阴影、坡度、建成区、入射角、MMU）
    → 与指定本底资产版本做变化检测，得到本次淹没
    → 矢量化与属性写入
    → 与统计对象叠加，出简单影响表
    → 渲染应急专题图
    → 写产品元数据、质检摘要，进入审核/自动发布策略
```

建议中间结果与正式产品分库：SNAP 中间件、临时栅格可清理；正式产品与本底资产不可当作临时文件删除。

### 3.2 小时级出图的真实含义

Sentinel-1 **不能**按小时成像。第一版把「小时级」落实为下面几条，研发必须按此时限设计，而不是按「每小时一景」设计调度。

| 阶段 | 时限目标（影像对平台可见起算） | 说明 |
| --- | --- | --- |
| 发现与建任务 | ≤ 10 min | 订阅/轮询 + footprint 与试点区相交判断 |
| SNAP 预处理 + 提取 | ≤ 40 min | 必须先按 AOI 裁剪；单试点区（约市级及以下）在 16 核/32 GB 量级机器上应可控制在此窗口 |
| 变化检测、统计、出图、入库 | ≤ 10 min | 本底和统计图层必须预投影、预裁剪、预建空间索引 |
| **端到端（可见→可发布）** | **≤ 60 min** | 超时要告警并保留断点，不得静默失败 |

实现约束：

- 尽早裁剪：SNAP 读入后或用子集图先切 AOI 外扩 2 km（避免边缘滤波伪影），禁止对整景 IW 全程跑完再裁。
- 预热：精轨、DEM、陆地覆盖、本底、行政区等要本地缓存，不允许运行时现下导致排队。
- 并行粒度：按「试点区 × 景」为任务，多试点区同时命中同一景时共享预处理切片，避免重复校正。
- 产品时间字段分开写：`acquisition_start/end`、`processed_at`、`published_at`、`sla_minutes`。
- 架构预留：任务模型不要写死「只等 S1」；后续若接更高频数据源，只换采集适配器，后续步骤保持不变。

若单景覆盖试点区不完整，仍产出 **部分覆盖产品**，元数据标记 `coverage_ratio`，专题图注明「本景未完整覆盖试点区」。

---

## 4. 数据源与输入

### 4.1 主数据（第一版唯一雷达源）

| 项 | 规定 |
| --- | --- |
| 卫星/模式 | Sentinel-1 A/C（及仍可用的历史 B）IW GRD |
| 产品级别 | GRD High Resolution，优先 Ground Range Detected，**不在第一版做 SLC 干涉水深** |
| 极化 | VV 为水体提取主通道；VH 必须一并预处理，用于辅助判定和质控，不单独作为主提取（除非配置档显式打开 VH 联合规则） |
| 轨道 | 升降轨都可跑；同一事件序列里 **优先与本底/前时相同一轨道方向** 的景，减少入射角和叠掩几何差异 |
| 分辨率 | 地形校正输出默认 10 m |
| 输入包 | SAFE 或平台已转的 COG 均可，但 SNAP 图以官方 SAFE 为基线路径 |

下载与编目由平台负责。本规范只要求每景至少具备：`scene_id`（推荐用官方 PRODUCT-ID）、平台/模式/极化、绝对轨道号、飞行方向、IPF 版本、起止时间（UTC）、footprint、本地路径、校验和。

### 4.2 辅助数据（必须预置为平台资产或本地缓存）

| 数据 | 用途 | 第一版建议 |
| --- | --- | --- |
| 精密轨道 | Apply-Orbit-File | 精轨优先，失败回退恢复轨道，并在元数据标记 `orbit_type` |
| DEM | 地形校正、坡度、叠掩/阴影 | 优先 Copernicus DEM 30 m；缺覆盖再 SRTM 1Sec。同一试点区锁定一个 DEM 版本 |
| 建成区/不透水面 | 误提/漏提质控 | 可用 GlobelCover/ESRI/动态世界/国内土地覆盖中的城镇类，分辨率尽量 ≤ 10～30 m |
| 坡度/水面掩膜派生 | 陡坡排除 | 由锁定 DEM 预计算，坡度阈值默认 15° |
| 常年水体参考（可选校验） | 抽检本底合理性 | JRC GSW occurrence、全国水系等，只作质检对照，不替代本底资产 |

### 4.3 统计对象（专题输入）

见第 10 节。必须与本底一样按资产入库（版本、适用区域、审核状态），禁止任务临时 shp 直跑无人管理。

---

## 5. 本底库（平台数据资产）规范

本底不是「这次任务用的一张临时水体图」。它是可被多个任务、多期产品引用的平台资产。没有有效本底，不得自动发布「本次淹没」产品（可只发布当期水体，并标记 `flood_event_status=baseline_missing`）。

### 5.1 本底类型（第一版）

| type | 含义 | 第一版要求 |
| --- | --- | --- |
| `permanent_water` | 常年/稳定水体（河湖库塘等） | **每个试点区至少 1 份已发布版本**，否则该区不能出「本次淹没」 |
| `seasonal_water` | 分旬/分月的季节性水体 | 可选；有则优先于单纯常年本底，按成像日期匹配生效时段 |
| `preevent_water` | 由事件前最近一景（同轨道优先）提取的水体 | 可选增强。与常年本底组合：本次淹没 = 当期水 −（常年 ∪ 事件前） |
| `ref_dem` / `ref_landcover` / `ref_admin` / `ref_road` / `ref_cropland` / `ref_settlement` | 参考与统计底图 | 按资产管，规则同本底 |

第一版默认变化检测口径：

```
flood_event = water_current − water_baseline_effective
```

其中 `water_baseline_effective` 的选择规则：

1. 若配置了 `seasonal_water` 且成像时刻落在某版本生效时段内，用该季节本底；
2. 否则用已发布的 `permanent_water`；
3. 若任务开启 `use_preevent=true` 且能找到合格事件前景，则再并上事件前水体；
4. 事件前景合格条件：与当期同极化、**同升降轨**、时相在事件前配置窗口内（默认 2～24 天，可配）、覆盖试点区比例 ≥ 90%（可配）、其自身质控通过。

### 5.2 资产主记录与版本（逻辑模型）

研发可拆表，但字段语义必须覆盖以下内容。

**资产主表 `data_asset`**

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| asset_id | string | 稳定主键 |
| asset_code | string | 人类可读编码，如 `BASE_PERM_WATER_PILOT_A` |
| name | string | 显示名 |
| asset_type | enum | 见上表 type |
| description | text | 来源与用途 |
| owner | string | 责任人/团队 |
| default_crs | string | 如 EPSG:4490 |
| status | enum | `active` / `archived` |
| created_at / updated_at | datetime | 使用 Asia/Shanghai 展示，存储 UTC |

**版本表 `data_asset_version`**

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| version_id | string | 主键 |
| asset_id | string | 所属资产 |
| version_no | string | 如 `v2026.06.01`，同一资产内唯一 |
| valid_from | datetime | 生效起始（含），必填 |
| valid_to | datetime | 生效结束（不含）；空表示当前仍有效 |
| applicable_area | geometry | 适用区域，建议 Polygon/MultiPolygon，CRS 明确 |
| applicable_area_name | string | 如试点区名、流域名 |
| review_status | enum | `draft` / `pending_review` / `published` / `rejected` / `deprecated` |
| reviewer | string | 审核人，draft 可空 |
| reviewed_at | datetime | 审核时间 |
| review_comment | text | 审核意见 |
| source | string | 生产来源：人工整编 / 多时相 S1 合成 / 业务导入 等 |
| algorithm_profile_id | string | 若由算法生成，记录配置档 |
| spatial_res_m | number | 像元大小（米） |
| crs | string | 该版本数据 CRS |
| gsd_note | string | 精度说明 |
| checksum | string | 文件哈希 |
| byte_size | integer | |
| storage_uri | string | 对象存储或文件路径，**禁止**只存在某任务工作目录 |
| preview_uri | string | 预览图 |
| schema_json | json | 栅格取值或矢量字段说明 |
| lineage | json | 源数据清单与处理说明 |
| created_by / created_at | | |

约束：

- 只有 `review_status=published` 的版本可被正式产品引用。
- 同一资产在同一地点、同一时刻，允许存在多个 published 版本，但必须能解析出 **唯一有效版本**：按 `valid_from/valid_to` 包含成像时间，再按 `applicable_area` 包含试点区；若仍冲突，用配置的 `preferred_version_id`，否则任务失败并告警，禁止静默任选。
- `deprecated` 版本仍可追溯历史产品，不可再被新任务选中。
- 删除必须是软删除；已被产品引用的版本不可物理删。

### 5.3 本底内容规定（水体类）

- 栅格：与产品相同的类别约定中，至少能区分 nodata 与水体；推荐 0/1（非水/水），分辨率 10 m，COG，LZW/DEFLATE，内部瓦片 256 或 512。
- 必须提供同版本矢量（或多边形化结果）便于人工审核。
- 适用区域外必须是 nodata，不能填 0 冒充「无水」。
- 建议附一份「编制说明」：时相范围、使用景数、阈值或人机交互步骤、已知缺陷（例如某段干涸河床是否纳入常年水）。

### 5.4 本底审核最低要求（第一版）

发布前至少通过：

1. CRS、分辨率、范围与试点区配置一致；
2. 与公开常年水体或已知河湖对照，重合率抽检（记录在 `lineage`，不设一刀切全国阈值，由试点区给出通过标准）；
3. 目视抽检：主干河湖是否漏，建成区、山地阴影是否大量误入；
4. 审核状态流转留下记录。

---

## 6. SNAP 处理步骤与预置参数

生产路径：**SNAP `gpt` + 预置 Graph XML**，参数由 `algo_profile` 注入。第一版锁定 SNAP 主版本后写入产品元数据 `snap_version`（建议 9.x 或 10.x，全环境一致，禁止混用）。

下列参数为 **默认配置档 `s1_grd_flood_v1`**。试点区可以覆盖阈值类参数，但不得随意改操作顺序，除非升版本号。

### 6.1 处理链（顺序固定）

1. `Read`（SAFE）
2. `Subset`（按试点区外扩 2 km 的 WKT/bbox；若 Graph 对复杂多边形支持不稳，先矩形外扩再在后处理精确裁）
3. `Apply-Orbit-File`
4. `Remove-GRD-Border-Noise`（按 IPF 版本条件执行，见下）
5. `ThermalNoiseRemoval`
6. `Calibration`
7. `Speckle-Filter`
8. `Terrain-Correction`
9. `LinearToFromdB`
10. `Write`（BEAM-DIMAP 或 GeoTIFF；后处理统一转 COG）

说明：部分新 IPF 产品已做边界噪声抑制。规则为：**IPF < 3.10 必须做步骤 4；IPF ≥ 3.10 默认跳过**，但在配置档保留开关 `force_border_noise_removal`。

### 6.2 预置参数

**Apply-Orbit-File**

| 参数 | 预置值 | 说明 |
| --- | --- | --- |
| orbitType | Sentinel Precise (Auto Download) | 精轨 |
| polyDegree | 3 | |
| continueOnFail | true | 精轨失败则继续，后写 `orbit_type=restituted_or_predicted` |

任务开始前应尽可能预拉精轨。若只用到恢复轨，产品置信在元数据中降一级（`orbit_quality=degraded`），不因此直接失败。

**Remove-GRD-Border-Noise**

| 参数 | 预置值 |
| --- | --- |
| selectedPolarisations | VV,VH（按实际波段） |
| borderLimit | 500 |
| trimThreshold | 0.5 |

**ThermalNoiseRemoval**

| 参数 | 预置值 |
| --- | --- |
| selectedPolarisations | VV,VH |
| removeThermalNoise | true |
| outputNoise | false |

**Calibration**

| 参数 | 预置值 | 说明 |
| --- | --- | --- |
| auxFile | Latest Auxiliary File | |
| outputSigmaBand | true | 输出 σ⁰（线性） |
| outputBetaBand | false | |
| outputGammaBand | false | |
| outputImageScaleInDb | false | **先线性定标，地形校正后再转 dB**，避免中间重采样在 dB 域引入偏差 |
| sourceBands | Intensity_VV，若有则加 Intensity_VH | |

**Speckle-Filter**

| 参数 | 预置值 | 说明 |
| --- | --- | --- |
| filter | Refined Lee | 保边，利于水体边界 |
| filterSizeX / filterSizeY | 7 | 窗口 7×7 |
| dampingFactor | 1 | 部分滤波类型使用，按算子默认即可 |
| estimateENL | true | 若算子提供 |
| enl | 1.0 | 仅在不估计时使用 |

禁止在第一版用过大窗口（≥ 11）换平滑，否则细河道和淹没边界会被吃掉。

**Terrain-Correction（Range-Doppler）**

| 参数 | 预置值 | 说明 |
| --- | --- | --- |
| demName | Copernicus 30m Global DEM | 缓存本地；缺幅再切 SRTM 1Sec HGT |
| demResamplingMethod | BILINEAR_INTERPOLATION | |
| imgResamplingMethod | BILINEAR_INTERPOLATION | |
| pixelSpacingInMeter | 10.0 | |
| mapProjection | 试点区配置的 **分析投影**（见 12.2） | 不要用 Web Mercator 做分析 |
| saveDEM | true | 供坡度/质控 |
| saveIncidenceAngleFromEllipsoid 或对应入射角波段 | true | 供入射角过滤 |
| saveLatLon | false | 除非调试 |
| maskOutAreaWithoutElevation | true | |
| nodataValueAtSea | 按试点区 | **沿海试点必须关闭「把海面当 nodata」的误伤**；内陆默认可开。配置项 `mask_sea_nodata` |
| alignToStandardGrid | true | 便于与本底、多时相对齐 |
| standardGridOriginX/Y | 按试点区锁定的网格原点 | 同一试点区所有产品、本底必须落在同一 10 m 网格 |

若 SNAP 版本参数名略有差异，以实现等效为准，并在 `algo_profile` 里记录实际参数键。

**LinearToFromdB**

| 参数 | 预置值 |
| --- | --- |
| sourceBands | Sigma0_VV, Sigma0_VH（若有） |
| multiplier | 10（线性→dB 的常用算子设置，按 SNAP 算子实际字段填写） |

输出波段命名统一为 `Sigma0_VV_dB`、`Sigma0_VH_dB`。后处理不得再对已是 dB 的波段重复取对数。

### 6.3 叠掩/阴影掩膜

在地形校正之后（或用 SNAP `SAR-Simulation` / 官方 layover-shadow 算子，以所选 SNAP 版本可用者为准）生成：

- `mask_layover`（叠掩）
- `mask_shadow`（雷达阴影）

第一版若某环境算子不稳定，最低限度也要用 DEM 坡度 + 局部入射角做近似掩膜，并在元数据写 `shadow_mask_method=full` 或 `proxy_slope_incangle`。近似法不得宣称「已精确扣除叠掩」。

### 6.4 GPT 图（逻辑示例，实施时按 SNAP 版本生成合法 XML）

参数用变量占位，由任务注入，禁止把路径写死在仓库唯一一份图里却无法按区配置。

关键变量：`${input}` `${aoiWkt}` `${orbitType}` `${demName}` `${mapProjection}` `${pixelSpacing}` `${output}`。

### 6.5 失败与降级

| 情况 | 处理 |
| --- | --- |
| 精轨下载失败 | 用恢复轨继续，标记 orbit 质量降级 |
| DEM 缺口 | 缺口区 nodata，不插值填假值；覆盖不足 80% 则任务失败 |
| 某极化缺失 | 仅 VV 也可出第一版产品，标记 `polarization=VV_only`；无 VV 则失败 |
| SNAP 崩溃 | 重试 1 次；仍失败则任务失败并保留日志 |

---

## 7. 水体提取与变化检测口径

全部提取在 **分析投影、10 m 网格、σ⁰(dB)** 上进行。阈值单位是 dB。

### 7.1 有效像元

同时满足才进入提取：

- 非 nodata；
- 入射角在配置区间内（默认 **30°～45°**，试点可调；超出的记入 qc，不进确定水体）；
- 不在叠掩掩膜内（叠掩默认直接排除）；
- 可选：不在「无高程」掩膜内。

雷达阴影不在此步直接当非水删除（阴影很像暗水面，见第 8 节），而是进质控。

### 7.2 主规则：VV 自适应阈值 + 夹逼

对试点区内有效像元的 `Sigma0_VV_dB` 做直方图：

1. 先用建成区和坡度＞15° 的像元 **不参与阈值估计**（避免把城市暗区和阴影当水体峰）。
2. 若直方图呈双峰且峰间可分，用 **KI（Kittler–Illingworth）** 或 Otsu 求阈值 `T_auto`。
3. 将 `T_auto` **夹逼** 到配置区间。默认夹逼区间：**[-23, -14] dB**。
4. 若无法稳定双峰（单峰、峰分离度不足、有效像元过少），回退到试点区预置阈值 `T_default`（默认 **-18 dB**）。
5. 主判定：`Sigma0_VV_dB < T` 为候选水体。

必须把实际使用的 `T`、`T_auto`、是否回退、直方图统计写入产品元数据，保证可复现。

### 7.3 辅规则（默认开，可关）

在 VV 候选基础上，用 VH 做弱约束，减少部分湿土/薄植被误提：

- 若存在 VH：候选水体若 `Sigma0_VH_dB > T_VH_bright`（默认 **-12 dB**，即 VH 仍偏亮），降为 `water_lowconf`，不直接当确定水。
- 第一版 **不单独用 VH 阈值提水**（VH 对水体更乱，易扩误提）。

配置项：`use_vh_constraint=true`。

### 7.4 形态与最小制图单元

顺序固定：

1. 去除面积小于 MMU 的候选图斑（默认 0.3 ha）。被删小斑若与确定水体邻接且距离 ≤ 1 像元，可选择并回（默认关闭，试点可开 `keep_adjacent_small_patches`）。
2. 形态学闭运算（默认结构元 3×3，消除内部小孔），再开运算（默认 3×3，去毛刺）。结构元边长可配，默认不超过 3 像元。
3. 闭运算后仍小于 MMU 的图斑删除。

河网细河道可能被 MMU 误删。试点区若以窄渠为主，应把 MMU 降到 0.1 ha，并在配置中写明理由。

### 7.5 变化检测（本次淹没）

```
water_current_hard = 确定水体（分类值即将写入 2 或 3 的像元，不含 4）
flood_event        = water_current_hard AND NOT water_baseline_effective
baseline_water     = water_current_hard AND water_baseline_effective
```

附加规则：

- 本底 nodata 的位置：当期即使提水，也只能进 `water_lowconf` 或单独标记 `baseline_gap`，**不得自动算作本次淹没**。
- 低置信像元（值 4）默认不进影响统计的「本次淹没」口径；统计表可另给一列「含低置信」供内部看，对外默认口径不含。
- 可选模式 B（事件对：前时相减后时相）作为增强，不替代本底差：

  `sigma0_pre_dB - sigma0_post_dB ≥ D_th` 且 `sigma0_post_dB < T`，`D_th` 默认 **3 dB**，且必须同轨道方向、已配准到同一网格。

  模式 B 与本底差的交集可作为「高置信本次淹没」内部标识，第一版对外仍只用本底差作为官方口径，避免两套数。

### 7.6 禁止的做法

- 用全球固定单一阈值、不允许试点区覆盖。
- 在 Web Mercator 上提水和算面积。
- 把本底文件拷到任务目录后失去版本引用，只写文件名不写 `version_id`。
- 用光学水体指数冒充本版结果（本版数据源仅 S1）。

---

## 8. 质检要点与常见误提

每景自动生成 `qc_flags` 和一份 `qc_summary`。质检不是可选项。下列三类是第一版必须处理的风险。

### 8.1 建成区（误提 + 漏提同时存在）

**机理简要：** 光滑屋面、部分路面、雷达几何造成的暗区会被当成水（误提）；洪水进入街巷时，二面角散射往往仍然偏亮，导致 **城市内涝大量漏提**。第一版不能假装能做准城市水深或室内积水。

**自动规则：**

- 叠建成区资产。建成区内的候选水体，默认降为 `water_lowconf`（值 4），并打 flag `URBAN`。
- 配置允许 `urban_policy=downgrade`（默认）或 `urban_policy=keep_with_flag`（保留为确定水但必须出旗标，仅当试点明确要「宁可误提也要提示城区积水」时使用）。
- 禁止第三种：直接把建成区全部掩成非水且不留痕迹。

**抽检要点：**

- 看机场跑道、停车场、工业厂房屋顶是否成片误提。
- 看沿河城区：若光学或灾情报道有积水但产品全空，属于预期限制，应在专题图注明「建成区探测能力有限」，不要在验收里当缺陷无限升级；但若把大片干燥屋顶报成淹没，属于缺陷。

### 8.2 阴影与叠掩

**机理：** 雷达阴影、部分陡坡背坡的低回波与开阔水体一样暗；面向雷达的叠掩则偏亮且几何错位。

**自动规则：**

- 叠掩区：强制 nodata 或非水，打 flag `LAYOVER`，不参与提取。
- 阴影区（或坡度＞阈值的近似阴影）：候选水体降为低置信，打 flag `SHADOW`。默认坡度阈值 **15°**，山区试点可降到 10°（更保守）。
- 与本底河湖相交的阴影区：若本底已是水，可维持本底水体，但不得把阴影新增部分计为本次淹没。

**抽检要点：**

- 山区河谷是否出现与方位向一致的条带状「假洪水」。
- 高楼背后是否出现规则暗条被提水。
- 对比升降轨（若有）：只在某一轨出现、且贴着山脊/楼影的图斑，高度可疑。

### 8.3 薄水、湿土与光滑地表

**机理：** 浅薄水层、雨后湿土、裸土、沙滩、收割后农田，σ⁰ 可能落在阈值附近，导致边界抖动或大面积浅色误提；植被遮挡的薄水则漏提。

**自动规则：**

- 水体边界外扩 1 个像元的边缘带打 flag `EDGE_MIXED`，统计时可单列，不改变确定范围多边形（多边形仍用硬分类）。
- 若开启 VH 约束，VH 偏亮的暗 VV 像元降为低置信（见 7.3）。
- 可选：与「裸土/耕地且非灌溉期」图层相交的新建图斑，若平均 σ⁰ 距阈值不到 1 dB，降为低置信，打 flag `THIN_OR_SOIL`。没有可靠耕地物候时不要启用这条，以免误伤真实农田淹没。

**抽检要点：**

- 雨后旱地、河滩、沙地是否一夜「全淹」。
- 已知浅淹农田是成片漏还是碎斑；碎斑可调 MMU，成片漏应检查阈值是否过低（太严）。
- 细小沟渠被 MMU 抹掉是否可接受（由试点用途决定）。

### 8.4 其他必做自动检查

| 检查 | 规则 | 超限处置 |
| --- | --- | --- |
| 入射角 | 超出 30°～45° 打 `INCIDENCE` | 不进确定水 |
| 面积暴涨/暴跌 | 本次淹没占试点陆地面积比例超过配置上限（默认 40%）或低于极小值且与历史差过大 | 自动发布阻断，转人工复核 |
| 本底覆盖 | 本底在试点区内有效像元比例 < 95% | 不可自动发布本次淹没 |
| 碎片度 | 确定淹没图斑数异常多、平均面积接近 MMU | 写入警告，不自动失败 |
| 轨道质量 | 非精轨 | 警告，可发布但标注 |
| 网格对齐 | 与本底网格偏移 | 失败，必须重裁重采样，禁止隐性平移 |

### 8.5 质控摘要（随产品）

至少包括：使用阈值及是否回退、有效像元比例、确定水体/本次淹没/低置信面积、各 flag 面积、本底 version_id、orbit 类型、覆盖率、是否触发人工复核。

---

## 9. 图层与元数据规范

### 9.1 坐标系与网格

| 用途 | 规定 |
| --- | --- |
| 分析、统计、正式栅格/矢量 | 试点区 `analysis_crs`（中国试点优先 CGCS2000 高斯克吕格 3° 带，如 EPSG:4544–4549 等，按中央经线选带） |
| 交换/预览瓦片 | 可另出 EPSG:4490 或 EPSG:4326 的 COG/矢量副本；Web Mercator 只用于展示瓦片，不作为分析原件 |
| 网格 | 10 m，`alignToStandardGrid`，原点在试点配置中锁死 |
| 面积单位 | m² 与公顷，在投影坐标系计算 |

高程基准只用于 DEM 质控，第一版产品不发布高程或水深。

### 9.2 产品命名

```
SARAP_FLOOD_{pilot_id}_{S1_PID}_{acq_start:%Y%m%dT%H%M}_{baseline_version_no}_{algo_profile}_{prod_ver}
```

文件名只含 ASCII、下划线。同一输入再跑必须升 `prod_ver` 或覆盖同一幂等键并保留 lineage。

### 9.3 必选图层

| 图层名 | 形式 | 取值/字段 | 说明 |
| --- | --- | --- | --- |
| `class_map` | GeoTIFF/COG, Byte | 0–4 见第 2 节 | 官方分类图，带内嵌色表与 `CATEGORY_NAME` |
| `flood_event` | COG, Byte | 0/1 | 本次淹没（仅确定级）的二值便捷层 |
| `water_current` | COG, Byte | 0/1 | 当期确定水体（含本底水 + 本次淹没） |
| `qc_flags` | COG, UInt16 | 位掩膜 | 见下 |
| `flood_event_poly` | GeoPackage（首选）或 Shapefile 备份 | 见属性 | 本次淹没多边形 |
| `water_current_poly` | GeoPackage | 见属性 | 当期确定水体 |
| `sigma0_vv_db` | COG, Float32 | dB | 可选但强烈建议随产品归档，便于复盘；对外分发可关 |
| `thematic_map` | PNG + GeoPDF | — | 见第 11 节 |
| `impact_stats` | GeoPackage 表 + CSV | 见第 10 节 | |
| `qc_summary` | JSON | 见 8.5 | |
| `metadata` | JSON | 见 9.5 | 与库表一致 |

`qc_flags` 位定义（可扩展，已用位不得改语义）：

| 位 | 名称 | 含义 |
| --- | --- | --- |
| 0 | URBAN | 建成区 |
| 1 | SHADOW | 雷达阴影或陡坡代理阴影 |
| 2 | LAYOVER | 叠掩 |
| 3 | INCIDENCE | 入射角超区间 |
| 4 | EDGE_MIXED | 水体边缘混合像元 |
| 5 | THIN_OR_SOIL | 薄水/湿土可疑 |
| 6 | BASELINE_GAP | 本底缺测 |
| 7 | MMU_REMOVED | 因 MMU 剔除（若需回溯可单独层，占位） |
| 8 | ORBIT_DEGRADED | 该景轨道质量降级（可整景写在元数据，不一定逐像元） |

### 9.4 矢量属性（`flood_event_poly` / `water_current_poly`）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| fid | integer | |
| product_id | string | |
| class_code | integer | 2 或 3（水体多边形按类拆开；本次淹没层只有 3） |
| area_m2 | double | 投影坐标计算 |
| area_ha | double | |
| perimeter_m | double | |
| confidence | string | `high` / `low`；官方范围层默认只有 high，低置信另层 `water_lowconf_poly`（建议第一版也出） |
| flags | integer | 图斑内主要 qc 位的或运算 |
| acq_start | datetime | |
| baseline_version_id | string | |

几何：面，允许 MultiPolygon。矢量化后做拓扑修复；简化容差默认 10 m（1 像元），不可过度抽稀。

### 9.5 产品元数据（最小集）

```json
{
  "product_id": "",
  "product_type": "SARAP_FLOOD_V1",
  "product_version": "1.0.0",
  "pilot_id": "",
  "scene_id": "",
  "platform": "S1A",
  "mode": "IW",
  "product_level": "GRD",
  "polarizations": ["VV", "VH"],
  "pass_direction": "ASCENDING",
  "ipf_version": "",
  "orbit_type": "precise",
  "acquisition_start": "2026-01-01T11:22:33Z",
  "acquisition_end": "2026-01-01T11:23:00Z",
  "processed_at": "2026-01-01T13:00:00Z",
  "published_at": null,
  "sla_minutes": 58,
  "crs": "EPSG:4548",
  "resolution_m": 10,
  "grid_origin": [0, 0],
  "aoi_coverage_ratio": 0.96,
  "algo_profile_id": "s1_grd_flood_v1",
  "snap_version": "10.0.0",
  "threshold_vv_db": -17.6,
  "threshold_vv_source": "auto_clamped",
  "threshold_default_db": -18.0,
  "mmu_ha": 0.3,
  "baseline_asset_id": "",
  "baseline_version_id": "",
  "baseline_type": "permanent_water",
  "preevent_scene_id": null,
  "urban_policy": "downgrade",
  "water_current_ha": 0,
  "flood_event_ha": 0,
  "lowconf_ha": 0,
  "review_status": "draft",
  "limitations": [
    "第一版不提供水深",
    "建成区探测能力有限",
    "Sentinel-1 非小时级重访"
  ]
}
```

`review_status` 与本底类似：`draft` / `pending_review` / `published` / `rejected`。自动质控通过且未触发阻断规则的，可按试点配置自动到 `published`。

---

## 10. 影响统计对象（第一版可落子集）

原则：只统计 **已经作为平台资产发布**、并与分析网格/投影一致（或任务中按标准流程重投影）的对象。统计对「本次淹没确定级」为默认口径，另输出「含低置信」附录列。

### 10.1 第一版必做

| 对象 | 建议层级 | 指标 | 说明 |
| --- | --- | --- | --- |
| 行政区 | 县级 + 乡镇级（有则做） | 淹没面积 m²/ha、占该行政区面积比例 | 最优先，几乎总能落地 |
| 耕地 | 多边形或 10～30 m 分类中的耕地类 | 淹没面积、占该区耕地比例 | 有全国/省级土地利用或耕地图即可做 |
| 道路 | 线，建议县道及以上（含高速、国省县道） | 受淹道路长度 m/km（线与淹没多边形相交的长度） | 第一版不做通行中断研判，只报「空间上相交的长度」 |
| 居民点 | 城镇村建设用地多边形，或居民地点（有面用面） | 相交面积或「被淹没范围压盖的居民点个数」 | 建成区提水能力弱，统计值要在表注里写「可能低估城内积水」 |

### 10.2 第一版不做或仅预留

学校、医院、危化、泵站、堤防、人口估算、经济损失、水深分区——预留对象编码和接口，数据不齐就不要在第一版页面上留空栏目充数。

### 10.3 统计表结构（每类一张或统一长表）

长表建议字段：

`product_id, object_type, object_id, object_name, parent_admin_code, metric, value, unit, scope(default|including_lowconf), baseline_version_id, computed_at`

`object_type` 取值：`admin_county` `admin_township` `cropland` `road` `settlement`。

行政区还必须写出 `admin_code`（国标码，若有）。

### 10.4 统计口径细节

- 面积：栅格像元计数 × 100 m²，或矢量相交面积。第一版 **以与 `class_map` 一致的栅格分区统计为准**，矢量相交可作为对照，相对差超过 5% 写警告。
- 道路：线与 `flood_event` 多边形相交长度；道路数据若为双线或过宽缓冲，不在第一版做路宽改正，元数据注明「中心线相交长度」。
- 居民点为点时：点落在确定淹没多边形内即计数；点在低置信内只进附录。
- 所有比例分母用对象自身在试点区内的面积/长度，不用试点区总面积当所有分母。
- 结果保留：面积公顷 2 位小数，平方米整数，长度米整数、公里 2 位小数。
- 对外展示必须附一句限制：「统计基于雷达提取范围与专题数据叠加，建成区可能低估，不含水深和人口。」

---

## 11. 应急专题图规范

### 11.1 输出

- 主文件：`thematic_map.pdf`（GeoPDF 或普通 PDF + 同期 PNG 预览 `thematic_map.png`，建议 300 dpi 长边 4000 像素内可调）。
- 必须能按试点区套用模板，模板本身也是可版本化资产。

### 11.2 版式最低要素

- 标题：`{试点区名称}洪水淹没范围（Sentinel-1）`
- 副标题：成像时间（转 Asia/Shanghai 显示，并标注 CST/UTC+8），轨道方向
- 主区：底图（浅色行政界与主要河流、道路）+ 本底水体（建议蓝色）+ 本次淹没（建议红色或橙色）+ 低置信（建议斜线或浅橙，可开关，默认开）
- 未覆盖区用灰色掩膜 + 文字「本景未覆盖」
- 图例、指北针、比例尺、坐标系、分辨率 10 m
- 本底资产名与版本号、算法配置档、产品 ID
- 固定脚注（不得省略）：
  - 「第一版产品给出淹没范围，不提供水深。」
  - 「建成区、山体阴影和薄水区域存在误提或漏提，请结合现场信息使用。」
  - 「本图反映成像时刻状况，非实时每小时监测。」
- 制图时间、制作系统：SARAP

颜色要考虑打印和色弱：不要只用红绿区分本底与本次淹没。

### 11.3 建议分幅

默认一张试点区全图；若区很大，可自动加「重点乡镇插图」（本次淹没面积最大的 1～2 个乡镇）。第一版不做复杂图集。

---

## 12. 试点区配置（必须可配置，禁止写死）

每个试点区一份配置（YAML/JSON 入库），修改配置不改代码。示例字段：

```yaml
pilot_id: pilot_xx
name: 示例试点
timezone: Asia/Shanghai
aoi:                      # Polygon，建议 GeoJSON 文件或库内 geometry
  crs: EPSG:4490
  geometry_uri: asset://...
analysis_crs: EPSG:4548   # 分析与统计投影
grid:
  res_m: 10
  origin_x: 0
  origin_y: 0
s1:
  modes: [IW]
  product_level: GRD
  polarizations: [VV, VH]
  pass_preference: same_as_baseline  # 或 ANY
algo_profile_id: s1_grd_flood_v1
overrides:                 # 只允许覆盖白名单参数
  T_default: -18
  T_clamp: [-23, -14]
  mmu_ha: 0.3
  slope_deg: 15
  incidence_deg: [30, 45]
  urban_policy: downgrade
  use_vh_constraint: true
  use_preevent: false
  mask_sea_nodata: false
  buffer_km: 2
baselines:
  permanent_water_asset_id: BASE_PERM_WATER_PILOT_XX
  seasonal_water_asset_id: null
  preferred_version_id: null
impact_assets:
  admin_county: ...
  admin_township: ...
  cropland: ...
  road: ...
  settlement: ...
publish:
  auto_publish_if_qc_pass: true
  flood_area_ratio_max: 0.4
map_template_id: flood_emg_v1
sla_minutes: 60
```

新试点 = 配 AOI + 发布常年水体本底 + 挂统计资产 + 选配置档。没有代码发版也可以上新区域。

---

## 13. 任务编排与幂等

### 13.1 状态机

`queued → preparing → snap_running → extracting → impact_mapping → qc → review_or_auto → published / failed / cancelled`

失败要写 `error_code` 和日志 URI，可从断点重跑（SNAP 成功则不要无故重跑校正）。

### 13.2 触发

- 新 S1 景 footprint 与任一启用试点区相交。
- 人工指定景 + 试点区重跑。
- 本底新版本发布后，允许对近期产品批量重算（可选，第一版可只支持手工触发重算）。

### 13.3 幂等键

```
(scene_id, pilot_id, baseline_version_id, algo_profile_id, param_hash)
```

相同键重复提交应返回已有任务/产品，除非 `force_rerun=true`（此时升 product 版本并保留旧产品）。

### 13.4 权限与发布

本底发布、产品自动发布开关属于业务权限，本规范只要求状态字段齐全、所有正式引用指向已发布资产版本。

---

## 14. 给研发的实现分工（可直接按此拆任务）

### 14.1 Python（处理链）

建议模块：

1. `ingest`：解析 SAFE/清单，写 scene 元数据。
2. `snap_runner`：渲染 Graph、调用 `gpt`、检查输出波段名、转 COG、写入 `orbit_type`/`snap_version`。
3. `extract`：直方图与 KI/Otsu、夹逼、VV/VH 规则、形态学、MMU。
4. `change`：按本底版本拉栅格，对齐网格（必须校验变换和原点），算本次淹没。
5. `qc`：建成区/阴影/叠掩/入射角/边缘，写 `qc_flags` 与 summary。
6. `vectorize`：polygonize、修复、简化、面积属性。
7. `impact`：raster zonal + 道路线相交。
8. `map`：基于模板出 PNG/PDF（matplotlib 或 QGIS atlas/pyqgis 均可，选一种锁死）。
9. `package`：组 metadata.json，上传到资产/产品存储，回调任务状态。

技术建议：`gpt` 为主；`rasterio`/`gdal`/`geopandas`/`shapely`/`skimage` 或 `opencv` 做后处理；COG 用 `gdal_translate -of COG`。单元测试至少覆盖：阈值夹逼、本底相减、MMU、建成区降级、网格不对齐要失败。

提供一份与第 6 节一致的 `s1_grd_flood_v1.xml.j2` 模板即可开工，不必等前端。

### 14.2 全栈（平台与接口）

必须先落库的对象：`data_asset`、`data_asset_version`（第 5.2 节字段）、`pilot_config`、`algo_profile`、`processing_job`、`product`、`product_layer`、`impact_stat`、审核日志。

接口最小集：

- 试点区 CRUD（含 AOI 上传、配置校验：缺已发布常年本底则不允许「启用自动本次淹没」）。
- 本底资产上传、版本、提交审核、发布、废弃；列表按区域/时段/状态筛选。
- 任务：按景自动建、手工建、重跑、查日志与 SLA。
- 产品：按试点区/时间检索，拉分类 COG、矢量、统计、专题图、元数据。
- 地图：COG 瓦片或 WMTS；前端分图层开关（本底水 / 本次淹没 / 低置信 / 行政区）。
- 权限：审核与发布和普通查看分离。

前端第一版页面建议三块：试点与资产治理、任务监控（含超时告警）、产品查看（地图 + 统计表 + 专题图下载）。不要在 UI 上出现「水深」入口。

展示时间一律 Asia/Shanghai，源数据时间存 UTC。

---

## 15. 验收标准（第一版）

功能：

- [ ] 对一个已配置试点区，投入一景相交的 S1 IW GRD，60 分钟内（测试环境硬件需达到第 3.2 节量级，否则按同等步骤跑通并记录实际耗时）产出第 9.3 节全部必选图层与专题图。
- [ ] 产品元数据包含本底 `version_id`、阈值来源、成像时间与处理时间。
- [ ] 无本底时不能自动发布本次淹没，但能出当期水体。
- [ ] 建成区误提默认进入低置信，而不是消失或直接算确定淹没（默认策略下）。
- [ ] 行政区、耕地、道路、居民点四类中，试点实际挂上的子集能出表；未挂的类不出现空壳指标。
- [ ] 新试点仅靠配置 + 本底发布即可运行，不改代码。

质量（试点预验收，定量门槛由试点区在启用时书面确认，下列为建议起步值）：

- 与人工勾绘或可靠光学（云量允许时）对照，开阔农田/洪泛区的本次淹没 IoU 作为主要指标，建议目标 ≥ 0.7；建成区不纳入该主要指标，单独评估误提率。
- 山影条带不得大面积进入确定级本次淹没。
- 面积统计与栅格像元计数误差 ≤ 5%。

文档与可复现：

- 同一幂等键结果一致（允许浮点/形态学极小差异，分类图斑级应稳定）。
- SNAP 版本、Graph、参数哈希入库。

---

## 16. 修订

后续若要增加水深、光学协同、小时级真重访数据源，另开 `v1.1+`，不得 silently 改第一版官方口径（尤其是「本次淹没 = 当期确定水 − 有效本底」）。
