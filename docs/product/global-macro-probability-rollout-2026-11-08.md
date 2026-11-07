# P2/P3 全球宏观与概率数据接入方案

记录日期：2026-11-08。本文只定义来源、适配器、快照契约和每日更新门槛，不把全球数据接入 LPPLS 拟合、顶部区间评分或底部判断。

## 证据边界

- **VERIFIED**：当前仓库已有独立 `workers/market-context` 快照接口和 `market-context.v1` 的 `source/asof/fetched_at/status/stale_reason/snapshot_sha256` 字段；该 Worker 尚未正式部署。
- **PR 作者报告**：[`global-stock-data`](https://github.com/simonlin1212/global-stock-data/blob/main/SKILL.md) 列出了 Treasury、BIS、ECB、纽约联储、美联储、EIA、BLS、CBOE 等适配方向，并给出了合规分级。仓库不会把 README 的分级当作本项目的法律意见，接入前仍需逐源复核当前条款、频率限制和商用展示许可。
- **PR 作者报告**：[`globalpercent`](https://github.com/simonlin1212/globalpercent) 以 Polymarket 和 Kalshi 的公开只读市场数据组成宏观事件隐含概率面板。它是参考实现，不是本项目已经取得的授权，也不是官方 FedWatch 数据源。
- **官方页面已核对**：Polymarket 的 Gamma/Data 端点提供匿名只读市场数据；Kalshi Help Center 也说明 API 可读公共市场数据，但其 Developer Agreement/Data Terms 对会员、重试和第三方再分发有额外限制。两者均不能仅因“无需 API key”就视为获得本项目公开展示许可。
- **NOT_ESTABLISHED**：大陆网络下对每个上游端点的可达性、稳定性、速率限制和长期商业许可尚未在本项目运行环境中验证。浏览器端不得直接跨域抓取上游。

## P2 来源适配器

每个适配器都输出同一条记录结构，保留原始响应（或压缩归档）和 SHA-256。数值缺失使用 `null`，不把缺失转换成 0。

| 模块 | 首选来源 | 建议字段 | 许可/网络状态 |
| --- | --- | --- | --- |
| 美债收益率曲线 | [U.S. Treasury Daily Treasury Par Yield Curve](https://home.treasury.gov/resource-center/data-chart-center/interest-rates/TextView?type=daily_treasury_yield_curve) 或 FiscalData | `tenor`, `yield_pct`, `quote_type`, `asof` | **官方页面已核对；许可仍待复核**。CMT 是基于纽约联储约 15:30 的 indicative bid quotes 由 Treasury 插值得到，并非成交价；XML 接口按年度或分页读取。保存发布日期与修订标记，不能用后来的修订值覆盖历史快照。 |
| SOFR/EFFR 等美元参考利率 | [New York Fed Markets API](https://markets.newyorkfed.org/) | `rate`, `volume`, `percentile_rank`, `asof` | **PR 作者报告；待复核**。对外展示附纽约联储免责声明文本。 |
| 央行政策利率、全球利率 | [BIS Data Portal](https://data.bis.org/)、[ECB Data Portal](https://data-api.ecb.europa.eu/service/data/)、美联储 H.10/H.6 | `institution`, `rate_type`, `currency`, `effective_date`, `published_at` | **PR 作者报告；待复核**。严格分开 `effective_date`、`published_at`，保留修订版本。 |
| CPI、就业、PPI、JOLTS、初请 | [BLS Public API](https://api.bls.gov/publicAPI/v2/)、[DOL ETA](https://oui.doleta.gov/unemploy/) | `series_id`, `value`, `unit`, `release_date`, `revision` | **PR 作者报告；待复核**。免 key BLS API 有请求与序列限制，适配器要做批量、缓存和退避。 |
| 原油/能源库存 | [EIA API](https://api.eia.gov/) | `product`, `price_or_inventory`, `unit`, `period` | EIA 自有数据可作为优先源；第三方转载价格必须单独标注，不能沿用 EIA 的许可结论。 |
| VIX/期限结构 | CBOE 官方产品或获授权文件 | `index`, `tenor`, `close`, `asof` | **NOT_ESTABLISHED**。`global-stock-data` 将 CBOE 标为需授权；没有授权时显示 `source_unavailable`，不得用 Yahoo 或网页抓取冒充官方 VIX。 |
| DXY | ICE/授权数据或可审计的官方货币篮子替代 | `index`, `close`, `asof` | **NOT_ESTABLISHED**。DXY 属于授权指数；未取得许可时只显示组成货币的官方汇率，不显示“DXY”。 |
| 黄金 | 经许可的基准价或可审计的公开官方替代 | `instrument`, `close`, `currency`, `asof` | **NOT_ESTABLISHED**。先确认基准价再接入，不能把第三方网页抓取标成官方。 |
| USD/CNY | 美联储 H.10、ECB/BIS 或可核验的 PBOC/CFETS 公告 | `pair`, `rate`, `quote_type`, `asof` | **NOT_ESTABLISHED**。必须显示中间价/收盘价口径，不能混用。 |
| 央行和宏观事件日历 | Fed、ECB、PBOC、BLS/统计机构官方日历 | `event_id`, `event_type`, `scheduled_at`, `timezone`, `status`, `source_url` | **NOT_ESTABLISHED**。保存当时发布的日历版本；不能用今天的日历补造过去。 |
| 全球新闻索引 | 许可明确的 RSS/API 白名单 | `title`, `source`, `published_at`, `url`, `language`, `content_hash` | **NOT_ESTABLISHED**。初期只保存标题、时间和链接；正文、摘要和情绪分析另行审计。 |

P2 页面只显示描述性上下文，例如曲线形状、最近变动、事件倒计时和来源新鲜度。它们不得成为 LPPLS 的输入，也不得在文案中被写成顶部或底部的因果证据。

## P3 预测市场隐含概率

`globalpercent` 的数据层可以作为可选 P3 适配器，但必须单独存储为 `macro-probability.v1`，不与 P2 数值混在一张表中：

```json
{
  "schema_version": "macro-probability.v1",
  "venue": "polymarket|kalshi",
  "market_id": "string",
  "question": "string",
  "outcome": "string",
  "implied_probability": 0.0,
  "probability_unit": "decimal_0_1",
  "liquidity": null,
  "volume_24h": null,
  "open_interest": null,
  "end_at": null,
  "asof": "YYYY-MM-DDTHH:mm:ssZ",
  "fetched_at": "YYYY-MM-DDTHH:mm:ssZ",
  "status": "ok|partial|stale|source_unavailable|schema_changed",
  "stale_reason": null,
  "source_url": "https://…",
  "raw_sha256": "hex",
  "evidence": "descriptive",
  "official_fedwatch": false
}
```

实现规则：

1. Polymarket 与 Kalshi 先并排显示。只有在两个市场的事件语义、结算时间和结果集合完全对齐，并且代码中登记了可复查的映射规则，才允许额外显示“跨平台比较”；默认不计算一个没有定义的“共识概率”。
2. `liquidity`、`volume_24h`、`open_interest` 取不到时保留 `null`，同时显示“流动性未取到”。不能用概率本身代替流动性。
3. 页面文案固定为“预测市场隐含概率（Polymarket/Kalshi）”，标注 `asof`、`fetched_at`、市场链接和 stale 状态；不得称为官方 FedWatch、央行概率或 LPPLS 预测。
4. 预测市场数据至少每 6 小时刷新一次；请求超时或境外端点不可达时保留最后一份快照并写 `stale_reason=source_unavailable`。全量 Kalshi 市场抓取耗时可能达到分钟级，必须异步、分页、限时和可恢复。Kalshi 的公开站展示仍需先完成其 Developer Agreement/Data Terms 许可核对。
5. P3 数据永远不进入 LPPLS、顶部评价器、底部价格层或任何回测分数。若未来要研究关联，只能在独立实验分支预注册变量、时间对齐和样本外评估。

## 统一快照与每日更新

P2/P3 采用与 P1 相同的异步快照思想，建议顶层结构为 `global-context.v1`：

```json
{
  "schema_version": "global-context.v1",
  "asof": "YYYY-MM-DD",
  "generated_at": "YYYY-MM-DDTHH:mm:ssZ",
  "run_id": "uuid",
  "evidence": "descriptive",
  "sources": {"treasury": {"status": "ok", "raw_sha256": "…"}},
  "rates": {"treasury_curve": []},
  "markets": {"vix": {}, "fx": {}, "gold": {}, "oil": {}},
  "events": [],
  "news": [],
  "probability": {"status": "not_requested", "items": []}
}
```

每条源记录都必须有 `source`, `source_url`, `asof`, `fetched_at`, `status`, `stale_reason`, `raw_sha256` 和 `license_tier`。建议状态枚举为 `ok`、`partial`、`not_available`、`stale`、`source_unavailable`、`schema_changed`。

每日作业分为三段：

1. **A 股日终段**：P1 适配器先封存交易日快照；只有完成两份真实、连续的日终快照后，前端才开启轮询和“历史复盘”入口。这里的两份快照必须来自真实上游响应和不同交易日，不能用 fixture 或今天的资料填充过去。
2. **全球日终段**：在当天发布窗口结束后运行 Treasury、BIS/ECB/Fed、EIA、BLS/ETA 和事件日历；以 `asof` 做幂等键，保留原始响应及哈希。建议失败重试一次，再把可用模块封存为 `partial`，而不是阻塞个股工作站。
3. **P3 高频段**：每 6 小时或按用户请求异步刷新 Polymarket/Kalshi。源不可达时返回上一份快照和 stale 原因，不回退到当前日期伪造历史。

Cloudflare Worker 的 Cron Trigger 适合正式运行；在尚未部署 Worker 前，GitHub Actions 只能做 artifact-only 研究抓取，上传不可变 artifact/独立数据分支，不得自动写 `main`、Pages 或生产 KV。每次作业输出一份 manifest：`run_id`、`asof`、源状态、原始哈希、schema 版本和失败原因。

建议的 TTL（可配置而非模型假设）：日频宏观数据 36 小时，事件日历 24 小时，预测市场 6 小时；超过 TTL 自动标记 `stale`。同一来源在两次成功抓取之间若响应哈希没有变化，仍需记录新的 `fetched_at`，不能把“未变化”误标为失败。

## 大陆访问与产品降级

- 浏览器只请求本站 Worker，不直连 Polymarket、Kalshi、CBOE 或各官方源。
- 境外源由服务端执行；在大陆网络不可达时，页面保留上次成功快照并显示具体 stale 原因和时间。不能通过空数组、0 或“暂无变化”掩盖抓取失败。
- P2/P3 卡片是渐进增强：宏观源失败不阻塞个股 K 线和 LPPLS；P3 未接入时卡片写 `planned`，不显示静态截图数字。
- 许可状态未完成前，公开预览只展示字段契约、来源链接和状态徽章；不展示需要付费或授权的原始行情。

## 验收清单

- [ ] 两个连续真实交易日的 P1 日终快照已封存，含原始响应哈希；历史日期只能读取对应快照。
- [ ] 每个 P2/P3 卡片展示 `source`、`asof`、`fetched_at`、`status`、stale 原因和来源链接。
- [ ] 任一源超时、限流或改版时，不写入伪造 0 值；上一份快照可读且标记 stale。
- [ ] 事件日历按当时版本回放，未用当前日历补造历史。
- [ ] P3 明确写“预测市场隐含概率”，并显示 venue、市场链接、流动性和抓取时间；不出现“官方 FedWatch”。
- [ ] P3 未进入 LPPLS、顶部/底部评价器、价格层或回测评分；相关代码搜索无 `probability` 到 LPPLS 输入的路径。
- [ ] 390px 与桌面端在源未接入、部分成功和 stale 三种状态下均可读；宏观失败不阻塞个股工作站。
- [ ] 正式部署前完成逐源许可、频率、保留期和大陆网络验证；当前阶段不合并、不发布。

