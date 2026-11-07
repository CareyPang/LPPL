# market-context Worker

独立的 P1 市场背景快照接口。它与 `workers/stock-query` 的个股 `/market` 分离，也不参与 LPPLS 拟合。

## 接口

- `GET /context?date=latest`：读取最新已封存快照。
- `GET /context/snapshot?date=YYYY-MM-DD`：只读取对应日期；没有该日期时返回 `CONTEXT_NOT_READY`，不会用当前快照补造历史。
- `POST /context/refresh`：服务端定时任务调用，要求 `X-Market-Context-Token`，返回 `202 + job_id`，同一日期并发刷新去重。
- `GET /context/status?job_id=...`：读取刷新任务状态。

快照使用 `market-context.v1` 契约，保留 `source/asof/fetched_at/status/stale_reason/snapshot_sha256`。来源失败时整体为 `partial`，局部模块保留错误；涨停原因、题材标签和历史晋级率缺失时写 `status=not_available`，不写成 0。

本目录只提供代码和本地 fixture 验证，不代表已部署 Cloudflare Worker。正式部署前仍需配置来源许可、刷新 token、定时任务、数据保留期和大陆网络可用性。
