# R-TR1 逐日风险状态的恢复与验收

策略日报需要四个指数逐交易日的三条件触发数 `n_on`。风险时段摘要只保存某些触发区间，不能还原全体日期和 K=2 的信号。每日市场快照保存的近期宽度与融资历史也不足以还原 2014–2022 年的开发段。

## 先恢复已有原件

首选原研究执行环境留下的 `n_on_history.json` 和相应输入清单。2026-11-19 核对的 [策略 PR](https://github.com/CareyPang/LPPL/pull/158) 与 [结果分支快照](https://github.com/CareyPang/LPPL/tree/98dd91c67bf59cff552a1bae25885eb793baba1c) 均未收录该文件。该 PR 的市场 smoke 压缩包只含两份市场 JSON。11 月 1 日发行的通用研究包早于本次实验，其大文件未解包核验。

现有读取格式为一个 JSON 对象，键为 `sh000001`、`sh000300`、`sh000852`、`sh000688`，每个值是按日期排列的记录数组。记录示例为 `{"date":"YYYY-MM-DD","n_on":2,"concentration_on":true,"margin_on":false,"index_on":true}`。来源、数据文件 SHA-256、规则提交号、各指数起止日、缺失行和生成时间另存清单。每条状态带三项标志时须与 `n_on` 一致。日期须唯一，计数须为 0–3 的整数。

## 从真实输入离线准备候选种子

以下为待输入齐备后执行的 PowerShell 步骤。本次修复未运行全历史计算。以留有出具方、口径、版本和数据截止日记录的文件替换示例路径。需要每日市场宽度（`date,MCL`）、集中度（`date,top50,top100`，占比用小数）、全市场融资余额（`date,RZYE`）和每个指数日收盘（`date,close`）。为首个可评估日提供足够的历史预热输入。

```powershell
. 'D:\CodexData\config\analysis-env.ps1'
$sourceDir = 'D:\CodexData\work\verified-strategy-inputs'
$reviewDir = Join-Path $env:CODEX_ANALYSIS_WORK ('risk-seed-' + [guid]::NewGuid())
$cutoff = '2026-11-18'
$cli = @(
  '--asof', $cutoff,
  '--breadth', (Join-Path $sourceDir 'breadth.csv'),
  '--concentration', (Join-Path $sourceDir 'concentration.csv'),
  '--margin', (Join-Path $sourceDir 'margin.csv'),
  '--out', (Join-Path $reviewDir 'episodes-review.json'),
  '--history-out', (Join-Path $reviewDir 'n_on_history.json')
)
foreach ($code in @('sh000001','sh000300','sh000852','sh000688')) {
  $cli += @('--price', ($code + '=' + (Join-Path $sourceDir ($code + '.csv'))))
}
python -m research.data.top_risk_episodes @cli
if ($LASTEXITCODE -ne 0) { throw '生成失败，请核对输入数据和列名。' }
Get-FileHash (Join-Path $reviewDir 'n_on_history.json') -Algorithm SHA256
```

1. 按原[预登记](preregistration_strategy_v1.md)逐指数对齐每天的行情和状态。核对每个开发／检验段的期望行数、实际行数、重复日期、缺档与第一处缺档。上市初期如果缺少计算历史分位所需的样本，单列为待核项，保留登记日期及旧报告。
2. 对至少一个触发日、一个未触发日和一个跨节假日样本，核对集中度五日均值、融资数据可用的前一交易日、分位观察数、指数位置及三项触发数。另核对既有风险时段表。单凭时段表一致不足以验收全部状态。
3. 历史状态获验收后，可以传入现有 `python -m research.backtest.publish --previous-history <核验的种子路径> --date <截止日> --breadth <同日市场宽度文件> --out <新的本地输出目录>`。这个步骤会请求行情并生成策略回放，应与只读核验分开。采用新的输出目录时，报告和历史文件会在全部生成成功后一起出现。已有目录按文件原子替换，供单一写入者使用。
4. 日报优先读取结果分支的 `strategy/n_on_history.json`，首次也可读取经审查入库的 `data/top_risk_n_on_history.json`。只有完整种子、输入记录和独立复核齐备后，再单独决定是否写入仓库。输入缺失时策略步骤失败，其他市场模块按各自的执行结果继续发布。策略文件只在策略步骤成功时进入同一次 Git 提交。
