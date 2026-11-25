# LPPL 缓存方案：一手文献核验矩阵

核验日期：2026-11-13。范围：9项论文/官方规范，阅读下列实际章节；未改代码、未运行模型、未做性能测量。下文“支持”指来源论述已核实，落到本项目的实现仍为建议。文献不证明项目已满足规范，也不证明预测能力或等待时间。

## L1 — HTTP缓存与资源验证

Roy T. Fielding、Mark Nottingham、Julian Reschke（编），**RFC 9111: HTTP Caching**，2022年6月，IETF Standards Track。

- [原文](https://www.rfc-editor.org/rfc/rfc9111.html)
- 实读：§3.5 authenticated requests；§4/§4.1 cache keys与Vary；§4.2.4 stale；§4.3 validation；§5.2.2.7 private。
- 支持：HTTP复用受请求身份、缓存指令和验证器约束；ETag可用于重新验证资源表示；private限制共享缓存保存，不能代替应用权限。
- 本项目推论：已授权的不可变结果可复用；latest指针要另查manifest。304表示满足本次条件验证、可复用对应已有表示；弱验证器不证明字节完全相同，也不能证明已获取最新交易日、供应商完整或模型有效。
- 边界：不支持“命中即绝对新鲜”“授权JSON随意公共缓存”。业务级stale原因须独立于HTTP Age。

## L2 — 旧内容先显示的有界机制

Mark Nottingham，**RFC 5861: HTTP Cache-Control Extensions for Stale Content**，2010年5月，Informational。

- [原文](https://www.rfc-editor.org/rfc/rfc5861.html)
- 实读：§3 stale-while-revalidate、§3.1示例、§4 stale-if-error。
- 支持：在规定时限内返回旧响应并后台验证，或在错误时按规则返回旧响应，能提高可用性。
- 本项目推论：先显示旧行情/旧分析，并保留asof、更新时间及stale说明；“旧结果可读”与“新任务运行中”并存。
- 边界：这不是无限期陈旧许可，不保证后台更新必定成功，不证明页面或计算1–2秒完成；过期数据显示不应直接触发新的金融条件提醒。RFC5861引用的旧Warning机制不要未经核对搬到现代HTTP实现。

## L3 — 租约之外还需要写入端拒绝旧请求

Mike Burrows，**The Chubby Lock Service for Loosely-Coupled Distributed Systems**，OSDI 2006。

- [出版页](https://www.usenix.org/conference/osdi-06/chubby-lock-service-loosely-coupled-distributed-systems)
- [原论文](https://www.usenix.org/legacy/event/osdi06/tech/full_papers/burrows/burrows.pdf)
- 实读：§2.4 Locks and sequencers（PDF第4–5页，核心sequencer论述在第5页）；§2.6 API（第6页），含generation及compare-and-swap。
- 支持：持锁方可能发出迟到请求；接收端应验证包含锁代次的sequencer并拒绝无效请求。仅延迟重新授锁是较弱措施。
- 本项目推论：超时接管后旧worker不可用旧fencing token更新manifest/latest；写入端必须实际检查token，不能只在任务表记录它。
- 边界：不是使用Redis SET NX就自动得到同样保证，也不是“任务恰好执行一次”的证明；网络或进程故障仍可能重复执行，需保证幂等提交。

## L4 — 依赖指纹与分层重建

Andrey Mokhov、Neil Mitchell、Simon Peyton Jones，**Build Systems à la Carte**，Proceedings of the ACM on Programming Languages 2(ICFP), Article79，2018，DOI 10.1145/3236774。

- [作者原文](https://simon.peytonjones.org/assets/pdfs/build-systems-original.pdf)
- 实读：§4.2.2 Verifying Traces、§4.2.3 Constructive Traces（79:14–15）；§6.3非确定性；§6.5 Self-tracking（79:25）。
- 支持：保存实际依赖值/hash可决定是否重建；保存结果可支持共享复用；任务自身的公式改变也是依赖变化。
- 本项目推论：分别缓存原始输入、窗口拟合、过滤聚类和展示；缓存键必须覆盖实际读取的数据、代码、参数与数值环境。
- 边界：论文不证明当前依赖集合完备；未记录外部全局状态或随机性时，仅输入数组相同不能确保相同结果。不能通过随意删掉版本检查换取命中率。

## L5 — 数据库并发不能由“先查不存在再插入”保证

PostgreSQL Global Development Group，**PostgreSQL 18 Documentation, §13.2 Transaction Isolation**，在线官方文档，访问2026-11-13。

- [原文](https://www.postgresql.org/docs/18/transaction-iso.html)
- 实读：§13.2.1 Read Committed、§13.2.3 Serializable，包括40001重试和唯一约束冲突说明。
- 支持：普通隔离级别存在并发异常；Serializable成功提交表现为某种串行顺序，但应用仍须处理重试及约束冲突。
- 本项目推论：任务身份用唯一约束，任务/outbox提交用短事务；worker提交结果通过条件更新校验版本和租约代次。
- 边界：SQL事务不自动覆盖对象存储上传或外部HTTP派发；outbox是工程设计推论，不是本节已提供的完整实现。不可把长LPPL计算放进长事务。

## L6 — 并行随机实验要绑定稳定任务身份

NumPy Developers，**Parallel random number generation**，官方参考文档，访问2026-11-13。

- [原文](https://numpy.org/doc/stable/reference/random/parallel.html)
- 实读：SeedSequence spawning、Sequence of integer seeds，尤其unique/deterministically created IDs与不安全root_seed+worker_id示例。
- 支持：由稳定且唯一的任务ID及root seed构造可重复的随机流；进程调度编号不应替代实验身份。
- 本项目推论：bootstrap种子绑定窗口输入hash、replicate_id、方法版本；100次扩展为200次时，既有编号不改变，重复实验逐项保存。
- 边界：文档没有保证任意库版本/硬件/优化器实现都逐位相同；仍需固定RNG类型、分布算法、环境与数值执行策略。固定seed不是整个拟合流程确定性的充分条件。

## L7 — 数据日期与信息可得日期必须分开

Federal Reserve Bank of St. Louis, Research Division，**ALFRED Help**，官方在线说明，访问2026-11-13。

- [原文](https://alfred.stlouisfed.org/help)
- 实读：What is ALFRED；Release Dates与如何确定；vintage数据准确性核验。
- 支持：过去观测值会被修订；历史研究需要过去可得版本。发布日期优先源端，其次供应商，仍未知时使用FRED首次可得日期。
- 本项目推论：区分trade_date/period_end、source_published_at、first_observed_at、revision_id；用不可变vintage保留旧预测输入。
- 边界：ALFRED管理的是宏观时间序列；不能据此声称A股供应商保存历史复权因子或题材版本，也不能把今天补抓的旧行情当成当年真实已公开的预测证据。

## L8 — LPPL降维支持算法研究，不支持新一天直接沿用旧解

Vladimir Filimonov、Didier Sornette，**A Stable and Robust Calibration Scheme of the Log-Periodic Power Law Model**，arXiv:1108.0099v3，2013年6月10日；Physica A 392(17),3698–3707，DOI 10.1016/j.physa.2013.04.012。

- [原文](https://arxiv.org/pdf/1108.0099)
- 实读：§III旧拟合的多极值问题；§IV.A线性/非线性拆分（PDF第10–12页，式(13)–(17)集中于第11页）；§IV.B与上海指数样本讨论。
- 支持：把相位展开为C1/C2，可将搜索集中于tc、m、omega三个非线性参数，并解线性系数。
- 本项目推论：相同输入/配置的计算可缓存；优化算法比较应保持输入、约束与预算可追溯。
- 边界：论文没有给出新增一根日线后无需重拟合的精确更新法，也不证明warm start与完整搜索等价；其示例不能证明本项目阶段顶提前5日、10日窄窗口、抄底或任何失败模型恢复预测效力。

## 对上一版方案的文献约束修订

补充文献 L9 见文末；本文共9项。产品/数据官方资料另列在[产品方案](../product/2026-11-13-investor-workstation-plan.md)，不混作缓存算法论文。

1. “同请求零网络下载”收窄为：已有可信且仍有效的数据manifest时，可以零上游数据下载；manifest过期允许增量或轻量核验。优化器调用可要求0，不能把验证请求也禁止。
2. “只改过滤就零拟合”必须附条件：过滤不参与搜索/早停，且在既定选择语义下所需统计齐全。仍对每窗已选最优解判阈值可复用选优行；若改为从所有起点/局部极小中选合格候选，则需完整候选或补搜索，不能恢复从未保存的候选。
3. “窗口hash相同即复用”必须包括完整计算依赖与环境；不可只比较文件名、日期或最后一行。
4. “租约防重复”改为：可发生重复执行，但只有当前代次允许提交；对象文件不能在检查代次前覆盖共享路径。
5. “先显示缓存”需要单独的访问权限、源许可、freshness与金融提醒门控；不能把HTTP命中当最新市场证据。
6. “第一次可见”拆为首次生成、服务器首次观察、用户浏览器首次可见和可核验公开发布。文献不允许把任意一个字段替代所有其他字段。
7. “1–2秒可用”只能是限定硬件/网络/命中类型下的验收目标，需要报告p50/p95、样本数、冷暖缓存与错误率；本轮NOT_ESTABLISHED。
8. 这些文献支持工程设计和复现边界，不能升级LPPL预测准确率，也不能替代严格as-of外样本检验。

## L9 — 热点请求风暴与迟到缓存回填

Rajesh Nishtala et al.，**Scaling Memcache at Facebook**，NSDI 2013，pp.385–398。

- [出版页](https://www.usenix.org/conference/nsdi13/technical-sessions/presentation/nishtala)、[原论文](https://www.usenix.org/system/files/conference/nsdi13/nsdi13-final170_update.pdf)。
- 实读：§2架构（PDF第1–2页）；§3.2.1 Leases（第4–5页）；§8 Related Work（第12页，印刷页396）关于不保证持久性的说明。
- 支持：热点失效可引起重复昂贵读取；迟到回填可能写入旧值。与特定key绑定、在回填时校验的token有助于协调。
- 本项目推论：相同缺失任务合并，发布时验证代次，缓存与权威结果索引分离。
- 边界：论文的吞吐/延迟结果不适用于本项目；不据此要求Facebook规模的基础设施，不把其机制直接视作本项目已经实现的故障安全。

## 阅读和引证边界

本文是相关章节的定向阅读矩阵，不是穷尽性系统综述。所有项目迁移方案均标为推论；没有复制论文图表、全文或把其他系统的性能数字作为LPPL结果。论文存在并不解决上游金融数据的使用许可。
