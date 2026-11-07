# 投资者工作站市场背景规划

记录日期：2026-11-07。本文规划市场背景功能与个股 LPPLS 当前分析的边界。市场背景是描述性上下文，不进入 LPPLS 拟合、顶部区间评分或任何交易信号。

## 本次已执行

- 工作站移除“看清行情，再研究时间。”和工作站徽章动效开关；首页海洋动效开关仍独立存在。
- 工作站新增“顶部时间 / 底部结构 / 市场背景”视图切换。K 线和成交量始终保留，分析说明不再只能出现在图表上方。
- 真实预览的底部面板显示当前 LPPLS 状态、底部结构的证据边界，以及市场背景入口；底部价格、目标价和抄底概率没有被虚构。
- 工作站导航接入已有 `market.html`。该页面的板块资金流热力图、涨停/炸板/跌停池、连板梯队、北向、两融和指数估值均标为描述性背景，不参与模型。
- 参考“开盘啦”类截图新增了日终“复盘啦”三页入口：盘面梳理、市场动向、涨停原因；只有已有快照能支持的数字会显示，缺失的原因、题材和历史晋级率会明确标记为未接入。
- 将当前涨停前 20 项按连板数整理成“连板天梯”矩阵。它是已保存快照的可读视图，不是实时龙虎榜，也不把单日梯队解释为持续性或收益预测。
- 增加“功能接入地图”，将题材库、龙虎榜/机构增仓、快讯/直播、商品/ETF、宏观概率分别标出 P1/P2/P3 依赖，避免页面用空数组或截图数字假装已经接通。
- 新增独立 `workers/market-context` Worker 和 `market-context.v1` 快照契约：读取与个股 `/market` 分离；刷新受保护、异步返回 `job_id`，同日请求去重，历史日期只读对应快照。

## P1 日终适配器（2026-11-08）

- **VERIFIED · 代码契约**：`research/data/market_p1.py` 已增加两个独立上游适配器。东财 `getYesterdayZTPool` 保存前一交易日池在当日的表现；同花顺涨停揭秘端点保存 `reason_type` 和对应题材标签。每条源记录 `source_url`、`fetched_at`、`status`、`ok`、`raw_sha256` 和许可证待核验标记。
- **VERIFIED · 代码契约**：`market_base.limit_pools()` 仍保留旧的 `zt/zb/dt/top20` 字段，同时封存完整 `pool_rows`。`attach_snapshot_extensions()` 只有在两份不同日期的完整 `pool_rows` 和显式交易日历同时存在时，才计算 `history.progression`；否则保持 `not_available`，不会从当前快照倒推历史晋级率。
- **VERIFIED · artifact runner**：`scripts/update_market_context.py` 每次只封存一个 `market_context_<asof>.json`，并更新带源哈希的 manifest；`.github/workflows/market_context_nightly.yml` 默认只上传不可变 artifact，不写 `main`、Pages 或生产 Worker。
- **VERIFIED · gate**：`scripts/market_context_gate.py` 要求两个不同交易日、`run_mode=live`、`fresh/partial` 状态和至少一个原始响应哈希，才返回 `ready_for_frontend_polling=true`。
- **NOT_ESTABLISHED · 运行证据**：本 PR 尚未完成两组真实日终抓取，故前端仍不轮询 `workers/market-context`；现有页面继续读取已封存的静态市场快照。适配器通过离线 fixture 和契约测试不等于上游当天可达或已取得商业再分发许可。

## 截图功能核对结果

截图中的产品形态与公开的 `vibe-astock` / `a-stock-data` 功能说明高度对应，但本仓库当前只有日终市场快照。当前可复用和不能直接复用的范围如下：

| 功能 | 当前状态 | 接入条件 |
| --- | --- | --- |
| 涨停/炸板/跌停、最高连板 | VERIFIED · 日终 | 现有 `market_latest.json`，保留数据日和来源 |
| 连板天梯 | VERIFIED · 日终 | 由快照 `top20` 生成矩阵，不补造未返回成员 |
| 行业/概念/地域热力图 | VERIFIED · 描述性 | 东财或新浪口径独立标注；历史分位需要可验证历史样本 |
| 涨停原因、题材库、题材轮动 | NOT_ESTABLISHED | 需要带交易日、来源、原始响应哈希的题材/原因快照 |
| 龙虎榜、机构增仓、股东/F10 | NOT_ESTABLISHED | 需要单独字段契约和使用条款核对 |
| 快讯、全球资讯、直播、盘中六时点 | NOT_ESTABLISHED | 需要服务端定时采集；不能从日终快照补出盘中过程 |
| 商品、ETF、全球宏观 | PLANNED · P2 | 先用官方或许可明确的源，逐品种保存 asof/fetched_at/stale |
| 美联储概率 | PLANNED · P3 | 只显示 Polymarket/Kalshi 市场隐含概率，不称官方 FedWatch |

`a-stock-data` 的公开 README 列出了板块资金、涨停/炸板/跌停、涨停原因、连板梯队、新闻和宏观等层；这证明功能类别可实现，不证明其上游接口可直接商业再分发。大陆环境下，`globalpercent` 需要境外后端或代理，并且刷新必须异步；这些约束进入 P2/P3 的验收。

## 功能分层

### P0：个股工作站

1. 日线 OHLCV 与当前 LPPLS 结果独立加载。
2. 顶部时间区间只显示完整日期范围；候选、观察、正式区间和历史重放严格分开。
3. 底部结构先显示“已验证的历史描述”和“尚未建立”的能力边界。任何价格目标、回撤区间或抄底概率都必须有独立样本外合同后才能显示。
4. 视图位置保存在当前浏览器；视图切换不改变模型请求、不重算结果。

### P1：A 股市场背景

来源适配可以参考 `simonlin1212/a-stock-data` 的公开接口设计，但不把上游仓库当成实时数据授权。接入时每个模块必须保存 `source`、`source_url`、`fetched_at`、`asof`、`status`、`stale_reason` 和原始响应哈希。

- 板块热力图：行业、概念、地域的涨跌幅、上涨/下跌家数和主力资金净额。
- 情绪与连板：涨停、炸板、跌停、最高连板、连板梯队、晋级率和炸板率。
- 资金与估值：北向成交、两融余额、宽基估值和交易日状态。
- 全球消息：只显示可追溯标题、来源、发布时间和抓取状态；不把新闻摘要转成模型变量。

### P2：全球宏观

- 利率曲线：优先官方 Treasury、央行或 BIS 数据，显示期限、时点和更新时间。
- 市场状态：VIX、DXY、黄金、原油、USD/CNY 等只作为跨市场背景。
- 事件日历：美联储、PBOC、ECB 和 CPI/PMI 发布日历，按事件时间显示。
- 美联储概率：若接入 `globalpercent`，页面必须写“预测市场隐含概率”，标注 Polymarket/Kalshi、抓取时间和流动性；不得写成官方 FedWatch，也不得称为预测能力。

### P3：数据与可靠性

- 个股 K 线、LPPLS、市场背景和宏观快照使用独立缓存与刷新状态；任何一层失败都保留上一份快照并标记 `stale`。
- 空数组、零值和缺失值分开表示；不可用时显示“未取到”及原因。
- 中国大陆访问优先采用异步快照和可替换源；不把浏览器直接跨域抓取作为正式架构。
- 所有市场背景数据默认 `evidence=descriptive`，不进入研究评分。只有经过单独预注册和样本外验证的变量，才能申请进入模型实验分支。

### P1 接口验收

- `GET /context?date=latest` 和 `GET /context/snapshot?date=YYYY-MM-DD` 只读取已封存内容；不存在时返回 `CONTEXT_NOT_READY`，不回退到最新日期。
- `POST /context/refresh` 需要服务端 token，返回 `202 + job_id`；同一日期的并发刷新去重。
- `GET /context/status?job_id=...` 返回 `queued/running/completed/failed`，失败保留稳定错误码，不透传上游响应正文。
- `limit_pools.reasons`、`limit_pools.topics`、`history.progression` 缺失时为 `not_available`，不能把缺失当作零值。

## 来源边界

`a-stock-data` 的 README 说明覆盖 A 股行情、板块资金、涨停池、连板、新闻和宏观利率；实际主源包含腾讯、东财、同花顺和新浪，商业使用前仍需逐源核对条款。`global-stock-data` 主要覆盖美股/港股及官方全球利率与宏观源，不提供 A 股连板。`globalpercent` 聚合 Polymarket/Kalshi 市场价格形成的事件隐含概率，适合做情绪温度计，不适合做确定性交易信号。

## 验收标准

- 390px 与桌面均能在顶部时间、底部结构和市场背景之间切换，切换不触发模型重算。
- K 线加载失败不隐藏已有分析；宏观或热力图失败不阻塞个股分析。
- 每张数据卡能看到 `asof`、`fetched_at`、来源和 stale 状态。
- 页面文案明确区分 VERIFIED、descriptive、NOT_ESTABLISHED；不把 H1/H2/H3、Q2、MPL、Ising、Q-DD2、PPE 的失败结果升级为预测能力。
- 新数据接入前先完成字段、许可、频率、缓存和原始快照审计，再进入独立 PR；不直接改 `frontend/app/lppl-data.js`。

