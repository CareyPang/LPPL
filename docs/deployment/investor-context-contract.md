# 独立投资者信息契约

本次实现为本地、无网络的聚合和腾讯云接口兼容代码。没有购买、部署、数据源授权、自动采集或线上发布。所有新闻、公告、复盘和公司资料均为独立描述性信息，不进入 LPPL 拟合、时间窗口、置信度、报警或目标价。

## 读取方式

`GET /investor-context?date=latest|YYYY-MM-DD&symbol=sh600519` 只读取已存快照。省略 `symbol` 表示市场级信息；有值时必须是小写交易所前缀与六位代码。日期允许资讯发生的自然日，但必须是真实 ISO 日期。明确请求的历史日期不存在时返回 `404 INVESTOR_CONTEXT_NOT_READY`，不得返回今日或其他资产资料。最新快照不合格时也不静默退回旧快照。

没有公开资讯写入端点。`InMemoryTencentStore.investor_snapshots[(asof, symbol)]` 仅用于本地契约测试；生产数据库、权限审核和条件写入仍待独立实现。

既有 `/context` 返回市场级 `investor_context`；既有 `/market?code=600519` 返回同数据日、同资产的 `investor_context`。没有合格资料时嵌套对象各节为 `not_available`，行情仍正常返回，不创建计算/抓取任务。市场响应的原封存哈希保存在 `base_snapshot_sha256`，投影后的响应重新计算 `snapshot_sha256`；原始存储对象不改写。

前端只能通过 `LPPL.market()`、`LPPL.marketContext()`、`LPPL.stock.market(code)` 的既有入口取得该嵌套对象。新信息客户端仅选择字段，不直接请求上游、不改受保护的 `lppl-data.js`。

## 聚合 API

```python
build_investor_context(
    asof="2026-11-06",
    available_at_cutoff="2026-11-06T12:00:00Z",
    symbol=None,
    attachments={"news": attachment},
    purpose="research",  # 或经过独立许可核验后的 publish
)
```

返回 `schema_version=investor-context.v1`、`kind=investor_context`、`asof`、`symbol`、`purpose`、`status`、`available_at_cutoff`、`sections` 和稳定 `snapshot_sha256`。固定 `evidence=descriptive`、`model_input_eligible=false`、`pit_status=NOT_ESTABLISHED`。

`sections` 固定包含：`news/announcements/reports/events/profile/financials/shareholders/unlock/dragon_tiger/fund_flow/topics/ladder/progression`。每节包含 `status/asof/rows/source/stale_reason/evidence/sample_size/publication_eligible/coverage_status`，有效解析时补充拒绝和过滤数量。状态为 `fresh/partial/stale/error/not_available/blocked`。未提供来源的节逐项保留为空；未知覆盖范围或部分样本标为 `partial`，不会因解析成功称为全市场完整数据。`sample_size` 只计展示行数，不代表独立统计样本或预测准确率。

## 附件及来源

附件至少提供 `asof`、`rows` 和 `source`；个股节还须提供 `symbol`，每行同样显式绑定该资产。`source` 必须包含 `source_id/source_url/raw_sha256/available_at`。链接必须为无用户名密码的 HTTPS，hash 必须为小写 64 位 SHA-256。可选 `fetched_at` 不得晚于 `available_at`。附件元数据本身不构成该 hash 与原始响应一致的证明，也不证明历史公开时间；原始响应封存与来源核验仍在独立证据层完成。

公开场景要求 `source.publication={"status":"verified","evidence_refs":["实际许可审查证据引用"]}`。这是调用方携带的审核记录；聚合器不会自行推断数据许可。缺少该记录时 `publish` 场景该节 `blocked` 且不返回行；`research` 场景可解析，但整个对象始终 `publication_eligible=false`。腾讯公开读取还会复核整体哈希、目的、来源许可、日期及资产和每行内容，不能只翻转顶层布尔值就公开研究数据。

`coverage_status` 为 `complete/partial/NOT_ESTABLISHED`。完整性必须由源适配器依据实际请求范围、分页和原始证据确定；不能将 top20 称为全市场天梯。

## 行字段与日期含义

| 节 | 主要允许字段 |
| --- | --- |
| news / announcements / reports | title、source、published_at、url、symbol（资产级必填）、hash |
| events | title、event_date、url、known_at、available_at、symbol（资产级必填） |
| profile | symbol、name、industry、region、description、website、listing_date |
| financials | symbol、report_period、published_at、metric、value、unit、currency、statement_type |
| shareholders | symbol、report_period、published_at、holder_name、shares、ownership_pct、change_shares |
| unlock | symbol、event_date、name、type、quantity、unit、ratio_pct |
| dragon_tiger | symbol、date、name、reason、net_buy、buy_amount、sell_amount、turnover_pct |
| fund_flow | symbol、date、main_net、small_net、medium_net、large_net、super_net 及对应 *_pct |
| topics / ladder / progression | topic_label/count；symbol/name/streak/limit_time/topic_label；from_streak/to_streak/eligible_count/advanced_count/rate |

所有行保留 `available_at` 和 `known_at`，未逐行提供时继承来源的可用时间。新闻类只保存索引，不保存文章正文、模型提示词、新闻摘要或未经验证的影响评分；`hash` 对允许字段重新计算。缺失数值保持 null；布尔、数字字符串、NaN 和 Infinity 不得作为金融数值。资金净额为人民币元，*_pct 为百分数；晋级率 rate 为 0–1 比例，必须与提供的分子分母一致。解禁数量必须显式携带单位，不猜万股或股。

`asof` 是资料所属日，`published_at` 是文章/报告发布时间，`available_at` 是附件可用时间，`known_at` 是声明的知识时间；均不替代真实预测首次对用户可见的时间。时间戳必须带时区。新闻发布时间不得晚于该资料日（按中国时区）或可用截止时间。未来 `event_date` 可展示已知日历事件；来源、行的 `available_at/known_at` 均不得晚于截止时间。报表期间不得晚于资料日；历史事件行不得混入将来观测。此契约不认证 PIT。

公司简介属于当前快照：来源可用日若晚于请求资料日，则 `current_profile_cannot_backfill_historical_snapshot`，禁止当前简介贴回历史。其余历史观测在晚于资料日才取得时，节标记 `vintage_status=retrieved_after_asof`；这种回溯资料不能作为当时已知的历史预测输入。历史当时视图应显式使用当日可用截止时间，当前截面回看必须展示知识截止日。

## 腾讯云市场快照门禁

市场 `/context/seed` 拒绝 `evidence_import`、`publication_eligible=false`、`research_import/fixture`、`p1.supplemental_sources` 和直接嵌入的 `investor_context`；独立资讯只能经过自己的校验后投影。市场快照要求已核验交易所日历与来源 hash，晋级率为 fresh 时还要求前一交易日已核验。

## 验收

- 新闻无正文、无不安全链接；来源未获公开许可时无公开行。
- 同资产同日期读取；缺失历史无今日回退；未来事件与未来才获知的信息分开。
- 来源/行可用时间受限，缺源/部分/失败/stale 状态可区分。
- 研究对象、篡改 hash、翻转顶层布尔值、跨资产记录无法公开读取。
- 行情不等待资讯，资讯读取不触发查询队列或外部网络。
- 真实数据上线、许可审核、大陆网络验证、并发数据库和 UI 仍需各自的实证验收。
