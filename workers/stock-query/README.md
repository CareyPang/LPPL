# 个股异步查询 Worker

Worker 提供独立日线行情、当前分析排队、按需历史回放及任务结果读取。它不执行 LPPL；当前版本仍派发 GitHub Actions。此目录的变更是代码与本地 fixture 验证，不代表生产绑定、真实行情或端到端耗时已验收。

## 查询流程

1. 浏览器先并行读取 `/market` 与无 `job_id` 的 `/result?kind=latest`，允许显示行情和已有结果。
2. 需要更新时提交 `/query`；默认只计算当前结果，不附带104周历史。
3. 使用返回的 `job_id` 查询状态及该任务结果。关闭页面后仍可用同一编号恢复查询。
4. 用户显式请求历史时提交 `mode=history`；历史失败不使已读到的当前结果失效。

## API

### `GET /market?code=600519`

独立读取腾讯 `fqkline` 接口的最多640根**不复权**日线。返回示例字段：

```json
{
  "code": "600519",
  "symbol": "sh600519",
  "name": "资产名称",
  "source": "tencent_fqkline",
  "adjustment": "none",
  "frequency": "1d",
  "closed_only": true,
  "asof": "YYYY-MM-DD",
  "generated_at": "ISO UTC",
  "cutoff": "YYYY-MM-DD",
  "price": [{"date":"YYYY-MM-DD","open":1,"high":1,"low":1,"close":1,"volume":1}],
  "latest": {"date":"YYYY-MM-DD","open":1,"high":1,"low":1,"close":1,"volume":1},
  "cache": "miss",
  "stale": false,
  "expected_source_sha": null,
  "model_computed": false
}
```

- 上海时间15:30前排除当天日线，与 `research.pipeline.stock._close_cutoff` 一致；去除周末、未来、无效OHLC和无效日期，按日期排序去重。
- `asof` 是实际最后一根有效日线日期。没有通过日历推断“最新交易日”；停牌、节假日、供应商延迟不能仅凭 `stale=false` 排除。
- `asof_freshness=not_established` 明示尚未核验交易所最新交易日；行情 `stale_reason` 说明缓存刷新失败原因。
- `stale` 描述**缓存更新状态**。60秒内复用缓存；上游失败时可返回旧缓存，明确 `stale=true`、`warning_code`、原始截至日及生成时间，不伪造新日期。
- `volume_unit=vendor_native`；不擅自把供应商数量换成股/手。未复权日线不能与模型的后复权曲线混用同一价格轴。
- 北交所代码显式映射 `bj`；是否有数据由接口响应决定。没有数据返回可读错误，不回退到同号码深圳资产。
- `expected_source_sha` 是全局缓存最多5分钟的 `main` SHA，仅用于识别旧版本；获取失败返回 `null`，不影响行情响应。可选元数据请求限时1秒，日线请求限时8秒。
- 行情使用独立 `market:CODE` Durable Object，不在同股票的 GitHub 派发/状态请求后排队。

### `POST /query`

```json
{"code":"600519"}
```

等价于 `mode=current`、`history_weeks=0`。历史请求：

```json
{"code":"600519","mode":"history","history_weeks":104}
```

历史默认104周，允许1至156周。`variant` 始终由服务端固定为 `stk_lite`；客户端提供的 `source_sha`、`job_id` 等不能控制计算版本。

HTTP 202 返回 `queued, deduped, code, mode, history_weeks, job_id, requested_at, since, source_sha, variant, ratelimit, status`。`since` 是兼容旧前端的 `requested_at` 别名。

派发前从可信 GitHub `commits/main` 解析40位 SHA，生成 UUID v4，先持久保存，再派发：

```json
{
  "event_type": "stock_query",
  "client_payload": {
    "code": "600519",
    "variant": "stk_lite",
    "mode": "current",
    "history_weeks": "0",
    "job_id": "UUID-v4",
    "requested_at": "ISO UTC",
    "source_sha": "40-hex"
  }
}
```

提交新任务前先读取 `stock/index.json`；Durable Object 按股票缓存索引60秒。仅复用状态成功、`asof`/模型版本/源码SHA有效且结果在最近一个工作日15:30（上海时间）之后生成的当前结果。历史结果还须与当前 `asof` 兼容并覆盖请求周数。索引缺失、不可读或格式错误时继续正常去重与派发。

运行中的历史任务只有在周数不少于本次请求时才复用。较小的任务仍可通过原 `job_id` 查询；更大请求会派发新任务并更新 `active:history` 指针。

新鲜度以最近收盘时间为界，不含节假日日历。**拟合代码变化本身不会使收盘后发布的结果失效**；这类结果会继续复用到下一次收盘后结果或夜间刷新发布。

### `GET /status?code=600519&job_id=UUID`

返回 `status/conclusion/phase`、`current_ready/history_ready/error_ready` 及任务身份。只有该任务产物的 `code/job_id/source_sha/mode` 一致，才标记可读。

- 当前产物可读：`status=completed, conclusion=success, phase=current_ready`；不等整个 Actions 工作流结束。
- 历史产物可读：`phase=history_ready`，不要求历史任务重新生成当前结果。
- 工作流成功但目标结果缺失：先等待最多2分钟发布可见性缓冲，随后 `conclusion=failure, phase=publish_failed`。
- 无匹配运行：仍为 `pending` 或 `dispatch_unknown`，不误认旧任务的成功。
- `workflow_status/workflow_conclusion` 单列；任务可读不代表流水线所有清理步骤均已完成。
- `phase=queued/current_running/history_running` 分别表达排队、当前分析计算、显式历史计算；发布可见性缓冲为 `publishing`。
- 本任务失败且同资产旧结果仍可读时，返回 `phase=stale`、`stale=true`、`stale_reason=refresh_failed_previous_result_retained`、旧 `asof/last_success_at`。`current_ready/history_ready` 仍只表示本任务产物，不能用旧指针冒充本次成功。
- 超过30分钟仍没有匹配运行/产物时，`reconciliation_required=true`；保留原任务编号，须核实远端队列，不自动重复派发。
- `first_worker_observed_at` 仅在首次核对到目标结果时记录。排队/计算期间为 null；它不等于生成时间、公开发布时间或浏览器可见时间。

状态缓存10秒。Actions 按精确 `stock_query CODE JOB_ID` 标题匹配，限定创建时间不早于请求前60秒、最多3页；未找到不能证明任务失败。派发响应丢失或5xx结果不确定时保留原任务，避免重复计算。若持续不确定，须由运维核实 GitHub 队列后处理；此接口不提供公开强制重派发或取消功能。

旧 `GET /status?code=...&since=<ISO timestamp>` 保留兼容，只匹配旧 `stock_query CODE` 标题；新客户端应始终使用 `job_id`。

### `GET /result?code=600519&kind=latest|history|error&job_id=UUID`

读取以下任务专属路径，绝不回退成其他任务或最新公共指针：

```text
stock/jobs/JOB_ID/CODE.json
stock/jobs/JOB_ID/CODE_history.json
stock/jobs/JOB_ID/CODE_error.json
```

无 `job_id` 时继续读取 `stock/CODE*.json`。所有存在的 `code/symbol` 必须一致，且至少有一个标的字段。缺失返回404及 `RESULT_NOT_FOUND`。

协调服务存在时，结果附带 `delivery_observation`，包含结果内容的 SHA-256 与持久化的 `first_worker_observed_at`，响应为 `no-store`。`first_visible_at`、`public_first_published_at` 保持 null：读取证据不证明人已看到或历史提前公开。浏览器另存 `first_visible_at_client`，仅在页面可见、结果进入视口并经过两帧绘制后记录；`client_clock_trust=unverified`、`scope=this_browser`，不能用于证明真实公开首发。清除浏览器存储会丢失该本地记录。

没有协调绑定时旧只读路径继续工作（公共指针30秒、任务结果300秒缓存），但不声称有持久化观察时间。源码、模型和数据版本与任务编号仍必须单独核对。

有绑定但已没有该任务记录时，任务专属产物仍可按资产、job_id、mode及源码SHA格式读取；`identity_verified_against=artifact_metadata_only` 明示无法与原任务记录比较。保留任务时为 `retained_job`。二者都不把读取时间升级为公开首发证据。

## 协调与额度

- `STOCK_JOBS / StockQueryState`：每股票持久任务与序列化请求；不能用 KV 的先读后写冒充原子去重。
- `QUERY_BUDGET / QueryBudget`：单个全局对象串行登记新任务额度，默认全局60次/小时、每IP5次/10分钟。`QUERIES_PER_HOUR` 与 `QUERIES_PER_IP_10M` 可在服务端配置，具有上界；客户端不能改额度。
- 行情缓存未命中另设全局300次/分钟、每IP30次/分钟额度；缓存命中不再次访问行情源。
- 两个 Durable Object 绑定任一缺失或故障时拒绝新查询，不回退成无限派发。旧只读结果接口仍可用。
- 任务预留与全局额度在 Durable Object 存储中持久化，重建对象不会抹去。额度为滚动窗口；任务记录暂未实现自动保留期清理，应监测存储增长。
- CORS 只是浏览器来源约束，不是用户身份认证。无 Origin 的请求仍受相同额度限制；未来收费账号不应沿用公开IP配额作为唯一权限控制。
- 所有错误返回稳定 `error_code` 与可读 `error`，不返回原始上游正文或凭据。

## 配置与协调上线

本变更不执行部署。获得明确部署授权后：

1. 先让默认分支具备新 `stock_query.yml` 输入、源SHA锁定、任务路径与元数据发布能力，完成对应CI。
2. 保留 `GH_TOKEN` 在服务端 secret。仓库派发需要 Contents 写权限，读取运行需要 Actions 读权限；限制到目标仓库，不能放入网页、README或配置文件。
3. `wrangler.toml` 新增两个 SQLite-backed Durable Object 绑定和 `v1-stock-jobs` migration。旧 `RL` KV 不再使用；移除绑定不等于删除旧namespace或数据，本变更不删除它们。
4. 先在独立预览 Worker、测试仓库与fixture确认迁移和恢复行为，再按授权切换正式服务；不能只跑 Node mock 就声称 Cloudflare 线上并发已验收。
5. 新 Worker 与新工作流就绪后再启用新前端，核查 `ALLOWED_ORIGIN`、Worker URL、真实任务身份与结果版本。

当前查询和 nightly 工作流不再自动触发 Pages；API直接读取 `stock-results`。静态站发布需独立授权。PR事件仅跑离线测试，不运行拟合任务、写结果分支或发布网站。

Cloudflare 同时支持声明式 `exports` 与旧 `migrations` 两种类生命周期配置，但同一 Worker 不应混用。本文件采用现有 Wrangler 广泛支持的 migration 形式；部署时保留历史 migration，不重复改名。[官方说明](https://developers.cloudflare.com/durable-objects/reference/durable-objects-migrations/)

## 本地验证

```sh
node --test workers/stock-query/test/index.test.mjs
```

全部上游请求使用 fixture；覆盖并发去重、跨股票全局额度、对象重建、派发回执丢失、代码版本锁定、任务结果身份、旧接口、当前/历史分离、日线闭盘过滤、缓存降级和超时。它们不是 Cloudflare 生产部署或真实供应商稳定性测试。

浏览器新流程使用仓库根目录的 `tools/stock_async_preview.py`，仅生成明确标注的合成数据，不调用行情、拟合或 GitHub。`dev/stub_server.py` 是**旧接口 legacy stub**，不支持新 `/market`、任务编号及独立历史流程，不能用它验收此次改版。
