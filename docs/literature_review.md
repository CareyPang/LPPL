# LPPLS 文献综述，以及与「临界点 2.0」原型做法的逐项对照

日期：2026-10-24。范围：Sornette 团队的 LPPL/LPPLS 文献、主要批评文献和相关金融物理方法。对照对象：`web/app/engine.js`、`web/app/critical.js`、`web/review.html`。

## 0. 先说结论

1. **原型的拟合核心符合文献做法。** 原型用 Filimonov–Sornette（2013）的线性化：把 φ 并入 C₁、C₂，只剩 tc、m、ω 三个非线性参数；"多窗口合格比例"这一思路也与 LPPLS Confidence Indicator 的定义一致。
2. **原型的过滤门槛和文献差异很大，三套规则都不是照搬文献：**
   - TOP_RULE 的阻尼门槛（D ≥ 0.3）比我核实到的所有文献都松；
   - TOP_RULE 的 R² ≥ 0.8 在我核实的文献过滤器里都没有出现；
   - ds 规则把"距今天数"压在 max(5, 0.1n) 以内，比 Shu & Zhu（2020）的 dt/5 窄约一半；
   - 振荡数口径：Sornette 团队的 DS LPPLS（E7）和 E6 都用 (ω/2)·ln[…] ≥ 2.5，约等于 0.8 个整周期；E4 按整周期计 ≥ 2.5。原型 ds 和 strict 按整周期计 ≥ 2.5，比 DS 口径严约 π 倍。
3. **原型缺少文献过滤器里的几项条件**：Shu & Zhu（2020）把 Lomb 检验、残差 AR(1) 检验和最大相对误差 ≤ 0.15 当作合格条件；Sornette 团队的 E7 把相对误差 ≤ 0.035 或 0.14 当作合格条件。原型一项都没有。（更正：Jiang 等（2010）只用 t_c > t₂、B < 0、0 < m < 1 三项过滤，Lomb 检验和单位根检验在该文里只是补充诊断。见第 8 节。）
4. **原型给 t_c 定区间的方法不是文献推荐的。** 文献给 t_c 定区间用修正 profile likelihood（Filimonov, Demos & Sornette 2017），原型用的是残差块 bootstrap。Brée、Challet & Peirano 指出，现有方法给出的崩盘时间窗口很可能偏乐观。
5. **窗口起点的选法**：文献用 Lagrange 正则化（Demos & Sornette 2019），原型的顶部扫描用的是 ZigZag 低点锚定。`engine.js` 里其实已有 `lagrangeBest`，但顶部扫描没有用它。
6. **批评文献集中在三点：**
   - 参数存在"sloppy"方向，t_c 难以识别；
   - 对数周期成分在统计上未必显著（Feigenbaum 2001）；
   - 早期研究里泡沫起点是凭肉眼选的（Brée & Joseph 2013）。

   这三点正好对应我们的验证计划：合成数据回收参数、和纯幂律做嵌套比较、按 PIT 规则选窗口。
7. **底部建模**：Sornette 团队有"反泡沫/负泡沫"和"反弹诊断"的文献，原型当时决定不用对 −ln P 做 LPPLS 拟合来找底。文献允许把负泡沫置信度当作一个特征，Yan 等（2012）用经过训练的 alarm index 在 10 个市场上检测反弹，结果好于随机（见第 9 节），因此"负泡沫信号不能用于择时"的说法不成立；它能否单独胜过多条件方案，要靠样本外比较来定，所以支持"多条件共振 + 三重障碍标签"的重写方案。
8. **建议**：在模型阶梯里加一个"文献版"对照组。注意：其中的 E6 是 Shu & Zhu 的后续工作，不是 Sornette 团队本人的论文；E4 才是 Sornette 团队的。它采用 Shu & Zhu（2020）的完整过滤器加残差检验、Gerlach 等（2019）的三尺度置信度、Lagrange 起点和 MPL 区间，和原型的三套规则一起，按样本外结果决定去留。

> 核实程度说明：标 **[全文]** 的，是我下载了 arXiv 全文并检索过相关段落；标 **[书目]** 的，只核对了题目、作者、期刊和 DOI，没有读到正文，本文不引用这些文献的具体结论。Sornette 等（2015）的上证 2015 论文没有找到开放全文，所以 `engine.js` 注释里"ds = Sornette DS LPPLS（2015 上证研究）"这组参数**我当时无法核实**。独立复审后，用同一团队的 E7 已能判定：ds 参数和 DS LPPLS 不一致，见第 8 节。

---

## 1. 文献清单

### 1.1 模型与理论（Sornette 团队）
| # | 文献 | 核实 |
|---|---|---|
| S1 | Johansen, Ledoit & Sornette (2000). Crashes as critical points. *IJTAF*. doi:10.1142/s0219024900000115（arXiv cond-mat/9810071） | 书目 |
| S2 | Johansen, Sornette & Ledoit (1999). Predicting financial crashes using discrete scale invariance. *J. Risk*. doi:10.21314/jor.1999.014（cond-mat/9903321） | 全文 |
| S3 | Johansen & Sornette (1998). Stock market crashes are outliers. *EPJ B*. doi:10.1007/s100510050163 | 书目 |
| S4 | Sornette (2003/2017). *Why Stock Markets Crash*. Princeton UP. doi:10.1515/9781400829552 | 书目 |
| S5 | Sornette (2009). Dragon-kings, black swans and the prediction of crises. arXiv 0907.4290 | 书目 |
| S6 | Sornette & Cauwels (2015). Financial bubbles: mechanisms and diagnostics. *Rev. Behav. Econ.* doi:10.1561/105.00000035（arXiv 1404.2140） | 全文 |
| S7 | Lin, Ren & Sornette (2014). The volatility-confined LPPL model. *IRFA*. doi:10.1016/j.irfa.2014.02.012 | 书目 |

### 1.2 标定与推断方法
| # | 文献 | 核实 |
|---|---|---|
| M1 | Filimonov & Sornette (2013). A stable and robust calibration scheme of the LPPL model. *Physica A*. doi:10.1016/j.physa.2013.04.012（arXiv 1108.0099） | 全文 |
| M2 | Filimonov, Demos & Sornette (2017). Modified profile likelihood inference and interval forecast of the burst of financial bubbles. *Quant. Finance*. doi:10.1080/14697688.2016.1276298（arXiv 1602.08258） | 全文 |
| M3 | Demos & Sornette (2019). Comparing nested data sets and objectively determining financial bubbles' inceptions（Lagrange 正则化）. *Physica A*. doi:10.1016/j.physa.2019.04.050（arXiv 1707.07162） | 全文 |
| M4 | Sornette, Woodard, Yan & Zhou (2013). Clarifications to questions and criticisms on the JLS model. *Physica A*. doi:10.1016/j.physa.2013.05.011（arXiv 1107.3171） | 全文（只看了摘要和关键词） |
| M5 | Nielsen, Sornette & Raissi (2024). Deep LPPLS. SSRN 4839066（arXiv 2405.12803） | 全文（只看了摘要） |

### 1.3 置信度指标与实证
| # | 文献 | 核实 |
|---|---|---|
| E1 | Sornette, Demos, Zhang, Cauwels, Filimonov & Zhang (2015). Real-time prediction and post-mortem analysis of the Shanghai 2015 stock market bubble and crash. *J. Investment Strategies*. doi:10.21314/jois.2015.063 | 书目（无开放全文） |
| E2 | Zhang, Sornette, Balcılar & Gupta (2016). LPPLS bubble indicators over two centuries of the S&P 500 index. *Physica A*. doi:10.1016/j.physa.2016.03.103 | 书目 |
| E3 | Demirer, Demos, Gupta & Sornette (2018). On the predictability of stock market bubbles: evidence from LPPLS confidence multi-scale indicators. *Quant. Finance*. doi:10.1080/14697688.2018.1524154 | 书目 |
| E4 | Gerlach, Demos & Sornette (2019). Dissection of Bitcoin's multiscale bubble history. *R. Soc. Open Sci.*（arXiv 1804.06261） | 全文 |
| E5 | Jiang, Zhou, Sornette, Woodard, Bastiaensen & Cauwels (2010). Bubble diagnosis and prediction of the 2005–2007 and 2008–2009 Chinese stock market bubbles. *JEBO*. doi:10.1016/j.jebo.2010.02.007（arXiv 0909.1007） | 全文 |
| E6 | Shu & Zhu (2020). Detection of Chinese stock market bubbles with LPPLS confidence indicator. *Physica A*. doi:10.1016/j.physa.2020.124892（arXiv 1905.09640） | 全文 |
| E7 | Zhang, Zhang & Sornette (2016). Early warning signals of financial crises with multi-scale quantile regressions of LPPLS. *PLoS ONE*. doi:10.1371/journal.pone.0165819 | 全文（独立复审读过；表 3 我核对过渲染图） |
| E8 | Sornette, Cauwels & Smilyanov (2018). Can we use volatility to diagnose financial bubbles? Lessons from 40 historical bubbles. *QFE*. doi:10.3934/qfe.2018.1.486 | 书目 |
| E9 | Demos & Sornette (2017). Birth or burst of financial bubbles: which one is easier to diagnose? *Quant. Finance*. doi:10.1080/14697688.2016.1231417 | 书目 |

### 1.4 反泡沫、负泡沫与反弹（和底部建模有关）
| # | 文献 | 核实 |
|---|---|---|
| B1 | Johansen & Sornette (1999). Financial "anti-bubbles": log-periodicity in gold and Nikkei collapses. *IJMPC*. doi:10.1142/s0129183199000437 | 书目 |
| B2 | Zhou & Sornette (2004). Antibubble and prediction of China's stock market and real-estate. *Physica A*. doi:10.1016/j.physa.2004.01.051（cond-mat/0312149） | 全文（只看了摘要） |
| B3 | Yan, Woodard & Sornette (2012). Diagnosis and prediction of rebounds in financial markets. *Physica A*. doi:10.1016/j.physa.2011.09.019 | 书目 |

### 1.5 批评与检验
| # | 文献 | 核实 |
|---|---|---|
| C1 | Feigenbaum (2001). A statistical analysis of log-periodic precursors to financial crashes. *Quant. Finance*. doi:10.1088/1469-7688/1/3/306（cond-mat/0101031） | 全文 |
| C2 | Brée, Challet & Peirano (2013). Prediction accuracy and sloppiness of log-periodic functions. *Quant. Finance*. doi:10.1080/14697688.2011.607467（arXiv 1006.2010） | 全文 |
| C3 | Brée & Joseph (2013). Testing for financial crashes using the LPPL model. *IRFA*. doi:10.1016/j.irfa.2013.05.005（arXiv 1002.1010） | 全文 |
| C4 | Geraskin & Fantazzini (2013). Everything you always wanted to know about LPPLs for bubble modelling but were afraid to ask. *Eur. J. Finance*. doi:10.1080/1351847x.2011.601657 | 书目 |
| C5 | Troude, Lera, Wu & Sornette (2024). Illusions of criticality: crises without tipping points. arXiv 2412.01833 | 全文 |

### 1.6 其他金融物理与计量方法（模型阶梯中的候选组件）
| # | 文献 | 核实 |
|---|---|---|
| P1 | Phillips, Shi & Yu (2015). Testing for multiple bubbles（GSADF）. *Int. Econ. Rev.* doi:10.1111/iere.12132 | 书目 |
| P2 | Scheffer et al. (2009). Early-warning signals for critical transitions. *Nature*. doi:10.1038/nature08227 | 书目 |
| P3 | Jiang, Xie, Zhou et al. (2019). Multifractal analysis of financial markets: a review（OpenAlex 显示被引 429 次） | 书目 |
| P4 | Filimonov & Sornette (2015). Apparent criticality and calibration issues in the Hawkes self-excited point process model. *Quant. Finance* | 书目 |

---

## 2. 原版 LPPLS 方法的演进（只写已核实的内容）

- **JLS 模型（S1、S2）**：t_c 是理性预期框架下崩盘风险率（hazard rate）的奇点，崩盘可能在 t_c 之前发生，也可能根本不发生。S2 报告多个事件中对数周期的标度比 λ 近似"普适"。
- **稳定标定（M1）**：原始的 LPPL 有 4 个非线性参数（m、ω、t_c、φ），代价函数是准周期的，有多个极小值。M1 把 φ 并入 C₁、C₂，只剩 3 个非线性参数，消除了由 φ 引起的准周期性。M1 把历史泡沫的"典型特征"总结为 **0.1 ≤ m ≤ 0.9、6 ≤ ω ≤ 13、|C| < 1、B < 0**，并说明这些约束是用来过滤结果的；不加约束时，拟合"总会给出一个结果"，但结果不一定可信。
- **多窗口置信度（E4、E6；定义来自 E1）**：置信度 = 在某个固定的 t₂ 下，扫描多个窗口长度 dt = t₂ − t₁ 时，满足过滤条件的窗口所占的比例。
  - E4（比特币）：窗口长度 30–720 日、步长 1 日；分短（30–120 日）、中（100–240 日）、长（200–720 日）三个尺度，各算一个置信度，分别有 91、141、521 个窗口。另外对 t_c 做聚类，每个簇作为一种情景，簇内拟合所占比例可以近似当作该情景的概率。
  - E6（沪深 300）：窗口长度 750 → 50 日、步长 5 日，共 141 个窗口。
- **起点选择（M3）**：直接比较 RSS 或 RSS/(N−p) 会偏好短窗口，造成过拟合。Lagrange 正则化先估计"过拟合倾向" λ，再对代价函数做修正，用来客观地确定泡沫起点。E4 实际用这个方法在 30–720 日范围内选 t₁。
- **t_c 区间（M2）**：之前的 LPPLS 标定中 t_c 很不稳定。M2 用修正 profile likelihood 把 m、ω 当作冗余参数处理，给出 t_c 的似然区间，而不是点估计；同时避开 (t_c, ω) 平面上沿对角线的"sloppy"长谷。
- **残差检验（E5、E6）**：E5 用 Lomb 谱分析检验去趋势残差，用单位根检验确认残差是有界的 Ornstein–Uhlenbeck 过程（对应 S7 的"波动受限"模型）。E6 把以下条件都写进了过滤器：最大相对误差 ≤ 0.15、Lomb 检验显著、对数残差服从 AR(1)（用 PP 和 DF 两种检验）。
- **最新进展（M5）**：用神经网络估计 (t_c, m, ω)。摘要声称参数误差分布优于现有方法，我没有复核。

---

## 3. 原型与文献逐项对照

文献列只写我在全文里核实到的数值。原型列出自 `engine.js` 的 `FILTERS`、`fitWindow` 和 `critical.js:90`。

| 项目 | 文献 | 原型 | 判断 |
|---|---|---|---|
| 模型形式 | 去掉 φ 后的线性化 LPPLS，3 个非线性参数加 4 个线性参数（M1） | 相同；QR 分解求线性参数（已和 Python 对数，误差约 1e-14） | **一致** |
| 优化方法 | 文献用过禁忌搜索、遗传算法、Nelder–Mead；E6 用 CMA-ES | DE + 有界 Nelder–Mead | 可以接受；已用合成数据比较四种优化器 |
| m 范围 | M1：[0.1, 0.9]；E4：(0, 1)；E6 搜索 [0, 1]，过滤 [0.01, 0.99] | ds：[0.01, 0.99]；strict：(0.1, 0.9)；TOP_RULE：[0.1, 0.95] | 都在文献范围附近 |
| ω 范围 | M1：[6, 13]；E4：[4, 25]；E6 搜索 [1, 50]，过滤 [2, 25] | 搜索 [2, 25]；ds：[2, 15]；strict：(6, 13)；TOP_RULE：[4, 15]；顶部扫描搜索 [3, 16] | 顶部扫描的搜索上限 16 **截掉了**文献允许的 16–25 区间 |
| t_c 范围 | E6：搜索 [t₂, t₂ + dt/3]，过滤 [t₂, t₂ + dt/5] | 搜索 [t₂+0.5, t₂ + min(252, max(20, 0.3n))]；ds：距今 ≤ max(5, 0.1n)；strict：≤ 90 日；TOP_RULE：1–115 日 | ds 约为 E6 的一半，**更窄**；TOP_RULE 是固定天数，**不随窗口缩放** |
| 阻尼 D = m\|B\|/(ω\|C\|) | E4：≥ 0.5；E6：≥ 1（写进搜索约束） | ds ≥ 0.5；strict ≥ 1；TOP_RULE **≥ 0.3** | TOP_RULE **比文献松** |
| 振荡数 O | E7（DS LPPLS）和 E6：(ω/2)·ln[(t_c−t₁)/(t_c−t₂)] ≥ 2.5，约等于 0.8 个整周期；E4：(ω/2π)·ln[…] ≥ 2.5 个整周期，且只在 \|C/B\| ≥ 0.05 时才检查 | 原型按整周期计：ds 和 strict ≥ 2.5；TOP_RULE ≥ 1.5 | ds 和 strict 比 DS 口径严约 π 倍；TOP_RULE 严约 1.9 倍 |
| R² 门槛 | 我核实的文献过滤器里都没有 | strict ≥ 0.9；TOP_RULE ≥ 0.8 | **没有文献依据**，需实测 |
| 最大相对误差 | E6：≤ 0.15 | 没有 | **缺失** |
| Lomb 对数周期检验 | E5、E6 要求 | 没有，原型用和纯幂律的嵌套 F 检验代替（自己也承认 iid 假设偏乐观） | **缺失**；F 检验应换成 bootstrap 零分布 |
| 残差单位根 / AR(1) 检验 | E5、E6 要求 | 没有 | **缺失** |
| 窗口集合 | E4：30–720 日逐日（691 个），分三个尺度；E6：50–750 日、步长 5（141 个） | `OD.WINDOWS` 16 个（60–750 日）；顶部扫描 `CP.WIN` 38 个（30–190 日步长 10，200–700 日步长 25），另加锚定窗口：最近两个 ZigZag 低点各取 −4 到 +12 日、步长 2，最多 18 个，长度 ≥15 日 | 顶部扫描最多 56 个窗口，约为 E6 的 2/5、E4 的 1/12；没有分尺度的置信度 |
| 置信度指标 | 合格窗口所占比例，分尺度计算 | 合格窗口的 t_c 做核密度聚类，要求至少 4 个尺度、一致度 ≥ 6% | 和 E4 的"t_c 聚类 + 比例"思路一致，但门槛是原型自己定的 |
| 起点 t₁ | Lagrange 正则化（M3、E4） | `critical.js` 的顶部扫描用 ZigZag 低点锚定；`lagrangeBest` 只在 `engine.js` 的 `OD.analyze` 里用于挑选最佳窗口，顶部扫描没有用 | **偏离** |
| t_c 区间 | 修正 profile likelihood（M2）；C2 认为现有的时间窗口估计偏乐观 | 残差块 bootstrap | **偏离**，需比较区间覆盖率 |
| t_c 的含义 | t_c 是风险率奇点，不是崩盘日（S1） | 原型的说明里写了 "t_c ≠ 峰值日" | **一致** |
| 底部 | 反泡沫（B1、B2）、负泡沫置信度（E6）、反弹诊断（B3） | 代码里**仍然**对 −ln P 做 LPPLS 拟合（`engine.js` 的 `OD.analyze` 做底部多窗口扫描；`critical.js:268-274` 的"反泡沫结构"是 6 项共振中的一项）；新方案改为多条件共振加三重障碍标签 | 新方案不属于 Sornette 体系；可以把负泡沫置信度作为一个候选特征 |
| 验证方式 | E1 和 E5 是实时预测和事后复盘；E2、E3 是长样本研究（结论我未读） | 计划用 PIT 数据、模型阶梯、Purged K-Fold/CPCV 和校准 | Sornette 团队自己也用训练/测试切分和误差图（第 9 节）；我们的计划在此基础上增加 PIT、CPCV 和校准，但目前还没有执行，不能算作结果 |

---

## 4. 批评文献对我们的直接含义

- **C2（sloppiness）**：LPPL 的 Hessian 特征值相差几个数量级，存在"sloppy"参数组合。作者用合成 AR(1) 数据复现 1987 年恒生指数，发现连这个例子对 t_c 的可预测性都只是"勉强"。**含义**：上一轮基准里，AR(1) 噪声 σ=0.03 时 t_c 中位误差为 17–21 天（σ=0.01 时约 5.6 天），方向与这篇文献一致。所以必须报告 t_c 区间的覆盖率，不能只给点估计。
- **C1（Feigenbaum）**：去掉崩盘前最后一年的数据后，1987 年 S&P 500 对数一阶差分里的对数周期成分不显著；样本太少，难以检验。**含义**：坚持做"纯幂律 vs LPPLS"的样本外比较；对数周期项必须有增量才能保留。
- **C3（Brée & Joseph）**：JS 早期研究中约一半的拟合曲线在泡沫期内出现下降；泡沫起点是"凭肉眼"往前挪的；崩盘的识别标准不明确。**含义**：泡沫起点必须由算法确定且符合 PIT（Lagrange 或预先登记的规则）；事件标签必须预先登记。
- **C5（Troude 等，Sornette 也是作者）**：非正态（non-normal）系统会出现"伪分岔"，产生临界慢化、方差上升等全套早期预警信号，误报可能远早于真正的分岔。**含义**：模型阶梯里的"统计物理"一级（AR(1)、方差、Kendall τ）误报风险高，必须用样本外结果证明有增量。
- **M4（Sornette 团队对批评的回应）**：关键词包括拟合方法、sloppiness、禁忌搜索、bootstrap、概率预测。可见团队承认这些问题，并给出了"最佳实践"。具体细节我还没读全文。

---

## 5. 建议对后续方案的调整（待你确认后执行）

1. **模型阶梯里加一个"文献版"对照组 LIT**（E6 的作者不是 Sornette 团队，见第 7 节）：
   - 过滤器用 E6 的完整版：m ∈ [0.01, 0.99]，ω ∈ [2, 25]，t_c ∈ [t₂, t₂ + dt/5]，振荡数用 DS 口径 (ω/2)·ln ≥ 2.5，D ≥ 1，最大相对误差 ≤ 0.15，Lomb 检验显著，残差为 AR(1)；
   - 加上 E4 的三尺度置信度；
   - 窗口起点用 M3 的 Lagrange 方法；
   - t_c 区间用 M2 的修正 profile likelihood。

   它和原型的 ds、strict、TOP_RULE 一起参加样本外比较。
2. **补上缺失的检验**：Lomb 检验、残差单位根/AR(1) 检验、最大相对误差，作为可开关的组件逐个检验增量。
3. **R² 门槛和 D ≥ 0.3** 没有文献依据，作为待检验的选项，不默认采用。
4. **t_c 区间**：在合成数据上比较 MPL 和块 bootstrap 的覆盖率与区间宽度，这一项并入阶段 3b 的优化器加难度测试。
5. **把顶部扫描的 ω 搜索上限从 16 放宽到 25**，和文献的过滤范围一致，避免 ω 被截断在边界上。
6. **负泡沫置信度**作为底部模型的候选特征，不作为单独的抄底信号。
7. **GSADF（P1）**保留在阶梯中，作为计量学的"爆炸性"基线。

## 6. 还没做到的地方

- E1、E2、E3、E7、E8、E9、C4 没有找到开放全文，或者还没有读，所以本文不引用它们的具体结论。如果你能提供 PDF，我可以补读。
- Sornette 的书 S4 没有读。
- 附件 `docs/framework_v2588.txt` 和 `review.html` 里提到的"原版 125 窗口"、"Trust 指标"等说法，我暂时还没能在一手文献里核实。

## 7. 对抗性自查记录（2026-10-24）

我逐条回到原文 PDF 和原型代码，核对了报告中的数字和判断，修正了以下几处：

| # | 原来的写法 | 问题 | 修正 |
|---|---|---|---|
| 1 | E6 振荡数为"半周期 ≥ 2.5，相当于 1.25 个整周期" | 论文式 (12) 写的是 ω/2，正文写的是 ω/π，两者矛盾 | 两种读法都列出，LIT 组各跑一版 |
| 2 | 顶部扫描为"38 个窗口加 2 个锚点" | 实际是每个 ZigZag 低点附近取 9 个锚定窗口，两个低点最多 18 个 | 改成准确的窗口构成和数量 |
| 3 | 窗口密度"低 4–18 倍" | 倍数算错了 | 改为约 E6 的 2/5、E4 的 1/12 |
| 4 | "AR(1) 下 t_c 误差 17–21 天" | 这只是 σ=0.03 时的数字 | 补上噪声水平，并给出 σ=0.01 时的对照值 |
| 5 | "我们的验证更严" | 验证计划还没执行，这样写属于把计划当成果 | 改为"计划中的" |
| 6 | 把 E6 当作"原版" | E6 是其他作者的后续研究 | LIT 组改名为"文献版"，并注明作者 |
| 7 | `lagrangeBest`"没接进来" | 说法不够精确：它其实在 `OD.analyze` 里用于挑选最佳窗口 | 写明用在哪里、哪里没用 |

已经核对无误的判断：
- M1 的约束；
- E4 的过滤表和三尺度划分；
- E6 的 t_c 范围、D ≥ 1 约束、最大相对误差、Lomb 检验和 AR(1) 条件、使用 CMA-ES；
- C1、C2、C3、C5 的结论；
- TOP_RULE 和 `TOP_OPT` 的代码数值（`critical.js:89-92`）。

这次自查没有覆盖的部分：标为"书目"的文献；`docs/framework_v2588.txt` 里的说法。同一个作者复核自己的结论仍有偏差，建议另开独立会话复审。

## 8. 独立复审后的修正（2026-10-24）

独立复审报告：PR #2 中的 `reports/red_team_literature_review.md`。下表中的 1–3、5 条我已对照原文 PDF 或代码亲自核实，第 4 条部分同意，第 6 条尚未核实。

| # | 复审发现 | 我的核实 | 结论 |
|---|---|---|---|
| 1 | (ω/2)·ln ≥ 2.5 是 DS LPPLS 的标准口径，不是 E6 的笔误 | E7 第 21 页表 3 的渲染图写的正是 (ω/2)·ln\|(t_c−t_start)/(t_end−t_start)\| | **成立**。第 7 节第 1 条的修正本身就错了；原型 ds 比 DS 口径严约 π 倍 |
| 2 | Jiang 等（2010）只用三项过滤 | 第 4 页原文："We filter on three parameters: tc > t2, B < 0, 0 < m < 1"；拟合方法是禁忌搜索加 LM | **成立**，已改正第 0 节第 3 条 |
| 3 | E7 是开放获取，可以直接核对 DS LPPLS | 表 3：搜索空间 m ∈ [0, 2]、ω ∈ [1, 50]、t_c ∈ [t_end−0.2dt, t_end+0.2dt]；条件 1：m ∈ [0.1, 0.9]、ω ∈ [6, 13]、t_c ∈ [t_end−0.15dt, t_end+0.13dt]、O ≥ 2.5、D ≥ 1.2、相对误差 ≤ 0.035；条件 2 用于 Trust 指标：t_c ∈ [t_end−0.2dt, t_end+0.12dt]、D ≥ 1、相对误差 ≤ 0.14；共 126 个窗口（125–750 日，步长 5） | **成立**。原型 ds（ω ∈ [2, 15]、D ≥ 0.5、t_c 只能在 t₂ 之后、没有相对误差条件）**不是** DS LPPLS 的参数。另外 DS LPPLS 允许 t_c 落在 t_end **之前** |
| 4 | 验证计划存在标签泄漏 | `CP.evaluate`（`critical.js:433-437`）用全样本 ZigZag 加全样本阈值定义顶部事件。标签本来就需要未来数据，这一点本身不算泄漏；但阈值 `zzThreshold(close, N−1)` 用了全样本波动率，确实会让未来信息渗进标签定义 | **部分成立**：严重程度定为中。新标签必须改用只依赖 t+H 以内数据的规则；"事件太少"和"多重比较"两点成立 |
| 5 | "原型不用 −ln P 找底"与代码不符 | `engine.js` 的 `OD.analyze` 有底部扫描；`critical.js:268-274` 有反泡沫这一项 | **成立**，已改表 |
| 6 | 漏掉了误报率和样本外检验方面的文献（Sornette & Zhou 2006，cond-mat/0304601；Yan 等 2012，arXiv 1108.0077；Zhou & Sornette 2002，cond-mat/0110445；Zhou & Sornette 2003，cond-mat/0310092；Laloux 等 1999，cond-mat/9804111） | 我还没读 | 待读，列入下一步 |

**据此调整第 5 节建议 1**：LIT 对照组改用 Sornette 团队自己的 DS LPPLS 过滤器（E7 表 3 的条件 1，同时用条件 2 计算 Trust 指标）作为主版本；E6 的 Lomb 检验和 AR(1) 检验作为可开关的附加项。

## 9. 补读：误报率与样本外检验文献（2026-10-24，均为 [全文]，读了摘要和结论部分的关键段落）

| 文献 | 内容 | 对我们的影响 |
|---|---|---|
| Sornette & Zhou（arXiv cond-mat/0304601，v3 版本 2004 年） | 把 LPPL 拟合结果交给模式识别算法，构造 alarm index，用误差图（Neyman–Pearson）评估。道指（DJIA）上明确列出了误报峰。恒生指数（HSI）上用 1987、1997 两次崩盘训练，另外 5 次没参与训练的崩盘中识别出 4 次 | 团队本身就区分训练段和测试段，并报告误报。我们也要输出**误差图**（漏报率对报警时间占比），并且必须与随机报警比较 |
| Yan, Rebib, Woodard & Sornette（arXiv 1108.0077） | 用崩盘和反弹的 alarm index 检验 10 个主要股指，误差图全部好于随机；多空策略有 7/10 跑赢基准；高波动期失效 | 负泡沫和反弹信号**有**正面证据，但依赖训练好的模式识别。底部模型的阶梯里应加入"负泡沫 alarm"这一级，并单独报告高波动期的表现 |
| Zhou & Sornette（arXiv cond-mat/0110445） | Lomb 周期图的误报概率**强烈依赖噪声类型**（重尾、相关性）；独立高斯噪声下的公式不能直接套用 | 如果用 Lomb 过滤，显著性门槛必须用**模拟零分布**来定：先拟合残差的分布和相关性，再生成替代序列；不能用标准 p 值 |
| Zhou & Sornette（arXiv cond-mat/0310092） | 检验 2000 年美股反泡沫：确认反泡沫已结束需要在新状态里待 **3–6 个月**；以美元、英镑、欧元或黄金计价，结论不同 | 底部识别有固有滞后，支持用"多条件 + 确认"的方式抄底，并提醒我们：要预先规定检验对象用名义价格还是通胀调整价格 |
| Laloux, Potters, Cont, Aguilar & Bouchaud（arXiv cond-mat/9804111，5 页） | 批评对数周期预测：1997 年 10 月的回调并不是一列几何级数局部低点的聚点；质疑相关研究的科学严谨性 | 作为怀疑派基线：任何"成功预测"都要在预先登记的规则下复现 |

## §16.11 补读状态（2026-10-24 夜；限速逐篇获取，三档核实标注）

| 文献 | 核实程度 | 来源 / 说明 |
|---|---|---|
| Lo–Mamaysky–Wang 2000, *Foundations of Technical Analysis*, J. Finance | **[全文]** | NBER WP w7613 全文（本地 `lit/nber_lo_mamaysky_wang.pdf`）。核回归平滑 + 10 类形态的条件收益分布检验（Kolmogorov–Smirnov），与本项目"起涨确认 = 成分股宽度"方向一致：形态本身只有弱信息，必须经分布检验，不可直接当交易规则。 |
| Harding–Pagan 2002, *Dissecting the cycle*, JME 49(2) | **[题录核实]** | DOI 10.1016/S0304-3932(01)00108-8，Elsevier 闭源，Unpaywall 无 OA 版本；此前下载到的 `harding_pagan_2002_wp.pdf` 实为天文学论文（arXiv:0805.4296），已删除。算法要点（BBQ：窗口 ±5 季、最短阶段 2 季、最短周期 5 季、峰谷交替）据公开摘要与 Pagan–Sossounov 2003 转述实现于 `research/eval/alt_labels.py::ps_turns`（日频参数 ±168/84/336 日）。 |
| Pagan–Sossounov 2003, *A simple framework for analysing bull and bear markets*, J. Applied Econometrics | **[摘要]** | OpenAlex 摘要（`lit/oa_A_simple_framework_...json`）；月频窗口 8 月、阶段 4 月、周期 16 月。 |
| Lunde–Timmermann 2004, *Duration dependence in stock prices*, JBES | **[摘要]** | OpenAlex 摘要；λ1=20%/λ2=15% 停时法实现于 `alt_labels.py::lt_turns`。 |
| Sornette–Demos–Zhang–Cauwels–Zhang 2015, *Real-time prediction and post-mortem analysis of the Shanghai 2015 stock market bubble and crash*, J. Investment Strategies 4(4) | **[题录核实]** | DOI 10.21314/jois.2015.063（付费）；SSRN 2647354（Unpaywall 标 OA，但 SSRN 对脚本下载返回 403）；此前误下的 arXiv:1508.01217 是另一篇（Bayesian kernel regression），已删除。本项目"7 指数 LPPLS 无增量"与其"实时预警命中"的差异（评价标准不同）见设计文档，正面对照待拿到全文后补。 |
| Harvey–Liu 2015, *Backtesting*, J. Portfolio Management 42(1) | **[题录核实]** | SSRN 2345489；多重检验下的 t 值门槛（Bonferroni/Holm/BHY），最终报告的多重比较将引用其框架；全文未获取。 |

未获取全文的，不在正文引用具体数值或页码。

### 16.12 原版细节遗漏清单（2026-10-25，对照手头全文：E5 Jiang 等 2010、E4 Gerlach 等 2019、M3 Demos–Sornette 2019、E7、M1、M2）
| # | 原版做法（出处） | 本仓库现状 | 影响 |
|---|---|---|---|
| 1 | 多尺度置信度：短 30–120 / 中 100–240 / 长 200–720 日各一个指标（E4 §4.1） | 单池 125–750 日；短尺度缺失 | 高 |
| 2 | t_c 聚类成情景：(dt, t_c−t₂) 平面 k-means + Silhouette 选簇数，每簇给 t_c 均值±std（E4 表 3）；A 股：合格拟合 t_c 的 20/80、5/95 分位区间为预测窗，事后核对峰值是否落入（E5 §3.1.1） | 未做；T-INT 用 IQR 对 20 日基线 | 高 |
| 3 | Lagrange 正则选 t₁（M3，E4 使用） | 未做 | 中 |
| 4 | 拟合器：Taboo 搜索 10 候选 + LM，每窗重复 3 次（E5 §2.1） | 单次 tc 网格 + LM | 中 |
| 5 | A 股过滤：Lomb 谱峰与 ω_fit 一致 + 残差单位根/O-U（E5 §2.3–2.4），不用阻尼阈值 | 未做 | 中 |
| 6 | t_c∈[t₂−0.2dt, t₂+0.2dt]（E7 表 3） | 仅 t_c>t₂ | 高 |
| 7 | t_c 区间：bootstrap（E5）/ 修正 profile likelihood（M2） | 未做 | 中 |
| 8 | 过滤阈值因论文而异：E7 条件 1 D≥1.2、误差≤3.5%、ω∈[6,13]；E4 D≥0.5、ω∈[4,25]、m∈(0,1)、O 仅在 \|C/B\|≥0.05 时启用；E5 无阻尼阈值 | 直接套 E7 条件 1 | 高 |

结论：不存在唯一"原版阈值"；A 股阈值须在开发段按原版评价标准做网格稳健性研究后冻结（预登记 §17.4）。

### 16.13 E3 Demirer–Demos–Gupta–Sornette (2018/2019) 核实（2026-10-25，[全文]，Pretoria 机构库 OA 版）
- 内容：对 S&P500 构建正/负泡沫的多尺度 LPPLS 置信度（窗口 30–750 日、步长 5、142 个窗口；短/中/长尺度分开），然后用 Markov-switching 预测模型检验**卖空活动与流动性能否预测这些置信度指标**。
- 对本项目的含义：它不是"置信度能否预测崩盘"的统计检验，不能作为原版评价标准的直接对照；原版团队对置信度→崩盘的评价仍主要是逐案实时预警与事后复盘（E1、E5）。我们的 A1/A2 + 循环平移零分布是自行设计的检验，报告时须如此标注。
- 可借鉴：负泡沫 = y→−y 镜像，B̂>0 判负泡沫（与 `LPPLS_SIGN=neg` 一致）；窗口集 30–750 与我们 v2 的 30–750 一致。

### 16.14 FBE 与 FCO 公开信息核实（2026-10-25）
- Woodard–Sornette–Fedorovsky 2010/2011, *The Financial Bubble Experiment Vol. III*, arXiv 1011.2882 [全文]：H1 = 泡沫可实时诊断；H2 = 泡沫终结可用概率窗口包住且优于随机。预测发布 t_c 的 20/80 与 5/95 分位（原拟合 + bootstrap 拟合集合）、最后观测日、拟合数；事后用 t₂ 后最大回撤、30/60/90 日上涨天数占比、Savitzky–Golay 局部增速判断体制改变；承诺公开全部成败案例。
- sornette.finance 公开页面（2026-10-25 抓取）：多尺度置信度（2–4 周至数年）、Combo 指标、每日正/负泡沫 Top-12、情景与 t_c 概率分布、"电影"功能（t_c 分布随新数据演化；案例以"分布稳定"作确认）、月报（约 450 系统性资产 + 850 个股）、Dragon King Protocol。"5 年实时 89% 成功率"为 FBE 自报口径，无对照组。内部实现不可知，不引用。
- Sornette–Cauwels 2015 §3.6 [全文]：正/负泡沫与高估/低估是两个维度，须分开表述。

### 16.15 FCO 月报方法附录与 sornette.finance 里程碑（2026-10-25）
- *The FCO Cockpit – Global Bubble Status Report, December 2019, Appendix: Methodology*（ETH Zurich × SIMAG，10 页，Internet Archive 存档，[全文]）：泡沫起点用 Lagrange 正则（Demos–Sornette 2019）；成熟度用 DS LPPLS 置信度（引 Johansen–Sornette 2010 综述）；可靠性用 k-means（Gerlach 等 2019），报告最大簇的 t_c 均值/标准差与"情景概率"（最大簇拟合数/总拟合数）；表格分正/负泡沫，列泡沫大小、持续时间、置信度，**按 |泡沫大小| 与置信度的几何平均排名**；个股按"泡沫信号 × 基本面"四象限。附录未给出过滤阈值、Trust、Bubble Score 定义。
- sornette.finance/milestones（2026-10-25 抓取）：2007 成立、2022 ETH 关停、2024 私有化重启；进行中 Dragon-King Protection Protocol（对冲/不对冲切换，对应 Sornette 2009 Dragon-King 概念，无方法论文）、规则化策略；下一步 Deep LPPLS（对应 Nielsen–Sornette–Raissi 2024，M5）。

### 16.16 FCO 平台公开前端文字与公开 OpenAPI 文档中的方法披露（2026-10-25；来源：sornette.finance 前端 JS 包内的界面说明文字、api.sornette.finance/v3/api-docs 公开 schema；均为未登录可见的公开内容，未访问任何需授权的数据）
- 四套拟合合格过滤集（前端 "Fit qualification" 原文）：STANDARD（参考集）damping ≥0.5、m ≤1、oscillations ≥2.5、2≤ω≤25；EARLY（实验）damping ≥0、m ≤1、oscillations ≥1.5、2≤ω≤25；END（实验）damping ≥0.8、m ≤1、oscillations ≥2.5、2≤ω≤25；PURE damping ≥0.5、m ≤0.9、oscillations ≥2.5、5≤ω≤13。前端把"哪几套合格"解读为阶段：仅 EARLY=forming，STANDARD=confirmed，+END=late，+PURE=late-narrow，并注明"这是过滤器不是泡沫年龄测量"。
- 置信度类型 confidenceType ∈ {WINDOWS, FITS, ALL}；每个指标（尺度）给 positiveConfidence / negativeConfidence 与 bestPositiveT1 / bestNegativeT1（最佳起点）及 T1Qualified 标志。
- Combo(p)：跨尺度置信度的幂平均，p=0 几何均值、p=1 算术均值、p 大→趋向最大值；默认 p=0.1；字段 combo01 / combo1 / combo10。前端"最佳信号"按 combo01（几何均值）排序；板块强度 = |bubbleScore| + combo10。
- BubbleScores 字段：bubbleScore、bubbleMultiScaleScore、bubbleSize、bubbleProgress、bubbleDuration、tc、scale（最长合格尺度）、confidenceIntervalFrom/To；正负泡沫各一组；positiveScales 计数。
- Scenario 字段：probability、tc 2.5%/97.5% 分位、tcMode、t1/t2、loss、adjustedLoss（按其排序选代表拟合）、closenessOfTcToT2、damping、oscillations、valid、indicatorType（四套过滤集之一）。
- 泡沫大小定义（FAQ 原文）：从泡沫形成起点到 t_c 处模型预测价格的轨迹幅度；"崩盘幅度通常是泡沫大小的一部分"。
- 月度体制带（描述性、非预测）：以资产自身前 60 个月为参照，月收益 <40 分位 Bearish、40–60 Neutral、60–80 Bullish、≥80 Rally；High risk 三通道：月收益 <5 分位；收益 <25 分位且日内波幅 excursion >40 分位；excursion >95 分位且收益 <60 分位。
- 仍未公开：窗口集合与尺度切分的具体数值、bubbleScore / bubbleProgress 的计算式、Dragon-King Protection Protocol 规则、Deep LPPLS 生产实现、校准方式。
- 对本项目：STANDARD 集（D≥0.5、ω∈[2,25]、m≤1、O≥2.5）落在 §17.4 网格附近（最近格点 D0.5 / w4_25 / m0_1，ω 下界 2 vs 4 有差）；建议把这四套原样加为网格点（提案，待确认）。

### 16.17 补读全文：M2 Filimonov–Demos–Sornette 2017 与 M5 Nielsen–Sornette–Raissi 2024（2026-10-25）
- M2（全文）：把 t_c 作为目标参数、{m, ω, A, B, C1, C2, s} 作为冗余参数，用修正 profile likelihood（Cox–Reid 型，含信息矩阵与 Jacobian 修正项）给 t_c 的似然区间（LI），避开 (t_c, ω) 平面的 sloppy 长谷；对 m、ω 的 LI 采用"固定 t_c 的降维模型"第三种方案（式 40）；案例窗口 180 日历日、上证 2015-06-12；指出 m 的 SSE 剖面在 0<m≲3 通常单峰，ω 多峰但趋势明显时主解清晰；§7 给跨窗口聚合 t_c 似然的方法。对本项目：我们的 t_c 区间用 bootstrap（Jiang 2010 式）与情景聚类，M2 的似然区间未实现——登记为候选（不新增模块，只在原版方法内替换区间估计方式；待确认后做）。
- M5（全文）：两类网络。M-LNN：对单条序列单独训练、含 LPPLS 结构的网络，直接最小化重构 MSE+参数约束罚；P-LNN：4 隐藏层 MLP，输入 252 点、输出 (t_c, m, ω)，在 10 万条合成 LPPLS 序列上监督训练（t_c∈[t₂, t₂+50]、m∈[0.1,0.9]、ω∈[6,13]、白噪 1–15% 或 AR(1) φ=0.9 噪 1–5%），验证 33,333 条；结果以误差 CDF 的一阶随机占优比较，P-LNN 对 LM 占优且单次标定 5 ms（LM 3.6 s）；经验数据只有 Nasdaq 1997–2000、UltraSilver 2010–11、Veslemannen 岩崩三例，作者自己说样本太小。对本项目：Deep LPPLS 是"更快的标定器"，不改变过滤/置信度/评价框架；在我们 8 核 11.5 小时的扫描成本下有工程价值，但其训练分布（m 0.1–0.9、ω 6–13、t_c 只在未来 50 日内）比 E7 搜索域窄，直接套用会把 t_c 落在窗内、m>1 的解系统性排除，与 v2 的发现相冲突。登记为"未来工程选项"，不进当前阶梯。
