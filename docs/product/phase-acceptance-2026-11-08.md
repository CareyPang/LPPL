# LPPL 工作站 P0–P3 实施与验收矩阵

记录日期：2026-11-08。本文是 PR #50 的执行边界，不改变 LPPLS、顶部评价器、价格层或回测评分。

## 状态词

- **VERIFIED**：代码、测试或隔离证据已实际检查。
- **PR 作者报告**：PR 历史中已有的结果，本轮未重新建立同一证据。
- **NOT_ESTABLISHED**：不能从当前代码或隔离证据推出已可用。
- **NOT_INSPECTED**：本轮没有执行对应检查。
- **PLANNED**：已定义接口和验收条件，但尚未实现或接通。

## P0 个股工作站

### 当前实现

1. **VERIFIED**：浏览器本地 `workstation-ledger.v1` 保存自选股、最近分析、顶部区间成员、asof、来源、证据状态、stale 和首次/最近可见时间。
2. **VERIFIED**：顶部区间修订按 append-only 记录并做重复抑制；失败刷新保留可读行情并提供重试入口。
3. **VERIFIED**：行情和分析状态独立，分析失败不阻塞行情；状态文案区分失败、缓存和 stale。
4. **NOT_ESTABLISHED**：本地账本不是账号级跨设备数据，也没有写入 Worker、腾讯云数据库或 Pages。

### 接受标准

- 桌面和 390px：输入资产后先看到 OHLCV/成交量；后台分析可以排队、失败或重试。
- 每条区间显示分析截止日、行情截止日、来源、证据状态和 stale 原因。
- 同一 revision 不重复写入；刷新失败不能覆盖上次可读记录。
- 未来区间只画日期带，不伪造未来 K 线、成交量或价格目标。

## P1 A 股复盘

### 当前实现

1. **VERIFIED**：交易日历解析器可从显式日期文件得到 `asof/prior_asof`，并携带日历版本、来源 URL、哈希和覆盖范围。
2. **VERIFIED**：日终 runner 生成按日期命名的快照、latest 和 manifest；已有日期的 payload/context/manifest 发生冲突时拒绝覆盖，latest 只向前推进。
3. **VERIFIED**：涨停原因、题材标签、前一交易日涨停池和次日晋级仅在两份不同日期、完整 pool rows 和显式交易日历同时存在时计算；缺失写 `not_available`。
4. **VERIFIED**：market-context Worker 和前端 client 支持 latest/指定日期读取、轮询和 stale 展示，但默认关闭。
5. **NOT_ESTABLISHED**：定时任务仍从干净 checkout 开始；没有可证明的跨运行累积存储。两日真实快照仍在 D 盘隔离证据目录，未导入 Worker/Pages。
6. **NOT_ESTABLISHED**：行业/概念/地域历史热力图、资金历史分位、公告/研报/F10/股东/解禁尚未接入可追溯的长期源契约。

### Append-only seed bundle

- **VERIFIED**：`market_context_persistence.py` 和 `prepare_market_context_seed.py` 只读已有日期文件，重算 `snapshot_sha256`、文件哈希和源哈希，要求 exchange-verified 日历、相邻交易日和第二日 fresh progression。
- **VERIFIED**：bundle manifest 记录日历源哈希、每个输入文件哈希、快照哈希、asof/prior_asof、状态和不可覆盖标记；同一日期出现不同快照哈希会被拒绝。
- **VERIFIED**：当前 D 盘两日旧快照没有 calendar 元数据，gate 返回 `real_snapshot_count=0`；seed preparation 也 fail-closed，不会补写或改写原始证据。
- **VERIFIED**：bundle 追加时检查日历位置连续性；Worker 的单次 `/context/seed` 只证明该日期快照合法，不能单独证明多日连续性，因此连续性必须由 bundle gate 在导入前证明。
- **PLANNED**：取得可核验交易日历后，重新封存新 bundle，逐日导入 Worker，再单独验收历史复盘与轮询。

### 每日更新边界

“工作日每天尝试生成 artifact”不等于“每天把历史快照写入后端”。在受控存储、源许可、频率和大陆网络核验完成前，不打开前端轮询，也不把当前快照补造成过去的晋级率。

### 接受标准

- 连续两个真实交易日的 `run_mode=live` 快照，保留原始响应哈希和抓取时间。
- 日期读取只返回同日期快照；缺失返回 `CONTEXT_NOT_READY`，绝不回退 latest。
- 复盘页能切换日期，并展示当时的池、原因、题材、晋级、炸板率和源状态。
- 任何缺失值显示“未取到/原因”，不把空数组或 0 当作真实结果。

## P2 全球宏观

### 当前实现

1. **VERIFIED**：Treasury、NY Fed、BIS、ECB、BLS、EIA 已有纯解析/封装契约，统一保存 source、asof、fetched_at、status、stale_reason、原始哈希和核验状态。
2. **VERIFIED**：global-context runner 只读取本地 incoming manifest，生成 artifact；没有浏览器直连、LPPLS 输入或 Worker/Pages 写入。
3. **VERIFIED**：P2 调度契约定义日频源 36 小时 TTL、事件日历 24 小时 TTL；失败尝试不推进成功时间。
4. **NOT_ESTABLISHED**：各源商业展示许可、频率/保留期、长期大陆网络可达性和生产抓取器尚未完成。
5. **NOT_ESTABLISHED**：VIX、DXY、黄金、原油、USD/CNY 没有在未授权时用第三方行情替代；它们保持 source-unavailable/待核验。

### 接受标准

- 每张卡显示来源、口径、时点、抓取时间、修订标记、状态和 stale 原因。
- 历史回放使用当时封存的事件日历和修订版本，不用今天的数据补造过去。
- P2 失败不会阻塞个股行情或 LPPLS 任务。
- P2 只作为描述性背景，不进入 LPPLS、顶部/底部评价器或回测分数。

## P3 资讯与概率

1. **VERIFIED**：新闻契约只保留标题、来源、发布时间、链接和内容哈希的设计边界；正文和情绪标签不在当前接入范围。
2. **VERIFIED**：Polymarket/Kalshi 适配器只接受明确数值的 `implied_probability`/`probability`；保留 venue、市场 ID、流动性、asof、fetched_at、stale、来源和哈希。
3. **VERIFIED**：固定 `official_fedwatch=false`；概率数据不会进入 LPPLS、顶部评价器、价格层或回测评分。
4. **NOT_ESTABLISHED**：预测市场书面许可、缓存/归档/公开展示权、长期大陆网络和生产抓取尚未确认。
5. **PLANNED**：许可完成后才启用六小时异步刷新；失败保留上一快照并标 stale，不能用空数组表示“没有变化”。

## 腾讯云兼容边界

- **VERIFIED**：`server/tencent/compat.py` 已提供 provider-neutral 的 `/market`、`/query`、`/status`、`/result`、`/context`、`/context/seed`、`/context/refresh` 合同，覆盖任务去重、日期快照不可覆盖、latest 单调推进和 refresh fail-closed。
- **PLANNED**：CloudBase/数据库/COS 的实际选型、费用、地域、备案、白名单和大陆链路需单独核验。
- **NOT_ESTABLISHED**：没有购买、部署、seed、Pages 配置或生产发布。

## 统一禁止事项

- 不把适配器测试、单次 endpoint 响应或隔离快照说成生产稳定性。
- 不把 H1/H2/H3、Q2、MPL、Ising、Q-DD2、PPE 的失败结果升级成预测能力。
- 不用后见之明的当前资料生成历史晋级率、事件日历或新闻时间线。
- 不把宏观、资讯或预测市场概率喂入 LPPLS 或顶部/底部评分。
- 未得到明确授权前，不购买、部署、seed、合并或发布。

## 下一阶段顺序

1. 在受控环境完成 P1 两日快照导入前的许可、保留期和网络核验。
2. 若门槛通过，按日期升序 seed 两日快照，逐日 GET 校验 asof/hash，再开启前端轮询。
3. 补 P1 行业/概念/地域、资金历史分位和公告/F10 等独立契约。
4. 完成 P2 官方源的修订与事件日历回放验收。
5. 取得 P3 书面许可后再启用六小时异步刷新。

## P1 真实闭环复核（2026-11-08）

此前“旧两日快照缺少 calendar、gate=0”仍作为旧证据保留。**VERIFIED**：在新的隔离目录 `D:\CodexData\analysis\lppl-real-preview-20261108-verified-v2` 中，使用已封存的上交所 2026 官方休市安排重新封存 2026-11-05/06 两份快照，未覆盖旧文件。

- 交易日历版本 `sse_2026_20251222_v1`，官方原始响应 SHA256 `ff188c710b8904758c185eb955e9eaa2c9bd7c2061af984d4f1d743f899c12a4`，日历 artifact SHA256 `07061ee00f5e6d025f84dc9f248ed3a660767f36f8a3b6514cbeee7ff1687593`。
- **VERIFIED**：两日 gate 返回 `real_snapshot_count=2`、`ready_for_frontend_polling=true`、`progression_ready=true`。
- **VERIFIED**：append-only bundle SHA256 为 `227af1d3b69924c68f8dcff998121f55097d3d00e275e10b2e52ec6faad2862a`，包含两份相邻日期快照。
- **VERIFIED**：Worker 实际 `validateSeedSnapshot` 对两份原始 JSON 均返回 `ok=true`。
- **NOT_ESTABLISHED**：尚未调用线上 Worker seed；没有 KV 写入回执、Pages 环境变量或线上轮询结果。

完整来源、文件哈希和验收命令见 [P1 两日真实快照闭环验收](../validation/2026-11-08-p1-real-closure.md)。
