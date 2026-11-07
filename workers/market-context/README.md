# market-context Worker

独立的 P1 市场背景快照接口。它与 `workers/stock-query` 的个股 `/market` 分离，也不参与 LPPLS 拟合。

## 接口

- `GET /context?date=latest`：读取最新已封存快照。
- `GET /context/snapshot?date=YYYY-MM-DD`：只读取对应日期；没有该日期时返回 `CONTEXT_NOT_READY`，不会用当前快照补造历史。
- `POST /context/refresh`：服务端定时任务调用，要求 `X-Market-Context-Token`，返回 `202 + job_id`，同一日期并发刷新去重。
- `POST /context/seed`：受控服务端导入已封存的真实日期快照，要求独立的 `X-Market-Context-Seed-Token`。请求必须包含 `market-context.v1`、工作日 `asof`、`descriptive` evidence、至少一个来源 `raw_sha256` 和匹配的 `snapshot_sha256`；已存在的日期永不覆盖，较早导入不会回退 `latest`。
- `GET /context/status?job_id=...`：读取刷新任务状态。

快照使用 `market-context.v1` 契约，保留 `source/asof/fetched_at/status/stale_reason/snapshot_sha256`。来源失败时整体为 `partial`，局部模块保留错误；涨停原因、题材标签和历史晋级率缺失时写 `status=not_available`，不写成 0。

本目录只提供代码和本地 fixture 验证，不代表已部署 Cloudflare Worker。正式部署前仍需配置来源许可、刷新/seed token、定时任务、数据保留期和大陆网络可用性。`/context/seed` 不接受浏览器公开调用，建议由受控 artifact 导入任务调用。

`MARKET_CONTEXT_SOURCE_URL` 必须由部署环境显式配置；未配置时 `/context/refresh` 会失败并保持已有历史快照不变，不会回退到仓库 `main` 的 mock 数据。
