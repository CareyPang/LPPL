# 个股引擎金融模型研究方案（2026-11-02 v1；基于文献与数学审计）

> 入口：`docs/project_full_plan.md` §5/§10。文献依据：`docs/literature_stock_math.md`（§1–§6 第一批 I/L/O/W 编号，§7 第二批 N 编号）、`docs/literature_review.md`（S/M/E/B/C/P 编号）、`docs/literature_regime_models.md`、`docs/literature_top_bottom_models.md`。审计依据：`reports/stock_math_audit.md`（F1–F10）。
>
> **硬规则（全篇有效）**：个股证据等级一律 `research_candidate`；t_c 只是理论临界时间/情景分位，不是顶部日期；不改 `docs/preregistration*.md` 已登记判据，判据问题只写建议；新方法只到"草案 / 描述性字段 / 研究对照"，不进产品模型；每条实验在新样本上只跑一次、只报告不选优。

## 0. 一页结论
1. **现状**：个股 LPPLS 链路数学上与指数链路逐位一致（F10），F1/F2 修复后 v2 网格覆盖完整；但横截面证据为"无预测信息"（`reports/ladder_dev_stock.md`、`reports/stock_rank_stk100_pos/summary.md`：Top-12 的 60/120 日事件率 0.195/0.349 vs 随机 0.180/0.298），强趋势/纯幂律零假设下 STANDARD 窗口误报 42.8%/34.2%（F9）。
2. **文献能支持什么**：LPPLS 作为"超指数 + 对数周期"形态诊断有理论与指数级事后证据（I1、L1、L2、N3、N11、N12）；个股层面的全文证据只有 N16（meme 股：能检出形态，不能预测外生大涨）与本仓库横截面；任何个股"预警"都没有样本外证据。
3. **因此研究主线不是换拟合技巧，而是三件事**：(a) 把误报率标定成每个信号的"零假设对照"字段；(b) 用预登记 Q-STK1 回答"控制动量与尾部风险后有无增量"；(c) 把 t_c 区间与 Trust 做成有统计含义的量（修正剖面似然、AR(1) 误差）。其他物理/量化方法只做描述性背景或研究对照。
4. **里程碑**：2026-11 完成 WP0/WP1；2026-12 WP2；Q-STK1 等用户批准登记后一次性运行（WP3，计算量约 300 机时，用 Actions 分片）；WP4–WP6 为 2027 年 Round 2 之后的候选。合并本 PR 不触发任何 WP 的"运行"，只固化方案。

## 1. 研究问题与文献依据映射
| 编号 | 研究问题 | 为什么要问（仓库证据） | 文献依据 | 等级上限 |
|---|---|---|---|---|
| RQ1 | 个股六档尺度下，各过滤集（box/END/STANDARD/EARLY）在 GBM/GARCH/强漂移/幂律/O-U 零假设下的误报率是多少？能否作为每条信号的"零对照"字段？ | F9：强漂移 GBM STANDARD 42.8%、纯幂律 34.2%，无漂移 5–7% | N1（预测显著性）、N3（GARCH 零假设 0.2% 的残差检验）、L8/C3、L12/C5、I1 p.23–24 | 描述性 |
| RQ2 | t_c 情景区间用修正剖面似然（MPL）或 AR(1)-GLS 误差后，覆盖率与宽度相对现行 iid 残差 bootstrap 如何？ | `intervals.profile_interval` 为未修正版；`trust.py` iid bootstrap（F5） | L4/M2、N8 附录、N6、N4 | 描述性 / 研究对照 |
| RQ3 | 控制动量（ret500、加速度）与横截面尾风险 λ_t 后，个股 6–12m/12–24m STANDARD 置信度对"120 日内确认顶"有无增量？ | 横截面无信息；Q-STK1 草案已写判据 | N12（因子 vs 羊群）、N19（λ_t）、E3（多尺度 OOS）、N16 | 通过 → `dev`（草案 §5） |
| RQ4 | 成分股广度（`standard>0` 比例、`conf≥0.5` 比例）对指数报警是否是独立信息？"内生/外生"分类能否作为描述性标签？ | R8 开发段 ΔBrier −0.0025；breadth 已上线描述性（PR #27） | N14、E1、T5 | 外部/前瞻评价后定 |
| RQ5 | 并列的"尾部层"（GARCH-EVT ES、CAViaR、ES-VaR）在个股上的覆盖率/FZ 评分是否合格？与 LPPLS 形态层并列展示是否改变用户决策口径？ | 产品只给区间与频率，没有尾部层 | W1、W6、N21、N19 | 需新预登记 |
| RQ6 | 市场层"关联度/吸收比、方差抬升"作为背景描述是否稳定、与泡沫阶段是否同步？ | 文献层多次否定 CSD/Hawkes 作信号 | O1、O8–O12、N17、N18 | 描述性 |
| RQ7 | 深度学习标定（Deep LPPLS）相对 `tcgrid_lm` 在合成序列上的参数误差分布如何？ | 标定方法已登记，不能换；但可作对照 | N5、L1 | 研究对照 |

## 2. 工作包

### WP0 数学/数值基线固化（本 PR 已完成的部分 + 收尾）——收尾 1–3 已完成（`boundary_share`、2–4w `display_only`、`_display_calendar`）；4（`_g2` 对照）待跑
- 已完成：F1（`grid_profile` 窗内 t_c）、F2（`_to_cal` 外推）、测试、§20 偏离登记、`MODEL_VERSION=prereg_v1.7_v2.1`。
- 收尾（代码小改，均不改判据）：
  1. 输出"撞边界标记"：m/ω/t_c 距离 v2 搜索域边界 <1% 的窗口数与比例（F10：600519 stk_full 181 窗 t_c 撞 ±0.2dt 搜索边界 30.9%，F1 修复后 38.1%；m 撞下界 14.4%、上界 12.7%），进入 `_indicators()` 的描述性字段。
  2. 2–4 周档（10–20 点拟合 7 参数）只展示 `n`，不参与任何比例（F7 建议）。
  3. `_to_cal` 改用交易日历外推（F2 后续）。
  4. 开发段 `_g2` 敏感性对照（§20 第 2 条）跑完并写 `reports/original_standard_dev_v2_g2/`。
- 验收：`ruff` + `pytest -m "not network"` 通过；审计报告 §7 建议逐条关闭或登记。

### WP1 零假设与误报率标定（RQ1）——**已完成第一轮**：`reports/null_calibration_stock.md`（六类零假设 × 六档 × 六过滤集，43,800 次拟合；`null_fpr` 描述性字段已接入个股 JSON）
- 假设：H0 = 各过滤集在无泡沫生成过程下的合格率与真实个股一致，即信号无区分度。
- 生成过程（每类 ≥200 条、长度 = 各档窗口；参数从真实个股后复权收益 PIT 估计）：GBM（μ=0 与 μ=样本 90 分位）、GARCH(1,1)-t、纯幂律 `A+B(tc−t)^m`、O-U 围绕指数趋势（N3）、块 bootstrap 重排的真实收益（破坏时间结构、保留分布）。
- 输出：按尺度 × 过滤集的误报率表（含 95% Clopper–Pearson 区间）；写入 `reports/null_calibration_stock.md`；在个股 JSON 增加描述性字段 `null_fpr{scale, set}`（文案："在无泡沫的随机序列中，该过滤集也有 x% 的窗口合格"）。
- 证伪：若真实个股合格率落在零假设区间内，相应过滤集在该尺度标"无区分度"，产品继续只显示"有/无合格拟合"。
- 工作量：合成 5 类 × 200 × 16 窗 ≈ 16000 次 lite 拟合，8 核约 2 小时。脚本沿用 `scripts/audit_stock_math/exp3_null.py` 扩展。

### WP2 t_c 区间与 Trust 的统计含义（RQ2、RQ7）
- 实验 A：对合成 LPPLS（σ∈{0.5%,1%,2%}，AR(1) 残差 φ∈{0,0.5,0.9}）比较三种区间：现行 iid bootstrap（`intervals.py`）、MPL（L4，`profile_interval` 加修正项）、AR(1)-GLS 剖面（N8 附录）。指标：名义 90% 区间的实际覆盖率与中位宽度。
- 实验 B：Trust 的 B=100 iid 残差 bootstrap vs 块 bootstrap（块长 = 残差自相关长度），在 5 只真实股票上的 Trust 值差异与稳定性（F5）。
- 实验 C（RQ7）：Deep LPPLS 的 M-LNN/P-LNN（N5 开源实现若可得；否则跳过并记录）与 `tcgrid_lm` 在同一合成集上的 |Δt_c|、|Δm|、|Δω| 累积分布。只作对照表，不改链路。
- 产出：`reports/tc_interval_calibration.md`；若 MPL/GLS 覆盖率显著更接近名义值，写入 `preregistration_round2_draft.md` 作为 Round 3 "模型细节"候选（战略路线已列）。
- 不做：用区间宽度去"选"窗口或尺度。

### WP3 个股横截面增量（RQ3，= 预登记草案 Q-STK1 的执行计划）
- 判据、样本、标签、比较对象**完全沿用** `docs/preregistration_stock_draft.md` §2–§6，本方案只补执行细节：
  1. 协变量扩展（需在登记前写死）：B1 动量 logistic 增加 Kelly–Jiang 式横截面尾指数 λ_t（N19，按月用全部 in_stats 个股日收益的 5% 尾 Hill 估计）与个股 60 日已实现波动；M1 = B1 + max(conf_6-12m, conf_12-24m)。λ_t 只是对照基线，不是产品字段。
  2. 市值分层报告（N15）：沪深300 / 中证500 分开列 ΔAUC，但判据按合并样本。
  3. 标签并列：PS 固定 25%（草案）与 LT 停时（Round 2 第 1 条口径），两套都报，不选优。
  4. 多重比较：3 条判据 × 2 标签 × 2 分层，Holm 校正写死在登记文件。
  5. 计算：约 800 只 × 347 周 × 4 s ≈ 300 机时 → GitHub Actions matrix（沿用 `stock_nightly.yml` 的 6 分片结构扩到每 job 一组代码），结果写 `stock-results` 分支；运行前冻结代码版本与数据版本哈希。
- 通过/失败后的产品处置：按草案 §5——失败维持 `research_candidate` + "无预测信息"提示；通过只升 `dev`，再经一轮前瞻日志。
- 前置：用户批准登记（冻结哈希）；WP1 的零对照字段先上线，使失败结果也能解释。

### WP4 广度与指数联动（RQ4）
- 描述性字段扩展：在 `breadth_sh000300.json` 增加按市值三分位的 `standard>0` 比例；增加 Song–Shu–Zhu 式"内生性标签"草案（N14）：指数回撤 ≥15% 事件发生时，前 60 日 6–12m/12–24m 置信度是否 ≥ 阈值 → 事后标"内生/外生"，只在成绩单复盘中展示。
- 评价（只在外部市场与前瞻日志，Round 2 第 7 条）：R8 相对 R7 的 ΔBrier 区间上界 <0。
- 不做：用广度调整指数阈值；用广度给个股评级。

### WP5 尾部风险层草案（RQ5；需新预登记 `docs/preregistration_tail_draft.md`，本方案只定范围）
- 候选模型（并列，不合成）：GARCH(1,1)-t + GPD 尾（W6）、CAViaR-AS（W1）、ES-VaR FZ 模型（N21）。
- 评价：1%/5% VaR 的 Kupiec 无条件覆盖 + Christoffersen 独立性；ES 用 FZ 损失（N21 §2）比较；按截止月块 bootstrap。
- 产品口径：若通过，只显示"过去 N 日该股 5% 日损失分位 x%，与同市值组比处于 y 分位"，不与 LPPLS 形态层合成任何分数（文献 §5 结论）。
- 不做：Kelly/风险预算类仓位建议（W5、N22 只作文献记录）。

### WP6 物理方法的"背景层"（RQ6；描述性，不报警）
- 候选：相关矩阵吸收比/最大特征值占比（O8、O9、N18）、市场方差与低频功率抬升（O1）、MST 平均边长（O10）。按周计算、按市场展示，附随机重排对照。
- 明确不做（文献已排除）：Hawkes 分支比（O3、N17）、局部 Hurst（O5）、CSD 作个股信号（O1、O2）、TDA（N9）、Ising/ABM 产品化（N10）、熵指标（本批全文未获取，不引用）。

## 3. 数据与计算约束
- 数据：腾讯 fqkline → kline×新浪 hfq 回退；as-of 截断；停牌不插值；一字板 degenerate；上市 ≥500 bar；全部沿用 `research/pipeline/stock.py`，不新增数据源。拉取限速限量（单次 ≤ 并行 3、间隔 ≥1 s），新样本先冻结 `data/frozen/` + sha256。
- 计算：lite 单股 3–4 s、full 80–110 s（F10 实测）；WP1/WP2 单机可跑；WP3 走 Actions 分片。
- PIT：F10 已验证价格层无泄漏；WP3 还需 PIT 成分（`data/universe/` 快照）与 PIT ST 状态（F6 建议：history 回放用当时状态）。

## 4. 统一评价口径与等级晋升
- 事件级计数（一个顶只算一次）、循环平移随机对照、按截止月块 bootstrap、Holm 校正、LOCO 不翻转（与 Round 1/Round 2 一致）。
- 个股等级：`research_candidate` → `dev`（Q-STK1 通过）→ `single_oos`（≥1 轮前瞻日志通过）→ `replicated_oos`（外部市场复现）。任何描述性字段不参与晋升。
- 每份报告固定附：n、事件数、零对照、失败标的数、代码/数据版本哈希。

## 5. 时间表
| 时间 | 内容 | 产出 | 需要用户 |
|---|---|---|---|
| 2026-11 | WP0 收尾；WP1 零假设标定 | `reports/null_calibration_stock.md`、JSON 描述性字段 | 无 |
| 2026-12 | WP2 区间/Trust/标定对照 | `reports/tc_interval_calibration.md` | 无 |
| 2026-12 | Q-STK1 登记文本补协变量/分层/Holm 条款 | `docs/preregistration_stock_draft.md` 修订（仍为草案） | **批准登记并冻结哈希** |
| 2027-Q1 | WP3 一次性运行 | `reports/q_stk1/`、等级裁决 | 无（结果只报告） |
| 2027-Q2 起 | WP4 随 Round 2 外部市场评价；WP5 预登记草案；WP6 背景层 | 对应报告与草案 | Round 2 打开授权 |

## 6. 风险与不做清单
- 风险：事件数少（个股 25% 回撤事件在 2019–2025 约数千个，但高度同期相关 → 块 bootstrap 必须按月）；数据源封禁（多源回退 + 冻结）；多重比较（判据写死 + Holm）；用户误读（文案模板：t_c = 情景，置信度 ≠ 概率）。
- 不做：回退 v1 框；用 t_c 聚类当日期；放宽任何判据；把 Confidence 与尾部层合成单一分数；未经登记上线任何新字段为"信号"。

## 7. 待拍板
1. 是否同意 WP1 的零对照字段进入个股 JSON（描述性）。
2. 是否批准把 λ_t 与市值分层写入 Q-STK1 登记文本（登记前必须定稿）。
3. WP5 尾部层是否立项写预登记草案。
