# 腾讯云部署迁移边界

本文只冻结提供商无关的接口和迁移顺序，不执行购买、部署或数据写入。

## 当前决策

- **控制面**：首版建议 CloudBase 云函数提供 HTTP API、定时任务和轻量协调。
- **状态与快照**：CloudBase 数据库保存 jobs、预算、市场缓存和不可变日期快照；COS 保存原始响应、manifest、拟合证据和 ZIP。
- **计算面**：先保留 GitHub Actions 的 SciPy 计算；需要迁移时优先使用 CloudBase Run 容器。SCF 只适合短任务或低流量试验，历史回放和大依赖不直接放到同步 HTTP 请求中。
- **前端**：只依赖统一路径契约，不读取 Cloudflare 专属地址。腾讯后端必须兼容现有 `/market`、`/query`、`/status`、`/result` 和 `/context` 语义。

腾讯官方资料说明 [CloudBase 云函数](https://cloud.tencent.com/document/product/876/46899) 支持 HTTP、定时触发、Node.js/Python，并与数据库和存储集成；[CloudBase Run](https://cloud.tencent.com/document/product/876/121989/) 可运行自定义容器；[SCF](https://cloud.tencent.com/document/product/583/9694/) 适合事件驱动函数，但其资源和时长边界需要在真实任务上复测。正式购买前仍需以控制台当前规格和价格为准。

## 前端配置契约

部署构建时注入一个同源配置对象，不能把密钥放进网页：

```html
<script>
  window.LPPL_RUNTIME_CONFIG = {
    queryApi: 'https://api.example.com',
    contextApi: 'https://api.example.com',
    contextEnabled: false
  };
</script>
```

也可以继续使用兼容字段 `LPPL_QUERY_API`、`LPPL_CONTEXT_API` 和 `LPPL_CONTEXT_ENABLED`。运行时代码只使用公开 API 地址和开关，不接受 seed token、数据库凭据或腾讯云密钥。

## 数据库约束

1. `jobs` 以 `job_id` 为主键，`symbol + asof + source_revision + mode` 建唯一约束。
2. `market_snapshots` 以 `asof` 为不可变键；重复写入返回冲突，不覆盖历史。
3. `latest` 只能向较新的 `asof` 推进；失败刷新只能写 stale 元数据。
4. `raw_sha256`、`snapshot_sha256`、`source/asof/fetched_at/status/stale_reason` 必须和 `market-context.v1` 一起保存。
5. 失败不写空数组或 0 值，不用当前资料补造历史日期。

## 分阶段迁移

1. 完成前端配置抽象和 P2/P3 TTL/刷新契约。
2. 在本地或 CI 用两日真实 P1 快照跑 seed/replay 协议测试。
3. 创建腾讯云测试环境，先部署只读 API 和快照读取，不开启生产刷新。
4. 导入两日快照并用 GET、哈希和历史日期回放验收。
5. 再接入已完成许可、频率和大陆网络核验的 P2 源；源不可达时保留上一份快照并标 stale。
6. 最后启用 P3 约 6 小时异步刷新。P3 只显示预测市场隐含概率，永远不进入 LPPLS 或评分。

## 证据状态

- **VERIFIED**：前端运行时配置已支持提供商替换；P2/P3 刷新规则不依赖云 SDK。
- **NOT_ESTABLISHED**：腾讯云账号、地域、价格、域名/备案、数据库方案、网络白名单和真实大陆链路尚未核验。
- **NOT_INSPECTED**：腾讯云测试环境部署、压测、费用和真实上游长期可达性。
