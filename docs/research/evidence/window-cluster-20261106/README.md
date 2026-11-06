# 时间窗与跨尺度聚类研究证据

正式报告：[研究方法、全部结果与裁定](../../2026-11-06-window-selection-and-cross-scale-clustering.md)。这是对既有开发段拟合的确定性重筛，不是新的样本外预测检验。

基线为完整周期1.5，九组策略在执行前记录于提交`0f6f154fc1736e0704c69e643cec07e78dbd5548`。源码、运行环境、参数、原输入及输出哈希记录于[v1/manifest.json](v1/manifest.json)。输入来自上一轮已取得的6指数g2拟合及冻结行情/旧main标签；[原包来源与摘要](../oscillation-refilter-20261106/github-artifact-inputs.json)。原文件没有覆写，重跑必须指定新的空目录。

| 文件 | 用途 |
|---|---|
| `v1/summary.csv` | 各指数及汇总，common/own覆盖分别报告，九组与两个H全部保留 |
| `v1/events.csv` | 每事件的可评价原因、首次报警、下一交易日可行动提前量、首区间联合结果 |
| `v1/paired_events.csv` | 预先指定对照之间的新增/丢失事件与共同命中的提前量变化 |
| `v1/asofs.csv.gz` | 所有标的/日期/策略，包含无报警、不可用状态和稳定性诊断 |
| `v1/scales.csv.gz` | 逐档原eligible窗口、合格窗口与固定分母 |
| `v1/clusters.csv.gz` | 所有合格候选簇，含主簇标记；未按事后事件重新挑选 |
| `v1/members.csv.gz` | 每个簇的窗口、尺度、前视距离及权重，可回溯一窗一票 |
| `v1/opportunities.csv.gz` | 所有评价机会，包括无报警日期；用于计算每100机会报警数、假报警占比和连续段数 |
| `verification.json` | 独立算术检查及本地测试记录 |

`.csv.gz`是gzip压缩的UTF-8 CSV，可用常规解压软件打开；Pandas也可直接`read_csv`。压缩时间戳固定为0；原始数值字节通过Git `-text`保留。计时字段会随运行负载变化，不承诺不同机器的输出包逐字节相同。

**VERIFIED：**本轮本地25项新增测试通过，与已有单位/规则回归合计39项通过，Ruff通过。独立检查4,236个标的日期、10,680个候选簇和87,160条成员记录通过；九组共同事件分母都是53。合法报警包含关系通过，thin因分母粒度不同不被错误要求为full子集。输入和执行源码前后SHA一致。

```text
pytest tests/test_window_clusters.py tests/test_window_cluster_research.py tests/test_oscillations.py tests/test_features_lppls_rules.py
ruff check research tests tools/lppl_window_cluster_research.py
```

**NOT_ESTABLISHED：**高覆盖不等于顶部预测准确率。W4 H120的50/53是“旧事件代理之前有过至少提前5日可行动报警”，同时其约79%的报警日期没有匹配旧目标；不能只展示前一个数字。10bar窄区间是算法约束，覆盖仍需单独检验。旧main是事件段结束后下一交易日代理，既有数据已被使用，均没有原始实时发布证据。

**VERIFIED（成本边界）：**thin计划窗口95→28，仅证明窗口数量减少70.5%，未实测新拟合加速或用户等待改善。`asofs.analysis_seconds`在同一日期多个策略间复用同一次mode计时；若求和须按symbol/date/mode去重，例如full只取`or4_full`、thin只取`or4_thin`。计时不是优化器成本，没有硬件隔离。

本轮代码仅在研究工具和测试中引用，未切换生产模型、网页或Worker；未合并或发布。GitHub实际CI状态以PR #50的最新提交为准，本地通过不替代远端结果。
