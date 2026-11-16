# DS 置信度：公开比例法的独立研究对照

日期：2026-11-16。状态：`TASK_SPEC_ONLY / EXPERIMENTS_NOT_RUN`。本文件是 Devin 的实施契约；没有新增拟合、回测成绩或生产功能。

## 1. 公开依据与方法身份

**VERIFIED（公开方法定义）：** Zhang、Zhang、Sornette（2016）在 “Consolidated DS LPPLS indicators” 节将 Confidence 定义为通过指定过滤条件的拟合窗口占比；Trust 则涉及残差重采样后的稳健性，两者不同。论文用不同窗口检验结构对尺度的敏感性。[原论文及 Table 3](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0165819)

本轮采用该比例思想，研究名为 **D1：公开 DS 置信度比例法的固定窗口改编**，`method_id=DS_PUBLIC_RATIO_FIXED_WINDOWS_1P5_V1`。不是论文全部实验的原样复现，也不是当前 Sornette Finance 的 Bubble Score/Combo 复刻；当前商业产品的精确组合、权重和数值等价性为 `NOT_ESTABLISHED`。DS-LPPLS 深度学习项目与这里的 DS Confidence 不是同一算法，不引入其网络训练。

以下是本项目为可比研究作出的明确选择，不能标成“官方默认”：

| 项目 | 本轮冻结选择 | 证据/边界 |
|---|---|---|
| 输入与时间域 | B0 的 log price，`tc > t2` | 项目 future-only 研究契约 |
| 振荡门槛 | 完整周期 `omega/(2*pi)*log((tc-t1)/(tc-t2)) >= 1.5` | 用户指定基线，不宣称论文统一采用1.5 |
| 窗口集 | T06a 登记的 B0 精确窗口清单及哈希 | 不临时扩大到论文窗口网格，不按结果挑窗口 |
| 其他过滤、求解器 | 从 B0 提取并逐字段冻结；包括边界、阻尼和数值有效规则 | 与论文 Table 3 的差异另列表，不直接替换生产参数 |
| 起点选择 | 不启用 Lagrange 或事后起点裁剪 | #99 F4 失败是 PR 作者报告，本轮未重跑；另案才能重启 |
| Trust / bootstrap | 本轮不计算 | Confidence 比例不能冒充 Trust 或统计置信区间 |

公开定义可核对，不等于本项目已实现或证明有效。D1 工程状态先写 `NOT_IMPLEMENTED`，效果状态写 `NOT_ESTABLISHED`；完成手工测试后才可把对应工程项改为 `VERIFIED`。

## 2. 单窗口计票与失败账本

每个 `asset/asof/window_id` 最多一票。窗口计划在求解前冻结，以当时日历和已登记的资产资格规则生成；新上市的事前结构性不适用窗口可另记 `NOT_APPLICABLE_PREDECLARED`，但不能把本应存在的缺失价格、停牌映射错误或求解失败事后排出分母。窗口排除规则、数量和原因必须可审计。

1. 固定每窗口 seed 清单、尝试/重试预算、数值有效条件和确定性并列规则。
2. 固定尝试计划全部结束后，在数值有效候选中按最小 SSE 选代表解；并列时按冻结的 `attempt_id` 排序。SSE 基于同一窗口同一输入，不能跨窗口比较选代表。
3. **先选代表，再做结构过滤。** 最小 SSE 解过滤失败时，该窗口不合格；不能改挑 SSE 较差的合格解增加占比。若 B0 过去采用 first-success 或不同代表规则，先记录契约差异；D1 从完整 attempt 账本构造自己的代表，不覆盖 B0 代表及成绩。
4. seed、同一解的复制、重试和 `y/-y` 的等价拟合不是额外窗口票。相同区间即使同时带多个尺度标签也只有一个窗口身份；总体汇总只算一次。
5. 有候选但计划尚未完成为 `PENDING`；全部候选数值无效/失败为 `UNKNOWN_SOLVER`，不直接判定“没有泡沫”。有限参数也不证明找到全局最优。
6. 复用缓存必须满足 T01 的完整身份与 attempt 留存；旧聚合只有合格解时，不能反推分母。缺少 attempts 标 `SOURCE_LEDGER_INCOMPLETE`，另登记补算成本，不能偷偷重拟合后称零成本复用。

对固定资产、asof、计划窗口全集，以**已核实方向的账本**为主，使用互斥终态计数：

```text
N = Q_direction + R_direction + U_solver + U_data + U_pending + U_contract
resolved = Q_direction + R_direction
unknown  = U_solver + U_data + U_pending + U_contract
coverage = resolved / N
```

`Q_direction` 为代表解通过该方向全部冻结过滤的窗口；`R_direction` 为代表解数值有效、过滤已完成但不合格于该方向（含合格于另一方向的窗口）。`U_contract` 包括应有attempt账本缺失、局部方向转换/来源映射无法核实等契约缺口，必须进入unknown及范围计算，不能只写warning而仍标COMPLETE。固定窗口计划本身无法核实时直接拒绝产出正常快照，记 `WINDOW_PLAN_UNVERIFIED` 错误；不能冒充N=0。每个拒绝/未知原因留存。

同一窗口有多个问题时，使用冻结优先级给唯一主状态：契约/身份缺口 → 数据缺口 → 未终结尝试 → 终结求解无效 → 已解析过滤结果；所有次要原因同时留存，计数不重复。

方向统一到 `log P=A+B*tau^m+...`：对采用 `0<m<1` 的冻结LPPLS域，`B<0` 为上行结构，`B>0` 为下行结构；若B0域不同，先显式解决语义差异，不能静默换m边界。若既有入口采用 `-log P`，先转换参数坐标并验证等价性。只允许复用同一候选全集已覆盖的方向；整个方向未搜索/未验证时，状态为 `NOT_INSPECTED`，该方向所有计数/比例字段为null，不得以0冒充不存在，也不阻止已核实方向出独立结果。两方向不能相减成“净风险”，下行结构也不等于底部预测能力。

只有两方向及逐窗联合分类均已核实时，才可额外输出联合表：`N=Q_positive+Q_negative+R_global+unknown`，其中 `R_global` 是两个方向均不合格。联合表不是生成正向结果的前置条件；不得将未核实负向填0来强行闭合。

对任一已验证方向 `d`，计算规则为：

| 输出 | 规则 | 展示解释 |
|---|---|---|
| `ci_full_d` | 仅 `N>0 && unknown==0` 时为 `Q_d/N`，否则 null | 完整计划的方向合格窗口比例 |
| `ci_resolved_d` | `resolved>0` 时为 `Q_d/resolved`，否则 null | 已解析窗口的条件比例，不能替代完整比例 |
| `accounting_lower_d` | `N>0` 时 `Q_d/N`，否则 null | 当前已确认合格份额 |
| `accounting_upper_d` | `N>0` 时 `(Q_d+unknown)/N`，否则 null | 假设全部未知均合格的上界 |
| `status` | 方向未核实先为 `NOT_INSPECTED`；其余N=0为 `NO_WINDOWS`；resolved=0为 `UNAVAILABLE`；其余未知为 `INCOMPLETE`；完全解析为 `COMPLETE` | 方法可用性/完成度，不是预测可信等级 |

`[accounting_lower, accounting_upper]` 仅是**固定计划的完成度核算范围**，不是统计置信区间、真实顶部概率范围，也不是官方 DS 指标的一部分。求解次数有限造成的局部最优风险仍然存在。未知全为0时，方向核算范围才退化为单个合格窗口占比。

## 3. 尺度、逐日快照与计算成本

逐尺度保留完整 `Q/R/U/N` 与精确窗口清单。尺度标签只描述拟合回看长度，不直接宣称短期顶或阶段顶。分组边界在 T06a 固定；同一窗口若有重叠组标签，总体分母去重。

- `ci_pooled` 是所有独立窗口的合格比例，受窗口枚举密度影响。
- 等尺度算术平均只能另命名 `custom_equal_scale_mean`，不是官方 DS/Combo；任一必需尺度缺失则该平均为 null，不临时重归一化。
- 示例：两尺度为9/10与1/100，总体为10/110≈9.09%，等尺度平均为45.5%。不能选较大的数展示为更高“置信度”。

D1 优先复用 T03 的不可变 attempt/窗口计划，额外成本是选代表、过滤和聚合；**实际耗时尚未测量**。不得为本项自动加入100次 bootstrap、104周额外历史或新优化器。保存聚合耗时、峰值内存、缓存命中和因账本不全新增的拟合数；数据/求解契约哈希不一致不能复用。

每个 asof 输出 append-only 快照，至少包含：

```text
asset, asof, evidence_mode, generated_at, first_visible_at,
method_id, contract_hash, run_id, data_hash, data_cutoff,
calendar_hash, window_plan_hash, fit_attempts_hash, representative_rule,
scale_id, direction, N, Q_direction, R_direction, U_solver, U_data, U_pending, U_contract,
coverage, ci_full, ci_resolved, accounting_lower, accounting_upper,
status, unknown_reasons, source_window_ids, source_attempt_ids,
revision_of, available_at_basis
```

方向行的 `R_direction` 与可选联合表的 `R_global` 必须用不同字段名，不能混用。方向行满足 `N=Q_direction+R_direction+unknown`；联合表满足本文件第2节的可选总式。未核实方向的null不能参与加总。

历史重放 `first_visible_at=null`，另存模拟可用/可行动时间；真实前瞻使用可核验的首次对用户可见证据，不能用生成时间代填。晚到数据或修正生成新快照引用原快照，不能改写过去。截断在任一 asof 重算与完整回放的该日结果一致；未来标签、行情和修订不得改变历史输出。

## 4. 三块展示各自归属

这是前端后续使用的数据/文案契约，本次不实现 UI。

| 展示块 | 必须展示 | 禁止推断 |
|---|---|---|
| **结构强度 · D1** | 合格/计划窗口数、完成度、每尺度比例、方法版本、缺数/失败与 asof；完整时如“60/100窗口合格” | 不写“顶部概率60%”“准确率60%”；未知不能显示0风险 |
| **临界时间候选区间 · B0/W1/C1** | 同一 asof 对应方法的区间、交易日映射、宽度、候选来源、边界集中/过宽及状态 | 不从 D1 数值或其峰值推导日期；不强裁成一周；拟合分布不是已校准事件概率 |
| **实际预警效果 · 具体提醒策略** | 策略ID、样本/时期、事件分母、首次正式区间、阶段漏报、提前≥5日及宽度联合指标；历史/前瞻分开 | 不把 B0 的成绩挂到 D1 名下；不把结构强度替代预警效果 |

跨面板必须按 `asset/asof/data_hash/contract` 对齐。来源日期不一致时分别标明并禁用合并解释。D1 没有提醒映射时，其召回、提前量和精确率为 `NOT_APPLICABLE`；尚未执行的有定义实验是 `NOT_RUN`。二者都不能显示0或借用其他策略数字。

## 5. 两个独立任务：D1 描述性对照，G1 提醒门对照

**D1（本轮必做任务规格）：** 用 B0 输入生成结构强度和来源账本，不改变 B0/W1/C1 的任何候选区间、自然提醒或评分。验证接入前后这些账本哈希一致。D1 与 B0 采用不同代表规则时必须可追溯，不宣称 D1 用的代表就是 B0 原来的代表。它回答“结构跨窗口是否稳定”，不直接回答“顶部提醒是否有效”。

**G1（独立登记、条件执行）：** 若要检验置信度对提醒有用，定义 `G1=B0原候选区间+冻结的D1门`。本任务单允许准备这个对照，但必须在查看本批新结果前，连同 T06a 冻结以下内容；否则状态为 `DEFERRED_NOT_PREREGISTERED`，只做 D1，不补调阈值。

- 门控方向、单个事前指定尺度或 pooled 字段、阈值校准办法、目标提醒负担及额外比较的统计/功效预算。没有预设“0.8就是顶”的阈值。
- 首版只使用 `COMPLETE` 的 `ci_full_positive`，不以条件比例或核算上界触发提醒。不完整日保留为计算/数据不可用，保留全部事件分母并归因；不能按未知删除困难样本。
- G1 只过滤当日 B0 候选，不生成、移动、缩窄或追溯恢复区间。门稍后通过只能在稍后实际可用时产生 G1 提醒；第一条主张、修订/新提醒规则和成熟度仍遵循 T02。
- 阈值只由独立时间顺序的训练/校准段确定；测试段冻结，不能按测试未来顶部或总提醒数选择前K条。阈值或字段选择使用过的资料登记为已消费。
- 同时给自然策略与共同机会等次数诊断，沿用 T06 全部事件分母及独立账本。G1 是过滤策略，可能减少误报也可能增加漏报/延迟；在同一时点只有一个B0候选时，共同机会诊断可能退化为相同区间，必须说明，不能据此宣布门控有收益。
- 报告 B0→G1 保留/拒绝的提醒、失去/新增的匹配事件、阶段顶漏报差、提前≥5日差、窗口宽度、通知数和占用天数。不能只报告筛选后命中率。
- 不把 D1/G1 与 W1/C1 捆绑做新组合臂；组合需要下一版登记。任何改善仍只可标 `IMPROVED_DEV_ONLY`，不足则 `NO_CLEAR_GAIN/REGRESSION/INSUFFICIENT_EVIDENCE`。

执行顺序：T01/T02 → **T07a（D1契约，G1若做则其规则）+T06a** → T03/B0 → T07b/D1；W1、C1继续原单项顺序。G1 如已登记，在 B0/W1/C1 基础对照完成后独立执行 T07c，不挤占原主比较的资源或改变其口径。

## 6. 手工验收与交付

以下为**预期真值**，不是已运行测试或真实市场结果。

| Fixture | 预期 |
|---|---|
| 单方向 Q=60，R=40，unknown=0，N=100 | 完整比例0.60；完成度1；核算范围[0.60,0.60] |
| Q=60，R=20，U_solver=15，U_data=5，N=100 | 完整比例null；条件比例0.75；完成度0.80；核算范围[0.60,0.80] |
| Q=R=0，unknown=100 | 完整/条件比例null；UNAVAILABLE；核算范围[0,1]，不显示0风险 |
| N=0 | 比例、完成度和核算范围均null；NO_WINDOWS |
| 同一窗口重复同一seed记录 | 计数和比例不变；重复身份记审计错误，不添加票数 |
| 代表解SSE最低但过滤失败，次优解合格 | R增加1；不改挑次优计Q |
| 一个候选合格但固定seed计划还未结束 | U_pending增加1；不得提前标COMPLETE |
| 新增缺失价格/失败窗口 | N保留；unknown增加，ci_full置null |
| 9/10与1/100两尺度 | pooled=10/110；自定义等尺度均值0.455；二者名称不同 |
| 完整周期等于1.5/略小于1.5；tc等于/小于t2 | 冻结浮点容差后分别判定；非未来域禁止abs/clamp修复 |
| 正/负坐标变换；同窗口多个尺度标签 | 方向一致；全局只有一票 |
| 正向完整、负向未搜索或未验证 | 正向可出完整比例；负向NOT_INSPECTED且计数/比例null；不生成联合表 |
| 个别窗口attempt账本缺失或方向映射异常 | 计入U_contract，ci_full=null；不以备注代替unknown；窗口计划本身缺失则明确报错 |
| 相同CI、不同拟合tc | CI可相同而时间区间不同；D1不生成日期 |
| 追加未来行情、修订或标签 | 已封存asof的D1与首次提醒不变 |
| D1启用前后 | B0/W1/C1区间、自然提醒和评分哈希一致 |
| G1晚五日过门/因unknown被挡 | G1记录自己的实际行动日与漏报/延迟；不沿用B0早期时间 |

Devin 必交（新 run_id，旧结果哈希保持不变）：

```text
ds_confidence_contract_frozen.json
public_method_to_project_diff.md
ds_window_plan.*
ds_representatives.*
ds_window_status.*
ds_confidence_snapshots.*
ds_source_and_failure_audit.md
ds_three_panel_contract.json
ds_fixture_results.json
DS_CONTROL_REPORT.md
g1_preregistration.json              # 已登记才执行；否则明确deferred理由
g1_prediction_ledger.*               # 仅G1执行时
g1_event_and_budget_scores.*         # 仅G1执行时
```

不覆盖历史文献报告、旧分母和旧评价器；本次不改变生产默认，不合并、部署、发布或手动触发模型 workflow。
