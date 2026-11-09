# P1 两日真实快照闭环验收（2026-11-08）

本记录只覆盖离线重封存、append-only bundle 和 Worker seed 前验收。没有执行 Worker/Pages/Tencent seed、部署、合并或发布。

## 交易日历

**VERIFIED**：日历来源为上交所《关于上海证券交易所2026年部分节假日休市安排的通知》，发布日期 2025-12-22：

- URL: <https://www.sse.com.cn/disclosure/announcement/general/c/c_20251222_10802507.shtml>
- 官方原始响应已封存于 `D:\CodexData\analysis\lppl-real-preview-20261107\calendar-evidence\sse-2026-holidays-ff188c710b8904758c185eb955e9eaa2c9bd7c2061af984d4f1d743f899c12a4.raw`
- 原始响应 SHA256: `ff188c710b8904758c185eb955e9eaa2c9bd7c2061af984d4f1d743f899c12a4`
- 交易日历版本: `sse_2026_20251222_v1`
- 覆盖范围: 2026-01-01 至 2026-12-31，共 242 个交易日
- 日历 artifact SHA256: `07061ee00f5e6d025f84dc9f248ed3a660767f36f8a3b6514cbeee7ff1687593`

仓库内同步保存：[trading_calendar_verified.json](./evidence/market-context-p1-20261108/trading_calendar_verified.json)。该日历只覆盖已发布的 2026 年休市安排，不声称覆盖临时停市或 2027 年安排；本次两日是 SSE/SZSE 共同开市日期。

## 重封存

**VERIFIED**：旧快照和原始响应未被覆盖。重封存输出位于：

`D:\CodexData\analysis\lppl-real-preview-20261108-verified-v2\`

重封存脚本为 [reseal_market_context.py](../../scripts/reseal_market_context.py)，只复制原快照、注入可追溯日历元数据、重算 canonical `snapshot_sha256`，并拒绝已有目标文件内容变化。

| asof | 状态 | calendar prior_asof | progression | snapshot_sha256 | 文件 SHA256 |
|---|---|---|---|---|---|
| 2026-11-05 | partial | 2026-11-04 | not_available（没有伪造前一日晋级结果） | `0c2b86b7102f2f53036be48ee316220eeb530114c465087a8fc36de0c8c62834` | `96a7a431ab8761c20dfb365a55ce2a4bd5fea9a7e2e17ec48c1fd6d19050328e` |
| 2026-11-06 | partial | 2026-11-05 | fresh，prior=2026-11-05 | `1d75513e5608bb544edc05981871cc9fb76bd6081ac7710993d574a7e2b8660b` | `cfc58adbce3d2df1d8d5e90e907bb3ef91c1673e170beea441cebc269479c262` |

两日均保留两份 P1 原始来源哈希；整体为 `partial`，没有把可选来源失败升级成全源成功。

## append-only bundle

**VERIFIED**：运行 `prepare_market_context_seed.py` 后得到：

- bundle: `D:\CodexData\analysis\lppl-real-preview-20261108-verified-v2\market-context-seed\manifest.json`
- bundle SHA256: `227af1d3b69924c68f8dcff998121f55097d3d00e275e10b2e52ec6faad2862a`
- snapshot_count: `2`
- 两日为验证日历中的相邻交易日
- 第二日 `prior_asof=2026-11-05`
- 第二日 progression 为 `fresh`
- 同日哈希变化和日期缺口会被拒绝

## gate 和 Worker seed 前验收

**VERIFIED**：`market_context_gate.py` 返回：

```json
{
  "real_snapshot_count": 2,
  "ready_for_frontend_polling": true,
  "progression_ready": true
}
```

**VERIFIED**：新增 [validate_market_context_seed.mjs](../../scripts/validate_market_context_seed.mjs) 使用 Worker 的实际 `validateSeedSnapshot` 对两份原始 JSON 文本验收，结果为两份 `ok=true`、`ready_for_worker_seed=true`。验收覆盖 schema、descriptive evidence、交易所日历哈希、来源 `raw_sha256`、snapshot hash 和原始数字词法。

**NOT_ESTABLISHED**：上述结果只证明“可以进入受控 seed 请求”。当前没有 Worker URL、seed secret、KV 写入回执、Pages 环境变量或线上历史读取结果；前端真实轮询仍未开启。

