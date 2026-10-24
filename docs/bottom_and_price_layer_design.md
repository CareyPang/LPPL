# 底部引擎、价格层拟合与金融物理模型：文献综述与设计方案（v1.5，2026-10-24 重写版）

本版替换同日上午的初稿。初稿只核了摘要；本版对核心文献下载了全文（限速、逐篇），引用标到节/表/页；无法取得全文的只引摘要并标明。证据等级：**[全文]** 读了全文并引具体节/表；**[摘要]** 只读到摘要（OpenAlex/arXiv/PLoS 接口）；**[出处已核]** 经 Crossref/OpenAlex 核实题名/期刊/年份，正文结论来自记忆。机构部分只引公开发表的方法。

本项目已有实测（均为开发段 2000–2018，不是样本外）：顶部阶梯 `reports/ladder_dev.md`；D-TOP 决策层 `reports/dtop_dev.md`；Q-DD `reports/qdd_dev.md`；**底部三重障碍标签事件数 `reports/bottom_label_events.md`**（本日新增）。

---

## 0. 结论先行

| 问题 | 结论 | 关键证据 |
|---|---|---|
| LPPLS 抄底为什么不准 | 机制不匹配而非数值问题。负泡沫 JLS 要求下跌**加速**且有对数周期结构；文献自己的验证是 S&P 500 59 年里 ±200 日定义的 19 个大底，策略成功率 66%、p 值 0.04–0.06（勉强显著）；A 股 2015/2018 底部是去杠杆/流动性事件，形态为余震衰减 | Yan–Woodard–Sornette 2010 **[全文]** §III.B（19 个反弹）、§V 表（77 笔交易 66.2%，p=0.055）；Bian 等 2018 **[摘要]**（强平后价格反转） |
| 底部用什么 | 五类"状态型"信号替代"奇点型"信号：**久期风险率**（熊市越久越可能结束）、**余震衰减**（Omori）、**流动性恢复**、**熊市×高波动状态**、**杠杆去化**；三重障碍标签已能区分有效底与半山腰（开发段指数 75 段、个股 1536 段，半山腰占候选底 8.0%/3.8%） | Lunde–Timmermann 2004 **[摘要]**；Petersen 等 2010、Lillo–Mantegna 2003 **[全文]**；Donier–Bouchaud 2015 **[全文]**；Cooper–Gutierrez–Hameed 2004 **[摘要]**；`reports/bottom_label_events.md` |
| 价格层还能怎么优 | 优化器不是瓶颈（合成数据全局极小 96%）；能做的是让 **t_c 区间**更诚实（MPL，已登记 v1.5），窗口选择（Lagrange，暂缓），噪声模型（GARCH 残差 bootstrap）。Deep LPPLS 只提速 | `reports/phase3b_summary.md`；Filimonov–Demos–Sornette 2017 **[摘要]**；Deep LPPLS 2024 **[摘要]** |
| 金融物理哪些可用 | 可日频标定且有样本外或大样本证据：LPPLS 置信度（顶部）、Omori 余震、回撤/龙王统计。**临界慢化证据为负**（五大指数百年无 CSD，只有方差上升）；Hawkes 需高频且两组研究结论相反；**Ising/agent-based 不可标定，只作机制解释** | Guttal 等 2016 **[全文]** 图 2/表 1；Diks–Hommes–Wang 2018 **[摘要]**；Filimonov–Sornette 2012 vs Hardiman 等 2013 **[摘要]** |
| 华尔街公开做法 | 没有公开的"抄底模型"。公开方法都是**状态→仓位**：波动率管理（高波动减仓、波动回落加仓）、动量在熊市后的崩盘/反转管理、牛熊状态切换、回撤控制 | Moreira–Muir 2017 **[摘要]**；Daniel–Moskowitz 2016 **[出处已核]**；Cooper 等 2004 **[摘要]**；Grossman–Zhou 1993 **[出处已核]** |
| 已有实测给的教训 | 顶部侧：概率阈值规则在 2015 年以外≈随机，无模型基线（波动率目标、跟踪止损）最强；Q-DD 预测"跌多深"不如无条件分位。底部侧设计必须**先放强基线**，候选不胜过它就不进产品 | `reports/dtop_dev.md`、`reports/qdd_dev.md` |

---

## 1. 诊断：LPPLS 抄底为什么不准（证据链）

### 1.1 文献自己的验证强度
Yan–Woodard–Sornette 2010 **[全文]**（arXiv:1003.5926）：
- 反弹定义：某日价格是前后各 200 日窗口的最低价（式 16，§III.B）；S&P 500 59 年只有 **19 个**这样的底；另给 ±365 日定义的结果。
- 方法：11,662 个 LPPLS 拟合中筛出 2,568 个"负泡沫拟合"，用模式识别（多时点投票）构造"反弹警报指数"；预测窗口 41 日（§IV，步骤 4："最长 20 日"）。
- 结果（§V 表）：策略 I 77 笔交易成功率 66.2%，累计超额对数收益 67%，**p 值 0.055**；夏普 p 值 0.043；策略 II 38 笔，p 值 0.058/0.036。错误图优于随机线 y=1−x（图 5–6）。
- 结论："negative bubbles are in general predictably associated with large rebounds"。
- **解读**：这是有信息但弱（p≈0.05、19 个事件、回溯学习）的证据，而且对象是美股长期底，不是 A 股 60 日尺度的止跌判断。

反泡沫 LPPL（Johansen–Sornette 1999；Zhou–Sornette 2003 **[摘要]**）描述的是熊市中段减速的对数周期震荡，用于回溯解释 2000–02 五次中间崩盘，不是底部预测器。

### 1.2 本项目的证据
- 原型 B3（−ln P 做 LPPLS）在用户经历中"抄在半山腰"（`docs/bottom_design_v13_draft.md` §1）。
- 三重障碍标签统计（`reports/bottom_label_events.md`）：开发段候选底中**到期未触达（既不涨 10%+ 也不再跌 5%+）占 78%**（指数 563/724），有效底 14%，半山腰 8%。含义：A 股大多数"看起来像底"的点既不是底也不是半山腰，而是**横盘**——任何只判"止跌"不判"随后能涨"的模型都会被这 78% 淹没。底部模型的主要任务其实是区分"有效底 vs 横盘"，其次才是"vs 半山腰"。

### 1.3 A 股底部的形成机制
- **杠杆**：Bian–He–Shue–Zhou 2018 **[摘要]**（NBER w25040）用账户级数据证明 2015 年崩盘中融资账户在逼近杠杆上限时大量卖出，被重仓的股票"出现异常下跌**随后反转**"——即强平完成后价格反弹。Hansman–Hong–Jiang–Liu–Meng 2018 **[摘要]**（NBER w24586）记录 2010–2015 融资扩张对价格的推升。→ 融资余额下降的**减速**是底部候选（2010 起子样本）。
- **流动性**：Donier–Bouchaud 2015 **[全文]** §4–5：三种"买方稀缺度"度量高度相关并"correctly predict the amplitude of potential crashes"；崩盘"因为价格太高且买家太少"。→ 买方恢复（成交额萎缩后回升、Amihud 非流动性回落）是止跌的微观结构条件。
- **余震**：Lillo–Mantegna 2003 **[全文]** §II：崩盘后 1 分钟收益超阈次数按 Omori 律衰减，p=0.85，对 5σ–7σ 阈值稳健；GARCH(1,1) 不能复现；崩盘后 VaR 按幂律演化（§IV）。Petersen 等 2010 **[全文]**：219 次市场冲击、531 只美股，市场级 Ω_a=0.32±0.01（冲击后）vs Ω_b=0.09（冲击前）；个股级 Ω_a=0.09±0.07。→ 余震率回到基准 = 市场消化完冲击。这些是高频结果，**日频版本需要本项目自己验证**（B3）。

---

## 2. 底部/反弹模型证据表（按预期价值排序）

| # | 模型 | 证据等级 | 文献结果（原文数字） | 日频可标定 | A 股数据 | 本项目候选 | 预期 |
|---|---|---|---|---|---|---|---|
| 1 | 熊市久期风险率 | Lunde–Timmermann 2004 **[摘要]**（JBES）；Pagan–Sossounov 2003 **[摘要]**（JAE） | "the longer a bear market has lasted, the higher is its termination probability"；利率也影响风险率 | 是 | 2000 起 | **B1**：回撤深度 PIT 分位、自峰值天数、20/60 日收益、波动率 | 中高；最便宜的强基线 |
| 2 | 熊市反弹作为独立状态 | Maheu–McCurdy–Song 2012 **[摘要]** | 四状态模型显式给出"熊市反弹→牛市 vs 回到熊市"的转移概率 | 是（月频估计为主） | 2000 起 | B1 附加：60 日内反弹次数（"半山腰"计数） | 中 |
| 3 | Omori 余震衰减 | Lillo–Mantegna 2003、Petersen 等 2010 **[全文]** | p=0.85（1 分钟）；Ω_a=0.32 市场级 | 是（日频超阈计数，需自验） | 2000 起 | **B3**：主震后 20 日余震率/基准率、Omori 指数、距主震天数 | 中高 |
| 4 | 流动性恢复 | Donier–Bouchaud 2015 **[全文]**；Amihud 2002 **[出处已核]**（JFM，引用 1 万+） | 买方稀缺度预测崩盘幅度 | 是 | 指数 amount 为空→用 volume×close | **B2**：Amihud 相对值、成交额 20/250 比值及其 5 日变化 | 中 |
| 5 | 熊市×高波动状态 | Cooper–Gutierrez–Hameed 2004 **[摘要]**（JF）：1929–1995 上涨市后动量月均 0.93%，下跌市后为负；Daniel–Moskowitz 2016 **[出处已核]**；Moreira–Muir 2017 **[摘要]** | 市场状态决定动量/反转；高波动期减仓产生 alpha | 是 | 2000 起 | **B4**：24 月收益<0 × rv20 分位 | 中 |
| 6 | 杠杆去化 | Bian 等 2018、Hansman 等 2018 **[摘要]** | 强平后价格反转 | 是 | 2010-03-31 起（沪深均有） | **B5**（子样本） | 中；覆盖短 |
| 7 | 长期反转 | De Bondt–Thaler 1985 **[摘要]**（JF）：输家组合 3–5 年后显著反弹；Moskowitz–Ooi–Pedersen 2012 **[摘要]**：1–12 月持续、更长期反转 | 横截面/长期 | 月频 | 2000 起 | 并入 B1（ret250/500） | 低—中 |
| 8 | 负泡沫 JLS | Yan 等 2010 **[全文]** | 66% 成功率，p≈0.05 | 是 | 需 −ln P 扫描 | **B6** | 低 |
| 9 | 原型反泡沫/支撑井 | 原型代码 | 无 | 是 | — | **B7** | 低；对照 |
| 10 | 临界慢化 | Guttal 等 2016 **[全文]**；Diks 等 2018 **[摘要]** | 五大指数百年崩盘前 **无** CSD；方差/低频功率 16 次越阈中 4 次对应 1929/1987/2000/2008；Diks：仅 1987 有证据 | 是 | 2000 起 | **B8**（R7 同款） | 低 |
| 11 | 情绪指数 | Baker–Wurgler 2006 **[全文]**；Huang–Jiang–Tu–Zhou 2015 **[摘要]**（RFS） | 低情绪后小盘/高波动股收益高；对齐情绪指数样本外显著 | 月频 | A 股代理（换手、新开户 2015 起、折价）覆盖不足 | 不进阶梯，描述性 | — |
| 12 | 估值比率 | Campbell–Shiller 2001 **[全文]**（NBER w8221）；Rapach–Strauss–Zhou 2010 **[摘要]** | 估值比率预测长期收益；单变量样本外弱，组合预测才稳健 | 月频 | 全市场 PE/PB 2005 起 | 不进阶梯，描述性 | — |
| 13 | Hawkes 分支比 | Filimonov–Sornette 2012 vs Hardiman 等 2013 **[摘要]** | 结论相反 | 否 | 无高频 | 不用 | — |
| 14 | Ising/agent-based | Sornette–Zhou 2006 等 **[出处已核]** | 机制解释 | 否 | — | 不用 | — |

---

## 3. 机构公开做法（只引公开来源）

| 做法 | 出处 | 原文要点 | 对本项目 |
|---|---|---|---|
| 波动率管理 | Moreira–Muir 2017 JF **[摘要]** | "Managed portfolios that take less risk when volatility is high produce large alphas, increase Sharpe ratios" | D-BOT 基线：波动回落自动加仓；D-TOP 已证它胜过所有概率阈值规则 |
| 市场状态与动量 | Cooper–Gutierrez–Hameed 2004 **[摘要]**；Daniel–Moskowitz 2016 | 下跌市后动量为负（输家反弹）；熊市+高波动是动量崩盘高发区 | B4 状态特征 |
| 牛熊状态模型 | Lunde–Timmermann 2004；Maheu–McCurdy–Song 2012；Pagan–Sossounov 2003 **[摘要]** | 久期风险率、熊市反弹转移概率 | B1 与底部区间 B-INT |
| 组合预测 | Rapach–Strauss–Zhou 2010 **[摘要]** | 单一预测变量样本外失效，组合预测稳健 | 底部状态概率用逻辑回归叠加多类特征，而非单指标阈值 |
| 回撤控制 | Grossman–Zhou 1993 **[出处已核]** | 距回撤限额越近仓位越低 | 跟踪止损基线（prereg §14.4） |
| 三重障碍/元标签 | López de Prado 2018 | — | 已采用 |

**明确不存在的东西**：任何机构"抄底指标"的内部参数与实盘记录。

---

## 4. 金融物理模型可用性

| 模型族 | 证据 | 日频 | 判定 |
|---|---|---|---|
| LPPLS/JLS 多窗口置信度 | 顶部有本项目开发段证据；底部 p≈0.05 | 是 | 顶部 R3/R4；底部 B6 对照 |
| Omori 余震 | 高频强证据，日频待验 | 是 | B3 |
| 回撤统计/龙王 | Johansen–Sornette 2001 **[摘要]**：98% 回撤服从拉伸指数，最大者为离群 | 是 | B1 的分布假设；Q-DD 底部版基线 |
| 临界慢化 | **负面**（Guttal 2016 全文） | 是 | B8 保留但预期弱 |
| Hawkes | 争议 + 需高频 | 否 | 不用 |
| MF-DFA | 描述性 | 长窗 | 不单列 |
| Ising/agent-based | 不可标定 | 否 | 不用 |

---

## 5. 价格层拟合（顶部/底部 LPPLS 共用）

| 改进 | 出处 | 改什么 | 预期 | 验证 | 状态 |
|---|---|---|---|---|---|
| MPL 修正剖面似然 | Filimonov–Demos–Sornette 2017 **[摘要]** | t_c 剖面加 nuisance 参数曲率校正 | 覆盖率从 76%（未校正）接近 bootstrap 87.5%，算力 1/50 | 合成 AR(1)/GARCH 覆盖率 ≥ 85% | **已登记 v1.5** |
| Lagrange 正则选窗 | Demos–Sornette 2017 **[摘要]** | 内生选最优窗口起点 | 不确定；需重扫 | 开发段 R4 变体 | 暂缓（待 R3/R4 结果） |
| GARCH 残差 bootstrap | Lillo–Mantegna 指出崩盘后 GARCH 不足；泡沫期仍优于 iid | 残差滤波后块 bootstrap | 区间更真 | 合成覆盖率 | 低优先 |
| t_c < t₂ 搜索 | Zhang–Zhang–Sornette 2016 [全文，见 literature_review] | 扩搜索域 | 更早捕捉 | R4 变体 | 低 |
| Deep LPPLS | 2024 **[摘要]** | NN 一次性估 (t_c,m,ω) | 只提速 | 合成一致性 | 算力门触发时再议 |

---

## 6. 底部引擎 v1.5（已登记 prereg §15，B0–B8）

### 6.1 标签（不变）与实测事件数
三重障碍（`research/labels/bottom.py`）。开发段：指数 6 个标的 75 事件段，个股 300 只 1536 段（门槛 30 通过）；候选底结局：有效 14% / 半山腰 8% / 到期 78%（指数）。敏感性：下障碍 33% 时半山腰升至 18%，67% 时降至 4%——阈值直接决定"半山腰"的定义宽严（`reports/bottom_label_events.md`）。

### 6.2 阶梯（实现于 `research/eval/ladder_bottom.py`，正在开发段运行）
B0 基率 → B1 回撤/久期（2 配置）→ B2 流动性（2）→ B3 Omori 2σ/2.5σ（2）→ B4 熊市高波动状态（1）→ [B5 杠杆去化：2010 起子样本单独阶梯] → [B6 负泡沫、B7 反泡沫：待 −ln P 扫描] → B7 支撑井（1）→ B8 统计物理（3）；× C∈{0.1,1} × 滚动 z 变体。主链/次要链双规则与顶部一致。

### 6.3 底部区间与"跌到哪"
区间 B-INT：以 B1 久期风险率 + B3 余震衰减预测时刻给中心与宽度，校准段保形缩放；基线 = 无条件熊市久期分位。"跌到哪"：Q-DD 底部版，目标为自峰值最终回撤；**顶部 Q-DD 开发段两组配置都不如无条件分位（Δpinball +0.0020，覆盖 82.7%）**，底部版预期同样困难。

### 6.4 决策层 D-BOT 与基线
基线：买入持有、波动率目标、固定日期分批、**跟踪止损反向版**（收复 60 日高点 10% 后加仓）。候选：止跌状态概率驱动分批 + 二波 50% 收复位减半 + 移动止盈。主评分：进场后 60 日假底率与费后收益。

### 6.5 产品表达
全部失败 → 只给回撤分位、熊市久期描述统计与波动率目标的加仓节奏；部分通过 → "止跌状态概率等级 + 见底时间区间 + 历史假底率"；永不给具体日期。

## 7. 不做的事
Hawkes、Ising、月频宏观牛熊指标进阶梯、再比较优化器、具体日期。

## 8. 文献清单与核实状态
全文（本地 PDF，限速下载）：Yan–Woodard–Sornette 2010 arXiv:1003.5926；Petersen–Wang–Havlin–Stanley 2010 arXiv:1006.1882；Lillo–Mantegna 2003 arXiv:cond-mat/0209685；Donier–Bouchaud 2015 arXiv:1503.06704；Guttal 等 2016 PLoS ONE doi:10.1371/journal.pone.0144198；Baker–Wurgler 2004 NBER w10449；Campbell–Shiller 2001 NBER w8221；Guo 2003 St. Louis Fed WP 2002-008（样本外可预测性）。
摘要（OpenAlex/arXiv/PLoS）：Lunde–Timmermann 2004 JBES；Maheu–McCurdy–Song 2012；Cooper–Gutierrez–Hameed 2004 JF doi:10.1111/j.1540-6261.2004.00665.x；Moreira–Muir 2017 JF；Bian–He–Shue–Zhou 2018 NBER w25040；Hansman 等 2018 NBER w24586；Huang–Jiang–Tu–Zhou 2015 RFS doi:10.1093/rfs/hhu080；Rapach–Strauss–Zhou 2010 RFS；Pagan–Sossounov 2003 JAE doi:10.1002/jae.664；Demos–Sornette 2017 QF doi:10.1080/14697688.2016.1231417；Diks–Hommes–Wang 2018 Emp. Econ. doi:10.1007/s00181-018-1527-3；Moskowitz–Ooi–Pedersen 2012 JFE；De Bondt–Thaler 1985 JF；Johansen–Sornette 1999/2001、Zhou–Sornette 2003、Filimonov–Sornette 2012、Hardiman 等 2013、Filimonov–Demos–Sornette 2017、Deep LPPLS 2024（arXiv）。
出处已核（Crossref）、内容据记忆：Amihud 2002 JFM；Daniel–Moskowitz 2016 JFE；Grossman–Zhou 1993 MF；Ang–Bekaert 2002 RFS；Sornette–Zhou 2006。
接口限制记录：Semantic Scholar 全天 429；arXiv 搜索 API 间歇 429（PDF 直链正常）；OpenAlex 20 次后 429；SSRN 403。后续查询一律限速（≥3 s/次）并分批。
