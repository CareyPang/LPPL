# 缓存方案独立对抗性审查

审查日期：2026-11-13。只读参考版本：PR #67 `79ff53f2b85936afea4935a2c30dc5442f93a403`；main `fd11186da8a6028a05ec4efab667dee1e80127a1`。未改业务代码，未运行模型，未执行真实网络行情采集或性能实验。下列修正是设计建议；不意味着漏洞已修复。

结论：保留“成品先命中、增量行情、窗口级缓存、检查点、共享任务”的方向，但不能以缓存命中作为数据最新、预测提前公开或数值正确的证明。当前证据不足以批准部署或宣称性能提升比例。

## 证据分类

- VERIFIED-CODE：已核对所列源码的行为/依赖，并非线上复现。
- DESIGN-RISK：反例针对拟议迁移或缓存设计，未声明当前线上已发生。
- NOT_ESTABLISHED：性能、预测效力、源历史修订覆盖及授权边界等尚无实测。
- 严重度“阻断/高/中”表示实施优先级，与产品路线 P0–P3 不同。

## 主要发现与纠正

| ID | 严重度与证据 | 最强反例 | 修订后的要求 | 验收反例 |
|---|---|---|---|---|
| A01 | 阻断 DESIGN-RISK；相关源码 VERIFIED-CODE | 直接把现有Python入口搬到长驻多线程服务。A线程设置`_FIT_LOGP=A`后，B线程改为B，A继续按A的任务元数据拟合B的价格。`ALLOW_INSIDE`也为全局。 | 独立进程隔离请求，或先将实际t/y及模型配置变成显式不可变函数参数；不能在线程池共享当前可变全局。 | 两资产交错执行、正负泡沫交错执行，与串行隔离基线对比每个输入hash及结果。未通过前禁止长驻线程并发。 |
| A02 | 阻断 DESIGN-RISK；因子读取与回填 VERIFIED-CODE | 用今日取得的修订因子重算过去，hash完全一致地命中“新版历史结果”，却放入当年真实预报。`effective_date<=bar_date`仅说明因子生效日期，不证明当时已知；缺失因子还会bfill。 | 历史原发预测不可变；保存因子原文、首次观察、供应商发布时间、版本。区分修订后历史重放、可证明的当时资料及真实发布。因子不足需显式失败/降级，不能默认为PIT。 | 设T+30修订T−200的因子；T时回放不得读入该版本。缺早期因子的bfill必须触发明确证据状态。 |
| A03 | 高 VERIFIED-CODE | 只用close hash复用整个成品，但high/low修订改变一字板异常占比，或名称变ST导致统计资格变化。 | 原始数学拟合、资格判断、过滤聚类、日历映射、展示及递送各有依赖；close不变只能在依赖允许时复用原始拟合。 | close相同而high/low、ST、日历变化：优化器0调用，资格/映射/成品更新，原发结果不被覆盖。 |
| A04 | 高 VERIFIED-CODE | 文档称“保持完整周期1.5”，但PA67/main含`osc`与`n_osc`多套规则、Trust旧口径。用一个字符串版本会混用不同门槛。 | 1.5是用户后续研究基线约束，不能声明此分支已统一。清单逐项保存单位、阈值、规则ID、方向及inside设置；迁移未经核对不得改成默认1.5。 | 同一数值1.5但单位不同必须产生不同规则key；不同研究/主线配置不得互相命中。 |
| A05 | 高 VERIFIED-CODE + DESIGN-RISK | 当前input hash包含整套windows和最大窗口，所以改大窗口让不受影响小窗口失效；反过来，过度精简新hash又可能遗漏搜索预算、符号变换或预处理。 | 单窗key覆盖真实t/y输入、模型与有效搜索配置；另有输入来源manifest和许可域。不能仅按`code/asof/n`命中，也不应为了命中而从数据中删除依赖字段。 | 同长度但起止、缺失处理、参数边界、方向、随机起点数变化应miss；增加无关窗口应hit原窗口。 |
| A06 | 高 VERIFIED-CODE | 现有缓存每窗只留最小SSE等结果，不是每个优化起点的账本。改候选筛选定义后，声称可恢复曾被丢弃的候选。 | 明确缓存语义。当前搜索检查未发现以过滤通过为条件的提前停止；纯后处理可以在已存结果语义上重做，但不能据此声称恢复所有候选。将来如搜索受过滤/早停影响，必须重新拟合。 | 测试“只改阈值”和“改候选选择/早停”两种变更；后者不得伪装成后处理命中。 |
| A07 | 高 VERIFIED-CODE | 非零bootstrap的seed由窗口枚举索引决定；16→20窗口或排序变化改变既有窗口seed。只保存比例/中位数，无法可靠续接replicate100–199。 | 原窗口hash＋稳定replicate ID＋明确PRNG/环境确定随机流；保存重复实验身份和必要结果。当前bootstrap续跑属新增功能，不能只拼接两个四舍五入后的比例。 | 1批200次与2批100次、换进程数、打乱任务顺序、进程中断恢复应得到同一replicate集合和相同聚合。 |
| A08 | 高 VERIFIED-CODE | 完成后再次POST仍创建新job；历史26周活动任务被104周请求复用，返回范围不足。 | 查完成结果→活动任务→事务派发。任务请求范围、实际已覆盖范围及可复用单日期产物独立；只能在覆盖满足时答复已完成。 | 完成后的相同分析0新增计算；26周/104周并发准确补差集，不把旧任务job_id当作范围满足的证明。 |
| A09 | 阻断 DESIGN-RISK | A租约过期，B接管并发布新数据；A迟到写回覆盖B。或SQL先更新latest，再发现对象上传失败。 | 期限本身不构成写入保护；接收写入的存储层必须验证fencing token/期望版本。先写不可变产物并验证，再事务提交索引；latest同时约束数据修订版本与模型配置，不能只看完成时间。 | 暂停A→B接管发布→A恢复；旧token提交必须拒绝。对象写入失败不能留下ready指针。 |
| A10 | 高 VERIFIED-CODE + DESIGN-RISK | 两进程从同一Parquet旧快照出发，各自追加后原子rename，后写覆盖前写新增。Actions前缀恢复也不自动合并并行cache。 | 原子文件替换只防半文件，不防丢更新；唯一键事务索引或带版本的manifest合并。缓存可删，证据和任务状态不可只存在Actions cache中。 | current/history同时计算不相交窗口，最终清单包含并集；允许重复执行，不允许缺失/错误覆盖。 |
| A11 | 高 DESIGN-RISK | 将带用户笔记、任务订阅或付费权限的JSON按股票公共缓存；用户B命中用户A内容。 | 数学复用身份与授权域分开；默认公有数据可共用计算，私有输入必须在受控namespace内。每次访问授权，CDN不得把认证响应错误标为public；退出账号处理本地私有缓存。 | 不同账号同股票、私有参数、上传数据、不同权益等负例。job_id不是授权凭据。 |
| A12 | 高 DESIGN-RISK | 只回看5–10日，漏掉半年以前历史修订；行情同日期更新但manifest仍称新鲜。 | 5–10日是成本假设，不是完备性保证；增加源修订水位/因子版本监控和周期全量核对。定义freshness覆盖的声明，无法确认则unknown。 | T−200旧bar修订但近10日不变；系统不得以最近区间没变宣布全历史未变。 |
| A13 | 高 VERIFIED-CODE + DESIGN-RISK | 无TTL的名称缓存将ST身份永久固化；同日参考日历缓存不响应迟到修订。短期脚本搬成长驻后延长缓存生命周期。 | 长驻迁移要审计所有lru_cache和模块状态；把元数据及日历更新/失效策略列入依赖清单，不能只增加HTTP缓存。 | 同进程内供应商名称变更、负缓存恢复、日历补录；重新装配状态必须更新。 |
| A14 | 高 DESIGN-RISK | 成品命中时创建新job或改generated_at，让同一科学结果出现新的“首次可见”；或把首次Worker读到当首次公开。 | scientific_artifact_id、execution_job_id、delivery_receipt_id分离；共享结果保留原始生成与输入版本。浏览器可见、服务端读到、实际发布分列，禁止互相回填。 | 同artifact多job/多浏览器重看，科学版本不变；每用户本地可见记录不越权共用；没有服务器发布证据仍NOT_ESTABLISHED。 |
| A15 | 中 NOT_ESTABLISHED | 用“再查0网络”和“p95 1–2秒”作为无条件保证；事实上需确认新交易日、权限、数据源健康。 | 0新增优化任务是可测目标，网络仅在有效manifest/授权缓存内才可能为0。1–2秒须指定网络、设备、payload、冷热比例、并发与时间范围；计入所有失败与超时。 | 冷/热/部分命中/源慢/源失败/周末/停牌分层；记录p50/p95、错误率、首个可用结果与最新结果两个时间。 |

## 代码证据位置

- `research/pipeline/stock.py:47–59,95–100`：共享`_FIT_LOGP`、`ALLOW_INSIDE`；多进程池与串行路径不同。
- `research/pipeline/stock.py:182–194`，`research/data/tencent_sina.py:107–130`：最新因子抓取、生效日映射、缺失bfill。
- `research/pipeline/stock.py:361–425`：high/low、ST、505样本与参考交易日历影响资格。
- `research/features/lppls_rules.py:28–53,92–95`，`research/lppls/trust.py:24–26`：osc/n_osc与不同阈值并存。
- `research/pipeline/stock.py:429–479,670–705`：代码hash、最大窗口hash、整批计算后落盘、Parquet并发风险。
- `research/features/lppls_scan.py:97–120`，`research/optim/optimizers.py:128–170`：固定seed、网格＋TRF各起点、保存最小SSE结果。未见按过滤通过提前停止，因此不能把该假设写成当前确认缺陷。
- `research/lppls/trust.py:35–46,54–68`：按窗口枚举seed、无逐replicate落盘、聚合/四舍五入。
- `workers/stock-query/src/index.js:314–353`：按mode活动任务去重、未先查完成结果；历史范围未比较。
- `research/pipeline/stock.py:266–274,320–358`：参考日历与名称LRU，名称没有时间键，名称参与ST判定。
- `frontend/app/stock-visibility.js:5–9,39–48`，`workers/stock-query/src/index.js:240–254`：浏览器身份和Worker读证据；当前代码已明确非公开首发，后续缓存改造必须保留此边界。

## 一手文献与适用边界

1. **Nishtala et al. (2013), Scaling Memcache at Facebook, NSDI.** [原论文](https://www.usenix.org/system/files/conference/nsdi13/nsdi13-final170_update.pdf)，§2、§3.2.1。论文讨论缓存不是权威存储、stale set与请求风暴，并用带token的写入核验协调回填。它支持A09/A10的机制选择，不能证明本项目故障安全或应采用Facebook规模的架构。
2. **RFC 9111 (2022), HTTP Caching.** [标准](https://www.rfc-editor.org/rfc/rfc9111.html)，§3.5、§4.2.4、§4.3、§7。支持区分认证响应、共享缓存、过期内容和资源验证；不替本项目决定金融数据“最新交易日”或授权政策。ETag匹配不能证明源数据覆盖完整。
3. **NumPy, Parallel random number generation.** [官方文档](https://numpy.org/doc/stable/reference/random/parallel.html)，Independent/Deterministic ID与SeedSequence部分。支持稳定任务ID与根seed组合的独立随机流设计；项目应使用replicate语义ID，而不是可变worker编号/窗口枚举。该规范不保证LPPL优化数值跨BLAS/平台完全一致，也不证明iid残差bootstrap适合所有金融序列。

## 审稿裁决

本表A01–A15由独立技术审查提出，再由主审对照源码复核；下面B01–B07补充产品/证据审查。它们是22项合并后的审查记录，不是22个已在生产复现的缺陷。

建议“有条件接受为设计交接，实施与上线待验收”。最低阻断项：A01长驻并发隔离、A02历史vintage边界、A03依赖分层、A04规则口径清单、A08范围覆盖、A09版本保护、A11权限隔离、A14证据身份。不要把此次对抗性分析写成这些测试已经通过，也不通过增加免责声明替代实现验收。

加速不构成预测准确性证据；任何H1/H2/H3、Q2、MPL、Ising、Q-DD2、PPE失败结果以及未校准LPPL区间均不得因缓存优化升级成可用预测概率。

## 产品与既有表述纠正

| ID | 严重度与证据 | 反例/发现 | 修订与验收 |
|---|---|---|---|
| B01 | 高 VERIFIED-CODE | 旧报告称浏览器可见记录最多200条，但当前文件加入rows后直接setItem，没有裁剪；身份含job/generated/source，非稳定科学hash | 明确撤回“200条已实现”。容量上限、迁移和产物/交付/用户回执身份由Devin单独实施测试，当前代码未修复 |
| B02 | 高 VERIFIED-CODE + DESIGN-RISK | ETF总份额增加的世界可以对应不同买方，机构也可在二级市场购买而份额不变；份额差×收盘价无法识别机构 | 份额、申赎估算、具名披露、官方事件分层；不显示无证据的每日国家队净买入 |
| B03 | 高 VERIFIED-CODE | ETF持有人选择最新report_date，缺原始发布日期；后来的报告可能进入更早回放 | 保存period_end/published_at/first_observed；未披露不等于0；严格回放排除时点未知资料 |
| B04 | 高 VERIFIED-CODE | 最后两条非空份额可能跨日；部分缺失合计、YTD覆盖不足、同日快照覆盖会误导 | 保存from/to/gap、共同日期及valid/expected，显示部分合计；append-only修订；两个样本不证明年度覆盖 |
| B05 | 高 NOT_ESTABLISHED | 官网可访问不能推导自动留存/派生/展示许可，也不能代表目标腾讯云或大陆网络稳定 | 使用条件和技术网络逐数据集分开记录；未知不写禁止，也不写已许可；未通过不启动生产源 |
| B06 | 中 VERIFIED-DOCUMENT | TradingView官网回放/告警不随嵌入图表库获得；开盘啦教程不是内部热度算法规格 | 自建回放/告警协议与可解释统计；明确库许可和自有datafeed，产品等价性未建立 |
| B07 | 高 VERIFIED-METADATA + NOT_INSPECTED | PA50研究、PA67异步代码、main、本机演示与生产可能被混称“完成” | 固定各自SHA/状态；部署单独核验。缓存实验不能证明至少提前5日，当前发布字段null不能改写成真实预报证据 |

### 补充固定源码定位

- [PA67浏览器账本](https://github.com/CareyPang/LPPL/blob/79ff53f2b85936afea4935a2c30dc5442f93a403/frontend/app/stock-visibility.js#L5-L51)：身份与未裁剪写入；客户端证据明确为NOT_ESTABLISHED。
- [Worker首次观察](https://github.com/CareyPang/LPPL/blob/79ff53f2b85936afea4935a2c30dc5442f93a403/workers/stock-query/src/index.js#L240-L254)：public_first_published_at为null。
- [ETF份额估算与缺失合计](https://github.com/CareyPang/LPPL/blob/79ff53f2b85936afea4935a2c30dc5442f93a403/research/data/nt_etf.py#L147-L165)、[最新持有人](https://github.com/CareyPang/LPPL/blob/79ff53f2b85936afea4935a2c30dc5442f93a403/research/data/nt_etf.py#L197-L205)、[快照写入](https://github.com/CareyPang/LPPL/blob/79ff53f2b85936afea4935a2c30dc5442f93a403/research/data/nt_etf.py#L362-L368)。

## 审查处理账本

- A01–A15与B01–B07的修订要求已写入本次设计与验收计划；**实现全部仍待Devin交付**。
- 未将“当前搜索按通过过滤早停”作为已确认缺陷；A06保留为候选保存语义与未来搜索变更约束。
- 未将200条上限、统一1.5、三个入口缓存共享或1–2秒性能写为已完成。
- 未把本轮静态反例写成故障注入通过。性能、并发恢复、跨环境数值、实际许可/网络和预测实用价值均未建立。

[执行交接与T01–T18验收](../product/2026-11-13-devin-handoff.md)；[完整缓存方案](../architecture/2026-11-13-cache-and-incremental-analysis.md)；[文献适用边界](2026-11-13-cache-literature.md)。
