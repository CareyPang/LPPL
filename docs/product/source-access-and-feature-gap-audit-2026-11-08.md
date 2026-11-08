# 数据源核验、日终快照与功能差距审计

记录日期：2026-11-08。本文决定 P1 两日快照是否可受控导入，以及 P2/P3 是否可进入生产刷新；不改变 LPPLS、顶部评价器、价格层或回测口径。

## 结论

- **VERIFIED：存在每日运行计划。** `.github/workflows/market_context_nightly.yml` 在工作日 10:20 UTC（北京时间 18:20）运行 `update_market_context.py`，以 `run-mode=live` 生成不可变 artifact。
- **NOT_ESTABLISHED：两日快照没有每日跨日持久化。** 每次从干净 checkout 开始，历史文件和 manifest 只存在于本次 artifact；`prior_asof` 默认为空，不能自动计算次日晋级率；`asof` 默认 runner 日期，也不保证是最近交易日。
- **VERIFIED：P1 Worker 有受控导入合同。** `/context/seed` 校验 schema、工作日、源哈希和快照哈希；日期快照不可覆盖，`latest` 只向前推进。
- **NOT_ESTABLISHED：暂不导入 P1 两日快照。** 东财/同花顺源的商业再分发、频率限制和大陆长期可达性尚未完成逐源核验。D 盘两日证据继续作为研究 artifact，不写 Worker、Pages 或腾讯云后端。
- **VERIFIED：P3 六小时刷新规则已冻结。** `global_context_schedule.py` 定义六小时边界和 stale 状态；**NOT_ESTABLISHED：生产抓取器、许可和线上刷新尚未启用**。

## 逐源核验

官方端点可访问不等于获得公开产品再分发许可；当前运行环境也不是大陆网络探针。

| 来源 | 核验结果 | 当前门槛 |
| --- | --- | --- |
| Treasury CMT/XML | CMT 是基于纽约联储 indicative bid 的插值曲线，XML 支持日频/分页 | **NOT_ESTABLISHED**：商业再分发需登记；大陆可达性未证实 |
| NY Fed Markets API | 官方文档和 Terms 适用于 reference rates/API | **NOT_ESTABLISHED**：具体序列、归属、频率和大陆可达性未完成 |
| BLS | V2 约 500 queries/day、50 series/query、20 years/query、50 req/10s；要求引用访问日期 | **CONDITIONAL**：需 key、退避、缓存；当前探针曾 403；大陆未证实 |
| EIA | 需要 API key；单次最多约 5000 行；官方建议限速 | **CONDITIONAL**：需 key、限速、归属和缓存；大陆未证实 |
| BIS/ECB | 统计可复用但需署名；ECB 不得修改且第三方数据除外 | **CONDITIONAL**：保留署名、发布日期、有效日和修订 |
| Polymarket | Terms 对 robots/data mining、复制、市场数据分发和受限地区有约束 | **NOT_ESTABLISHED**：未获许可不接生产 P3 |
| Kalshi | Data Terms 偏向个人非商业用途；缓存、归档和软件分发需书面许可 | **NOT_ESTABLISHED**：未获书面许可不接生产 |
| Cboe VIX / ICE DXY | 需要市场数据协议或授权产品 | **NOT_ESTABLISHED**：未授权时保持 `source_unavailable` |
| 黄金/原油/USD-CNY | 许可取决于具体基准价、交易所和供应商 | **NOT_ESTABLISHED**：先登记口径和再分发条款 |
| 东财/同花顺 P1 | 两日真实抓取和原始哈希已存在 | **NOT_ESTABLISHED**：公开接口不等于商用再分发许可；长期大陆可达性未证实 |

证据链接：[Treasury terms](https://www.treasurydirect.gov/legal-information/developers/web-api-terms/)、[NY Fed API](https://markets.newyorkfed.org/static/docs/markets-api.html)、[BLS FAQ](https://www.bls.gov/developers/api_faqs.htm)、[EIA terms](https://www.eia.gov/opendata/terms-of-service.php)、[BIS policy](https://data.bis.org/help/legal)、[ECB policy](https://www.ecb.europa.eu/stats/ecb_statistics/governance_and_quality_framework/html/usage_policy.en.html)、[Polymarket terms](https://polymarket.com/tos)、[Kalshi API](https://help.kalshi.com/en/articles/13823854-kalshi-api)、[Cboe documents](https://www.cboe.com/data/market-data-services/document-library)。

当前运行环境探针记录在 `D:\CodexData\analysis\lppl-global-source-audit-20261108\source-audit.json`：Treasury、NY Fed SOFR、BIS、EIA、Polymarket、Kalshi 等端点曾返回可读响应，BLS 曾返回 403；这些结果只证明当前运行环境的 endpoint 行为，不能证明大陆可达性、授权或生产稳定性。

## 两日快照是否每日更新

当前是“工作日每天尝试生成 artifact”，不是“每天把历史快照累积到后端”。`update_market_context.py` 写出当日文件、latest 和 manifest，但 Workflow 从干净 checkout 开始；`prior_asof` 空时晋级结果保持 `not_available`；周末和节假日不运行。`scripts/daily_update.sh` 的调用是非阻塞的，失败保留旧快照。

- **VERIFIED：** 每日运行计划和单日封存。
- **NOT_ESTABLISHED：** 两日快照每日刷新、跨日保留、自动晋级率和线上轮询。

## 与同类产品的差距

| 能力 | 开盘啦 | 同花顺 | 金十数据 | LPPL 当前状态 |
| --- | --- | --- | --- | --- |
| 盘中行情/竞价 | 竞价、板块竞价、实时龙虎榜 | 实时全球行情、盘口、Level-2 | 20,000+ 品种报价 | **NOT_ESTABLISHED**：主要是日终 |
| 涨停/题材/复盘 | 题材库、板块强度、复盘啦、连板梯队、异动 | 涨停聚焦、问财、热点板块 | 市场参考 | **部分 VERIFIED**：日终池和天梯；历史轮动未接通 |
| 资金/机构 | 北向、主力、深度龙虎榜、机构增仓 | 龙虎榜、融资融券、资金流、大宗、研报 | 数据中心 | **部分 VERIFIED**：北向/两融描述性快照；历史分位不完整 |
| 个股资料 | 股东、F10、公告、机构纪要 | 财报、公告、研报、F10、估值 | 关联资讯 | **NOT_ESTABLISHED** |
| 全球资讯/宏观 | 商品现货、市场情绪 | 全球行情、资讯、日历 | 7×24 快讯、财经日历、直播/同传 | **PLANNED**：P2 适配器有，生产源未接通 |
| 自选/预警/同步 | 个性化版面、异动提醒 | 自选云同步、预警、模拟交易 | 自定义推送 | **NOT_ESTABLISHED** |

公开参考：[开盘啦功能说明](https://app.mi.com/details?id=com.aiyu.kaipanla)、[同花顺官网](https://web.10jqka-official.com.cn/index.html)、[金十数据介绍](https://www.jin10.com/about/introduce.html)。这些页面只证明功能类别存在，不证明数据可复制或商用。

## 可补充功能与来源边界

`a-stock-data` 可作为 A 股端点设计参考：分钟/逐笔、研报、热点、北向、龙虎榜、解禁、行业/板块资金、融资融券、大宗、股东、分红、F10、公告、涨停/连板/炸板、ETF、期权、筹码、估值历史和宏观日历。`global-stock-data` 可作为 BIS/ECB/NY Fed/Treasury/EIA/BLS/SEC 等全球官方源适配参考。两者只分发代码，不等于上游数据许可。

优先补充：

1. **P0 工作站**：自选股、最近分析、顶部区间修订日志、数据截止日、证据状态、失败重试。
2. **P1 复盘**：交易日历、两日 append-only 快照、行业/概念/地域热力图、晋级率、炸板率、题材热度、资金历史分位、公告/研报/F10。
3. **P2 宏观**：先接许可和频率明确的 Treasury、NY Fed、BIS、ECB、BLS、EIA；VIX/DXY/黄金/原油/USD-CNY 逐品种核验。
4. **P3 资讯和概率**：全球新闻只存标题/来源/时间/链接/hash；预测市场只在书面许可后做六小时异步状态卡，不称官方 FedWatch。
5. **差异化**：顶部时间区间、模型首次可见时间、修订账本、行情/公告/宏观事件时间轴和“为什么没有正式提醒”的证据解释。

## 实施顺序与当前决定

1. 先修交易日历和 `asof/prior_asof`，让每日任务找到最近已收盘日与前一交易日。
2. 把日期快照和 manifest 放入 append-only 受控存储，导入前逐条校验 raw hash、snapshot hash、source status 和条款状态。
3. 只有连续两日真实快照、条款通过、源健康可追踪后，才允许 `/context/seed` 和前端轮询。
4. P2 先做官方描述性卡片；P3 先保持 planned，许可通过后再启用六小时异步队列。

当前决定：**不写入 P1 两日快照，不启用 P3 生产刷新，不购买、不部署、不发布。** 可继续做日历解析、source registry、append-only 存储合同、字段适配和前端 stale 状态。

公开功能来源：[a-stock-data SKILL](https://github.com/simonlin1212/a-stock-data/blob/main/SKILL.md)、[global-stock-data SKILL](https://raw.githubusercontent.com/simonlin1212/global-stock-data/main/SKILL.md)。
