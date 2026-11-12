# Phase 4 前瞻日志硬化：核验命令、周检工作流、精度指标落盘（2026-11-12）

> 代码 `research/pipeline/forward_log.py`（新增 `check`、`precision` 子命令与 `_alarm_matrix`），工作流 `.github/workflows/forward_log_check.yml`（每周一 10:00 北京时间 + 手动），测试 `tests/test_forward_log_check.py`。

## 事先写死的成功标准与结果
| # | 标准 | 结果 |
|---|---|---|
| 1 | 对仓库现有 ledger（24 条）运行 `check`：哈希 24/24 一致、无重复、无缺工作日、无"首条有、后续缺"的顶层键 | **通过**（`ok=True`） |
| 2 | 注入四类故障各一（篡改文件内容、删顶层键、ledger 重复行、封存日缺口）在单元测试中必须全部被捕获 | **通过**（6 个测试全过：篡改→`bad_hash`，删键→`schema_drift`，重复→`duplicates`，缺口→`missing_bdays`，停更→`stale`） |
| 3 | 新增顶层键只记录不判失败（契约允许加字段） | **通过**：2026-10-29 起 12 个文件新增 `price_history`，记入 `schema_added`，不触发失败 |
| 4 | `precision` 对成熟记录（asof ≤ 最新日 − 120 交易日）按 Phase 0 同一定义（首报、lead、hit、miss_up、avoid、fwd120）落盘；无成熟记录时正常退出 | **通过**（当前输出"成熟记录中无首报"，`_alarm_matrix` 有单元测试） |
| 5 | 全量 `pytest -m "not network"` 通过、`ruff` 通过 | **通过** |

## 核验发现的实际问题（需要你决定）
- **前瞻日志自 2026-10-30 起停更**：`check` 报 `stale_bdays=9`（exit 2）。原因：`scripts/daily_update.sh`（跑 `research.pipeline.daily` 六指数 + `forward_log seal`）**没有任何定时工作流调用它**；`market_daily`/`stock_nightly` 发布的是市场复盘与成分股扫描，不封存指数契约 JSON。ledger 只有 10-27～10-30 四个 as-of。
- 底部侧契约字段 `bottom.state_p / thrust_p` 均为 `null`（fail_i），所以 `precision` 目前只能落盘顶部侧 T-top/P-top；底部四指标要等有可显示的底部信号后才有对象。

## 建议
1. 新增 `forward_log_seal.yml`：工作日 18:30 北京时间跑 `scripts/daily_update.sh` 并把 `forward_log/` 变更提交到 main（需要 `contents: write`；取数走腾讯/新浪，限速已内置）。这是前瞻样本能否在 2028-H1 攒到 ≥6 季度的前提。本 PR 不加（涉及写 main 的权限与取数策略，需你确认）。
2. 周检 `forward_log_check` 已就位：硬失败 exit 1、停更 exit 2，产物含 `forward_log_check.json` 与 `precision_*.csv`。
