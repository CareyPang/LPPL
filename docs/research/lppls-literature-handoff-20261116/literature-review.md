<!-- Public documentation adaptation; original report content hash is in provenance.json. -->

RESEARCH REVIEW · 2026-11-16 · READ-ONLY

# LPPLS：哪些研究值得进入你的框架？

优先修正可识别性、时间窗与验证方式；把深度学习放在校准加速的候选位置。现有文献与 GitHub 示例，不能把“形状拟合得好”直接升级为“至少提前五天、准确定位十天内的阶段顶”。

对照对象：长期记忆及本地交接文档中的 V2588 / DCTE、V4.8-R2 Time、PPE-U2-R5.1 Price；最新用户约束为完整振荡周期 1.5、局部顶与阶段顶分别评分、不用跌幅定义顶部成功。本文不是 CareyPang/LPPL 最新代码完整审计。

**决策：**保留现有研究主线，暂不迁入 DS-LPPLS；优先做统一单位、逐日预测账本、相关残差下的不确定性和全流程假阳性验证。P-LNN 可以成为候选初值生成器，不能直接充当顶部报警器。价格层与底部层继续独立验证。

**GitHub 交接更新：**本报告为文献研究快照。随后核对的 [PR #99](https://github.com/CareyPang/LPPL/pull/99) 作者报告 F2/F3/F4 合成门未通过，未由本轮独立复现。执行优先级以 [交接入口](README.md) 与 [任务单](DEVIN_TASKS.md) 为准：先统一口径，W1先比较固定稀疏窗口；Lagrange/GLS/profile候选不绕过失败门。不要把旧文献建议解释成当前已通过或生产配置。

## 01 · 证据范围与阅读边界

**[VERIFIED]** 本次读取用户指定论文正文与附录，核对其图表；静态阅读指定仓库的拟合、过滤、bootstrap、聚类与图表链路，并沿参考文献和后续引用检索稳定校准、分位数回归、profile likelihood、窗口选择、负泡沫、前瞻试验和反向研究。

不能声称已经搜尽、读完所有 LPPL/LPPLS 文献。文末逐条列出“全文方法阅读”“关键章节”“摘要/元数据”等深度；受限全文不补造内容。论文的成功实验一律属于作者报告，本轮没有运行拟合、训练网络、重现统计结果或验证收益。

| 标签 | 本文含义 |
| --- | --- |
| VERIFIED | 已核对的文本、数学恒等式、静态代码或文档事实；不自动代表预测有效。 |
| 论文作者报告 / PR 作者报告 | 原作者声称的效果或性能；未由本轮独立重现。 |
| NOT_ESTABLISHED | 当前证据不能确立该能力、概率或泛化结论。 |
| NOT_RUN / NOT_INSPECTED | 本轮没有运行实验 / 未取得或检查对应材料。 |
| 研究建议 | 本报告提出的设计，必须通过预先冻结的检验，不是已经实现或有效。 |

交叉对照的本地原始文件：`V2588完整项目交接_HANDOFF.md`、`V2588历史研究证据报告.md`。这些历史文档帮助恢复方法和失败记录；它们不证明当前仓库已实现全部设计。本轮也未恢复 XAU/XAG、纳指、KOSPI 当年真实发布的原始预测包。

## 02 · 先把模型、事件与收益分开

**[VERIFIED]** 在标准未来临界点任务中，令 `τ=t_c−t>0`。Filimonov–Sornette 重参数化把四个线性系数与三个非线性参数分开，使校准更容易控制。

y(t)=ln P(t)=A+Bτ<sup>m</sup>+C₁τ<sup>m</sup>cos(ω ln τ)+C₂τ<sup>m</sup>sin(ω ln τ)<br>θ=(t<sub>c</sub>,m,ω)，β=(A,B,C₁,C₂)<br>Q(θ)=min<sub>β</sub> ‖y−X(θ)β‖²

依据：[Filimonov & Sornette，2013](https://arxiv.org/abs/1108.0099)。建议实现用 QR/SVD 或稳定的最小二乘求解，避免显式求逆；“在合适数据上目标函数更平滑”不能推广为每条金融序列必有唯一全局解。

需要区分四层问题：①曲线是否呈现 LPPLS 结构；②在这类结构假设下，参数 t<sub>c</sub>在哪里；③真实市场是否会在该时间附近形成所定义的顶部；④行动能否改善风险或收益。前三层之间也需要验证，不能直接从参数密度跳到交易建议。

VERIFIEDJLS 理论中的临界时间与泡沫结束风险相关，不等于一个确定的崩盘预约日。对 0<m<1，模型的 log-price 在 t<sub>c</sub>处趋向 A，而其变化速度可能出现奇异行为。**[NOT_ESTABLISHED]** 由此不能推得崩盘幅度或崩盘后的最低价。[JLS 原文](https://arxiv.org/abs/cond-mat/9810071)

**对现有框架的直接要求：**未来预测只接受 `t_c>asof` 的定义；绝对值延拓 `|t_c−t|`、截断 τ、样本内部临界点属于另一模型/诊断任务。可以研究，但必须另设 model_id 和评分，不得用已发生的 t<sub>c</sub>计作提前命中。

### 参数与时间尺度：保留方法身份

历史交接的严格研究过滤包括 m∈(0.1,0.9)、ω∈(6,13)、方向约束、damping与拟合质量门槛；这些是历史经验规则，不是理论定理。周期门槛已按最新用户指示改为1.5完整周期研究基线。旧窗口族约为短60–225、中250–700、长750–2250、超长2500–7000/全历史观测；它们仅定义回看长度，不能代替顶部等级标签。旧主预测域不超过90个有效观测步的限制也必须记录，不能暗中改成更窄日期域。

相对地，DS-LPPLS 的搜索范围约为 m∈[0,2]、ω∈[1,50]、t_c∈[0.95n,1.05n]。搜索域、后过滤域与时间轴均不同，直接比较最终图形或运行分钟数没有可比性。建议保存 search_bounds、filter_bounds、clock、lookback、forecast_horizon 与规则版本，而不是只记录“使用LPPLS”。

## 03 · 文献主线：各自解决什么，不解决什么

| 文献方向 | 可靠的用途 | 对你的框架的安排 | 不能直接推出 |
| --- | --- | --- | --- |
| [稳定校准，2013](https://arxiv.org/abs/1108.0099) | 降低非线性维度 | 保留为 Time 求解基础；比较求解器时统一目标函数 | 最低拟合误差＝最佳顶部预警 |
| [多尺度分位数回归，2016](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0165819) | 检查结论对价格路径不同部分的敏感性 | 中位数/分位数作为稳健性对照；Confidence 与 Trust 分开存 | 窗口通过比例＝见顶概率 |
| [Modified profile likelihood，2016/2017](https://arxiv.org/abs/1602.08258) | 显式处理其他参数对 t_c 不确定性的影响 | 保留多情景及边界诊断；用模拟检查区间覆盖 | profile likelihood 归一化后就是事件后验概率 |
| [Lagrange 窗口正则化，2017](https://arxiv.org/abs/1707.07162) | 减少短窗天然更容易拟合造成的起点偏好 | 作为“选窗”单项对照，不和聚类同时改 | 正则化选出的起点就是真实泡沫起点 |
| [比特币多尺度 t_c 聚类，2018/2019](https://arxiv.org/abs/1804.06261) | 组织不同窗口的候选时间 | 逐 asof 聚类、去重、跨日追踪；重新验证事件定义 | 密集峰等于经过校准的概率 |
| [沪深300 Confidence，2019/2020](https://arxiv.org/abs/1905.09640) | A股指数的历史检测实例与过滤模板 | 可做复现支线，尤其核对振荡数、残差检验 | 已证明对所有个股提前五天精准逃顶 |
| [负泡沫/反弹，2010/2011](https://arxiv.org/abs/1003.5926) | 研究加速下跌结束 | 独立底部标签、负样本与阈值 | 把上涨模型翻号就获得准确抄底系统 |
| [Financial Bubble Experiment](https://arxiv.org/abs/1011.2882) | 事前封存预测、事后公开核验的流程 | 优先借鉴不可改写的首次可见记录 | 其个案成功率可直接搬到新网站 |
| [参数 sloppiness，2010/2013](https://arxiv.org/abs/1006.2010) | 解释低误差与参数不稳定可以并存 | 同时检查 loss、参数变化与日期漂移 | 一条漂亮拟合曲线能证明 t_c 精确 |
| [Deep LPPLS，2024](https://arxiv.org/abs/2405.12803v1) | 学习型参数估计 | P-LNN 暖启动候选；保留独立搜索与拒绝机制 | 毫秒参数推理＝毫秒完成可靠预警 |
| [G-LPPLS-NN，2024](https://doi.org/10.1016/j.econlet.2024.112003) | 临界时间和临界价格扩展方向 | 列为探索项，先做基线增量验证 | 临界价格＝泡沫破裂后的低点 |
| [Log-periodicity: Fact or fiction?，2026](https://doi.org/10.1016/j.irfa.2025.104848) | 质疑特定拟合后残差检验的显著性解释 | 将整个搜索/过滤/筛选链纳入零假设模拟 | 一篇反向研究已否定所有 LPPLS 方法 |

上表“安排”是本报告的研究建议。原论文中的应用结果属于作者报告，不代表本轮复现；详细阅读边界见书目。

## 04 · 用户指定的 Deep LPPLS：速度来自哪里？

VERIFIED[Nielsen、Sornette、Raissi（2024）](https://arxiv.org/html/2405.12803v1)提出两种校准器：M-LNN 对每条序列另行训练；P-LNN 预先用合成 LPPLS 序列训练，再估计固定长度输入的非线性参数。本文版本的 P-LNN 使用 252 点输入，合成噪声包含白噪声与 AR(1)。

| 论文表2：平均耗时 | 数值 | 证据状态 |
| --- | --- | --- |
| LM | 3.5795 秒 | 作者实验报告 |
| M-LNN | 11.5002 秒 | 作者实验报告 |
| P-LNN | 约 0.005 秒 | 作者实验报告，仅参数估计 |

这些数字未计网站排队、行情下载、全部窗口、不确定性重拟合和预训练总成本。金融实例为历史纳指与白银 ETF；纳指示例的“临界区间”覆盖从峰值到后续回撤低点的一段时期，不是你要求的狭窄顶部日期标签。本轮已核对原文图4/5及表2。**[NOT_ESTABLISHED]** 本轮没有找到可确认为作者官方发布、且与论文一一对应的完整代码和权重。

补充范围差异：论文 M-LNN 的归一化 t_c 软约束为 [0.8,1.2]，并非严格 future-only；原文没有充分说明样本内 t_c 的数值处理，不能替作者假设绝对值延拓。合成训练和测试属于同类生成机制，少数历史金融案例也不是全市场前瞻误报/漏报验证。

### 原文之外，对你的项目最有价值的推论

**可以把神经网络当初值生成器。**对同一窗口输出若干 θ 候选，再送入原来的 FS 目标函数精修和质量检查。需要保留一部分独立随机/网格初值，否则网络可能把所有窗口推入同一个训练先验偏好的局部解。这是提速方案，不是已经证实更准的模型。

**先问“有没有事件”，再问“哪一天”。**仅做参数回归的网络通常会对无泡沫输入也给一个 t_c。上线前必须提供域外/不支持状态；拒绝阈值由无泡沫对照与真实事件评价确定。不能把“总能吐出一个日期”当成产品完整性。

**252 点不是万能标准。**窗口的交易时钟、真实跨度、归一化、停牌与缺失处理必须一致。把不同长度时间序列插值为 252 点会改变可见振荡与噪声结构；若这么做，应把跨度和映射规则冻结，并重新生成相匹配的训练数据。

**误差需要分两张成绩单。**合成数据上的参数 RMSE/覆盖率说明能否恢复已知参数；逐日真实市场上的阶段顶漏报、误报和提前量说明有没有用。前者提高不保证后者提高。

### 相关第三方实现也不能直接当论文复现

静态核对[mvs-86/lppls_py，固定提交 a81f4f6](https://github.com/mvs-86/lppls_py/tree/a81f4f685e1874810f912246f439f644845cf394)存在输入/时间映射需要另验的问题：合成数据归一化后再加噪，与真实输入归一化顺序有差异；推理将固定轴映射到起止自然日；不同实现对非正 τ 分别截断或拒绝。它不应作为“作者官方权重”使用。[推理代码](https://github.com/mvs-86/lppls_py/blob/a81f4f685e1874810f912246f439f644845cf394/lppls/inference.py)、[M-LNN代码](https://github.com/mvs-86/lppls_py/blob/a81f4f685e1874810f912246f439f644845cf394/lppls/mlnn.py)

## 05 · DS-LPPLS：适合研究代码问题，不适合直接迁入

**[VERIFIED]** 审查固定提交 `d6eb89a40afca7024a245bf204d88d5649814b41`。这是传统拟合/过滤/图表项目，与上面的 Deep LPPLS 神经网络论文不是同一实现。主拟合对七个参数联合做 L-BFGS-B，并尝试正序、反序及组合初值；不是现有框架的 FS 三参数消元流程。

| 位置与已见行为 | 影响判断 | 接入前必须做什么 |
| --- | --- | --- |
| [filter_model.py 振荡数](https://github.com/ImanNasrEsfahani/DS-LPPLS/blob/d6eb89a40afca7024a245bf204d88d5649814b41/filter_model.py#L136)：存在正确完整周期函数，但主过滤使用 ω/2×ln 比值 | 数字 2.5 实际约为 0.796 完整周期，不能与当前 1.5 直接比较 | 所有规则保存公式与单位；旧结果另设 legacy_id |
| [run_model.py KPSS 路径](https://github.com/ImanNasrEsfahani/DS-LPPLS/blob/d6eb89a40afca7024a245bf204d88d5649814b41/run_model.py#L183)：对已经取 log 的输入再取 log | 检验残差与主拟合不在同一量纲 | 建立 raw_price/log_price 显式数据契约 |
| [run_model.py bootstrap](https://github.com/ImanNasrEsfahani/DS-LPPLS/blob/d6eb89a40afca7024a245bf204d88d5649814b41/run_model.py#L277)：重采样残差后取 exp | 返回价格，再交给期望 log 输入的拟合路径；iid 重采样也会丢失时序相关性 | 逐步校验单位；相关噪声下用适当区块/参数法并检验覆盖 |
| [filter_model.py Confidence/Trust](https://github.com/ImanNasrEsfahani/DS-LPPLS/blob/d6eb89a40afca7024a245bf204d88d5649814b41/filter_model.py#L349)：两处 B 的正负方向命名不一致；bootstrap 汇总变量被逐窗覆盖 | 上下行指标和多窗分母不可直接解释 | 方向、窗口级统计、全局汇总分开测试 |
| [show_charts.py](https://github.com/ImanNasrEsfahani/DS-LPPLS/blob/d6eb89a40afca7024a245bf204d88d5649814b41/show_charts.py#L80)：本地坐标 t_c 与过滤后行号混合；跨历史行聚类 | 日期偏移；若据此回放早期预测，会引入后来的结果 | 先换算绝对交易日，再按 asof 单独聚类与追踪 |
| 拟合允许 t_c 落入样本，而原式仍用 t_c−t；未完整检查优化成功/有限值 | 分数幂与 log 可能无效；不能把返回参数视为有效拟合 | 定义未来域、保留失败、边界与优化状态 |
| 相位计算含整数转换；README 所述分位数能力未在主链找到 | 派生量与介绍不完全一致 | 按实际代码能力列功能，重新核对相位定义 |

**慢的来源也要按工作量拆开。**默认嵌套窗口约为 400 至 121 点、逐日重复；通过过滤后每窗又进行 100 次 bootstrap，每次调用多阶段优化。这个任务量与“只看最新一天、十几个窗口、没有 bootstrap”不能按总分钟数比较。这里是静态调用量判断，**没有实测该仓库运行速度**。

作者声明 / NOT_ESTABLISHEDREADME 写有 MIT 声明，但本次未核实到完整对应 LICENSE 文本；不要把 README 描述当成数据、代码和模型权重均已获得相同许可。没有安装运行该项目、读取其 Excel 样本或验证其输出。本报告不修改该仓库。

## 06 · 振荡数：统一公式，比争论数字重要

**[VERIFIED]** 对 cos(ω ln(t_c−t))，完整相位变化除以 2π 才是完整周期数：

N<sub>cycles</sub> = [ω/(2π)] ln[(t<sub>c</sub>−t₁)/(t<sub>c</sub>−t₂)]，t<sub>c</sub>>t₂

| 实际表达式 | 阈值写 2.5 时对应完整周期 | 结论 |
| --- | --- | --- |
| ω/(2π) × ln 比值 | 2.5 | 完整周期口径 |
| ω/π × ln 比值 | 1.25 | 半周期口径 |
| ω/2 × ln 比值 | 2.5/π≈0.796 | 不能标成完整周期数 |
| 当前研究基线 | 1.5 | 明确用第一行公式；尚不是最优阈值结论 |

关键发现：[Shu & Zhu 论文](https://arxiv.org/pdf/1905.09640v2)印刷页9–10的式(12)写 ω/2，而相邻正文写 half-periods、ω/π。这是目视 PDF 确认的同文不一致，不能靠“FCO口径”四个字消除。公开论文中的多种研究过滤器，也不足以确认当前商业 FCO 服务的私有实现。

### 它为何会影响提前量？这里可以直接推导

若窗口有 N 个等距交易观测，d=t_c−t₂>0，则周期门槛 q 隐含：

N<sub>cycles</sub> = [ω/(2π)] ln[(d+N−1)/d] ≥ q<br>⇒ d ≤ (N−1) / [exp(2πq/ω)−1]

| 窗口点数 N | ω=13，门槛1.5 | ω=13，门槛2.5 |
| --- | --- | --- |
| 60 | d 上界约55.4交易步 | 约25.1交易步 |
| 100 | 约93.0 | 约42.2 |
| 250 | 约233.9 | 约106.1 |

数学推导更高周期门槛会在给定窗口下排除较远的 t_c，可能让早期候选更难通过。表中是**合格域的上界**，不是保证能提前这么多天；实际还受 t_c 搜索域及其他过滤器限制。因此“严格一点必更准确”与“放宽必少漏报”都要用相同报警预算验证。

## 07 · 时间窗选择和跨尺度聚类如何改

**先分清三条时间轴。**历史回看长度 L、未来预警范围 H、用于事后确认标签的观察长度 E 是不同参数。长期记忆里的短/中/长/超长窗口是回看范围，不能直接命名为“短期顶/阶段顶”。“1–6个月上涨后的阶段顶”需要独立事件定义与样本，不能仅靠窗口长度判断。

固定窗基线继续保留。Lagrange 正则化是可比较的选窗方法，但要在每个 asof 只使用当时数据估计其选择规则。不能看见后来的顶部后再选择起点，也不能以同一个样本外成绩反复选择正则化强度。[窗口起点研究](https://arxiv.org/abs/1707.07162)

### 建议的聚类契约（尚未运行）

- **窗口层：**每个 asof 保存全部候选和失败，记录 lookback、方向、seed、优化状态、t_c 交易坐标、过滤拒绝理由。

- **尺度内：**将同一窗口多 seed 收敛到的近重复解归为同一解族；多 seed 主要检查数值稳定，不能直接变成更多市场证据。

- **尺度间：**预先固定各尺度的总权重，避免某一尺度因枚举更密就支配峰值。按交易日坐标聚类，保存不同峰及其覆盖窗口。

- **跨日：**先在当日独立生成情景，再与既有情景匹配。后日结果只能形成修订，不能回写前日首次提醒。

- **概率层：**密度、跨尺度覆盖度、连续出现天数只能先做特征；经过严格样本外校准后，才可解释成指定事件概率。

**不要把同源信号当独立投票。**181 个高度重叠窗口、同一序列的多个分位数、不同 seed 和相邻交易日往往高度相关。聚类峰高可能只是枚举设计的产物。尺度平衡后还需要统计验证，不能把“多个时间尺度同区间”直接转换成 80% 或 90%。比特币文献提供了组织情景的参考，并未替你的 A 股阶段顶任务做校准。[Gerlach 等](https://arxiv.org/abs/1804.06261)

**不要强行挤成十日窗。**先以最低支持/覆盖要求寻找可发布区间；若无法同时满足，应显示宽区间观察或无正式提醒。把所有分布裁成十日后再报告“区间精确”，只改变了展示，不增加信息。

## 08 · 不确定性、假阳性与“看上去很准”的陷阱

文献方法profile likelihood 的价值是：固定一个 t_c 后，重新优化其余参数，而不是只围绕最优点画一个窄钟形。多峰可能代表不同情景；边界解可能代表数据还不够识别。原文也未把完整大规模前瞻回测作为已完成结论。[Modified profile likelihood](https://arxiv.org/abs/1602.08258)

**对你的框架：**先检查旧 MPL 的工程修复与数值诊断是否一致，不能因为历史上曾有 MAXITER 问题，就断言修复后的版本仍存在同一故障；反过来，测试通过也不能恢复其市场预测能力。当前历史报告中的否定/不支持结果仍有效，除非新的独立实验推翻它们。

已读历史报告纳指历史窄窗分析曾出现明显残差相关；相关区块重采样下 t_c 区间大幅变宽、严格过滤通过率较低。因此过去某次点估计碰巧落在一周内，不能自动改称“一周置信区间经过验证”。本轮没有重新执行这些历史实验。

**残差相关性要进入区间构造。**iid bootstrap 会打散依赖结构。可对照 moving/stationary block bootstrap、明确假设的 AR 噪声及更复杂噪声，但每种都需检查适用性和模拟覆盖；“用了区块”本身也不保证正确。任何重采样都要重新跑选窗、拟合与过滤，不能只给最后一个参数点加噪。

论文作者报告Bree、Challet、Peirano 讨论 LPPL 参数的弱可识别性：不同参数可给相近拟合。Grobys 对特定 LPPLS 后残差 ADF/PP 结论提出全流程零假设校准问题。本轮后者仅核对摘要、作者公开复现说明及部分代码，未取得可完整阅读的正式论文。[Sloppiness](https://arxiv.org/abs/1006.2010)；[Grobys](https://doi.org/10.1016/j.irfa.2025.104848)；[作者复现材料](https://zenodo.org/records/17712092)

**因此建议增加对抗样本。**随机游走、带漂移随机游走、波动聚集/厚尾、跳跃、趋势改变、普通均值回归、无后续转折的持续上涨，都应穿过**完整的同一条流水线**。先模拟再搜索再过滤再挑峰，得到的假警报率才与线上行为可比。不能只比较一条真 LPPLS 曲线与一条干净白噪声。

也应加入简单基线：无条件事件频率、相同报警预算的随机区间、仅趋势/动量/波动指标，以及现有固定窗口版本。复杂模型只有在未参与调参的数据中带来稳定增量才有价值。

## 09 · 与长期记忆框架逐层对照

L0 PIT → [V4.8-R2 Time ∥ PPE-U2-R5.1 Price ∥ Grouped Aux]<br>→ Cross-Fitted Joint → Resolution-Aware Governor → Portfolio / Execution

这是从历史交接文档恢复的框架结构，**不是已核实当前仓库的全功能完成状态**。

| 层 | 本次文献可提供的帮助 | 保留的边界 |
| --- | --- | --- |
| L0 / PIT | FBE 的事前封存思想；为每次拟合保存输入哈希、公司行动版本与 asof | 今天下载的复权历史不等于当年可获得的版本；历史重放与真实发布分开 |
| S4 / Time | FS 消元、窗口正则化、profile、多尺度组织；神经初值为候选加速器 | 同一未来域、周期单位、失败保留；不能通过更窄搜索域制造精准日期 |
| 事件映射层 | 把参数结构转为明确阶段顶目标的学习任务 | 分别估计事件是否发生与条件日期；保留 no-event，不将似然直接叫概率 |
| S5 / Price | 仅将时间结构作为可检验的条件特征；临界价研究可作为探索基线 | 价格密度几何不是未来回撤分布；时间模型不直接决定低点 |
| Grouped Aux / HMM | 可提供市场状态、流动性和变点特征 | 与价格同源，不算独立票；历史状态只能用 filtered，不能用含未来的 smoothed |
| Cross-Fitted Joint | 用按时间交叉拟合的结构特征评估增量 | 资产依赖和标签重叠要隔离；概率必须校准，不能直接相乘 |
| Governor / Execution | 将“观察/正式提醒/无结论”与动作区分 | 以当时可交易信息决策；不把未来确认位置当作可买卖时点 |

**应保留的事件分解：**`p_H=P(阶段顶在未来H内发生 | F_t)`；`g(u | 事件发生,F_t)`给事件条件下的日期分布；无事件质量为`1−p_H`。这是研究架构，不是当前已有可用概率。不同峰应分别显示，不能为了页面简洁揉成一个虚假的高精度区间。

NOT_ESTABLISHEDH1/H2/H3、Q2、MPL、Ising、Q-DD2、PPE 的既往失败或不支持结果，不会因为新论文存在而晋级。旧的 top10_20_60 及价格/年龄模型实验可以保留作历史对照，不能重新用“未来跌10%”替代用户现在的顶部日期目标。已经反复查看的 2016–2025 数据也不能再称真正未见的最终测试集。

## 10 · 底部与价格层：为什么不能直接镜像顶部

数学事实在同一设计矩阵、无约束线性最小二乘下，把 y 改成 −y，会令 β 改成 −β，而残差平方和完全相同。因此 log P 与 −log P 的无约束拟合不是两张独立选票。方向约束、事件定义与判别器才会让两个任务真正不同。

负泡沫研究讨论加速下跌及潜在反弹；anti-bubble 常指峰值后减速的对数周期衰退，二者不能混名。底部可能受到流动性、政策冲击、跳空和基本面重新定价影响，必须独立训练/评价。历史反弹实验是参考证据，不能直接证明当前 A 股个股抄底有效。[Negative bubbles](https://arxiv.org/abs/1003.5926)；[Anti-bubble 研究](https://arxiv.org/abs/cond-mat/9907270)

你需要的价格层包含三个不同输出：①未来回撤幅度的条件分布；②在指定未来时段内的价格区间；③接近底部后是否具备可操作的反转证据。`exp(A)`最多是特定 LPPLS 形式中临界时刻的拟合价格极限，绝不是泡沫破裂后的支撑位。

G-LPPLS-NN 的临界价/时间扩展值得后续阅读和复现，但本轮仅取得摘要及部分章节，不能据此宣布解决回撤和低点。建议仍将 Price 的条件分位数、尾部覆盖、first-hitting 等单独评分，之后再测 Time 特征是否带来增量。任何潜势/KDE“价格密集区”在校准前只能叫历史结构区。[Ma & Li，2024](https://doi.org/10.1016/j.econlet.2024.112003)

## 11 · 可交给 Devin 的单项实验计划

研究建议 · NOT_RUN每次只改变一项；先冻结数据、目标和指标，再比较结果。保留旧评价器和旧产物；以下不是授权本轮执行开发或模型计算。

| 实验 | 只改变什么 | 主要记录 | 晋级条件 |
| --- | --- | --- | --- |
| E0 单位与数值契约 | 显式完整周期、未来域、价格/log量纲、日期轴 | 旧值映射；有限值；边界；失败；重复解 | 数学单元检查与历史结果差异可解释 |
| E1 求解器 | DE+独立L-BFGS-B vs 网格/多起点TRF | 同预算/同误差目标两种比较；loss差、参数漂移、失败率、p50/p95耗时 | 数值可靠性与资源代价改善；不预设哪个更优 |
| E2 日期宽度 | 正式提醒发布规则，而不是隐藏裁剪分布 | 窄区间覆盖、宽观察比例、无事件、提前不足 | 固定报警预算下改善阶段顶表现 |
| E3 窗口选择 | 固定窗口 vs 正则化/有限候选起点 | 拒绝原因、事件召回、不同尺度贡献 | 独立时期可复现，不依赖少数名例 |
| E4 聚类 | 原始密度 vs 去重/尺度平衡/跨日追踪 | 有效解族数、情景漂移、报警寿命与新提醒数 | 相同提醒次数及报警占用天数下有增量 |
| E5 不确定性 | iid vs 相关噪声方法及完整pipeline零假设 | 合成参数覆盖、真实事件覆盖、假阳性、区间宽度 | 在合理噪声压力下不过度自信 |
| E6 神经暖启动 | 在已验证的求解流程前加 P-LNN 候选 | 训练/推理/精修全部成本、域外失败、遗漏低loss解 | 保留独立探索时节省耗时，事件指标不劣于冻结基线 |

### 阶段顶评价必须与用户目标一致

局部顶、阶段顶、两者重合分别保留；事后标签可以使用未来确认信息，但特征、阈值和发布日期绝不能使用这些未来信息。阶段顶强调 1–6 个月上涨后的转折，具体标签半径、平台高点规则、同段多个峰的处理应沿用已确认例集并版本化，不能由本报告悄悄重定义。

- 逐事件记录：未提醒、窗口偏早、偏晚、过宽、提前不足，以及多个问题同时发生。分别保存**首次正式区间**与后续最佳修订，主成绩不得用最佳修订冒充首次预报。

- 提前量从首次真实可见时间计算；日终生成不能在同日收盘前视为可执行。至少5个交易日与最多10交易日的愿望是需要检验的门槛，不是设计后自然满足的保证。

- 事件与提醒做确定的一对一匹配，避免一个长期报警覆盖多个顶、一个顶被重复算命中。相同提醒次数之外，同时控制报警占用天数，防止长时间常亮取得高召回。

- 报告阶段顶漏报率、合格提前召回、匹配区间覆盖/宽度、误报频度、提醒修订幅度、各市场/波动/行情状态的分层结果。不仅展示成功案例。

- 先在训练/校准段确定规则，然后锁定外层测试。标签未成熟标 pending；切分按实际 label_end 去重叠，依赖资产按共同日期分组。统计不确定性按时间/事件块处理，不能把数千重叠窗口当独立样本。

### 速度对比如何公平

同时做“相同计算预算”和“达到相同质量所需时间”两张表。统一机器、线程数、数据、范围、精度容限、随机种子策略及失败处理；分别记录行情 I/O、排队、拟合、bootstrap、历史回放。先校准最新日，历史重放后台按需触发。旧窗口缓存只有在数据哈希与模型契约完全一致时可复用；新增一天可暖启动，但不是无需重新验证的一次简单增量相加。

## 12 · 账本与前端：让速度和证据同时可见

借鉴前瞻实验最值得做的是保留“当时到底说了什么”。FBE 的数字指纹/事前封存提供了流程示例，但预先存证和预先冻结完整评分规则是两回事；历史作者成绩不能代替你的网站评价。[FBE III](https://arxiv.org/abs/1011.2882)

prediction_id · parent_id · asof · data_cutoff · generated_at · first_visible_at<br>mode={historical_replay,prospective} · model_id · data_hash · code_commit<br>event_level · state · tc_intervals · no_event_status · reject_reasons · supersedes

状态转换应可追溯：早期观察 → 正式区间提醒；同一事件情景变化形成修订；不相关的新情景产生新提醒。所有转换只使用当时已有信息。预测即使没有合格窗口，也要记录“未形成正式区间”和原因，避免只保存成功输出造成选择偏差。

工作站的推荐呈现顺序：行情与截止日立即显示 → 已有分析连同 stale 标记显示 → 当前分析独立排队 → 历史重放按需启动。模型仍处观察状态时展示具体原因，例如“跨尺度支持不足”“区间过宽”“未来临界点受边界限制”“数据不足”，不能显示“无风险”。

以上为产品与接口建议，未修改前后端，也未验证最新 Devin 工作分支。

## 13 · 具体推进顺序与验收门槛

**第一步：修正比较基础**冻结1.5完整周期、future-only、数据量纲、交易日轴、旧结果映射、阶段顶标签和首次提醒评分。先完成E0，并把已有91个阶段顶的失败分类做成可复核表。

**第二步：找出真正的性能瓶颈**跑E1数值对照；在同一账本上分别做E2/E3/E4。不要同一版本同时改窗口、聚类和概率阈值，否则无法归因。

**第三步：校准可信程度**执行E5全流程对抗检验，报告覆盖与无事件表现。只有通过后，才讨论正式提醒阈值与概率用语。

**第四步：验证提速与扩展**E6作为挑战者。底部与Price另开冻结实验；不靠顶部结果替它们背书。真实前瞻账本持续积累，成熟后独立评估。

时间安排可用第一周完成契约/样本核对、一个月内完成有限资产的单项对照与对抗验证、三个月积累前瞻记录；这是规划窗口，计算量和事件数量未实测，不承诺三个月即可证明有效。

- 所有振荡数显示公式版本和单位；legacy规则可复现。

- 固定种子、线程/预算、数据哈希、代码提交；成功/失败/未完成数量守恒。

- 每次 t_c 参数转换与交易日映射可逆可核对，不混自然日。

- profile 固定 t_c 后重新优化 nuisance 参数；记录多峰及边界。

- 按 asof 聚类，不跨未来行；同一解和高度重叠窗口不得伪增样本量。

- 局部顶、阶段顶分别评分；保留 no-event 与 pending；不用10%跌幅替代日期目标。

- 同报警预算及占用天数下比较漏报、误报、提前量、宽度，不只报平均拟合误差。

- 首次发布与历史重放分开，修订不可覆盖原预测。

- 价格和底部输出都有独立成绩，失败实验原样保留。

- 未完成检验前使用“研究候选/观察区间”，不写“已验证精准逃顶/抄底”。

## 14 · 书目与阅读深度

以下是本轮已定位并使用的核心文献与实现。年份区分预印本和期刊；“全文方法阅读”表示核对研究问题、方法与限制，不表示逐式证明、重现全部实验。

[R01 · Crashes as Critical Points](https://arxiv.org/abs/cond-mat/9810071)

Johansen; Ledoit; Sornette · 2000（预印本1998） · 阅读深度：摘要及理论定位；未逐式核验原始推导。用途：临界时间、随机崩盘与事件定义边界

[R02 · A Stable and Robust Calibration Scheme of the Log-Periodic Power Law Model](https://arxiv.org/abs/1108.0099)

Filimonov; Sornette · 2013（预印本2011） · 阅读深度：全文重点：重参数化、目标函数、校准方法。用途：保留三非线性参数与四线性参数分离的校准基础

[R03 · Prediction accuracy and sloppiness of log-periodic functions](https://arxiv.org/abs/1006.2010)

Brée; Challet; Peirano · 2013（预印本2010） · 阅读深度：全文重点：参数可识别性、Hessian与噪声实验。用途：低拟合误差不保证临界日期稳定

[R04 · Modified Profile Likelihood Inference and Interval Forecast of the Burst of Financial Bubbles](https://arxiv.org/abs/1602.08258)

Filimonov; Demos; Sornette · 2017（预印本2016） · 阅读深度：全文方法与适用范围；未逐式验证所有推导。用途：显式处理nuisance参数、多峰与区间不确定性

[R05 · Comparing nested data sets and objectively determining financial bubbles’ inceptions（预印本：Lagrange regularisation approach…）](https://arxiv.org/abs/1707.07162)

Demos; Sornette · 2019（预印本2017） · 阅读深度：全文重点：窗口选择及正则化。用途：作为固定窗口基线的单项挑战者

[R06 · Birth or burst of financial bubbles: which one is easier to diagnose?](https://doi.org/10.1080/14697688.2016.1231417)

Demos; Sornette · 2017 · 阅读深度：摘要与出版信息。用途：允许起点与终点可识别性不同；未收敛时保留观察状态

[R07 · Early Warning Signals of Financial Crises with Multi-Scale Quantile Regressions of Log-Periodic Power Law Singularities](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0165819)

Qun Zhang; Qunzhi Zhang; Sornette · 2016 · 阅读深度：全文重点：分位数、Confidence/Trust定义与案例。用途：研究稳健性；不能当成校准的未来事件概率

[R08 · Diagnosis and Prediction of Market Rebounds in Financial Markets](https://arxiv.org/abs/1003.5926)

Yan; Woodard; Sornette · 2010，修订2011 · 阅读深度：全文重点：负泡沫、标签、训练测试设计。用途：底部单独建模；历史伪样本外与真实发布分开

[R09 · The Financial Bubble Experiment: advanced diagnostics and forecasts of bubble terminations, Volume I](https://arxiv.org/abs/0911.0454)

Sornette; R. Woodard; Fedorovsky; Reimann; H. Woodard; Zhou · 2009–2010 · 阅读深度：全文重点：封存/披露协议；未独立重算所有hash。用途：首次预测存证；存证不等于冻结完整评分规则

[R10 · The Financial Bubble Experiment: advanced diagnostics and forecasts of bubble terminations, Volume II — Master Document](https://arxiv.org/abs/1005.5675)

Sornette等 · 2010 · 阅读深度：全文重点：协议与区间表；未重新核算成功率。用途：前瞻账本设计参考，不外推一周精度

[R11 · The Financial Bubble Experiment: advanced diagnostics and forecasts of bubble terminations, Volume III](https://arxiv.org/abs/1011.2882)

Woodard; Sornette; Fedorovsky · 2010，修订2011 · 阅读深度：摘要、版本与披露安排。用途：前瞻实验线索；具体成功率未独立确认

[R12 · A Statistical Analysis of Log-Periodic Precursors to Financial Crashes](https://arxiv.org/abs/cond-mat/0101031)

Feigenbaum · 2001 · 阅读深度：摘要。用途：加入早期截断和合理噪声对照；不以此裁定所有后续模型

[R13 · Significance of log-periodic precursors to financial crashes](https://arxiv.org/abs/cond-mat/0106520)

Sornette; Johansen · 2001 · 阅读深度：摘要；与批评成对读取。用途：避免只读支持或反对单一方向

[R14 · Testing for financial crashes using the Log Periodic Power Law model](https://arxiv.org/abs/1002.1010)

Brée; Joseph · 2013（预印本2010） · 阅读深度：全文重点：研究设计与过滤规则敏感性。用途：完整日历中的误报、漏报与参数规则敏感性

[R15 · Detection of Chinese Stock Market Bubbles with LPPLS Confidence Indicator](https://arxiv.org/abs/1905.09640v2)

Shu; Zhu · 2019预印本；2020期刊 · 阅读深度：全文重点；PDF印刷页9–10额外渲染目视核验。用途：确认原文振荡数公式与半周期正文不一致；A股历史对照

[R16 · Real-time Prediction of Bitcoin Bubble Crashes](https://arxiv.org/abs/1905.09647)

Shu; Zhu · 2019 · 阅读深度：摘要。用途：采样频率与事件尺度匹配；不外推加密货币成绩

[R17 · Real-time prediction and post-mortem analysis of the Shanghai 2015 stock market bubble and crash](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2693634)

Sornette; Demos; Qun Zhang; Cauwels; Filimonov; Qunzhi Zhang · 2015 · 阅读深度：摘要与作者/期刊元数据；未审计全部原始预警文件。用途：中国市场前瞻案例追索线索，不认定具体提前命中

[R18 · Deep LPPLS: Forecasting of temporal critical points in natural, engineering and financial systems](https://arxiv.org/html/2405.12803v1)

Nielsen; Sornette; Raissi · 2024，v1 · 阅读深度：正文及附录方法/实验；图4/5与表2额外PDF目视核验。用途：神经校准可作暖启动挑战者；速度与真实事件效果分开

[R19 · Dissection of Bitcoin’s Multiscale Bubble History from January 2012 to February 2018](https://arxiv.org/abs/1804.06261)

Gerlach; Demos; Sornette · 2019（预印本2018） · 阅读深度：全文关键方法、窗口/聚类与案例选择；未重现。用途：逐asof多尺度候选组织；不直接移植事件成绩

[R20 · Log-periodicity: Fact or fiction?](https://doi.org/10.1016/j.irfa.2025.104848)

Grobys · 2026期刊；2025复现材料 · 阅读深度：摘要、作者Zenodo复现README及部分脚本；正式全文访问受限。用途：完整拟合与过滤链的零假设校准；不报告未核实百分比

[R21 · Detecting market bubbles: A generalized LPPLS neural network model](https://doi.org/10.1016/j.econlet.2024.112003)

Juntao Ma; Chenchen Li · 2024 · 阅读深度：出版页面摘要、引言与部分方法；未完整审查附录。用途：临界价/时间扩展候选，不等于崩盘后低点预测

[R22 · Log-periodic power law bubbles in Latin-American and Asian markets and correlated anti-bubbles in Western stock markets: An empirical study](https://arxiv.org/abs/cond-mat/9907270)

Johansen; Sornette · 2001（预印本1999） · 阅读深度：摘要。用途：区分峰值后减速结构与加速下跌负泡沫

公开原文与公式核对页：[Deep LPPLS 原论文](https://arxiv.org/pdf/2405.12803v1) · [Shu–Zhu 原论文](https://arxiv.org/pdf/1905.09640v2) · [公式所在页](https://arxiv.org/pdf/1905.09640v2#page=9) · [半周期说明页](https://arxiv.org/pdf/1905.09640v2#page=10)。

[下载机器可读证据目录 JSON](literature-evidence-index.json)（含22篇文献、阅读深度、仓库提交和历史框架文件哈希）。

核查日期：2026-11-16。范围：公开论文、公开代码静态阅读及本地历史交接文件。原文研究阶段未执行模型、未修改项目或推送。本次仅将报告与任务单提交文档 Draft PR；未部署或发布。报告结论涉及未验证的研究设计时，均应通过固定口径的独立实验后再晋级。
