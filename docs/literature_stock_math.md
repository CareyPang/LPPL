# 个股引擎数学审计的文献基础：Ising/羊群、LPPLS 前沿、其他临界预警方法、华尔街尾部风险模型（2026-11-02）

> 用途：为 `reports/stock_math_audit.md`（个股 LPPLS 引擎数学审计）提供文献依据。与仓库已有综述去重：`docs/literature_review.md`（LPPLS 主线 S/M/E/B/C/P 编号，含 Filimonov–Sornette 2013、Demos–Sornette 2019、Zhang–Zhang–Sornette 2016、Gerlach 2019、Jiang 2010、Brée–Joseph、Geraskin–Fantazzini 等全文）、`docs/literature_regime_models.md`（HMM/CSD/趋势/波动率管理）、`docs/literature_top_bottom_models.md`、`docs/literature_crash_bottom_echo.md`、`docs/literature_price_layer.md`。**已在上述文件中给出全文结论的文献本文只写"与个股引擎数学直接相关的补充核对"，不重复综述。**
>
> 获取方式：arXiv API + arxiv.org/pdf（间隔 ≥4 s）、PLoS printable、NBER/纽约联储/意大利央行/哥大/普林斯顿公开 PDF；全部 PDF 在 `~/lit/pdf/`（未入库），文本抽取 `~/lit/txt/`。共 41 篇获取成功（arXiv 29 + 其他 12），1 篇 404（MacLean–Thorp–Ziemba 2010，改用书目）。页码为 PDF 页。
>
> 证据等级三档：**OOS** = 样本外/前瞻实证；**IS** = 样本内实证（事后拟合、案例）；**TH** = 理论/模型/模拟。
> "可做 / 不可做"针对个股引擎（`research/pipeline/stock.py`，证据等级 research_candidate）；所有"可做"均指**写建议或草案、不直接进产品模型**（用户硬性规则）。

## 0. 一页结论（面向审计）

1. **LPPLS 的微观基础（Ising/羊群）只支持"形态诊断"，不支持"t_c = 顶部日期"**：JLS 2000 明确 t_c 是崩盘**最可能**的时间，崩盘可在 t_c 之前任何时刻发生，也有有限概率不崩（p.2、p.6）。个股引擎"t_c 只作情景区间"的规则与原始理论一致，应保持。
2. **线性化（Filimonov–Sornette 2013）**：A、B、C1、C2 四个线性参数在给定 (t_c, m, ω) 下有闭式最小二乘解，非线性参数只剩 3 个；仓库 `research/lppls/core.py::lin_fit` 用 lstsq(SVD) 实现，与文献 §3 等价（文献用正规方程，SVD 更稳）。文献建议的搜索域 m∈[0.1,0.9]、ω∈[6,13]（§2，用于过滤而非搜索）与仓库 v2 搜索域 m∈[0.01,2]、ω∈[1,50]（E7 表 3 搜索域）不同——仓库刻意用宽搜索域 + 窄过滤域，这与 Filimonov–Sornette 的"先宽搜索、后过滤"做法一致。
3. **t_c 在窗内的搜索域（[t₂−0.2dt, t₂+0.2dt]）来自 E7/Gerlach 2019**，但仓库 `tcgrid_lm` 的 t_c 网格阶段不评估 t₂ 之前的点（审计 F1），只靠随机起点和 LM 漂移覆盖——文献没有这一限制。
4. **Confidence/Trust 定义（Sornette 等 2015、Zhang–Zhang–Sornette 2016）**：Confidence = 合格窗口占比（对 t₁ 敏感性），Trust = 残差 bootstrap 重拟合后合格比例的中位数（对噪声实现的敏感性）。仓库实现口径一致；但两者在个股层面的任何预测力都只有 IS 级证据（Shu–Zhu 2020 对 A 股指数；Gerlach 2019 对 BTC），无 OOS。
5. **批评文献（Brée–Joseph 2013、Geraskin–Fantazzini 2013、Feigenbaum 2001、Troude 等 2024）**的共同点：LPPL 形态在 GARCH/随机游走等零假设下也能"合格"，误报率取决于过滤集；因此个股引擎的任何合格比例都必须和零假设误报率一起报告（审计 §3 做了 GBM/幂律/GARCH 零假设）。
6. **其他临界预警（CSD、Hawkes 临界、多重分形、RMT、GSADF）**对"崩盘时点"均无 OOS 证据：Guttal 等 2016 发现金融崩盘前**无**临界慢化（但方差上升）；Filimonov–Sornette 2013/Hardiman 等 2013 表明 Hawkes 分支比"接近 1"受核函数设定与非平稳性驱动；Grech–Mazur 2003 的局部 Hurst 只能"事后看出"。它们可作为**描述性背景层**候选（写草案），不能作为个股报警判据。
7. **华尔街量化风险模型（EVT/GPD、CAViaR、CoVaR、跳跃扩散、互激跳跃、Kelly）**回答的是"给定分布的尾部有多大 / 仓位多大"，不回答"顶在何时"。对本项目个股层的含义：可用 EVT/条件分位给出**后复权收益的尾部分位（描述性）**，与 LPPLS 形态并列展示，不合成单一分数；Kelly 类仓位规则属于执行层，须另做预登记。

## 1. 金融物理：Ising 模型与羊群效应（LPPLS 的微观基础）

| # | 文献（PDF 文件名） | 关键结论（页/节） | 证据 | 对个股引擎 |
|---|---|---|---|---|
| I1 | Johansen, Ledoit & Sornette (2000) *Crashes as critical points*, IJTAF 3(2) 219–255；arXiv cond-mat/9810071（`jls2000_crashes_critical_points.pdf`）。仓库 S1 只有书目，此处补全文 | §2.2.1 平均场 + §2.2.2 层级钻石格 Ising 噪声交易者，模仿强度 K 趋近临界 K_c 时 hazard rate h(t)∝(t_c−t)^{−α}；理性预期约束 dp/p = κ h(t) dt 给出 ln p(t) ≈ ln p_c − κB(t_c−t)^β[1 + C cos(ω ln(t_c−t)+φ)]（p.13 式 (17)–(22)）。**t_c 是崩盘最可能时间而非确定时间**，崩盘可在 t_c 前任何时刻发生、也可能不发生（摘要 p.2；§2.1 p.6）。实证：1929/1962/1987/1997 HK 事后拟合；GARCH(1,1)-t₄ 1000 条替代序列只有 66 条参数落入崩盘拟合范围（p.23–24）。 | TH + IS | **不可做**：把 t_c 当顶部日期（理论本身否定）。**可做**：报告里引用 p.2/p.6 作为"t_c 情景区间"的理论依据；GARCH 替代序列误报率（约 6.6%）可作零假设基线对照本审计 §3。 |
| I2 | Kaizoji (2000) *Speculative bubbles and crashes in stock markets: an interacting-agent model*, Physica A 287；cond-mat/0010263（`kaizoji2000_interacting_agent.pdf`） | 无限程 Ising（平均场）：交易者互动强度超临界 → 二阶相变分出牛/熊相；外场（投资环境）变化引起一阶相变 = 崩盘；多稳态与滞后（摘要 p.1；结论 p.16）。用日本 1987–1992 数据估计参数（§5）。 | TH + IS（单案例） | 理论上支持"崩盘 = 一阶相变、可无先兆"，即 LPPLS 形态不是崩盘的必要条件。**不可做**：据此加"投资环境外场"变量进个股模型。 |
| I3 | Bornholdt (2001) *Expectation bubbles in a spin model of markets*, IJMPC 12(5)；cond-mat/0105224（`bornholdt2001_expectation_bubbles.pdf`） | 局部铁磁耦合 + 对全局磁化的反铁磁耦合 → 跨尺度挫败 → 亚稳、间歇、混沌相；重现幂律收益分布与波动聚集（p.1 摘要；图 2–3 p.3–4）。无崩盘时点预测。 | TH | 说明"幂律尾 + 波动聚集"可由纯模仿动力学产生，不需要外生冲击；是本审计 GARCH 零假设的理论注脚。不可做为信号。 |
| I4 | Kaizoji, Bornholdt & Fujiwara (2002) *Dynamics of price and trading volume in a spin model…*, Physica A 316；cond-mat/0207253（`kaizoji_bornholdt_fujiwara2002_spin.pdf`） | 磁化 ↔ 成交量，价格由磁化决定；收益累积分布尾指数 >2；牛熊切换时间呈幂律分布（摘要 p.1；结论 p.12）。 | TH | 成交量是"羊群强度"的代理——但本项目禁用滞后指标且成交量预测顶的 OOS 证据缺失；**只可作描述性展示建议**。 |
| I5 | Zhou & Sornette (2005/2007) *Self-fulfilling Ising model of financial markets*, EPJ B 55；physics/0503230（`zhou_sornette2005_self_fulfilling_ising.pdf`）；长版 Sornette & Zhou (2006) *Importance of positive feedbacks and overconfidence…*, Physica A 370；cond-mat/0503607（`sornette_zhou2005_overconfidence_ising.pdf`） | 动态 Ising：耦合系数按"过去新闻解释收益的程度"持续更新；只有当 agent **过度自信、把新闻的成功误归因于羊群**时才重现程式化事实，系统自组织到临界点附近（摘要 p.1；长版摘要 p.1；多重分形谱 §6）。 | TH | 提供"接近临界点"的机制，但**模型没有可从价格序列直接估计的临界距离**；不可做为个股特征。 |
| I6 | Harras & Sornette (2011) *How to grow a bubble: a model of myopic adapting agents*, JEBO 80；arXiv 0806.2989（`harras_sornette2008_grow_bubble.pdf`） | 公共新闻 + 网络朋友意见 + 私有信息三源加权，权重按近期预测表现自适应；泡沫起于一串好运正面新闻 → 暂时性集体羊群 → 过冲 → 崩盘跌破基本面（摘要 p.1；结论 p.19–20）。 | TH | 说明泡沫起点由噪声决定、不可预测，**与 Lagrange 选 t₁ 的"客观起点"只能是事后描述一致**。不可做：用起点预测。 |
| I7 | Cont & Bouchaud (1997/2000) *Herd behavior and aggregate fluctuations in financial markets*, Macroecon. Dyn. 4；cond-mat/9712318（`cont_bouchaud1997_herd.pdf`） | 随机图上的羊群簇（渗流）→ 收益分布为指数截断幂律；超额峰度与模仿倾向、订单流相关（摘要 p.1；§3–4）。 | TH | 重尾与羊群的联系；对 EVT 层（§4）有理论支持：个股尾指数可随"羊群程度"变化，GPD 尾估计要用滚动窗。 |
| I8 | Kaizoji, Leiss, Saichev & Sornette (2015) *Super-exponential endogenous bubbles in an equilibrium model of fundamentalist and chartist traders*, JEBO 112；arXiv 1109.4726（`kaizoji_leiss_saichev_sornette2011_superexp.pdf`） | 理性 CRRA 投资者 + 受社会模仿与动量驱动的噪声交易者；时变羊群倾向 → 瞬态超指数增长与**近似**对数周期（摘要 p.1；§5 解析论证）；动量策略瞬态盈利（强化羊群）。 | TH + IS（dotcom 案例） | 文献层面确认"超指数（m<1，B<0）"是核心特征、对数周期只是近似——支持仓库把 m∈(0,1)、B<0 作为基础过滤、把 ω 过滤放宽（STANDARD ω∈[2,25]）。 |

**小结（§1）**：微观基础只给出"模仿强度接近临界 → 超指数 + 近似对数周期 + hazard 上升"这一定性链条，没有任何一篇给出可从单只股票价格外推的崩盘日期；"崩盘 = 一阶相变"类模型（I2、I3）还说明崩盘可以没有 LPPLS 先兆。**审计含义**：个股引擎输出的任何 t_c 量都只能标注为情景；Confidence 只能作"形态存在"的描述。

## 2. LPPLS 前沿：线性化、Confidence/Trust、t₁ 选择、t_c 区间、多尺度、负泡沫、A 股、识别性批评

（`docs/literature_review.md` 已对 E1–E12、C1–C4 等给出全文结论；下面只写与个股引擎**数学实现**直接相关的核对项。）

| # | 文献（PDF） | 关键结论（页/节） | 证据 | 对个股引擎 |
|---|---|---|---|---|
| L1 | Filimonov & Sornette (2013) *A stable and robust calibration scheme of the LPPL model*, Physica A 392；arXiv 1108.0099（`filimonov_sornette2013_calibration.pdf`） | 式 (12)–(13) p.10–11：C₁=C cos φ、C₂=C sin φ，模型变为 3 个非线性 (t_c,m,ω) + 4 个线性 (A,B,C₁,C₂)；线性参数在给定非线性参数下由正规方程闭式解出（§3，式 (14)–(16)）；目标函数 F(t_c,m,ω) 在模型适用时通常**单一极小**（摘要）；§4 进一步把 (m,ω) 从属于 t_c 做一维剖面（"subordination"），得到 t_c 的剖面曲线（p.12–14）。 | TH + IS | 仓库 `core.lin_fit`（lstsq/SVD）与式 (14)–(16) 等价且数值更稳（避免显式 XᵀX 病态）；`tcgrid_lm` 的"t_c 网格 + (m,ω) 网格剖面 + LM 精修"正是 §4 subordination 的离散版。**审计 F1**：文献剖面对 t_c 的扫描覆盖整个搜索区间，仓库网格阶段却跳过 t_c≤t₂，需修。 |
| L2 | Zhang, Zhang & Sornette (2016) *Early warning signals of financial crises with multi-scale quantile regressions of LPPLS*, PLoS ONE 11(11)（`zhang_zhang_sornette2016_plos_trust.pdf`；仓库 E8 已有） | **Table 3 (p.21)**：搜索域 m∈[0,2]、ω∈[1,50]、t_c∈[t_end−0.2dt, t_end+0.2dt]；过滤条件 1：m∈[0.1,0.9]、ω∈[6,13]、t_c∈[t_end−0.15dt, t_end+0.13dt]、Damping≥1；条件 2 增加振荡数 O=(ω/2)ln\|(t_c−t_start)/(t_end−t_start)\|≥2.5、t_c∈[t_end−0.2dt, t_end+0.12dt]（p.19–21）。Confidence = 合格拟合窗口比例（对 t₁ 的敏感性）；Trust = 用拟合残差 bootstrap 100 次加回拟合价、重新校准、满足条件 2 的比例（p.21）；两者对 16 个历史泡沫均为事后展示（§6）。 | IS | 仓库 v2 搜索域（m∈[0.01,2]、ω∈[1,50]、t_c∈[t₂−0.2dt, t₂+0.2dt]）与 Table 3 一致；`lppls_rules.rules()` 的 `box`/`p_ds`/`lit1`/`lit2` 与条件 1/2 对应；`trust.window_trust` 的 B=100 残差 bootstrap + 条件 2 与 p.21 一致。**差异**：仓库 Trust 用 iid 残差 bootstrap，文献 p.21 未指明块长；仓库 Trust 输出标 `descriptive`，与证据等级一致。 |
| L3 | Demos & Sornette (2017/2019) *Lagrange regularisation approach to compare nested data sets and determine objectively financial bubbles' inceptions*, Physica A 522；arXiv 1707.07162（`demos_sornette2017_lagrange.pdf`；仓库 E3） | 在伪现在 t̄₂ 固定下，对不同起点 τ 的窗口比较 χ²_np=SSE/(N−p)，再加 λ·N 的"Lagrange 正则项"（λ 由 χ²_np 对 N 的斜率经验估计，p.1–2），最小者给出客观 t₁*；用于 1987、2000、2008 等起点判定（IS）。 | IS + TH | 仓库 `_fit_pairs` 用固定窗口集合而非 Lagrange 选 t₁；个股 Confidence 把"多 t₁"当作抽样而非选最优，**这是 Confidence 的定义要求（L2），不是缺陷**。可做：报告里建议把 Lagrange t₁* 作为描述性输出（草案），不进过滤。 |
| L4 | Filimonov, Demos & Sornette (2017) *Modified profile likelihood inference and interval forecast of the burst of financial bubbles*, Quant. Finance 17；arXiv 1602.08258（`filimonov_demos_sornette2016_mpl.pdf`；仓库 E4） | 对 t_c 做（修正）剖面似然，把 m、ω、damping 当作 nuisance 参数处理，给出 t_c 的**区间估计**而不是点估计（摘要 p.1；§3）；修正项显著减少局部极值数（p.1）。 | TH + IS | 仓库 `intervals.profile_interval` 实现的是**未修正**剖面似然（文件注释已声明），区间偏窄；`tc_bootstrap` 另给块 bootstrap 区间。个股 `predict()` 中 `scenarios` 用的是跨窗口 t_c 分位（q20/q80），**不是**任何一种似然区间——报告建议统一命名为"跨窗口情景分位"，避免与 L4 的"区间预测"混淆。 |
| L5 | Gerlach, Demos & Sornette (2019) *Dissection of Bitcoin's multiscale bubble history*, R. Soc. Open Sci. 6；arXiv 1804.06261（`gerlach2018_bitcoin_multiscale.pdf`；仓库 E7） | Confidence 定义为多窗口合格拟合比例（摘要 p.1）；对不同伪现在 t₂，用 k-means 对各窗口 t_c 聚类得到多个"情景"（p.1），每个簇是一个情景而非预测；长/短泡沫分开（多尺度）。 | IS | 仓库六尺度 Confidence 与"t_c 情景分位"均源于此；**个股 t_c 聚类/分位只能叫情景（与用户硬规则一致）**。 |
| L6 | Yan, Woodard & Sornette (2012) *Diagnosis and prediction of market rebounds*, Physica A 391；arXiv 1003.5926（`yan_woodard_sornette2010_rebounds.pdf`） | 负泡沫 = 正反馈导致的加速下跌，JLS 模型镜像（B>0）；用模式识别（多时间窗参数 pdf 的问卷法）得到反弹报警，误差图/贝叶斯/交易策略显示优于随机（摘要 p.2；§4–6）。 | IS（回测） | 仓库 `lppls_rules` 的 `box` 要求 B<0（只做正泡沫）；个股引擎**不做负泡沫**是当前预登记范围。可做：建议作为草案列出负泡沫 B>0 情景，不进产品。 |
| L7 | Yan, Woodard & Sornette (2011) *Detection of crashes and rebounds in major equity markets*, arXiv 1108.0077（`geraskin_fantazzini2011_lppl_faq.pdf` 文件名有误，内容为此篇）| 用 JLS + 模式识别构造报警指数，10 个主要市场回测优于随机（摘要 p.1）；用"问卷"（参数 pdf 差异）在崩盘/反弹窗与无事件窗间判别（p.8）。 | IS（回测，非真正前瞻） | 对个股：仅支持"多窗口参数分布"作为特征的**研究思路**，未提供个股层面证据。**不可做**：直接把报警阈值搬到个股。 |
| L8 | Brée & Joseph (2013) *Testing for financial crashes using the LPPL model*, Int. Rev. Fin. Anal. 30；arXiv 1002.1010（`bree_joseph2010_testing_lppl.pdf`；仓库 C1） | 恒生 1970–2008 的 11 次大跌只有 7 次 LPPL 参数落入 JS 事后给定范围（摘要 p.5）；JLS 机制要求期望价格持续上升与实证不符（结论 p.23）；崩盘与泡沫起点定义不清（p.24）。 | IS（反例） | 支持本审计把"合格比例"与零假设误报率并列；个股层面参数范围更不稳定（审计 §3 边界比例）。 |
| L9 | Jiang, Zhou, Sornette, Woodard, Bastiaensen & Cauwels (2010) *Bubble diagnosis and prediction of the 2005–2007 and 2008–2009 Chinese stock market bubbles*, JEBO 74；arXiv 0909.1007（`jiang2009_china_bubbles.pdf`；仓库 E5） | 对 SSEC/SZSC 两次泡沫给出事前时间窗预测（2007-10、2009-08；摘要 p.1）；用 Lomb 谱与 (H,q) 分析验证对数周期（p.1）。 | OOS（两次公开事前预测）+ IS | 唯一与 A 股直接相关的 OOS 证据，但只针对**指数**，窗口 ≥ 数月；个股层面无证据——维持 research_candidate。 |
| L10 | Shu & Zhu (2020) *Detection of Chinese stock market bubbles with LPPLS confidence indicator*, Physica A 557；arXiv 1905.09640（`shu_zhu2019_china_lppls_confidence.pdf`；仓库 E6） | 沪深 300 2002–2018：搜索域加入 damping 条件，过滤增加最大相对误差、Lomb 检验、残差单位根（PP/DF）（摘要 p.1）；结论为事后"诊断对应历史事件"，无样本外检验（全文未出现 out-of-sample）。 | IS | 仓库 `lit2`/`g_fco_*` 含相对误差与 Lomb 项，与此一致。**不可做**：把这篇作为 A 股 Confidence 预测力证据。 |
| L11 | Shu & Zhu (2019) *Real-time prediction of Bitcoin bubble crashes*, Physica A 548；arXiv（`shu_zhu2019_bitcoin_lppls.pdf`） | 用 Confidence/Trust 做"实时"（伪现在）预测 BTC 2017–2018 崩盘（摘要）；本质是滚动事后。 | IS（伪前瞻） | 同 L10。 |
| L12 | Troude, Lera, Wu & Sornette (2024) *Illusions of criticality: crises without tipping points*, arXiv 2412.01833（`troude2024_illusions_criticality.pdf`） | 非正规（non-normal）随机系统中"伪分岔"可重现**全部**早期预警信号（临界慢化、方差上升、维度坍缩），且可发生在任何真实分岔之前（摘要 p.1）。 | TH + IS（脑电） | 对所有"接近临界"类指标（含 LPPLS 的 hazard 解释）给出一般性警告：**任何个股临界信号都必须附零假设误报率**；不可做：把 Confidence 解读为"距临界点距离"。 |

**小结（§2）**：仓库 v2 搜索域/过滤/Confidence/Trust 的**定义**与 L1、L2、L5 一致；需要修正的是实现层（网格阶段 t_c 覆盖，审计 F1）和命名层（t_c 分位 ≠ 似然区间，审计 F-命名）。个股层面所有文献证据为 IS 或无；A 股唯一 OOS（L9）是指数级。

## 3. 其他前沿方法：临界慢化/预警信号、Hawkes、多重分形、RMT/网络、GSADF、机制转换

（GSADF/PSY、HMM/机制转换、CSD 的主线文献已在 `docs/literature_review.md` §P 与 `docs/literature_regime_models.md` 全文综述，此处只补本次新获取的全文及其对个股引擎的含义。）

| # | 文献（PDF） | 关键结论（页/节） | 证据 | 对个股引擎 |
|---|---|---|---|---|
| O1 | Guttal, Raghavendra, Goel & Hoarau (2016) *Lack of critical slowing down suggests that financial meltdowns are not critical transitions, yet rising variability could signal systemic risk*, PLoS ONE 11(1)（`guttal2016_plos_no_csd.pdf`） | 过去一个世纪主要崩盘前**没有**临界慢化（lag-1 自相关无或弱趋势，Kendall-τ，p.6），但方差与低频谱功率上升显著（p.1、p.4 表 1：16 次越阈，其中若干为误报）；结论：崩盘不是鞍结分岔类临界转变（p.1）。 | IS（事后） | **不可做**：把 CSD（自相关上升）作为个股预警；**可做（草案）**：滚动方差/低频功率作为描述性"波动抬升"层，并与 LPPLS 形态并列展示。 |
| O2 | Dakos et al. (2012) *Methods for detecting early warnings of critical transitions in time series illustrated using simulated ecological data*, PLoS ONE 7(7)（`dakos2012_plos_ews_methods.pdf`） | 各类 EWS（自相关、方差、偏度、DFA、谱比、条件异方差等）对去趋势方式与带宽敏感（p.14 表：Gaussian 滤波带宽、滚动窗长）；趋势强度用 Kendall-τ 并需替代数据显著性（p.4–5）。 | TH（模拟） | 任何"预警指标趋势"都要同时报告：去趋势方法、窗长、替代数据显著性——与本审计对 LPPLS 合格率要求零假设对照一致。 |
| O3 | Filimonov & Sornette (2015) *Apparent criticality and calibration issues in the Hawkes self-excited point process model*, Quant. Finance 15；arXiv 1308.6756（`filimonov_sornette2013_apparent_criticality.pdf`） | Hawkes 分支比 n 的估计在幂律核 + 离群值、核正则化形式、边界效应、多局部极值下**系统性上偏**，n≈1 的"临界"可在真值 n=0 时出现（摘要 p.1）；日内季节性导致外生项非平稳是偏差的主要来源（p.2）。 | TH + IS | **不可做**：用日线构造"内生性/分支比"信号（日频数据连核都无法识别）。 |
| O4 | Bacry, Mastromatteo & Muzy (2015) *Hawkes processes in finance*, Market Microstructure & Liquidity 1；arXiv 1502.04592（`bacry2015_hawkes_finance.pdf`） | 综述：‖Φ‖（核 L¹ 范数）= 分支比；经验估计常 ≥0.9（p.21），近临界与非平稳难以区分（p.6）；非参数核估计需高频数据（§4）。 | TH + IS | 同 O3；可在文献层记录"近临界 Hawkes = 高内生性"作为 Ising/羊群的另一种刻画，无个股日线可行路径。 |
| O5 | Grech & Mazur (2004) *Can one make any crash prediction in finance using the local Hurst exponent idea?*, Physica A 336；arXiv cond-mat/0311627（`grech_mazur2003_hurst_crash.pdf`） | DJIA 1929/1987 及 1995–2003：局部 Hurst 指数在大跌前下降（相关性减弱，p.3）；窗长 N 的选择决定信号（p.5）；仅案例。 | IS（案例） | 同类局部 Hurst/DFA 在仓库 `docs/literature_review.md` 已评为"事后"；**不可做**为判据。 |
| O6 | Kantelhardt et al. (2002) *Multifractal detrended fluctuation analysis of nonstationary time series*, Physica A 316；arXiv physics/0202070（`kantelhardt2002_mfdfa.pdf`） | MF-DFA 定义 F_q(s)∼s^{h(q)}，h(2)=Hurst（式 (5) p.2）；非平稳序列需去趋势阶数选择；与 WTMM 等价性比较（§4）。 | TH | 方法论基础；个股 500–1500 bar 的 h(q) 估计方差大（见 O7 有限尺寸效应），不可做为判据。 |
| O7 | Jiang, Xie, Zhou & Sornette (2019) *Multifractal analysis of financial markets: a review*, Rep. Prog. Phys. 82；arXiv 1805.04750（`jiang2018_multifractal_review.pdf`） | §7.1 伪多重分形与有限尺寸效应（p.90–91）：有限样本 + 肥尾即可产生表观多重分形谱宽；崩盘前后谱宽变化的证据零散（p.66）。 | TH + IS | 明确**不可做**：以多重分形谱宽作个股泡沫判据；仅可在文献层备注。 |
| O8 | Laloux, Cizeau, Bouchaud & Potters (1999) *Noise dressing of financial correlation matrices*, PRL 83；arXiv cond-mat/9810255（`laloux1998_noise_dressing.pdf`） | S&P500 相关矩阵绝大部分特征值落在 Marchenko–Pastur 噪声谱内，仅少数大特征值携带信息；小特征值对噪声最敏感而恰是 Markowitz 优化所用（p.1）。 | IS | 对本项目：任何用相关矩阵的"系统性"层须先做 RMT 去噪；个股引擎本身不涉及。 |
| O9 | Plerou et al. (1999) *Universal and non-universal properties of cross-correlations in financial time series*, PRL 83；arXiv cond-mat/9902283（`plerou1999_rmt_cross_corr.pdf`） | 1000 只美股 1994–95：特征值统计符合 GOE 普适性，少数最大特征值偏离；IPR 揭示局域化特征向量（p.1）。 | IS | 同 O8。 |
| O10 | Mantegna (1999) *Hierarchical structure in financial markets*, EPJ B 11；arXiv cond-mat/9802256（`mantegna1998_hierarchical.pdf`） | 以 d=√(2(1−ρ)) 构造 MST，次优超度量树给出有经济含义的分类（p.1、p.4）。 | IS | 网络层方法基础；不涉及个股时间维预警。 |
| O11 | Onnela, Chakraborti, Kaski, Kertész & Kanto (2003) *Dynamics of market correlations: taxonomy and portfolio analysis*, PRE 68；arXiv cond-mat/0302546（`onnela2003_market_correlations.pdf`；文本抽取字体损坏，仅据摘要） | 滚动 MST 的归一化树长在 1987 Black Monday 期间显著收缩（市场同步化），MST 中心性与投资组合有关（摘要）。 | IS | "崩盘时树收缩"是**同期**现象而非先导；不可做为预警。 |
| O12 | Zheng, Podobnik, Feng & Li (2012) *Changes in cross-correlations as an indicator for systemic risk*, Sci. Rep. 2:888（`zheng2012_scirep_crosscorr.pdf`） | PC1 解释比例（吸收比）的月度变化与随后 12 个月大跌相关（p.3–4）；窗长 n 太大会抹平冲击（p.3）。 | IS（回测） | 属于市场层系统性风险描述，可写入"背景层"草案，不进个股判据。 |

**小结（§3）**：这些方法在"崩盘时点"上没有一篇给出 OOS 证据；O1、O3、O7、Troude 2024（L12）还分别指出 CSD、Hawkes 临界、多重分形谱、所有 EWS 的伪信号机制。对个股引擎，它们全部属于"**只写建议/草案**"范围。

## 4. 华尔街量化模型中与泡沫/崩盘风险相关的部分

| # | 文献（PDF） | 关键结论（页/节） | 证据 | 对个股引擎 |
|---|---|---|---|---|
| W1 | Engle & Manganelli (1999/2004) *CAViaR: Conditional autoregressive value at risk by quantile regression*, NBER WP 7341 / JBES 22（`engle_manganelli1999_caviar_nber.pdf`） | 把 VaR 视为条件分位并直接对分位做自回归（摘要 p.1）；提出 DQ 检验（命中无偏、独立）做回测（p.27–28）。 | IS + OOS（回测含样本外） | **可做（草案）**：对个股后复权日收益做条件分位（如 5%/1%）作描述性尾部层；回测须用 DQ。不得与 LPPLS 合成单一分数。 |
| W2 | Adrian & Brunnermeier (2008/2016) *CoVaR*, FRBNY Staff Report 348 / AER 106（`adrian_brunnermeier_covar_fedny.pdf`） | ΔCoVaR = 机构困境 vs 中位状态下系统 CoVaR 之差；分位回归估计；杠杆、规模、期限错配、资产价格繁荣可**样本外**预测 ΔCoVaR（摘要 p.1；forward-ΔCoVaR p.3）。 | OOS（预测 ΔCoVaR，而非崩盘时点） | 说明"资产价格繁荣 → 尾部风险贡献上升"有 OOS 证据，但是宏观/机构层；个股可做草案："泡沫形态 × 条件尾部"二维展示。 |
| W3 | Kou (2002) *A jump-diffusion model for option pricing*, Management Science 48（`kou2002_jump_diffusion.pdf`） | 双指数跳跃扩散：解析期权定价，解释左偏肥尾与波动率微笑（p.1–2）。 | TH | 为"崩盘 = 跳"提供定价框架，但跳强度常数、无时点信息；不可做为预警。 |
| W4 | Aït-Sahalia, Cacho-Diaz & Laeven (2010/2015) *Modeling financial contagion using mutually exciting jump processes*, NBER WP 15850 / JFE 117（`aitsahalia2010_contagion_nber.pdf`） | 漂移 + 随机波动 + Hawkes 互激跳：一地区跳提高本地与他地区跳强度（自激/互激，摘要 p.1；§2 p.6）。 | IS（GMM 估计） | 与 O3/O4 同源：跳强度是"事后抬升"量，可作尾部风险条件项（草案）；不是顶部时点。 |
| W5 | Kelly (1956) *A new interpretation of information rate*, Bell Syst. Tech. J. 35（`kelly1956_information_rate.pdf`） | 最大化资本对数增长率 G 的下注比例 = 信息率（p.1、p.3）；对概率估计误差敏感（p.2 讨论）。 | TH | 仓位规则属执行层，**与预登记判据无关且未预登记**；只可写"若有校准概率才可用 fractional Kelly"的草案。MacLean–Thorp–Ziemba (2010) 原文 404 未获取，依书目记。 |
| W6 | EVT/GPD（McNeil–Frey 2000 *Estimation of tail-related risk measures…*, J. Emp. Fin. 7；Rocco 2014 *Extreme value theory for finance: a survey*, J. Econ. Surveys 28——**本次获取的 Bank of Italy PDF 内容有误（为按揭证券化论文），未能验证页码**；补充抓取见 §6） | 标准做法：GARCH 过滤 + 对标准化残差超阈值部分拟 GPD，条件 VaR/ES；阈值选择（均值超额图/Hill）是主要不确定性来源。 | IS + OOS（McNeil–Frey 回测） | **可做（草案）**：个股后复权收益 GARCH-EVT 条件 ES 作为"尾部层"描述；窗长 ≥1000 bar；对 ST/一字板个股失效（收益截断）。 |

**小结（§4）**：这些模型回答"尾部多大/仓位多大"，不回答"顶在何时"；它们与 LPPLS 的正确关系是**并列展示**（形态层 vs 尾部层），不是合成。任何进入产品的尾部层需要新的预登记。

## 5. 汇总：对个股引擎"可做 / 不可做"（均为建议或草案，不改产品模型与预登记判据）

| 主题 | 不可做（文献依据） | 可做——写进审计报告/草案 |
|---|---|---|
| t_c 解释 | 把 t_c 或其分位当"顶部日期"（I1 p.2/p.6；L5） | 统一命名"跨窗口 t_c 情景分位"；区分 L4 的似然区间与仓库 bootstrap 区间（`intervals.py`） |
| 搜索域/过滤 | 回退 v1 框或把过滤域当搜索域（L1 §2、L2 Table 3） | 保持 v2 搜索域 = L2 Table 3；修正网格阶段对 t_c≤t₂ 的覆盖（审计 F1） |
| Confidence | 把合格比例解读为崩盘概率（L8、L12） | 与 GBM/幂律/GARCH 零假设误报率并列报告（I1 p.23–24 的 6.6% 为历史参照） |
| Trust | 在个股 Q-STK1 评价中跑 Trust 以调参（预登记禁止） | 保持 B=100 残差 bootstrap 与条件 2（L2 p.21）；标注 descriptive |
| t₁ 选择 | 用 Lagrange t₁* 替代多窗口 Confidence（二者目的不同，L3） | 作为描述性字段输出 t₁*（草案） |
| 负泡沫 | 在当前预登记下加入 B>0 判据 | 文献层标注 L6/L7 的镜像情景 |
| CSD/Hawkes/MF-DFA/RMT/网络 | 任何作为个股预警判据（O1、O3、O7、L12） | 市场层"背景描述"草案（方差抬升、吸收比） |
| 尾部风险 | 与 LPPLS 合成单一分数 | GARCH-EVT 条件 ES / CAViaR 分位作并列"尾部层"草案（W1、W6），需新预登记 |
| 仓位 | 未经预登记引入 Kelly 类规则（W5） | 文献层记录 fractional Kelly 的前提（校准概率） |

## 6. 与仓库已有综述的去重及获取记录

- 已在 `docs/literature_review.md` 给出全文结论、本文仅补"实现核对"的文献：Filimonov–Sornette 2013（E2）、Demos–Sornette 2019（E3）、Filimonov–Demos–Sornette 2017（E4）、Jiang 等 2010（E5）、Shu–Zhu 2020（E6）、Gerlach 等 2019（E7）、Zhang–Zhang–Sornette 2016（E8）、Brée–Joseph 2013（C1）、Geraskin–Fantazzini 2013（C2，本次未重新下载，文件 `geraskin_fantazzini2011_lppl_faq.pdf` 实为 Yan–Woodard–Sornette 2011）、GSADF/PSY（P 系列）、Scheffer 2009/Dakos 2012（`docs/literature_regime_models.md`）。
- 本次新增全文（此前仓库只有书目或没有）：JLS 2000、Kaizoji 2000、Bornholdt 2001、Kaizoji–Bornholdt–Fujiwara 2002、Zhou–Sornette 2005/2007、Sornette–Zhou 2006、Harras–Sornette 2011、Cont–Bouchaud 2000、Kaizoji–Leiss–Saichev–Sornette 2015、Yan–Woodard–Sornette 2012（负泡沫）、Troude 等 2024、Guttal 等 2016、Filimonov–Sornette 2015（Hawkes）、Bacry 等 2015、Grech–Mazur 2004、Kantelhardt 等 2002、Jiang 等 2019（多重分形综述）、Laloux 等 1999、Plerou 等 1999、Mantegna 1999、Onnela 等 2003、Zheng 等 2012、Engle–Manganelli 1999、Adrian–Brunnermeier 2008、Kou 2002、Aït-Sahalia 等 2010、Kelly 1956、Martins-Filho–Yao–Torero 2016（arXiv 1612.08099，非参数 GARCH 型位置-尺度 + GPD 的条件 VaR/ES，含一致性与渐近正态，§2–4；IS/TH）、Martín 等 2023（arXiv 2306.12202，GPD 贝叶斯先验 VaR/CVaR；TH）、Yashaswi 2021（arXiv 2112.04576，Heston 状态空间自适应校准；TH——Heston 1993 原文无公开 PDF，未下载）。
- 获取失败/有误：MacLean–Thorp–Ziemba 2010（404）；Rocco 2014 EVT 综述（Bank of Italy 链接返回按揭证券化论文，内容无效，已在 W6 标注）；Onnela 2003 文本抽取字体损坏（仅摘要）。
- 总计有效 PDF 41 篇（arXiv 31、PLoS 3、NBER 2、FRBNY 1、哥大/普林斯顿等 4），均在会话机 `~/lit/pdf/`，**未入库**。

## 7. 第二批补查（2026-11-02；为 `docs/research_plan_stock_math.md` 服务；限速 3 s/次，22 篇全文，PDF 在会话机 `~/lit/pdf2/`，未入库）

证据等级同上：**OOS** = 样本外/前瞻实证；**IS** = 样本内实证；**TH** = 理论/方法。"可做/不可做"均指**建议或草案**，不改产品模型与预登记判据。

### 7.1 LPPLS 方法与识别性
| # | 文献（文件） | 关键结论（页/节） | 等级 | 对个股引擎 |
|---|---|---|---|---|
| N1 | Sornette & Johansen (2001) *Significance of log-periodic precursors to financial crashes*, QF 1；cond-mat/0106520（`sornette_johansen2001_…`，38 p） | 回应 Feigenbaum：去掉最靠近 t_c 的 15% 数据再检验幂律发散是"naive"（摘要）；§9 给出港股指数 20 年系统性样本外检验与"crash roulette"显著性公式；§12 列 20 个主要案例的对数周期谱 | IS + 部分 OOS（港股） | 可做：任何个股信号评价都要配 N1 式"预测轨迹显著性"（按事件计）；不可做：用"去尾再拟合"来否定或肯定单只个股的拟合 |
| N2 | Sornette, Woodard, Yan & Zhou (2013) *Clarifications to questions and criticisms on the JLS model*, Physica A 392；arXiv 1107.3171（27 p） | 逐条澄清 JLS 的理论地位与标定问题（含 B<0、m∈(0,1)、ω 范围的物理含义，§3–§5）；结论承认"领域仍在成熟中"（Conclusion p.18） | TH | 可做：过滤条件的物理解释写进产品文案的"方法说明"；不可做：引用本文把 Confidence 说成"崩盘概率" |
| N3 | Lin, Ren & Sornette (2009/2014) *A consistent model of 'explosive' financial bubbles with mean-reversing residuals*（volatility-confined LPPL）；arXiv 0905.0128（32 p） | 残差 O-U 均值回复是模型的一部分；残差单位根检验对 GARCH 基准的误报率 0.2%（摘要）；S&P500 1950–2008 识别 1987/1997/1998/2000 四个泡沫；§6 结论 | IS（含 GARCH 零假设） | 可做：把"残差 ADF/PP 平稳性"作为**描述性**附加字段并与本仓库零假设误报率（GBM 6.6%、幂律 34%）并列；不可做：以此替换预登记的 box/FCO 判据 |
| N4 | Lin & Sornette (2009/2013) *Diagnostics of rational expectation financial bubbles with stochastic mean-reverting termination times*；arXiv 0911.1921（25 p） | 两个 RE 模型：价格或动量的幂律正反馈 + **随机均值回复的终止时间**（§5 结论）；t_c 本身是随机变量 | TH | 支持硬规则"t_c 不是日期"；可做：产品文案引用"t_c 为随机临界时间"；不可做：给 t_c 点估计 |
| N5 | Nielsen, Sornette & Raissi (2024) *Deep LPPLS*；arXiv 2405.12803（16 p） | M-LNN 对 (t_c, m, ω) 的绝对误差分布对 LM 一阶随机占优（§4 Fig.3 p.6）；P-LNN 可对固定长度序列秒级给参数；训练噪声多样性决定稳健性（§5） | TH + 合成 IS | 可做：作为**标定对比实验**（与 `tcgrid_lm` 在合成序列上比误差分布，WP2）；不可做：进产品链路（无实盘/样本外证据，且改变已登记的标定方法） |
| N6 | Petrillo (2021) *Verification and validation of LPPL models*；arXiv 2106.05116（4 p） | 子样本重估 + 取中位数的"subordinated algorithm"；t_c 平均绝对误差随窗口逼近临界点仅有不显著下降（Conclusion） | 合成 IS | 可做：跨窗口中位数（本仓库已是多窗口口径）；提醒：逼近 t_c 不保证精度提升，支持只给区间 |
| N7 | Geraskin & Fantazzini (2013) *Everything you always wanted to know about LPPL…*，MPRA 47869（36 p；**替换上一批错配文件**） | §4 三种估计法（JLS 两步非线性、遗传算法、2/3 步 ML）；§5 残差诊断 + 随机终止时间诊断 + 图形工具；§6 黄金 2009-12 案例 | TH + IS | 可做：残差诊断清单作为审计用例；不可做：把黄金单案例外推到 A 股个股 |
| N8 | Wheatley, Sornette, Huber, Reppen & Gantner (2018/2019) *Are Bitcoin bubbles predictable?*，R. Soc. Open Sci.；arXiv 1803.05663（20 p） | 基本面（广义 Metcalfe）× LPPLS 技术面交叉诊断，至少 4 次泡沫；附录给出 **GLS + AR(1) 误差 + 剖面似然 t_c 95% 区间** 的算法步骤（p.18–19） | IS（事后）+ 少量前瞻 | 可做：WP2 的 t_c 区间按 AR(1) 误差而非 iid 残差 bootstrap（与 `trust.py` iid 假设对照）；不可做：个股无"基本面网络价值"可比，不能照搬交叉诊断 |
| N9 | Akingbade, Gidea & Manzi (2023) *Why TDA detects financial bubbles?*；arXiv 2304.06877（29 p） | 拓扑数据分析的早期预警信号在 LPPLS 成立时由对数周期振荡产生（§7）；合成 + 比特币 | TH + IS | 不可做：引入 TDA 为新模型；可做：文献层记录"TDA 信号 = LPPLS 振荡的另一种读数"，无独立信息 |

### 7.2 微观基础与行为证据
| # | 文献 | 关键结论 | 等级 | 对个股引擎 |
|---|---|---|---|---|
| N10 | Sornette (2014) *Physics and financial economics (1776–2014): puzzles, Ising and agent-based models*，Rep. Prog. Phys. 77；arXiv 1404.0243（76 p） | Ising/随机效用/logit 作为社会模仿的统一框架；泡沫 = 正反馈导致的有限时间奇异性；§8 结论强调物理只是"概念与工具框架"而非预测器 | TH（综述） | 定位文献：Ising 只支持"形态诊断"的解释层，不提供可估计的临界距离（与 §1 结论一致） |
| N11 | Hüsler, Sornette & Hommes (2013) *Super-exponential bubbles in lab experiments*，JEBO；arXiv 1205.0635（24 p） | 实验室价格形成中超指数增长显著，来源是交易者基于**过去价格**而非已实现收益上调乐观预期（摘要、§6） | 实验 IS | 支持 LPPLS 的"超指数"前提；不可做：实验室参数外推到 A 股 |
| N12 | Zhou & Sornette (2005) *Fundamental factors versus herding in the 2000–2005 US stock market and prediction*；physics/0505079（29 p；替换上一批错下的文件） | 用 AIC/Wilks 比较加入利率、利差、波动率、汇率因子的模型，**最佳模型仍是不含任何因子的二阶 LPPL**（摘要、§5–§6） | IS | 可做：WP3 中"控制动量/波动率后 LPPLS 是否仍有增量"的设计正是本文方法的预登记化；不可做：把结论当作个股层面成立 |

### 7.3 A 股 / 个股 / 危机类型
| # | 文献 | 关键结论 | 等级 | 对个股引擎 |
|---|---|---|---|---|
| N13 | Shu & Zhu (2019) *Diagnosis and prediction of the 2015 Chinese stock market bubble*；arXiv 1905.09633（20 p） | SSEC/SZSC 2014–2015-06：CMA-ES 搜非线性参数、Lomb 谱检出对数周期、残差 PP/ADF 平稳（§4 结论）；回测属事后 | IS（事后） | 可做：Lomb 谱与残差平稳性作描述性诊断；不可做：引用为个股预测证据 |
| N14 | Song, Shu & Zhu (2021) *The 2020 global stock market crash: endogenous or exogenous?*；arXiv 2101.00327（25 p） | 用 Confidence 作"内生/外生崩盘"分类代理：10 指数中 CSI300 2020-03 回撤 16.1% 判为内生，HSI/NIKKEI/FTSE 外生（Table 1） | IS（事后分类） | 可做：描述性"内生性标签"草案（WP4）；不可做：用于预警或等级 |
| N15 | Shu, Song & Zhu (2021) *The 'COVID' crash of the 2020 U.S. stock market*；arXiv 2101.03625（19 p） | W5000/SP500/SP400/R2000 崩盘前均处正泡沫，中小盘跌幅更大（§4） | IS（事后） | 提醒：市值分层下泡沫形态与回撤深度不同，WP3 需按市值分层报告 |
| N16 | Takagi (2021) *Exploring the endogenous nature of meme stocks using the LPPL model and confidence indicator*；arXiv 2110.06190（9 p） | 四只个股（TSLA/GME/KOSS/AMC）：CI 能检出先前的负泡沫（GME 2019-08 CI≈0.8），但**无法预测**由逼空等外生因素引发的大涨（§5） | IS（个股，事后） | 目前唯一直接的"个股 LPPLS"全文证据，结论与本仓库横截面"无预测信息"一致；强化 `research_candidate` |

### 7.4 市场微结构 / 系统性 / 尾部风险 / 仓位
| # | 文献 | 关键结论 | 等级 | 对个股引擎 |
|---|---|---|---|---|
| N17 | Hardiman, Bercot & Bouchaud (2013) *Critical reflexivity in financial markets: a Hawkes process analysis*，EPJ B；arXiv 1302.1405（9 p） | E-mini 1998–2011 Hawkes 核积分恒≈1（幂律核），与 Filimonov–Sornette "反身性上升"结论相反（摘要、Conclusion） | IS | 与 O3 合读：分支比对核形式极敏感 → **不可做** Hawkes 临界作个股信号（维持 §3 结论） |
| N18 | Billio, Getmansky, Lo & Pelizzon (2010/2012) *Econometric measures of connectedness and systemic risk*，NBER w16223 / JFE（58 p） | PCA 吸收 + Granger 因果网络衡量金融机构关联度，可识别并部分预示危机期（§7） | IS + 部分 OOS | 可做：市场层"关联度/吸收比"描述性背景草案（WP6）；不可做：个股预警 |
| N19 | Kelly & Jiang (2013/2014) *Tail risk and asset returns*，NBER w19375 / RFS（51 p） | 用个股横截面日收益的 Hill 估计得到月度尾指数 λ_t（AR(1)=0.927，p.3）；对市场 1 月–5 年收益有预测力；高尾风险股 vs 对冲股三因子 α 差 5.4%/年（§5） | OOS（预测回归） | 可做：WP3 把 λ_t 作为**协变量/对照基线**（与动量并列），检验 LPPLS 置信度是否有增量；不可做：直接作为个股顶部信号 |
| N20 | Bollerslev & Todorov (2011) *Tails, fears, and risk premia*，JF 66（47 p） | 稀有事件补偿占股权/方差风险溢价很大部分；用 EVT 近似 + 高频估计统计跳跃尾、期权估计风险中性尾，构造"投资者恐惧指数" | IS/OOS 混合 | A 股个股无足够期权数据 → 不可做；文献层记录 |
| N21 | Patton, Ziegel & Chen (2017/2019) *Dynamic semiparametric models for ES and VaR*，JoE；arXiv 1707.05108（71 p） | 利用 Fissler–Ziegel 联合可引出性建模 ES-VaR；4 国际指数 1990–2016 样本外优于 GARCH/滚动窗（§6） | OOS | 可做：WP5 尾部层草案的候选模型与**评分函数**（FZ 损失）；需新预登记 |
| N22 | Maillard, Roncalli & Teiletche (2010) *The properties of equally weighted risk contribution portfolios*，JPM（23 p） | ERC 波动率介于最小方差与 1/n 之间；全球分散组合 Table 6：1/n 最大回撤 −45.3%、MV −19.7%、ERC −22.7%（p.16） | IS | 可做：文献层"风险预算"记录；不可做：任何仓位规则进产品（需预登记且与泡沫信号无关） |

### 7.5 本批获取失败 / 未引用数值
Diks–Hommes–Wang 2019（Springer/Tinbergen 均返回 HTML 或超时）、Gençay–Gradojevic 2017（MDPI 403）、Pincus–Kalman 2004（PNAS/EuropePMC 403）、Thorp 2006 Kelly（404）、Phillips–Shi–Yu 2015 GSADF（Cowles/SMU 返回 HTML；仓库 R2 已实现 PSY 口径，题录见 `literature_review.md` P1）、Demos–Sornette 2017 *Birth or burst*、Forró–Woodard–Sornette 2015、Ardila–Forró–Sornette 2021、Sornette 等 2015 上海泡沫（arXiv 无）。以上**只作题录**，正文不引用其具体数值。上一批中 `zhou_sornette2005_fundamental…` 原为错误文件（自动交易系统论文），已替换为 physics/0505079；`geraskin_fantazzini2011_lppl_faq.pdf` 实为 Yan–Woodard–Sornette 2011，本批用 MPRA 47869 补齐。
