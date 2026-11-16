# LPPLS 初值与独立精修：有限样本研究交接

日期：2026-11-16。状态：`SOURCE_PREFLIGHT_COMPLETE / BLOCKED_CHECKPOINT_PROVENANCE / NEW_EXPERIMENTS_NOT_RUN`。

目的：以有限开发样本公平比较 P-LNN 初值＋独立精修、DE 多 seed＋L-BFGS-B、网格＋多起点 TRF，回答计算代价、阶段顶漏报和顶部区间是否改善。先小样本，不重跑全部资产/1990s，不预设神经网络优胜。

执行入口：[Devin任务](DEVIN_TASKS.md)、[机器可读契约](pilot-contract.json)、[新方法与自对弈审查](METHOD_REVIEW.md)。

最新执行条件先读 [P-LNN代码/权重核验与交接](P_LNN_PREFLIGHT.md) 和 [逐源机器记录](source-verification.json)。已核验两份第三方实现，但未建立作者代码/可用checkpoint的来源链；README加载路径不能作为真实权重。当前可先冻结84例及工程fixture，D/G基线如运行仅属部分完成，P保持NOT_RUN_MODEL_UNAVAILABLE。本次Devin交接以A阶段耗时/拟合质量报告为终点，B不自动启动。

## 与正在进行的研究隔离

- 本文档分支基于 `main@e90f2de736ff7eb957946d4b5e627c334d702727`。仅增加本目录文档，不改现有实验、配置、结果、工作流或生产默认。
- [#100](https://github.com/CareyPang/LPPL/pull/100) 的拟合、首次提醒与DS分离约束继续有效，固定引用 `3f2de2e541c519e962d010055da8715733101e20`。
- [#102](https://github.com/CareyPang/LPPL/pull/102) 契约实现固定引用 `e104c7f0f29dc1712df839e50e0c880e98af2255`。
- [#104](https://github.com/CareyPang/LPPL/pull/104) 在本轮读取期间更新；本文引用 `4b62fb181fb2a56a1f36e7c3486c534f84aa6652`，不复用可变分支名当版本。其完整计划是4,236个symbol-asof×95窗；475窗smoke及约0.44秒/fit属于作者报告，未独立重跑。
- #104 的 S10 协议和每5个交易日一次的扫描保留。本次另建每日小样本协议，不修改其主指标，不把其2015年工程smoke变成效果留出集。
- #100曾把神经训练列为延期项；本次仅新增有预算的warm-start研究规格，不解除其他延期项，不自动启动训练或全量扫描。

## 执行顺序与停止边界

1. 冻结版本、样本、权重来源和计算预算；先完成future-only及初值映射测试。
2. A阶段：36个真实窗口案例＋48个合成/负例案例，做数值与耗时比较；其中12个真实案例附统一TRF精修器的机制诊断。不能据此报告真实阶段顶召回。
3. B阶段预留：完整三臂A工程通过并完成成本/拟合质量审查后，另提交A_DECISION与B启用变更，按仅基于成本的预登记规则选择1或2个连续开发区块。所有方法使用相同12窗（四尺度各3窗），明确不是95窗B0复现；当前B禁用。
4. 到达总预算即停止、保存pending；样本不足写 `INSUFFICIENT_EVIDENCE`。完整对照未完成不得自动扩样。

保持完整周期 **1.5**、`tc>t2`、相同数据/过滤/聚类/标签/提醒语义。重点报告阶段顶漏报、首窗覆盖、至少提前5个交易日和宽度不超过10日的联合指标，不以之后跌10%定义成功。

本次只提交新 Draft PR。Devin 后续实现与运行使用独立研究分支、新run_id和append-only输出；不合并、不部署、不发布，不修改或重启 #102/#104 的既有运行。
