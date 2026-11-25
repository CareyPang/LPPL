# LPPL 缓存、增量数据与等待优化方案

日期：2026-11-13。性质：**建议设计，交给 Devin 实现；本次没有实施、运行模型或部署**。

阅读顺序：[执行交接](../product/2026-11-13-devin-handoff.md) → 本文 → [对抗审查](../research/2026-11-13-cache-adversarial-review.md) → [文献核验](../research/2026-11-13-cache-literature.md)。产品与数据范围见[复盘和 ETF 方案](../product/2026-11-13-investor-workstation-plan.md)。

## 1. 决策与基线

**建议决策：先完成精确复用和任务恢复，再研究改变优化路径的加速。** 不减少窗口、种子或 bootstrap 预算来伪装缓存收益。不承诺冷启动秒出结果。

本轮单独读取远端 main：`fd11186da8a6028a05ec4efab667dee1e80127a1`；PR #67：`79ff53f2b85936afea4935a2c30dc5442f93a403`，open/draft、未合并。下面实现定位以 **PR #67 固定提交**为主，不能推导生产已部署。PR #50 的研究/设计分支不是 main。

证据用语：`VERIFIED`=指定源码或原始文档已检查；`PROPOSED`=建议设计；`NOT_RUN`=本轮未执行；`NOT_ESTABLISHED`=没有足够证据证明；`NOT_INSPECTED`=本轮没有检查。源码存在与生产生效分别记录。

用户指定完整周期 **1.5** 是后续研究基线要求。当前 main/PR #67 仍有多个规则，包含 `n_osc >= 2.5` 与 `osc >= 2.5`，不是已经统一到1.5。缓存工程必须保存现行规则身份；新研究配置另外版本化、并排验收，不能在缓存修复中静默切换阈值。[规则源码](https://github.com/CareyPang/LPPL/blob/79ff53f2b85936afea4935a2c30dc5442f93a403/research/features/lppls_rules.py#L20-L53)

## 2. 已有缓存为何仍然慢（VERIFIED：静态检查）

| 项目 | 当前行为 | 缺口与工程影响 |
|---|---|---|
| [Worker query](https://github.com/CareyPang/LPPL/blob/79ff53f2b85936afea4935a2c30dc5442f93a403/workers/stock-query/src/index.js#L314-L353) | 去重活动任务 | 完成后再次 POST 没有先命中完成结果；仍可能排队、启动环境、取数 |
| 同上 | 同股票内按 mode 去重 | 26/104周需求未比较覆盖范围，不能保证返回的活动任务满足请求 |
| [行情缓存](https://github.com/CareyPang/LPPL/blob/79ff53f2b85936afea4935a2c30dc5442f93a403/workers/stock-query/src/index.js#L277-L311) | 短期缓存及失败回退 | 不是持久化增量行情库 |
| [数据加载](https://github.com/CareyPang/LPPL/blob/79ff53f2b85936afea4935a2c30dc5442f93a403/research/pipeline/stock.py#L175-L200) | 每次拉因子及指定起点历史 | `cache.download` 名称不意味着已读取已有磁盘数据 |
| [拟合缓存](https://github.com/CareyPang/LPPL/blob/79ff53f2b85936afea4935a2c30dc5442f93a403/research/pipeline/stock.py#L649-L705) | 截止日/窗口/输入/代码匹配，补缺项 | hash含最大窗口及整个窗口清单；variant目录分开；写整份Parquet不解决并发丢更新 |
| [nightly batch](https://github.com/CareyPang/LPPL/blob/79ff53f2b85936afea4935a2c30dc5442f93a403/research/pipeline/stock_batch.py#L85-L95) | 调 predict 未传 cache_dir | 没有贯通用户查询的拟合缓存；不能声称三个入口已共享 |
| [前端 stale](https://github.com/CareyPang/LPPL/blob/79ff53f2b85936afea4935a2c30dc5442f93a403/frontend/app/stock-session.js#L42-L46) | 比较 main 整仓 source_sha | 纯文档/样式提交可能使结果被判版本落后；需要计算兼容版本 |
| [Trust](https://github.com/CareyPang/LPPL/blob/79ff53f2b85936afea4935a2c30dc5442f93a403/research/lppls/trust.py#L35-L68) | 每次重采样；窗口枚举序号作seed | 不是可按稳定replicate身份续跑的缓存；当前仅描述性证据 |

这些问题的延迟贡献 **NOT_ESTABLISHED**；没有把静态推断当性能剖析结果。

## 3. 缓存与事实仓库分离

| 层 | 内容 | 是否可丢弃 | 身份与边界 |
|---|---|---|---|
| 浏览器展示 | 最近K线、摘要、任务引用 | 可以重建 | 账户/权限分区、资产、价格口径、schema、artifact |
| 热点内存/Redis | manifest、热点响应、短状态 | 可以重建 | 不是任务唯一性或预测证据的唯一存储 |
| 原始数据档案 | 获准留存的raw、factor、源元数据及修订 | 按独立保留政策 | 来源、有效时间、可得时间、首次采集、内容hash |
| 科学计算产物 | 单窗口结果、完整attempt清单、bootstrap记录 | 冷数据可按政策分层 | 输入和全部算法依赖；与HTTP生命周期分离 |
| 任务与结果索引 | lease、outbox、覆盖范围、latest指针 | 持久化 | 数据库约束/事务；不依赖临时CI缓存 |
| 预测证据账本 | 发布回执、原结果、修订关系 | 不按展示缓存LRU清理 | 原生成/发布时点不因命中重写 |

GitHub Actions cache是可丢失的加速副本，不能承担事务合并或证据唯一存储。[官方说明](https://docs.github.com/en/actions/reference/workflows-and-actions/dependency-caching)

## 4. 数据增量：先固定快照，再计算

1. 规范化资产ID（市场/交易所/代码），先授权，再查允许访问的manifest。
2. 以交易所日历、个股交易状态及源最终性确定目标；不能仅凭本机15:30或最后一根bar判数据已最终发布。
3. raw不复权行情与factor分开保存；取缺失区间并重叠回看最近若干交易日。5–10日只是假设初值，需根据供应商修订特征验证；另设长历史核对。
4. 校验响应日期、分页总量、证券身份、单位、重复、OHLC关系、因子覆盖及未完成bar。
5. 形成不可变 `data_snapshot_id`；记录变更日期/字段/因子作用范围。相同内容幂等，不覆盖旧版本。
6. 任务固定读取这个snapshot。取数后数据再更新，不可让同一任务的不同窗口读取不同快照。
7. 对准确依赖切片重算hash，按差集规划计算；新结果发布前再校验snapshot、规则和任务身份。

上游支持start/end不必然意味着只传输增量；必须测请求次数、字节数、返回覆盖范围。若需全量请求因子或源不支持增量，应如实列出，不能声称网络请求为零。

**数据版本与预测发布证据分别记录**：`observed_live`（当时实际留存）、`historical_vintage`（外部可信旧版本及可得时间证据）、`reconstructed_latest`（用现在的历史版本重建）描述输入资料；三者均不能单独证明预测曾提前发布。真实提前发布须有原预测产物及可独立核验的发布时间、内容对应关系；当时留存或后来找回的外部原始档案均可提供证据，后来重算的结果不能充当原预测。发布证据也不自动证明输入符合严格as-of、结果可复现或预测有效。[ALFRED版本处理](https://alfred.stlouisfed.org/help)

因子生效日不等于因子发布时间。最新HFQ/QFQ不自动满足point-in-time；缺失因子不能用后来因子向前填后再标成严格历史输入。原始证据和计算规范化输入分别hash。

## 5. 依赖图与缓存身份（PROPOSED）

```text
raw/factor/证券状态/日历版本
  ├─ 校验与资格状态 ───────────────────────────────┐
  ├─ 精确时间/价格变换 → 单窗口搜索 → 候选集合       │
  │                                  ├─ 过滤/聚类 ─┤
  │                                  └─ bootstrap ─┤
  └─ OHLCV展示、事件/来源证据 ───────────────────────┤
                                                   ↓
                                      成品分析/显示/发布记录
```

**单窗口键建议**：资产ID、规范化输入t/y的hash、窗口起止、变换/缺失处理策略、方向、模型域（future/inside）、公式版本、边界、搜索网格/初值/seed、优化器、容差、预算/提前停止策略、必要的数值环境。

`unit=full_cycles` 与阈值必须显式记录；不能只写 `osc=1.5`。数值环境至少记录精确依赖版本，并按实际复现风险记录BLAS、线程数、运行平台。相同seed不证明跨环境逐位相同。

规范化序列化需预登记：字段顺序、字节序、时间单位/时区、浮点格式、缺失/NaN/Inf策略、重复bar处理。不得为提高命中率随意四舍五入。拒绝无效输入后才查可用产物。hash证明字节身份，不证明来源可信、授权或统计正确。

**完成结果键不能只复用单窗口价格hash**。现代码资格还使用high/low、约505根样本、ST状态；展示还依赖日历和证据状态。这些必须进入独立资格/成品依赖。[资格逻辑](https://github.com/CareyPang/LPPL/blob/79ff53f2b85936afea4935a2c30dc5442f93a403/research/pipeline/stock.py#L361-L425)

分离：`fit_hash`、`candidate_set_hash`、`filter_cluster_hash`、`eligibility_hash`、`presentation_hash`、`artifact_hash`。相同收盘价而high/low或ST变化，可复用数学拟合，但不能无条件复用整份分析。

源码提交SHA继续用于信任与溯源，另加计算兼容版本；不能删除可信源码检查。复用结果保留原产生SHA，新的展示封装记录自己的assembly版本，不冒充原产物来自新提交。

### 复用边界

| 变化 | 原始拟合 | 其他处理 |
|---|---|---|
| 相同输入/配置/兼容环境 | 精确命中 | 完成结果其余依赖也需匹配 |
| 新增一个完整交易日 | 新截止日的窗口通常重新拟合 | 未变化的旧截止日保持 |
| 16窗口扩到20窗口 | 在每窗搜索配置独立且相同时复用16个 | 重新聚合20窗口；若原预算随总窗口数变化，则不能保证只算4个 |
| 修订旧bar/因子 | 计算影响闭包，重算受影响窗口 | 资格、展示、证据版本相应更新 |
| 仅成交量变化 | 仅用t/y的拟合可复用 | 量柱/资金/质量规则若依赖它则更新 |
| 改过滤阈值/聚类 | 若仍作用于每窗已选最优解、所需统计齐全且搜索未受规则影响，可复用现有选优行 | 若改为在所有起点/局部极小中选择合格候选，则须有完整候选集合或补搜索；不能把选优一行冒充全部候选 |
| 改CSS/文案 | 不应触发拟合 | 展示资源更新 |
| 改优化器/域/边界/seed/预算 | 拒绝不兼容拟合 | 保留旧结果供并排研究 |

## 6. 随机、失败与断点恢复

先明确产物语义与选择策略，不要求无限穷举。若只对每窗已选最优解做后处理，完整的所需统计即可支持阈值重评；不把保存全部attempt作为所有后处理的前置条件。为支持搜索断点恢复、预算扩展或改为跨起点挑选合格候选，应保存相应预算内的attempt状态与候选；主结果+manifest说明哪些attempt已完成、保存到什么粒度。旧缓存缺失的信息不能凭空恢复。

每窗或小批完成写不可变记录，manifest事务提交。合法的“不通过结构过滤”可以缓存；HTTP错误、超时、数值崩溃和不完整任务分别记录，不能转成“无泡沫”。更改搜索预算/重试策略必须产生新实验身份。

bootstrap按基础拟合/数据/重采样方法/replicate_id/随机流版本标识。100→200只补后100项的条件是：前100编号和生成策略稳定，重复编号不计作独立样本，新增样本不会改变旧编号的抽样。区块bootstrap、iid残差bootstrap不可混池；调整种子映射本身是版本变化。[NumPy并行随机数](https://numpy.org/doc/stable/reference/random/parallel.html)

昨日解warm start、减少全局搜索、提早停止属于独立算法实验，不属于精确缓存。在未比较输出和失败率前不纳入默认服务。LPPL校准文献不能证明本仓库任何优化器组合总优或预测可靠。

## 7. 任务去重、发布与迁移

建议顺序：授权 → 轻量manifest校验 → 完成结果 → 已有覆盖任务 → 事务创建任务/outbox → 执行。

请求身份、计算身份和输出身份分别定义。26周/104周用明确的截止日集合表达；可以共享子任务，不能返回26周job却标成104周完成。顶/底、用户私有参数、数据vintage不能误合并。

数据库唯一约束管理需求；outbox让派发可重试且沿用job_id。工作者持租约与递增代次，写入端/CAS检查代次；过期工作者不得覆盖新结果。SQL事务不包含HTTP派发或对象存储写入：先写不可变对象、校验，再事务发布manifest；孤儿对象可按独立回收政策处理。最新指针比较目标数据/配置/代次，不能仅按“最后完成时间”。

系统可在故障下重复执行，但应保证只接受有效代次的提交；不要承诺端到端exactly-once。缓存命中也不能绕过用户权限或独立请求限流。[Chubby §2.4/§2.6](https://www.usenix.org/legacy/event/osdi06/tech/full_papers/burrows/burrows.pdf)、[PostgreSQL事务隔离](https://www.postgresql.org/docs/18/transaction-iso.html)

**迁往长驻服务的阻断项**：现有 `_FIT_LOGP`、`ALLOW_INSIDE` 是可变全局状态；不得把现有串行函数直接交给多线程同时分析不同股票。先保持进程隔离/显式上下文，验证输入不串扰。股票名称/ST查询的进程内lru_cache没有业务TTL，需加入状态时点和刷新策略。[工作者状态](https://github.com/CareyPang/LPPL/blob/79ff53f2b85936afea4935a2c30dc5442f93a403/research/pipeline/stock.py#L47-L104)、[名称缓存](https://github.com/CareyPang/LPPL/blob/79ff53f2b85936afea4935a2c30dc5442f93a403/research/pipeline/stock.py#L320-L359)

初期：API、隔离计算进程、SQL索引/任务、文件或对象存储即可；不先要求购买Redis集群。当前任务保留容量，历史切块低优先级，避免每个job再开满CPU导致过量并行。nightly/current/history同一结果索引、同一科学身份。

## 8. 浏览器与HTTP

IndexedDB存最近行情/结果，localStorage仅轻量偏好和任务引用。共享科学产物与私有账户内容分区；切换账号不可展示上一账户私有内容。浏览器缓存可被清除，不是审计账本。[MDN](https://developer.mozilla.org/en-US/docs/Web/API/Storage_API/Storage_quotas_and_eviction_criteria)

完整不可变artifact可长缓存；latest指针短缓存并验证；任务状态短缓存。公共CDN只承载明确可公开的内容，hash URL或job_id不是权限控制。私有数据、收费权限和用户回执先授权，按协议设private/no-store等策略。

HTTP Age/TTL/ETag用于表示缓存；交易日、源最终性、数据修订和模型版本属于业务新鲜度。304不代表今天数据已经齐全。stale-while-revalidate/stale-if-error必须在源策略允许范围内，不可盖过must-revalidate等限制。[RFC9111 §4.2–4.3/§5.2](https://www.rfc-editor.org/rfc/rfc9111.html)、[RFC5861 §3–4](https://www.rfc-editor.org/rfc/rfc5861.html)

UI分开显示 `result_status`（fresh/stale/absent/version_mismatch）和 `job_status`（queued/running/ready/failed）。先显示有截止日的旧结果；正式新提醒不得因读取旧缓存而重复触发。离线仅显示离线状态；回放不得发送真实通知。

按钮：查看分析（不强制拟合）、更新到最新（if_changed）、历史回放（先读已完成范围）、高级重新计算（显式新实验）。历史JSON按manifest/视窗分页，不每次进站下载全部104周。

页面隐藏暂停轮询，回前台先查原job；状态退避和抖动按实测配置。进度显示reused/completed/pending/failed，不伪造百分比或ETA。

## 9. 性能实验与保留政策

**NOT_RUN**：本轮未做新性能、故障注入或数值一致性实验。以下是给Devin的验收方案。

分别测冷启动、浏览器热、服务端热、拟合热但成品冷、新增一日、因子修订、100同key并发、多个不同资产、源超时、进程重启。固定机器/依赖/数据/参数，交错运行对照；记录样本数、原始记录与p50/p95，不把同一缓存连点当独立冷样本。

阶段指标：manifest校验、源下载字节/次数、排队、环境启动、缺失窗口数、优化器调用、数值计算、bootstrap、结果可读、浏览器可见、失败率。分别记录端到端与服务端时间。

暖缓存已有内容1–2秒可见只是待确认目标；在声明网络、设备、缓存层和权限路径的测量条件前，不能称SLA或已达成。冷任务不预报未测秒数。缓存一致性要求：身份/日期/分类结果一致；数值采用事先声明的严格比较与边界案例检查，不能事后放宽容差掩盖变化。

增量复用优先减少重复工作，不证明预测能力提高。历史重放、真实提前发布、失败模型的结论边界不因缓存更快而改变。

保留策略区分热缓存、可重建科学中间产物与受保护证据；按实际字节量和来源许可制定容量与冷存储策略。COS版本控制可辅助误覆盖恢复，不能替代应用的append-only/访问控制/审计证明。本轮不购买、不迁移、不删除任何用户资料。
