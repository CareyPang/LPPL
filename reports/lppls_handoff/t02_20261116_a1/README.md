# T02 两级评分与首次提醒账本

评分合同：`two_level_first_alert_v1`。PR #50 原评价器按源提交 `7f7fe930ab4065295718dfcfe89b87cedcaaf1fb` 原样移植；该分支单独的移植提交已保留。

本目录是研究交付，不是生产配置、模型重拟合、预测能力声明或新 holdout。报告中的数值变化属于**评分定义变化，不算模型进步**。

## 冻结语义

- close；short 10/10；stage 63/42；同价合并 G=5；谷点21/21；阶段上涨段21–126；H=63；lead=5；含端点宽度10。
- `parameter_status` 原样保留为 `RESEARCH_DEFAULT_NOT_FROZEN`；冻结的是评分合同版本，不表示这些研究默认是最优参数。
- 标签状态为 unknown/pending/no_event/mature_event；事件显式保存 support_end、label_available_session、label_version。阶段资格来自事件标签规则，不由拟合窗口长度决定。
- Claims ledger 只追加；历史回放不伪造 first_visible_at，保存 simulated availability/action 与 delay assumption；forward 需 delivery evidence，完整收盘数据的 first_visible_at 不早于带时区的收盘证据且最早下个 session 可行动。
- 所有 arm 共用完整区间几何门：未来、inclusive width≤10、区间起点至少提前5、终点≤action+63；不缩窄 observation interval。
- PR #50 evaluator 对所有保存 forecast 计分并把几何问题列为失败原因；T02 按同一数值阈值将不合格区间留作完整 observation、不作为 formal alert 计分。
- 匹配不读区间：行动日后 H=63 内下一同级事件；遇 unknown/pending 锚点停止并 pending；首条正式主张决定成绩，revision/换episode不修复；一对一并固定 tie-break。
- 零分母输出 null；主表成熟事件分母保留数据/运行失败，条件子集使用显式独立分母；unknown 标签另表列示，不混进 E。
- burden 中 alerts/year 与 alarm-occupied days 包含所有可见 observation/formal/revision/new 通知及未缩窄区间；另列 formal-only alerts 与 occupied days。
- 旧−10%幅度标签如有，保持原字段名和含义；T02 不添加跌幅成功条件，不重命名或覆盖旧幅度标签。

## PR #50 replay 输入与旧新比较

- PR #50 evaluator/replay source SHA：`7f7fe930ab4065295718dfcfe89b87cedcaaf1fb`；saved source 的 evaluator version：`top_time_evaluator_v1_dev`。
- 旧 evaluator 的 `scoring.py` 与 PR #50 源 SHA256 字节相同：`True`（`ab4cff21eee0230ce3a8762dd030b9150a12936ab402d1e8379e6c200d1ae0bb`）。
- 已对 120 个 symbol×arm×scope 组重跑 PR #50 evaluator；按 E/P/TP/FN/recall/precision 对比其封存 metrics，差异 0 项。
- Attribution CSV 含 910 行，即 91 个阶段事件 × 10 个保存策略；每行保留多标签 flags 和优先级唯一主因。
- 原始输入哈希：`{"daily_replay_ledger.csv.gz": "a6df55f1be2333dbfb1680a6573d9f3af6403cb309b0e0a3b3144f71a22c5a71", "evaluations.jsonl.gz": "e5c72ea3371649f96b67ed52e4ef9a8ef4d2a19234e64a64f7367e2588766606", "event_scores.csv": "192be7c6d9f2572ae99056ede31b1e5b2c8d98eea3a23c49fb22a2700dea5db2", "hypothetical_forecasts.csv.gz": "f0dbd3769363b32333777d61183e97fd2971adff039a219b55f6874e32f17cb2", "input_map.json": "f87ec2341044d5ab1b17b9f69859d8e045578a6d980201eb08564828bff15d53", "label_books.jsonl.gz": "2d844d272bd5cb66fd13fda65a6fd4e30077d59c994fdd32972146de8609aa10", "manifest.json": "4dd581cedbf4e3bb595cdfac392d57a49dd99146e1a1e0d80295c7d1135e6a15"}`。
- PR #50 默认数值与 T02 研究默认相同；变化集中于版本化、多态标签状态、append-only/PIT账本、首正式区间指标和显式分母。逐项见 `old_vs_new_scoring.md`。
- 旧对照中 `TP/P`、首次旧 claim 和旧 notifications 沿用 PR #50 定义；T02 用首 formal claim 与明确的已解析分母。未定义的新旧同名指标须按 `old_vs_new_scoring.md` 注释解释。

## 数据与 sh000001 语义检查

- sh000001：VERIFIED_ON_FROZEN_QFQ_SNAPSHOT；short 2024-03-18=mature_event；stage 2024-05-20=mature_event。
- 本地 qfq 文件只读；6/6 个指数源 SHA 与 PR #50 manifest 一致；其调整类型为 qfq。
- label state/event 表由本地 frozen v20261024 qfq 生成；unknown 清单同时标记本地重算和 PR #50 保存 label book 的来源。它们是事后快照标签，不代表当时可得因子或真实首见时刻。
- 未知/未成熟 label 状态行：1626，详见 `unknown_label_list.csv`。

## NOT_ESTABLISHED

1. PR #50 历史模型 vintage、用户实际可见时间与真实发布/送达证据；其输出都是 hypothetical replay。
2. 回放所用观测日期是完整交易所日历，或假设 action_session 等同实际可成交时间。
3. v20261024 qfq 的历史逐日 PIT 复权因子和公司行动可得性；快照哈希一致不建立PIT。
4. 任何模型预测技能、独立前瞻表现或性能改善；本任务不运行扫描、重拟合或 forward study。
5. PR #50 保存区间是否曾真实通知用户、原始 scope 的真实语义及线上stage/short分级。
6. attribution 主因是互斥的审计分类，不证明失败机制的因果关系。

## 交付与复现

- `scoring_contract_frozen.json`：版本、默认值、状态、几何门、账本和指标分母。
- `label_state_table.csv` / `label_event_table.csv` / `unknown_label_list.csv`：逐session标签、事件支持和未知清单。
- `hand_cases.json` 与 `hand_cases.sha256`：人工预期 fixture 的原样副本及哈希。
- `historical_claim_ledger.csv`：历史回放 claim rows，保留 observation 原宽度及模拟时序。
- `first_alert_failure_attribution.csv` 与 `old_vs_new_scoring.md`：91×10事件策略归因及旧/新指标。
- 用 `python scripts/research/t02_manifest.py` 在源 PR #50 commit 和本地 frozen data 可用时再生；目标目录已存在会拒绝覆盖。
