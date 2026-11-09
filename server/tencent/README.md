# 腾讯云兼容层（本地契约适配器）

本目录只冻结未来 CloudBase 云函数/CloudBase Run 的 API 与存储语义，不包含腾讯云 SDK、网络客户端或部署脚本。

`TencentCompat.dispatch()` 兼容现有前端需要的路由：

- `GET /market?code=600519`
- `POST /query`
- `GET /status?code=600519&job_id=...`
- `GET /result?code=600519&kind=latest|history|error&job_id=...`
- `GET /context?date=latest|YYYY-MM-DD`
- `GET /context/status?job_id=...`
- `POST /context/seed`
- `POST /context/refresh`

`InMemoryTencentStore` 是本地测试 double。生产实现必须把以下操作替换成原子数据库/COS 操作：

1. `jobs` 以 `job_id` 为主键，并以 `code + mode` 对运行中任务去重；
2. 结果读取带 `job_id` 时绝不回退到其他任务；
3. `market_snapshots` 以 `asof` 为不可变键，重复 seed 返回冲突；
4. `latest` 只能向更新日期推进；
5. refresh 未配置已核验源时 fail-closed，不产生空快照；
6. stale 只保留上一份成功数据和失败原因，不用当前资料补造历史。

当前适配器没有任何云写操作，测试命令：

```sh
pytest tests/test_tencent_compat.py -q
```

测试通过不代表腾讯云线上部署、并发、网络或费用已经验证。
