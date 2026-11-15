# 文献补查（2026-11-15）：LPPLS / Ising / 其他对本引擎可能有效的信号

> 用途：回答"还有没有对当前 LPPLS、Ising 或其他引擎模块有效的模型信号"。与 `docs/literature_review.md`、`docs/literature_stock_math.md`、`docs/literature_regime_models.md`、`docs/literature_top_bottom_models.md`、`docs/literature_price_layer.md`、`docs/bottom_and_price_layer_design.md` 去重，只记录这些文件中**没有**的条目。
> 获取方式：arXiv API（q-fin 与全库，2023-01 起，按提交时间倒序，间隔 4 s）+ OpenAlex（期刊论文，2017/2022 起）。**本轮只读了摘要，没读全文**；下表数字均出自摘要，未核对正文。Semantic Scholar 接口返回 429，未使用。
> 证据等级：**OOS** 样本外/实时；**IS** 样本内/事后案例；**TH** 理论/仿真。"候选"均指登记草案，用户确认前不运行、不进产品（规则同 §21–§23）。

## 0. 结论

1. **Ising 方向没有新的可用信号。** 2025–2026 年的 Ising/羊群论文（4 篇）全部是仿真复现典型事实，没有一篇做样本外的顶部/底部预测，和 §21.7(d) 的负面结论一致。不建议继续投入。
2. **LPPLS 方向：新文献里有样本外证据的，都把 LPPLS 当风险/波动的预测因子，不当顶部日期。** Gupta–Nielsen 等（2023–2025，含 Sornette 组成员）用多尺度 LPPLS 置信度（MS-LPPLS-CI）做 G7 月度样本外预测，结论是"对短中期已实现波动有预测力"。这个目标我们**没测过**。我们所有负面结论都是针对"顶部/底部日期"和"顶价"。
3. **最直接针对"逃顶价格不准"的一类方法是实时崩盘/恢复监测**（Whitehouse–Harvey–Leybourne 2023 *OBES*、2025 *IJF*；Phillips–Shi 2018 *ET* 反向回归）。它不预测顶部，而是在顶部之后尽快确认"崩盘已开始"，并在理论上保证"不会早于崩盘发生就报警"。卖出价由确认延迟决定，所以这类方法改进的是价格层，而不是时间层。项目里的 GSADF（R2）只用作顶部概率的阶梯特征，崩盘确认和恢复日期这两个用途**没测过**。
4. **混合因果–非因果自回归（MAR）** 给出显式的"泡沫存活分布/崩盘赔率"（Fries 2021 *JBES*：非因果 AR(1) 的泡沫存活时间服从参数为 ρ^α 的几何分布）。这是唯一能输出校准过的"何时破"概率的模型类，但实证主要是商品和比特币的样本内案例，优先级低。
5. **LPPLS 统计检验的新批评** Grobys 2025 *IRFA*："LPPLS 签名"常用的残差 ADF/PP 检验配表上临界值，存在严重的检验水平失真；改用与估计流程对齐的 bootstrap 临界值后，许多已发表的签名不再成立。这和 §22 Q3（窗口级重拟零对照）的思路一致，可以引作 Q3 的外部依据，不需要新判据。

## 1. 新增条目

| # | 文献 | 摘要要点 | 证据 | 和本项目已有结果的关系 | 判断 |
|---|---|---|---|---|---|
| U1 | Grobys (2025) *Log-periodicity: Fact or fiction?* IRFA, doi:10.1016/j.irfa.2025.104848 | 残差单位根检验配表上临界值会膨胀拒绝率；用保留粗糙度/波动、但不含对数周期的合成序列，按完整两阶段估计流程重算 bootstrap 临界值后，检验水平回到名义值，S&P 500 上的许多签名被推翻 | 方法 + IS | 支持 WP1 和 §22 Q3 的做法（零假设必须重跑完整拟合流程） | 引作依据；不新增判据 |
| U2 | Gupta, Nielsen, Pierdzioch (2024) *Stock market bubbles and the realized volatility of oil price returns*, Energy Econ., doi:10.1016/j.eneco.2024.107432；同组 ASMB 2024（黄金收益/波动，doi:10.1002/asmb.2887）、JBEF 2023（情绪→MS-LPPLS-CI，doi:10.1016/j.jbef.2023.100804）、Economies 2025（doi:10.3390/economies13020024） | G7 月度 1973–2020：MS-LPPLS-CI 正/负泡沫指标在收缩回归（Lasso/EN/Ridge）中对短到中期已实现波动有样本外预测力 | OOS（月度，同一研究组，无独立复验） | 目标是波动/风险，不是日期；与 Phase 0–2"日期/顶价无信息"不冲突 | **候选 W7**（见 §2） |
| U3 | Whitehouse, Harvey, Leybourne (2023) *Real-time monitoring of bubbles and crashes*, OBES, doi:10.1111/obes.12540；同作者 (2025) *Real-time monitoring procedures for early detection of bubbles*, IJF, doi:10.1016/j.ijforecast.2024.12.005 | 两阶段：先监测泡沫，出现泡沫后用一阶差分均值的符号变化实时监测崩盘；临界值来自训练期；渐近上保证快速检出，且不会早于崩盘发生就报警。2025 年那篇用不同的方差标准化加快泡沫检出，同时不提高单位根零假设下的误报 | 方法 + 蒙特卡洛 + 案例 | 处理的是"报警后到顶还涨 12–33%、确认滞后决定卖价"这个价格层问题；本项目没测过 | **候选 W8**（最优先） |
| U4 | Phillips & Shi (2018) *Financial bubble implosion and reverse regression*, Econometric Theory, doi:10.1017/s0266466617000202 | 证明 PSY 实时监测在多种崩盘形态下的性质；把 PSY 反向用于样本，检测危机并估计市场恢复日期，给出日期估计量的一致性 | 方法 + 案例 | "恢复日期"对应抄底时间；R2 只用了正向 BSADF | 并入 W8 |
| U5 | Gourieroux & Zakoian (2017)；Hecq & Voisin (2020) *Forecasting bubbles with MAR models*, EcoSta, doi:10.1016/j.ecosta.2020.03.007；Fries (2021) JBES, doi:10.1080/07350015.2021.1953508；Krabbe (2026) arXiv 2608.28115 | 非因果重尾 AR 生成局部爆炸的泡沫轨迹；存在闭式的预测分布和事前崩盘赔率；非因果 AR(1) 泡沫存活时间服从参数 ρ^α 的几何分布 | TH + IS（商品、比特币、互联网泡沫） | 唯一能给出"何时破"概率分布的模型类，可以用可靠性图检验校准；在 A 股和样本外都没有证据 | 候选 W9（低） |
| U6 | Garcia Seuma (2026) arXiv 2607.27070 | 7 次加密货币爆仓：价格的临界慢化特征在内生积累型事件中 5/7 出现，在 2 次外生新闻冲击中完全没有；没有一个变量在所有事件中都成立 | IS（n=7） | 和 Phase 3a"恐慌底 vs 阴跌底"一致：临界类信号只适用于内生积累型 | 不新增；作为 §23 `bottom_regime` 的旁证 |
| U7 | Nayar & Islam (2024) *Endogenous crashes as phase transitions*, arXiv 2408.06433 | 声称动态相变框架的预警（波动、反常维度）优于 LPPL；S&P 500 成分股 2019–2024 | IS | 没有零对照、没有样本外 | 不做 |
| U8 | Giorgio (2025) arXiv 2504.19050；Benítez & Dorso (2025) arXiv 2512.17925；Sudarsanam (2025) arXiv 2501.13078；Weng (2026) arXiv 2607.27063（A 股羊群 ABM） | Ising/平均场/格点 ABM 复现波动聚集、厚尾、动量-反转 | TH | 和 §21.7(d) 一致：Ising 只解释典型事实 | 不做 |
| U9 | Cao, Shao, Yan, Geman (2025) *Hyped LPPL*, arXiv 2510.10878 | 用 LPPL + 情绪 + hype 指数生成泡沫标签，再训练双流 transformer；美股 2018–2024 回测年化 34% | IS（回测） | 标签由 LPPL 生成，再用于预测，存在循环；需要新闻数据 | 不做 |
| U10 | Rao & Rojas (2025) *Predicting market troughs*, arXiv 2509.05922 | DML 因果框架：期权隐含风险偏好的波动与市场流动性是谷底的主要驱动；可实时识别投降式抛售 | IS + nowcast | A 股期权历史从 2015 年才有；流动性已在 B2（成交额/Amihud） | 不新增；期权仅作 WP5 备注 |
| U11 | Shu & Zhu (2020) Physica A, doi:10.1016/j.physa.2020.124892；Shu & Zhu (2022) Stat, doi:10.1002/sta4.460；Wu, Tang 等 (2021) 物理学报, doi:10.7498/aps.71.20201940 | A 股 2015 单次事件：提前约 2 个月预测临界日；加入媒体情绪改进预警 | IS（单事件） | 和 Phase 0"信号几乎全部来自 2007/2015"一致 | 不做 |
| U12 | Yang & Ferrer (2023) *Explosive behavior in the Chinese stock market: a sectoral analysis*, PBFJ, doi:10.1016/j.pacfin.2023.102104 | Phillips–Shi 2019 方法：各行业都有爆炸期，2007/2015 两轮为共同期，行业间爆炸期显著同步 | IS | 行业爆炸同步属于广度信号，已在 WP4 草案中 | 并入 WP4 |
| U13 | Yang (2025) arXiv 2512.08000（A 股 Hawkes 传染） | 指数/行业日收益的自激/抑制 Hawkes 过程，描述趋势与轮动 | IS | 描述性 | 不做 |

## 2. 候选（只写不跑；用户逐条确认后登记新节 §24，开发段一次，门写在结果之前）

| 候选 | 问题 | 做法（草案） | 零对照 / 基线 | 门（草案） | 算力 | 优先级 |
|---|---|---|---|---|---|---|
| **W8 实时崩盘确认 + 恢复日期** | 价格层：报警后到顶还涨 12–33%，卖价取决于确认顶部的延迟；抄底时间：恢复日期 | 6 指数开发段：在 PSY/BSADF 已报泡沫的区间内，逐日运行 Whitehouse–Harvey–Leybourne 崩盘监测（训练期临界值）；Phillips–Shi 反向回归估计恢复日期。指标：确认日相对真实顶的滞后（交易日）、确认日价格/顶价 −1、恢复日相对真实底的偏差 | 同一报警频率的"顶后固定 N 日卖出"、20/60 日均线跌破、回撤 −10% 止损三条朴素规则；循环平移零对照 | 剔除 2007/08/2014/15 后，在 ≥4/6 指数上，确认价/顶价 −1 的中位数优于三条朴素规则中最好的一条，且误报（确认后 60 日内创新高）≤ 朴素规则 | 低（线性 AR 递推，6 指数 < 10 分钟） | 高 |
| **W7 LPPLS 置信度 → 未来波动** | LPPLS 换用途：从"何时顶"改成"未来风险有多大" | 用现有 `lppls_v2_g2` 扫描构造多尺度正/负置信度，作为 20/60 日已实现波动与未来最大回撤的预测变量 | HAR-RV、GARCH(1,1)、仅涨幅/回撤特征（R1/B1） | CPCV 下 QLIKE/MSE 相对 HAR-RV 降低，90% 区间不含 0；剔两轮大顶后仍成立；增量须超过 R1/B1 | 低（复用已有扫描，不重拟） | 中 |
| **W9 MAR 崩盘赔率** | 时间层：给出校准过的"何时破"概率，而不是 t_c 点 | 滚动估计非因果 AR(1)（t 或 α-稳定误差），在爆炸段输出 H 日内崩盘概率 | 基率、GSADF p20（R2） | 合成门（已知 ρ、α 的模拟泡沫存活分布可回收）→ 开发段可靠性图 + Brier 优于 R2 | 中（6 指数 × 滚动 MLE） | 低 |

不再投入：Ising 序参量、Hyped-LPPL/新闻 transformer、动态相变预警、单事件 2015 预测类、Hawkes 传染（均见 §1，理由：无样本外证据或标签循环）。

## 3. 与本项目已有结论对照

| 已有结论 | 新文献是否改变 | 说明 |
|---|---|---|
| 普通年份顶部日期 ≈ 随机（Phase 0/1b） | 否 | 新文献里没有一篇给出 LPPLS 顶部日期的独立样本外命中证据；中国相关的都是 2015 单事件 |
| `exp(A)` 无目标价信息（Phase 2a） | 否 | 没有文献把 A 当目标价做样本外检验 |
| Ising 序参量未过门（§21.7 d） | 否 | 2025–26 Ising 论文均为仿真 |
| 恐慌底 LPPLS 无效、阴跌底有信息（Phase 3a） | 加强 | U6：临界类信号只在内生积累型事件出现 |
| 零假设必须重跑完整拟合（WP1、Q3） | 加强 | U1 Grobys 2025 |
| 价格层没有建模路径（Phase 2b） | **可能部分改变** | U3/U4 的崩盘确认改的是卖出时点 → 卖出价，不依赖 LPPLS 参数（W8） |
| LPPLS 只能作描述性字段 | **可能部分改变** | U2：LPPLS 作为波动/风险预测因子有外部样本外证据，未在 A 股测过（W7） |

## 4. 获取记录与局限

- arXiv API 检索式：`log-periodic`+bubble/crash、LPPL(S)+ML/confidence、Ising+市场、早期预警+崩盘、负泡沫、GSADF、Hawkes、dragon-king、q-fin 分类下的 LPPL/Ising/泡沫检测/崩盘预测/中国/反弹/广度；共约 400 条，2023 年后新增且相关的约 25 条。
- OpenAlex：10 组关键词 + 6 组定向（MAR、反向回归、实时监测、MS-LPPLS-CI、A 股 LPPLS、A 股抄底）；摘要由 `abstract_inverted_index` 还原。
- 只读摘要；W7/W8/W9 登记前需要读全文核对：临界值构造、训练期长度、日频适用性（U2 为月度）。
- 原始检索结果在会话机 `~/lit3/`（未入库）。
