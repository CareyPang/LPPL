# 价格层文献综述：回撤幅度、止跌确认、二波、时间层能不能预测（2026-11-01）

目的：在动手做 B 卡（底部两层）与 W 卡（二波）之前，回答四个问题——

1. 顶后回撤幅度 / 回撤分位能否预测（需要具体价格吗？能给吗？）
2. 止跌确认有没有金融物理模型能提前给出，还是只能事后确认
3. 二波反弹的收复比例 / 具体价格能否预测
4. 时间层（t_c、顶 / 底时间区间）能否靠 LPPLS 之外的模型辅助提高精度

检索纪律：限速（每次请求间隔 ≥4 s）、限量（第一轮新下 16 篇全文 + 复用已有 10 篇，第二轮回撤幅度专项再下 13 篇；3 篇 SSRN/付费墙只到摘要级）。所有页码指 arXiv/工作论文 PDF 页码。与 `docs/literature_crash_bottom_echo.md`、`docs/literature_top_bottom_models.md` 已覆盖的内容只引用结论、不重复展开。

证据等级（本文沿用项目口径）：
`replicated_oos` 独立样本外复验 ｜ `replicated` 多案例但同一作者组/同一样本 ｜ `single_event` 单次事前预测 ｜ `descriptive` 只做了描述统计 ｜ `tested_here_fail` 本项目开发段/校准段已测失败 ｜ `research_candidate` 文献有依据、本项目未测 ｜ `abstract_only` 本次只核到摘要。

---

## 0. 一句话结论

| 问题 | 文献能给什么 | 文献不能给什么 | 对 B/W 卡的含义 |
|---|---|---|---|
| 回撤幅度 | **崩盘概率**随泡沫涨幅上升（GSY 2019，样本外复验）；信贷/杠杆 + 涨幅 → 危机概率 45% vs 7%（GHSS 2022）；回撤分布是拉伸指数 + 龙王离群（JS） | LPPLS 参数 → 回撤幅度：κ 不可识别，YWS 2010 的 κ 是事后算的；估值分位对深度无预测力；没有任何论文给出稳定的"顶→谷"价格预测 | B 卡"便宜层"只能是**条件经验分位 + n**（P1 已做）；条件变量优先级 杠杆 > 涨幅 > 估值；是否优于无条件分位需 Q-DD2 检验（未登记） |
| 止跌确认 | 停时规则（LT 15%）是正式确认层；熊市 hazard 随持续期上升（LT 2004）；负泡沫 LPPLS 在美股有样本外反弹时点技能（Yan 2010） | 底部**价格**；负泡沫在 A 股本项目 0/424；Omori 余震只描述衰减 | B 卡"确认层"只展示 LT 规则是否触发 + 滞后天数，不评价 |
| 二波 | MMS 2012：熊市反弹平均 ~半年、+7.1%，0.93 的牛市由熊市反弹过渡而来；二波顶可被 LPPLS 当短泡沫捕获（Jiang 2010） | 二波"收复比例"的预测；二波目标价 | W 卡 = 历史收复比例分位 + n（descriptive），状态概率为 Round 2 候选 |
| 时间层 | 分位回归 / 轮廓似然 t_c 区间（Zhang 2016、Filimonov 2017）；t_1 比 t_c 好定（Demos 2017） | 更精确的 t_c：LPPL sloppy（Brée 2013），波动率、Hawkes 都不给日频顶/底时间 | 不承诺精确日期；区间规则本项目已测弱于朴素窗，维持 `dev_only` |

**没有发现任何一个金融物理模型，能在独立样本外给出"具体价格"（回撤目标价、底部价、二波目标价）。** 唯一"价格锚 + LPPLS 时间"的正式范例是 Wheatley 等 2018 的 Bitcoin（Metcalfe 基本面值做支撑位，LPPLS 做时机），其基本面模型是加密货币特有的，股指只能用估值分位类比，且该文无样本外检验。

---

## 1. 回撤幅度 / 回撤分位

### 1.1 LPPLS 原模型不含幅度信息（全文已读）

- Johansen–Ledoit–Sornette 2000 *Crashes as critical points*（cond-mat/9810071 p6）：崩盘跌幅 κ 是"固定百分比"假设，只经 μ(t)=κh(t) 进入价格，解为 log p(t)/p(t0)=κ∫h。κ 与 hazard 的尺度**不可分离识别**——拟合得到的 B、C 等参数是 κ·h 的乘积。
- Johansen–Sornette 1999 *Critical crashes*（cond-mat/9901035 p3）："say between 20 and 30% of the price increase above a reference value p1"——这是**模型假设**，不是估计。同文 p5 表：六次崩盘实际跌幅 14%（DEM 1985）到 46.9%（1929）、46.2%（HK 1997），跨度 3 倍以上，与 β、ω 没有可见关系。
- Lin–Ren–Sornette 2009 波动约束 LPPL（0905.0128 p6）：引入 OU 残差后 κ 仍是外生常数；贝叶斯检验只说明超指数加速成立（p19），对幅度无增量。
- Sornette–Cauwels 2014（1404.2140 §3.6）明确区分"正/负泡沫"与"高/低估"：LPPLS 不说价值。

结论：**从 LPPLS 参数预测回撤幅度没有理论基础**。本项目 Q-DD（60 日最大回撤 90% 分位回归）不优于无条件分位，与此一致，维持 `tested_here_fail`。

### 1.2 泡沫涨幅 → 崩盘概率（不是幅度）

- Greenwood–Shleifer–You 2019 *Bubbles for Fama*（NBER w23191 p4、p15、p28、p21）。崩盘定义 = 两年内回撤 ≥40%。美国行业 1926–2014：两年超额涨幅 50% → 崩盘概率 20%；100% → 53%；150% → 80%。国际行业 1985–2014 作为**样本外**：36% → 50%。但 100% 信号 47% 误报，且正确识别的泡沫平均还再涨 6 个月。p21 定义 "acceleration"（两年涨幅中最后一年占比）与波动率、增发一起有预测力。→ `replicated_oos`，对象是**概率**而不是幅度。
- Goetzmann 2016 *Bubble investing*（NBER w21693 p2–3、p9）：全球市场 1900 起，翻倍后吐回全部涨幅的概率约 10%；次年再翻倍 8.33% > 次年减半 4.17%（后者是无条件的两倍）。→ 大涨后崩盘概率只略高于无条件；"涨幅大 → 一定跌得深"在全球面板上不成立。
- Sornette–Cauwels–Smilyanov 2018 *Can we use volatility…*（QFE 2(1) p1–2、p6）：40 个泡沫，崩盘前波动率无一致行为，约 2/3 在崩盘前反而**降低**。→ 淘汰"波动率升高 → 回撤加深"路线。

### 1.3 回撤分布形态

- Johansen–Sornette 2001/2003 回撤拉伸指数 + 龙王离群（已在 `literature_crash_bottom_echo.md` §2）；Sornette–Zhou 2006（cond-mat/0304601 §3）用模式识别预测 r0=10–15% 级别回撤："20% 以上回撤样本太少无法得出统计结论"。

### 1.4 对 B 卡"便宜层"的含义

- 可做：P1 回撤情景表（按泡沫涨幅/时长分桶的 20/50/80 分位 + n）、估值分位带。两者都是 `descriptive`，必须写"历史分位，不是预测"。
- GSY 的"涨幅 → 崩盘概率"可作为 Round 2 候选（`research_candidate`），预登记后在 A 股 + 外部市场上检验；它输出概率，不输出价格。
- 不做：任何从 LPPLS 参数（B、C、m、ω、t_c）回归回撤幅度的"预测器"。

### 1.5 专项追查（2026-11-01 第二轮）：有没有"哪怕不准、但比没有参照更好"的回撤幅度模型

用户追问后，专门检索"崩盘/熊市深度的条件变量"文献（新下 13 篇全文：NBER w27396/w8992/w14760/w21486/w25040/w7687/w25775、QJE Baron–Xiong、arXiv 1011.5343/cond-mat 0010050/0106520、JAE Kole–van Dijk、Weigand–Irons 2012）。结论分四层：

**(a) 唯一声称"LPPLS 扩展能给崩盘幅度"的论文，不是预测。** Yan–Woodard–Sornette 2010 *Inferring fundamental value and crash nonlinearity*（arXiv:1011.5343 p6–7、p11、p16–17）把崩盘幅度写成 κ(p−p1)^γ，p1 为拟合约束（p1>0.2·p_min）得到的"基本面价"。但文中 RC（崩盘幅度 / 高估部分）是用**事后实际回撤 DD** 算出来的，κ=RC 只对 γ=1 的模型按定义成立；三案例 RC：S&P 1987 0.34–0.40，SSEC 2009 0.23–0.45（不同模型相差 2 倍），HSI 1997 见其表 I。无样本外、无误差统计。→ `single_event / in_sample`，不能作为幅度预测器。

**(b) 有独立样本外证据的条件变量，对象都是"概率"而不是"幅度"：**
- 涨幅（GSY 2019，§1.2）；
- 信贷 + 涨幅：Greenwood–Hanson–Shleifer–Sørensen 2022（NBER w27396 p2、p4、p12、p17–18）42 国 1950–2016，3 年企业信贷增速前 1/5 且股价涨幅前 1/3 → 3 年内金融危机概率 45.3%（常态 7%），1 年 13%（常态 4%），有 1973 起滚动的真实时间样本外 R²；
- 银行信贷扩张：Baron–Xiong 2017 QJE（p1、p4、p30）20 国 1920–2012，信贷扩张超 95 分位 → 银行股指后 3 年超额收益 −37.3%（t=−2.5），probit 与分位回归一致。这是文献里**唯一给出条件均值回撤数字**的结果，但对象是银行股指、条件是宏观信贷，不是指数顶后回撤；
- 杠杆与衰退深度：Jordà–Schularick–Taylor 2015（NBER w21486 p5、p23–24、p29）1870–2013 17 国：股市泡沫若无信贷扩张对衰退深度"几乎没有影响"，伴随高信贷时衰退多 1 年、5 年累计 GDP −3.6%。对象是 GDP，但支持"杠杆是深度的条件变量、涨幅本身不是"；
- A 股杠杆：Bian–He–Shue–Zhou 2018（NBER w25040 p2、p4、p6–7）2015 账户级数据，接近平仓线的账户抛售 → 价格异常下跌**随后反转**，影子配资贡献更大；市值 7 月底前蒸发约 30%。单事件，但是 A 股"杠杆 → 跌幅 + 反弹"的直接证据；国内《统计研究》2016 用 VECM 发现融资余额与股指短期双向正反馈。

**(c) 估值作为深度条件变量：证据弱。** 从业者统计（S&P 1950–2020 按 CAPE 三分位分年）：次年回撤中位数与估值无关（都约 −10%），只有"便宜"组回撤范围更窄；CAPE 高于均值只预警 21 次 ≥10% 回撤中的 10 次。Weigand–Irons 2012（22 次美股熊市底 1881–2011）：底部 E10/P 显著扩张、1950 后估值底越来越高，且盈利收益率"不再可靠均值回归"。→ 估值分位只能做地板带参照，不能做深度预测变量。

**(d) 无条件参照已经很强。** Johansen–Sornette 2001（cond-mat/0010050 p2；cond-mat/0106520 p19）：约 98% 的回撤服从（拉伸）指数分布，Nasdaq >10%、DJIA >3–5% 的回撤属于另一分布（离群）；Barro–Ursúa 2009（NBER w14760 p6、p9）30 国 232 次 ≤−25% 多年累计崩盘，平均持续 3.2 年，每年进入概率 0.101，美国最深 1929–31 −55%。从业者两份牛→熊统计相互矛盾（BCA 2014：涨幅与随后跌幅无关甚至负相关；Ned Davis 类：弱牛后熊市均 <27%、强牛 10 次有 9 次 >27%），样本都只有 ~14 个。

**对"比没有参照更好"的回答：**
1. 最诚实的"更好"是**条件经验分位**（P1 已做），但它是否真的比无条件分位窄、覆盖率是否仍对，文献没有替我们回答——从业者证据相互矛盾，学术证据只到概率。
2. 文献支持的条件变量优先级：**杠杆/信贷（两融余额占流通市值、场外配资代理）> 涨幅与加速度 > 估值分位**。LPPLS 参数、波动率不在列。
3. 如果要测，正确的形式是 Q-DD2：对象为 PS 顶后顶→谷回撤（6–24 月），条件变量为对数涨幅、持续月数、两融余额/市值分位、估值分位；基线为无条件分位；指标为 pinball loss 与 80% 区间覆盖；A 股 + 外部四市场留一市场。n≈58 事件、尾部离群，预期只能在中位数附近有增量，80% 分位大概率无增量（JS 2001 的离群结论）。**按用户指示：先不登记，待进一步核实后再定。**
4. 即便通过，输出形式仍是"区间 + n + 条件说明"，不是目标价。

---

## 2. 止跌确认

### 2.1 停时规则是唯一"正式"的确认机制

- Lunde–Timmermann 2004（UCSD WP p3、p16、p19）：20/10 与 15/10 过滤。**熊市 hazard 在长持续期最高**（越久越可能结束），牛市相反；加息使熊市 hazard 大幅下降（更久下跌）。可作为"确认层"的时间先验说明，但它是 1885–1997 美股结果，A 股未测。→ `descriptive`。
- 该规则天然滞后（必须先涨 15–20% 才确认），在 `literature_crash_bottom_echo.md` §3 已评价。

### 2.2 负泡沫 LPPLS（金融物理的"止跌预警"）

- Yan–Woodard–Sornette 2010/2012（1003.5926 p10–13、p22、p26–28、p32）：负泡沫 + 模式识别预测 S&P 500 反弹（1950–2009，学习集 <1975-01-01，之后前瞻）。误差图优于随机；两组参数的策略成功率 66.2% / 65.8%（77 / 38 笔），持仓时间只占 15% / 5.2%，Sharpe 与 bias ratio 相对 1000 次随机策略 p 值小。给的是**反弹时点**概率，不给价格、不给反弹幅度。→ 美股 `replicated`（同作者组、单市场）；A 股本项目 0/424 → `tested_here_fail`。
- Zhou–Sornette 2004 中国反泡沫（cond-mat/0312149 摘要、§5 Fig.10）：用 2001-08→2003-10 数据预测"2003 年底止跌、6 个月内至少涨 25%"。核对：上证 2003-11 低点 1307 → 2004-04-07 高点 1783（+36%），短期反弹预测对；但真正熊市底在 2005-06-06 998 点。→ `single_event`，反弹对、熊市底错。Jiang 等 2010（0909.1007 §4）自己也强调"反泡沫外推 ≠ 崩盘预测"。
- Zhang–Zhang–Sornette 2016（PLoS ONE p22）：分位回归 LPPLS 在智利 1994 负泡沫、1998 反弹上给出 OLS 漏掉的信号。单案例、无统计。
- Shu–Zhu 2019（1905.09640）：CSI 300 2002–2018 的正/负泡沫**事后**识别，无前瞻误报统计 → `descriptive`。
- Fry–Cheah 2016（IRFA，`abstract_only`）：负泡沫与冲击模型用于 Bitcoin/Ripple，资产类别不同。

### 2.3 余震 / Hawkes

- Lillo–Mantegna 2003（cond-mat/0209685 p1–3）：崩盘后 |r|>4σ 超越次数按 Omori 幂律衰减，GARCH(1,1) 不能复现。描述余震衰减，不给底部价。本项目 B3 校准段不过。
- Filimonov–Sornette 2012（1201.3572 p3、p7、p16）：Hawkes 分枝比 n 测内生性，2010-05-06 闪崩前 n 异常——**高频、单事件**。Hardiman–Bercot–Bouchaud 2013（1302.1405 p1）：用幂律核重估，n≈1 在 1998–2011 始终接近临界，否定"内生性上升可预警"。→ Hawkes 对日频顶/底时间没有可用证据，不进入候选。

### 2.4 对 B 卡"确认层"的含义

- 可做：显示 LT 15% 规则当前是否触发、触发日、距最低点的滞后天数与涨幅；附"熊市已持续 N 月"的历史 hazard 分位（descriptive，美股来源需标注）。先只展示、不评价（用户指示）。
- 不做：负泡沫 LPPLS 做正式止跌报警（A 股开发段失败）；Omori/Hawkes 做底部时间预测。
- Round 2 候选：Yan 2010 的模式识别方案在外部四市场上按原版复现（`research_candidate`），通过才考虑 A 股分层。

---

## 3. 二波反弹

### 3.1 正式定义与统计

- Maheu–McCurdy–Song 2012 *Components of bull and bear markets*（JBES；bb.pdf p3–4、p11、p15、p17）：4 状态 Markov-switching，125 年美股周频。熊市反弹平均持续略超半年、累计收益均值 **+7.1%**（熊市下跌状态 −12.4%）；熊市平均 1.5 年、累计 −10%。**牛市开始前一状态是熊市反弹的概率 0.9342**（p15），即几乎所有熊转牛都经过"二波"状态；反弹可回到主熊市或转牛市。贝叶斯估计可给长周期累计收益预测密度。→ `replicated`（单市场、同作者），输出是**状态概率与收益密度**，不是收复比例也不是价格。此前文档中"待核对"的内容此处已核。
- Lunde–Timmermann 2004：熊市 hazard 随持续期上升——二波后"重返主跌"的概率随熊市年龄下降，可为 W 卡的"熊市已持续 N 月"注脚。

### 3.2 二波顶的可识别性

- Jiang 等 2010（0909.1007 摘要、§1）：2008-11→2009-08 的 A 股反弹作为短泡沫被 LPPLS 事前预测顶部窗口（Bastiaensen 等 2009）。→ 二波顶可复用现有顶部机制（本项目观察到 2009-08 短档有报警但 Round 1 标签漏掉，见 `literature_crash_bottom_echo.md` §0）。
- Forró–Woodard–Sornette 2015 PRE 91, 042803（`abstract_only`）：LPPLS 交易策略在多资产多期优于随机，属相变识别，不给二波目标价。
- Fantazzini 2010（SSRN，`abstract_only`）：熊市中泡沫/反泡沫中期交易，SSRN 403 未取全文。

### 3.3 对 W 卡的含义

- 可做：二波"收复比例 = 反弹高点收复首跌幅度的百分比"的历史分位 + n（A 股 + 外部四市场分层），`descriptive`；附 MMS 的"熊市反弹平均 +7.1%、半年"作为文献参照（标注美股）。
- Round 2 候选：按 MMS 2012 原版 4 状态模型在 A 股估计熊市反弹 → 牛市 / → 主熊市 的状态概率（`research_candidate`），只输出概率。
- 不做：二波目标价；用趋势/动量判断二波结束（只允许作对照基线）。

---

## 4. 时间层：能否借其他模型把 t_c / 顶底时间做精

- Brée–Challet–Peirano 2013（1006.2010 摘要）：LPPL 是 sloppy 模型，t_c 属于"几乎不影响残差"的参数方向；在复制 HSI 1987 的合成 AR(1) 数据上，发散时间的可预测性都是边界的。→ **精确日期在原理上不可承诺**。
- Demos–Sornette 2017（Quant. Fin.，`abstract_only`）：Hessian 分析显示泡沫起点 t_1 比终点 t_c 更容易约束。
- Filimonov–Demos–Sornette 2017（1602.08258）修正轮廓似然给 t_c 区间预测；Zhang–Zhang–Sornette 2016（PLoS p5、p8、p11）分位回归给 t_c 情景族（Quantile-Violin）与 DS Confidence/Trust。两者都是**区间 / 情景**方法。本项目 t_c 20–80% 分位窗覆盖率 1–4%、不优于朴素窗，T-INT 组已淘汰 → 维持 `dev_only`，可在 Round 2 测轮廓似然区间作为对照。
- 波动率（§1.2）、Hawkes（§2.3）均无日频顶/底时间证据。
- Sornette–Zhou 2006 模式识别（cond-mat/0304601 §3–4）：DJIA 三崩盘训练后泛化出 8 次大跌/变局，报警占时 <40% 覆盖全部 10–15% 回撤目标，HSI 独立复验"promising"。给"大变动将至"的概率，不给日期，不给幅度。

结论：**没有找到能把 t_c 做得更精确的辅助模型**；文献方向一致是"给区间/情景、不给点"。产品层维持"情景区间 + 证据等级"，不加精确日期。

---

## 5. 证据矩阵

| 方法 | 预测对象 | 文献等级 | 本项目状态 | 可进入 |
|---|---|---|---|---|
| P1 回撤情景表（涨幅/时长分桶分位） | 回撤分位 | descriptive | 已做（PR #16） | B 卡便宜层（标 descriptive + n） |
| 估值分位 / 地板带 | 价格带 | descriptive | 已做（上证/沪深300/中证500/上证50） | B 卡便宜层 |
| GSY 涨幅→崩盘概率 | 崩盘概率 | replicated_oos（美/国际行业） | 未测 | Round 2 预登记候选 |
| LPPLS 参数→回撤幅度 | 幅度 | 无理论基础（κ 不可识别） | Q-DD tested_here_fail | 不做 |
| YWS 2010 广义 JLS（p1 基本面 + κ） | 幅度 | single_event / in_sample（RC 事后算） | — | 不做 |
| 信贷/杠杆 + 涨幅 → 危机/崩盘概率（GHSS 2022、Baron–Xiong 2017） | 概率、银行股条件均值 | replicated_oos（宏观面板） | 未测 | Round 2 候选：两融余额/市值作 Q-DD2 条件变量 |
| 2015 杠杆平仓 → 跌幅与反转（Bian 等 2018） | A 股单事件机制 | single_event | — | 条件变量来源，不单独建模 |
| 估值分位 → 回撤深度 | 幅度 | 从业者统计否定；Weigand 2012 底部估值漂移 | 地板带已做 | 仅作地板带参照 |
| 无条件回撤分布（JS 2001、Barro–Ursúa 2009） | 分布 | descriptive | — | Q-DD2 的基线 |
| 波动率→回撤/崩盘 | 幅度/时间 | 40 泡沫否定 | — | 不做 |
| LT 15% 停时 | 止跌确认（事后） | descriptive（滞后） | 已在设计 | B 卡确认层（只展示） |
| LT 熊市 hazard 随持续期上升 | 止跌时间先验 | descriptive（美股） | 未测 | 注脚，标美股来源 |
| 负泡沫 LPPLS + 模式识别（Yan 2010） | 反弹时点 | replicated（美股） | A 股 0/424 tested_here_fail | Round 2 外部市场原版复现候选 |
| 反泡沫外推（Zhou–Sornette 2004） | 止跌时间+幅度 | single_event（反弹对、底错） | JS1999 规则 0/54 | 不做 |
| Omori 余震 | 余震衰减 | descriptive | B3 校准不过 | 不做 |
| Hawkes 分枝比 | 内生性 | 高频单事件；被 Hardiman 否定 | — | 不做 |
| MMS 2012 4 状态 MS | 二波状态概率、收益密度 | replicated（美股） | 未测 | W 卡文献参照；Round 2 候选 |
| 二波顶 = 短泡沫 LPPLS | 二波顶时间窗 | single_event（2009） | 短档当时有报警 | 已有顶部机制覆盖 |
| 分位回归 / 轮廓似然 t_c 区间 | t_c 区间 | replicated（同作者） | 分位窗 dev_only 弱于朴素 | Round 2 对照 |
| Metcalfe 价值 + LPPLS 时机（Wheatley 2018） | 价格锚 + 时机 | 单资产、无样本外 | — | 仅作"估值锚 + LPPLS"思路参照 |
| Gamma/加速度因子、趋势动量 | 收益 | 因子研究 | — | 只作对照基线（"原版没有不加"） |

---

## 6. 对下一步的建议（不实现、待用户裁定）

1. **B 卡便宜层**：直接用 P1 的回撤分位表 + 估值分位带，不新增模型。文案固定："历史分位，不是预测；n=…"。
2. **B 卡确认层**：只显示 LT 15% 规则状态（未确认 / 已确认于某日，距低点 N 日、+X%）。不显示任何"预计底部"。
3. **W 卡**：从 PS 标签顶后的首跌 → 反弹高点，算收复比例分位 + n（A 股单独 n<5 不显示，与 P1 口径一致），再写"熊市反弹文献参照（美股）：均值 +7.1%、约半年"。
4. **Round 2 预登记新增候选**（只登记，不上线）：GSY 涨幅→崩盘概率；Yan 2010 负泡沫原版在外部四市场复现；MMS 2012 4 状态在 A 股的状态概率；轮廓似然 t_c 区间 vs 朴素窗。
5. **明确不做**：LPPLS 参数回归回撤幅度；波动率预警；Hawkes/Omori 底部时间；二波目标价；精确顶/底日期；任何未经预登记的金融物理指标进正式报警。

---

## 来源

全文（~/lit/price、~/lit/pdf）：
- Johansen, Ledoit, Sornette (2000) Crashes as critical points. arXiv:cond-mat/9810071
- Johansen, Sornette (1999) Critical crashes. Risk 12(1). arXiv:cond-mat/9901035
- Yan, Woodard, Sornette (2012) Diagnosis and prediction of rebounds in financial markets. Physica A 391. arXiv:1003.5926（短版 1001.0265）
- Wheatley, Sornette, Huber, Reppen, Gantner (2018) Are Bitcoin bubbles predictable? arXiv:1803.05663
- Filimonov, Sornette (2012) Quantifying reflexivity… PRE 85. arXiv:1201.3572
- Hardiman, Bercot, Bouchaud (2013) Critical reflexivity… EPJB 86. arXiv:1302.1405
- Lillo, Mantegna (2003) Power-law relaxation… PRE 68. arXiv:cond-mat/0209685
- Lin, Ren, Sornette (2009/2014) A consistent model of 'explosive' financial bubbles. arXiv:0905.0128
- Lunde, Timmermann (2004) Duration dependence in stock prices. JBES 22(3). econweb.ucsd.edu/~atimmerm/dur-14-2.pdf
- Maheu, McCurdy, Song (2012) Components of bull and bear markets. JBES 30(3). maheu.azurewebsites.net/bb.pdf
- Sornette, Cauwels, Smilyanov (2018) Can we use volatility to diagnose financial bubbles? QFE 2(1):1–105
- Zhang, Zhang, Sornette (2016) Early warning signals… multi-scale quantile regressions of LPPLS. PLoS ONE 11(11)
- Greenwood, Shleifer, You (2019) Bubbles for Fama. NBER w23191
- Goetzmann (2016) Bubble investing: learning from history. NBER w21693
- Zhou, Sornette (2004) Antibubble and prediction of China's stock market and real-estate. Physica A 337. arXiv:cond-mat/0312149
- Jiang, Zhou, Sornette, Woodard, Bastiaensen, Cauwels (2010) Bubble diagnosis and prediction of the 2005–2007 and 2008–2009 Chinese stock market bubbles. JEBO 74. arXiv:0909.1007
- Sornette, Zhou (2006) Predictability of large future changes in major financial indices. Int. J. Forecasting 22. arXiv:cond-mat/0304601
- Filimonov, Demos, Sornette (2017) Modified profile likelihood inference and interval forecast of the burst of financial bubbles. Quant. Fin. arXiv:1602.08258
- Brée, Challet, Peirano (2013) Prediction accuracy and sloppiness of log-periodic functions. Quant. Fin. arXiv:1006.2010
- Sornette, Cauwels (2014) Financial bubbles: mechanisms and diagnostics. arXiv:1404.2140
- Shu, Zhu (2019) Real-time prediction of bitcoin bubble crashes / CSI 300 LPPLS. arXiv:1905.09640

- Yan, Woodard, Sornette (2010) Inferring fundamental value and crash nonlinearity from bubble calibration. arXiv:1011.5343
- Greenwood, Hanson, Shleifer, Sørensen (2022) Predictable financial crises. J. Finance. NBER w27396
- Baron, Xiong (2017) Credit expansion and neglected crash risk. QJE 132(2)
- Jordà, Schularick, Taylor (2015) Leveraged bubbles. J. Monetary Econ. NBER w21486
- Bian, He, Shue, Zhou (2018) Leverage-induced fire sales and stock market crashes. NBER w25040
- Mishkin, White (2002) U.S. stock market crashes and their aftermath. NBER w8992
- Barro, Ursúa (2009) Stock-market crashes and depressions. NBER w14760
- Chen, Hong, Stein (2001) Forecasting crashes: trading volume, past returns, and conditional skewness. JFE. NBER w7687
- Brunnermeier, Rother, Schnabel (2019) Asset price bubbles and systemic risk. NBER w25775
- Johansen, Sornette (2001) Large stock market price drawdowns are outliers. J. Risk. arXiv:cond-mat/0010050
- Johansen, Sornette (2001) Significance of log-periodic precursors to financial crashes. Quant. Fin. arXiv:cond-mat/0106520
- Kole, van Dijk (2017) How to identify and forecast bull and bear markets? JAE 32(1)
- Weigand, Irons (2012) The relative valuation of US equities at bear market bottoms. IMFI 9(2)

摘要级（未取到全文）：
- Forró, Woodard, Sornette (2015) Using trading strategies to detect phase transitions in financial markets. PRE 91, 042803
- Demos, Sornette (2017) Birth or burst of financial bubbles: which one is easier to diagnose? Quant. Fin. 17(5)
- Fantazzini (2010) Modelling bubbles and anti-bubbles in bear markets. SSRN
- Fry, Cheah (2016) Negative bubbles and shocks in cryptocurrency markets. IRFA 47
- Ardila, Forró, Sornette (2021) The acceleration effect and Gamma factor in asset pricing. Physica A
