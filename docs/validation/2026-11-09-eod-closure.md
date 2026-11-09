# 日终复盘归档实现与本地验收

日期 2026-11-09；起始版本 `d9f0ca4`。本轮只有本地代码、测试、研究导入与 PR 更新；没有在线 seed、部署、合并、发布或购买。

## 实现范围（VERIFIED）

- 新纯质量检查：完整 ZT/ZB/DT 与 top20 分开；总数、行数、重复/无效代码、连板、返回日期与分页证据逐项检查。结构完整不等于来源证据完整。
- 新本地 append-only SQLite 账本：原始 HTTP 响应、开始/失败/跳过回执和同日修订；UPDATE/DELETE 被拒绝；单次事务提交快照与结束回执。
- 新受控日终入口：验证日历/覆盖范围、北京时间 15:30、未来/休市日期；默认来源访问未审核时不发请求；只有显式 capture 且逐源策略通过才请求。
- 网络路径只读取三个日终池、THS 原因标签与昨日表现；每次最多 10 次请求，单响应归档最多 8 MiB；保留实际 body 后再解析。当前这条联网路径只用离线 HTTP 样例测试，未连接供应商。
- 两日晋级要求原始响应、来源覆盖和相邻已验证会话；前日版本必须早于本次运行开始，晚取得资料不能倒填。
- 真实空集合、覆盖不全、失败与 stale 分开。THS 只给 page1/limit200 或只有请求日期时，不声称全量/来源日期已验证。
- 恢复核验数据库、payload/raw hash、run/回执/修订日期与时间关联；损坏状态不可静默替换为新空库。
- nightly 恢复同 workflow/main 的前一状态，失败后独立 finalize；只有验证成功的 state 上传为下一轮恢复输入。诊断文件单独保存；默认仓库开关与来源策略均关闭，且任务必须在私有仓库运行。公开仓库不能上传原始研究响应，即使误开变量也会跳过；腾讯私有后端仍需另行授权部署。

原 `update_market_context.py`、旧 gate、旧源解析器及旧结果继续保留。新日终路径是更严格的独立实现，不用更新旧报告来掩盖证据差异。新研究归档始终不可公开、不可作为模型输入；首次公开可见时间为 null。

## 真实旧两日离线运行（VERIFIED）

使用新 CLI 分别读取原 11 月 5/6 日 JSON；没有重抓数据。执行证据：[local-acceptance.json](evidence/eod-closure-20261109/local-acceptance.json)。

| 日期 | ZT / ZB / DT 唯一行 | 原因/标签覆盖 | 新结果 | 原件 SHA256 |
| --- | --- | --- | --- | --- |
| 2026-11-05 | 84 / 48 / 0 | 83 / 84 | partial，严格晋级 not_available | `96a7a431ab8761c20dfb365a55ce2a4bd5fea9a7e2e17ec48c1fd6d19050328e` |
| 2026-11-06 | 32 / 14 / 15 | 32 / 32 | partial，严格晋级 not_available | `cfc58adbce3d2df1d8d5e90e907bb3ef91c1673e170beea441cebc269479c262` |

原 11 月 6 日旧晋级 `fresh` 保存在新记录的 `legacy_progression`，没有改写原文件。新口径不承认旧记录已有完整 raw/date/pagination 证明。原因和标签原文仍保留；两日的取得时间晚于资料日，`vintage_status=retrieved_after_asof`。

本地数据库：`D:\CodexData\analysis\lppl-eod-closure-20261109\real-import\journal.sqlite`。两次导入生成 revision 1、2，旧文件 hash 导入前后相同。两次新归档的本地可用时间为 11 月 9 日，不是原预测发布时点。

实际执行备份 → 新路径恢复：`restored_revisions=2`，数据库/内容校验通过。当前 raw_response_count=0，明确反映旧原始响应没有被补造。

额外运行两次无网络门禁：

- 当日 2026-11-09 北京时间收盘前：`skipped / EOD_NOT_CLOSED`，没有发出行情请求。
- 指定历史日 capture，但审核文件仍默认关闭：`failed / SOURCE_ACCESS_NOT_REVIEWED`，没有发出请求，也没有替换已有两份研究快照。

最终账本有四次执行：两次 partial 导入、一次 skipped、一次 failed；只有两份修订。失败不等于当日无行情，保留上次可读资料日 `2026-11-06`。

## 自动化验收（VERIFIED）

- 新增 164 项针对测试：quality 41、archive 48、pipeline 34、restore/finalize 41。
- 最终全仓非网络 Python：**847 passed、2 skipped、3 deselected**；6 条既有 Pandas 弃用警告，0 失败。最终执行退出码为 0，结果标记与独立收集的 849 项选中测试一致。
- Ruff 对 research/tests/server/tencent 及新增三个 CLI 检查通过。
- 真实 SQLite 六线程 24 个 run、同一 run 双封存竞争、写入中断、失败与已有版本并存、坏备份、时间倒填、跨日响应、raw 字节/非200、实际响应解析失败前归档均有测试。
- THS 集成测试保留实际解析器、响应归档和 SQLite，只替换 HTTP 传输：验证 ISO/紧凑日期与完整总数可通过，错日/缺总数/分页截断保持 partial；修复来源日期证明没有同步到原因/题材的缺口。
- 未运行独立模型重拟合、外部采集或上线性能测试；原拟合周期 1.5、时间窗、跨尺度聚类及两级提醒评分未改动。

## 操作方式

从项目根目录使用既有 Python 环境，分析缓存和输出使用 D 盘。离线导入：

```powershell
. 'D:\CodexData\config\analysis-env.ps1'
python -m scripts.capture_market_eod `
  --archive D:\CodexData\analysis\my-eod\journal.sqlite `
  --calendar docs/validation/evidence/market-context-p1-20261108/trading_calendar_verified.json `
  --asof 2026-11-06 --input-context <已封存context的路径> `
  --report D:\CodexData\analysis\my-eod\report.json
```

真实 capture 改用 `--capture --source-policy <已完成逐源审核的策略文件>`；这不是当前启用指令。仓库默认 policy 不允许联网。定时 workflow 还需要单独启用开关且处于私有仓库，当前没有启用或执行。

GitHub 官方说明，有仓库读取权限的登录用户能下载 artifact。因此公开仓库的 artifact 不能当作私有研究存储；新增私有仓库门禁，而不是用 `publication_eligible=false` 冒充访问控制。恢复参数依据 [artifact REST API](https://docs.github.com/en/rest/actions/artifacts#list-artifacts-for-a-repository) 和 [跨运行下载说明](https://github.com/actions/download-artifact#download-artifacts-from-other-workflow-runs-or-repositories)；可见性依据 [下载权限说明](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/download-workflow-artifacts)。

Tencent 后续使用独立持久存储运行同一采集逻辑，前端只读归档结果；共享采集不因每个用户打开页面重复请求上游。公开投影及在线写入仍需独立审核与明确授权。

## 尚未成立

**NOT_ESTABLISHED**：逐源实际研究访问许可、供应商频率、公开再分发权限、大陆可达性、完整返回日期/分页字段的实时样本、连续真实日终采集、生产持久化和公开前端更新。不能把测试、规范化旧资料或 workflow 配置当作这些结果。

**NOT_INSPECTED**：腾讯实际实例、网络延迟/高并发、真实每日调度运行、线上恢复和用户体验。本轮没有重新设计 UI，因此不重复声称新一轮桌面/手机视觉验收。

极端 runner 销毁可能导致本次未上传回执丢失，`always()` 不保证跨机器持久性；前次有效 artifact 不会被坏状态替换。生产需持久卷与独立运行监控。

下一项按 [四阶段执行规划](../product/information-closure-plan-2026-11-09.md) 完成逐源审核与有限真实样本，再积累连续交易日；完成后才进入个股资讯全链路和统一时间轴。
