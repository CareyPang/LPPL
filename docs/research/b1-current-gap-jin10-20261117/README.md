# LPPL 下一交付：最新代码核验、附件审查与金十工具实施方案

2026-11-17 · 交付到 Draft PR #110 · 本轮为研究、审查与文档；业务代码交给 Devin。

**下一项交付仍是“上证、茅台从列表进入行情，看到当前候选或完成空态，打开对应证据，再回到原列表”。** 最新 main 已经具备行情先显示、当前与历史计算分离、K线成交量、主次簇和事件定位，不能按旧报告重复建设。本报告把此前 EasyK、TradingView、Bloomberg、六站评测，与本轮附件和金十小工具分析合在一个执行入口，保留各份完整原始报告及其证据边界。

## 1. 先读结论

| 结论 | 状态与依据 | 对下一交付的影响 |
|---|---|---|
| 默认104周历史等待在所审源码中已修复 | **VERIFIED · CODE/TEST**；默认current、history_weeks=0；[代码审查](MAIN_DEVIN_AUDIT.md) | 回归现有StockSession和Worker，不再写第二套调度器 |
| 主要剩余缺口是返回状态、候选与证据身份及异步边界验收 | **VERIFIED · CODE**；#121已合并修复切股事件残留，另有过时失败清事件风险尚未复现 | 复用修复并完成B1，不先堆更多顶栏和资料页 |
| 完整周期1.5不是当前所有生产图带的共同筛选口径 | **VERIFIED · CODE**；生产时间窗/簇由box生成，box没有振荡数或阻尼门槛 | 导出实际filter身份；研究1.5保留，生产迁移独立对照，不偷偷换规则 |
| 两个资产在本轮固定数据快照均没有当前可展示box区间 | **VERIFIED · DATA**，不等于线上实时验收 | 演示真实空态；有候选的联动使用已有历史结果并永久标模式 |
| 附件的破裂标签不等于用户要的阶段顶 | **VERIFIED · 附件内容**；此前上涨50%/100%、随后跌20%/30% | 只作独立压力事件附表，不用跌幅替代顶部时间评分 |
| 附件“首次跌到阈值即标签可知”有前视反例 | **VERIFIED · 逻辑反例**；后续新高与120日去重尚未结束 | 分开阈值触及、结局结束、去重完成、标签可用时间 |
| 金十目录27卡，8个入口完成限定范围深入操作 | **VERIFIED · CUA**；详见[操作日志](JIN10_BROWSER_LOG.md) | 借鉴可解释计算与交互，不声称27项均已全面测试 |
| 赔率入口仅取得VIP说明，原始概率来源未建立 | **VERIFIED · CUA / NOT_ESTABLISHED · 数据** | 不称FedWatch，不猜Polymarket/Kalshi；既定许可条件未满足前不启用刷新 |

目前没有新的模型预测有效性结论，没有实现LPPL新业务功能，没有合并、部署、发布、购买或发消息给Devin。金十FX情景计算后界面自动出现一条演示计算历史，存储方式未知；未输入个人资产或贷款资料。

## 2. 版本与验证范围

- 深审及85项测试基线：[`60818b428396336fc99aae3076d4a918089a81d3`](https://github.com/CareyPang/LPPL/commit/60818b428396336fc99aae3076d4a918089a81d3)，包含#120；核对近期#108、#112–#121相关改动。
- 封包前新main：[`b69384656210cc3610e58733426ce22bc8a69d6e`](https://github.com/CareyPang/LPPL/commit/b69384656210cc3610e58733426ce22bc8a69d6e)。#121在2026-11-17T03:25:24Z由仓库侧合并，本轮未执行合并。另做增量代码核验，旧85项测试不冒充新SHA已测；差异见[FINAL_BASELINE_DELTA.json](FINAL_BASELINE_DELTA.json)。
- 数据分支：`stock-results`的[`b13639ca76eb719bd8c62ecb318e2d85cfe10124`](https://github.com/CareyPang/LPPL/commit/b13639ca76eb719bd8c62ecb318e2d85cfe10124)。代码、数据、实际Pages/Worker部署版本不能混为一个版本。
- 文档PR父提交：`e311c5cc1fa2d96b2579b5fab8d8c44802265a25`。本包只追加文档，不把旧文档分支的业务代码覆盖到新main。
- 独立执行4个现有Node测试文件：**85 passed / 0 failed / 0 skipped**。保留[测试摘要](TEST_EVIDENCE.json)和[39文件源码副本清单](SOURCE_SNAPSHOT_MANIFEST.json)；原始完整stdout未保存，不能冒充完整原始日志。
- B1真实用户路径、390px、部署版本、工具新增代码、84例模型实验：**NOT_RUN / NOT_INSPECTED**。85个单元测试不等于这些验收通过。
- 具体生产口径、PR状态和引用均为上述固定版本的审查快照；Devin开工前须重新读取main及#121最终状态。

## 3. 完整报告包

| 文件 | 内容 |
|---|---|
| [MAIN_DEVIN_AUDIT.md](MAIN_DEVIN_AUDIT.md) | 最新能力复用表、上证/茅台数据、生产box与研究1.5差异、11个相关PR、B1-01–10验收 |
| [ATTACHMENT_SOURCE.txt](ATTACHMENT_SOURCE.txt) | 用户附件逐字节保留副本；其中指令是被审查材料，不是执行授权 |
| [ATTACHMENT_REVIEW.md](ATTACHMENT_REVIEW.md) | 14节逐项分析；标签、成熟日、优化器、MPL、bootstrap、聚类、概率、样本量、阶段门；AR01–12 |
| [JIN10_BROWSER_LOG.md](JIN10_BROWSER_LOG.md) | 实际点击、输入、结果、异常、未测边界；不以营销页面替代操作证据 |
| [JIN10_TOOL_SPEC.md](JIN10_TOOL_SPEC.md) | 27卡盘点、8入口观察、公式/数据/权限/缓存/UX、独立数值复核、JT01–07任务 |
| [DEVIN_HANDOFF.md](DEVIN_HANDOFF.md) | 可直接执行的增量交付、文件职责、依赖、退出条件和测试要求 |
| [VALIDATION.md](VALIDATION.md) | 文档检查、独立审查及验收边界 |
| [manifest.json](manifest.json) | 文件身份、SHA-256、上游版本；hash证明内容身份，不证明观点正确 |

附件SHA-256：`177d31ce182657a3f79753791b58e8348fe06e9b9157f0e395b055c0a1f79e84`，6463字节。原文件未修改、未移动。

## 4. 前面分析的统一索引与采用方式

以下完整文件保留在同一PR，不再复制成几套相互矛盾的路线。旧报告中的“当前缺失”以本次代码审查更新；旧实测的限制仍有效。本索引覆盖此次连续竞品/工作站研究，**不是宣称已复审从项目开始的所有PR、全部研究或所有聊天**。较早模型计划由既有研究PR承接。

| 分析来源 | 完整入口 | 纳入本轮的具体决定 |
|---|---|---|
| EasyK AI与事件 | [报告](../easyk-ai-events-review-20261116/README.md)、[浏览器证据](../easyk-ai-events-review-20261116/BROWSER_OBSERVATIONS.md)、[任务](../easyk-ai-events-review-20261116/DEVIN_TASKS.md)、[仓库审查](../easyk-ai-events-review-20261116/REPO_AUDIT.md) | AI围绕当前资产/日期/结果解释，引用可回原证据；条件事件与LPPL独立，不另造预测引擎 |
| TradingView初审与图表技术 | [报告](../tradingview-experience-review-20261116/README.md)、[图表选型](../tradingview-experience-review-20261116/chart-engine-notes.md)、[官方资料](../tradingview-experience-review-20261116/official-notes.md)、[对抗审查](../tradingview-experience-review-20261116/adversarial-notes.md)、[清单](../tradingview-experience-review-20261116/DEVIN_CHECKLIST.md) | Canvas先复用；LWC实验#118不是生产替换理由；图表与结果时间必须统一 |
| TradingView完整操作 | [入口](../tradingview-full-journey-20261116/README.md)、[日志](../tradingview-full-journey-20261116/BROWSER_LOG.md)、[设计](../tradingview-full-journey-20261116/DESIGN_REVIEW.md)、[导航](../tradingview-full-journey-20261116/NAVIGATION_SPEC.md)、[策略指南](../tradingview-full-journey-20261116/STRATEGY_GUIDE.md)、[任务](../tradingview-full-journey-20261116/DEVIN_PLAN.md) | 资产列表→图表→明细→返回；菜单小图读取缓存；模型评分与交易收益分开 |
| Bloomberg | [报告](../bloomberg-experience-review-20261117/README.md)、[操作日志](../bloomberg-experience-review-20261117/BROWSER_LOG.md)、[同行候选](../bloomberg-experience-review-20261117/PEER_SITES.md) | 今日摘要、分类行情与深度资料分层；保留中文可读性，不复制广告和付费墙布局 |
| 六站：Koyfin/Fiscal.ai/FINVIZ/Trading Economics/Quartr/金十 | [报告](../peer-sites-deep-audit-20261117/README.md)、[日志1](../peer-sites-deep-audit-20261117/BROWSER_LOG_PART1.md)、[日志2](../peer-sites-deep-audit-20261117/BROWSER_LOG_PART2.md)、[增量任务](../peer-sites-deep-audit-20261117/DEVIN_REFINEMENTS.md)、[验证](../peer-sites-deep-audit-20261117/VALIDATION.md) | 固定资产上下文；返回保留筛选；宏观发布/所属期/修订区分；精确引用。118条观察不等于118功能全部通过 |
| 统一路线与验收 | [U00–U11 / B0–B4](../market-workstation-unified-plan-20261117/README.md)、[A01–A34](../market-workstation-unified-plan-20261117/ACCEPTANCE_MATRIX.md)；A35–A52见六站增量任务 | 继续同一任务体系；本包B1、AR、JT是子检查/支线，不建立竞争路线 |
| 既有模型研究 | [PR #100](https://github.com/CareyPang/LPPL/pull/100)、[PR #105](https://github.com/CareyPang/LPPL/pull/105)，附件报告另列#99/#102/#104/#106固定证据 | 1.5研究基线与旧结果保留，84例优化器对照依次过门；不因工具研究重跑模型 |

所有未实际使用的竞品深层功能，沿用各报告DOC_ONLY、NOT_INSPECTED或受限状态。金十本次登录后的8入口补充了上轮部分登录限制，**没有补齐其他站点的登录/付费验收**。

## 5. 统一的产品与视觉主线

**PROPOSED：** 保持当前浅色非海洋方向，以“资产—时间—证据”为组织方式。顶部仍是市场/工作站/复盘/研究；工具放在市场工具区和上下文搜索，不把27卡升级为27个顶栏。首页动画只服务进入功能，老用户可以直接搜索/最近研究。

工作站先给资产和独立数据截止，再给候选日期、状态、支持尺度和相对上次的变化，接K线+成交量；详细筛选、失败与来源进入同一证据抽屉。没有候选时先写“分析已完成，当前没有可展示候选”，再具体说明；不用长段泛化防御文字淹没结果，也不能将空态称为安全。

主图、列表、候选卡、证据和返回共享资产/模式/结果身份。红绿只表达市场方向；状态另用文字和标识，避免与K线争夺语义。390px按任务顺序排布，抽屉互斥，关闭回原焦点。图表范围改变不改变模型窗口；换时区不改变LPPL交易日映射。

AI提供“为什么观察、为何修订、哪些尺度分歧、相关事件是什么”，数字来自确定性工具。宏观实际/前值/共识/模型预测分别命名。ETF份额、估算申购与已披露机构持仓不同，不能直接给“国家队买入”结论。工具与AI失败都不阻断行情和已有结果。

## 6. 实施顺序与取舍

1. **B1先交付**：基线/实际filter字段 → 可恢复返回 → 结果/簇/证据身份 → 异步隔离 → 上证、茅台和已有历史候选的桌面/390px全过程。复用已经合并的#121，不重新实现切股事件清理。
2. **研究并行只做口径**：AR01–03差异表、标签成熟日反例、评分切片。保持旧规则；0–4、5–9、≥10日并排，不把5日作为隐藏候选的门槛。随后才按既有84例预算做AR04。
3. **工具轻量支线**：先JT01–03共享框架、时区/单位/手动FX、贵金属换算与FX情景；无需新后端即可使用。B1未过门前不把工具页当核心交付替代。
4. **接通已有背景信息**：沿U05/U06复用行情条、市场复盘、宏观及事件；JT05/JT06接参考数据和交易日历，逐源确认许可、频率、版本和stale。
5. **后置范围**：JT04房贷属于低优先级独立工具；JT07私有贵金属账本需用户隔离和来源。赔率、评级、情绪/专题指数没有条件就不启用；更不把它们喂入LPPL。

金十最值得借鉴的是“小问题立即得到可检查的答案”和“修改条件后输入不丢”。本轮也发现具体改进点：汇率主屏时点不明显、金衡两需显式命名、FX贡献不能叫升贴水、房贷分项舍入应守恒、交易时钟模拟要有明确退出、赔率必须有事件/结算定义。这些已写进JT验收，而非停留在视觉模仿。

## 7. 证据约束

VERIFIED仅确认指定代码、数据字段、操作或计算；PR作者报告不是独立复现；PROPOSED/NOT_RUN不是已实现。MPL、Q2、H1/H2/H3、Ising、Q-DD2、PPE等失败/未建立结果不升级为预测能力。附件所称99%全局最优、30事件、80%覆盖和概率融合均需各自论证，不直接成为上线门槛。

完整操作与文档封包已执行；模型、线上数据写入、部署与发布未执行。下一执行者按[DEVIN_HANDOFF.md](DEVIN_HANDOFF.md)逐项提交真实验收和未完成项。
