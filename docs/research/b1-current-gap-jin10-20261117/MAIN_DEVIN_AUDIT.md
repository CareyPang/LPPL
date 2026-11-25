# 最新 main / Devin 改动核验与 B1 复用清单

核验日期：2026-11-17（Asia/Singapore）。本文件为只读代码、GitHub 元数据及有限既有单元测试审查；没有运行 LPPL 拟合，没有提交业务代码、触发计算、合并、部署或发布。

**结论：行情先显示、当前与历史计算分离、stale、主次聚类、事件定位等基础能力已存在。下一交付应补齐两个资产的连续路径和证据身份，不能重新实现已有模块。最明确的缺口是目录返回状态、过时异步请求的失败防护、图上候选与证据之间的稳定定位，以及生产结果实际口径的说明。封包前 #121 已由外部合并，基础切股清事件补丁应直接复用，不再安排等待合并或重复开发。**

## 1. 固定基线与证据等级

| 对象 | 本轮固定版本／状态 | 边界 |
|---|---|---|
| 初次审查 main | `60818b428396336fc99aae3076d4a918089a81d3`；最后提交为已合并 #120 | 本文主体固定源码与 85 项测试的基线；文件内容核验不代表运行中的 Worker 或 Pages 一定是同一版本 |
| 封包前 main | `b69384656210cc3610e58733426ce22bc8a69d6e`；已包含 #121 | 已独立读取比较结果及全部 3 个变化文件；本轮没有对该 SHA 重跑测试，详见第 10 节 |
| stock-results | `b13639ca76eb719bd8c62ecb318e2d85cfe10124`；分支提交时间 `2026-11-17T01:52:30Z` | 数据分支与代码 main 分开核验 |
| #121 | 已合并；head `dcaef2252c93248a5cc66e92505a715bfd02267a`，merge `b69384656210cc3610e58733426ce22bc8a69d6e` | GitHub `merged_at=2026-11-17T03:25:24Z`；外部操作，本审查没有合并 |
| #118 | open，非Draft；head `2e529af11d201ef61567a89ce86f9b08cd9e5309` | 图表试验页，未接入生产导航 |
| 既有方案PR #110 | 文档分支 | 实施须基于最新业务main，不能从旧文档分支复制陈旧业务代码 |

标签约定：`VERIFIED · CODE`=实际读到固定源码；`VERIFIED · DATA`=固定Git数据文件字段核验；`VERIFIED · TEST`=本轮独立运行所列测试；`VERIFIED · CI`=读到GitHub相应检查结果；`PR 作者报告`=PR文案自述，不能升级为独立验收；`PROPOSED / NOT_RUN`=给Devin的任务；`NOT_INSPECTED`=未执行现场验收。下文未特别标注的建议均为PROPOSED。

正文保留 `60818b4…` 固定链接便于复核原审查。封包前比较确认除第 10 节列出的 3 个前端文件外没有其他变化；发生变化的文件在第 5.2、10 节另给 `b693846…` 证据。测试计数和原有 CI 记录仍按各自提交归属，不能移记到封包前新 main。

适用规则已读：[frontend/AGENTS.md](https://github.com/CareyPang/LPPL/blob/60818b428396336fc99aae3076d4a918089a81d3/frontend/AGENTS.md)。业务数据只能通过`lppl-data.js`；不在前端拟合；Open Design不直接改该数据层。具体改动由Devin按现有职责实施。文档中的旧证据限制与#120后的逐尺度展示契约需同步校准，但不能以设计任务放开失败概率或目标价。

## 2. 已有能力：必须复用

| 流程环节 | main 实际代码 | 已建立什么 | 下一步 |
|---|---|---|---|
| 列表与资产身份 | [stock-catalog.js:13](https://github.com/CareyPang/LPPL/blob/60818b428396336fc99aae3076d4a918089a81d3/frontend/app/stock-catalog.js#L13) | 目录规范化、类型/板块/所属指数/发布状态筛选、排序、自选；指数链接到`index.html?code=sh000001`，个股到`stock.html?code=600519` | 复用，不再造一份目录；保持交易所前缀与类型，不能把上证000001当作深圳000001个股 |
| 同页打开个股 | [stock-page.js:28](https://github.com/CareyPang/LPPL/blob/60818b428396336fc99aae3076d4a918089a81d3/frontend/app/stock-page.js#L28) | `LPPL.catalog()`与`LPPL.stock.index()`并行取数，目录点击个股提交已有搜索；结果显示后隐藏目录 | 补显式返回路径及状态恢复 |
| 唯一数据入口 | [lppl-data.js:180](https://github.com/CareyPang/LPPL/blob/60818b428396336fc99aae3076d4a918089a81d3/frontend/app/lppl-data.js#L180) | 静态latest/history、Worker行情、查询、状态和远端结果分别已有方法 | 页面不得直接拼数据文件或另加接口绕开此层 |
| 行情先可用 | [stock-session.js:249](https://github.com/CareyPang/LPPL/blob/60818b428396336fc99aae3076d4a918089a81d3/frontend/app/stock-session.js#L249) | latest、remote latest、market并行，各自成功即emit；行情响应可先渲染 | 独立验证真实网络路径及冷/热缓存，不再实现第二套调度器 |
| 历史不阻塞当前 | [stock-session.js:273](https://github.com/CareyPang/LPPL/blob/60818b428396336fc99aae3076d4a918089a81d3/frontend/app/stock-session.js#L273) | 已有历史文件的读取不进入当前就绪屏障；仅显式history才发历史计算 | “读取已有history”与“触发104周计算”分开计数 |
| 默认当前计算 | [Worker:1154](https://github.com/CareyPang/LPPL/blob/60818b428396336fc99aae3076d4a918089a81d3/workers/stock-query/src/index.js#L1154)、[stock-session.js:183](https://github.com/CareyPang/LPPL/blob/60818b428396336fc99aae3076d4a918089a81d3/frontend/app/stock-session.js#L183) | 默认`mode=current`、`history_weeks=0`；显式history仍默认104周；前端已有“生成104周回放”按钮 | 旧“默认104周导致等待”问题在该源码版本已修，验收回归即可 |
| 状态与失败保留 | [stock-session.js:145](https://github.com/CareyPang/LPPL/blob/60818b428396336fc99aae3076d4a918089a81d3/frontend/app/stock-session.js#L145)、[Worker:946](https://github.com/CareyPang/LPPL/blob/60818b428396336fc99aae3076d4a918089a81d3/workers/stock-query/src/index.js#L946) | queued/current_running/current_ready/history_running/publishing/stale/failed等；刷新失败保留旧结果、截止日和原因 | 复用状态映射，补真实场景验收；不能把没有合格拟合写成请求失败 |
| 任务恢复与去重 | [stock-session.js:73](https://github.com/CareyPang/LPPL/blob/60818b428396336fc99aae3076d4a918089a81d3/frontend/app/stock-session.js#L73)、[Worker:860](https://github.com/CareyPang/LPPL/blob/60818b428396336fc99aae3076d4a918089a81d3/workers/stock-query/src/index.js#L860) | 本地保存任务ID；Worker复用兼容已发布结果和活跃任务；重进页面可恢复 | 不因返回列表/切换页签重复POST |
| K线、成交量与未来空位 | [stock-view.js:44](https://github.com/CareyPang/LPPL/blob/60818b428396336fc99aae3076d4a918089a81d3/frontend/app/stock-view.js#L44)、[stock-view.js:906](https://github.com/CareyPang/LPPL/blob/60818b428396336fc99aae3076d4a918089a81d3/frontend/app/stock-view.js#L906) | 已有Canvas图、未来交易日空位、尺度区间、多簇轨道数据；未来没有伪价格/成交量 | 复用现有图；本次不换库 |
| 主簇和次级簇 | [top-clusters.js:14](https://github.com/CareyPang/LPPL/blob/60818b428396336fc99aae3076d4a918089a81d3/frontend/app/top-clusters.js#L14)、[stock.html:1113](https://github.com/CareyPang/LPPL/blob/60818b428396336fc99aae3076d4a918089a81d3/frontend/stock.html#L1113) | 逐尺度读取主/次簇，日期与占比前置；旧结果明确“未分簇”；无区间有完成空态 | 补图带→相同簇的证据定位；不另做浏览器聚类 |
| 当前报价与模型价格区分 | [stock-header.js](https://github.com/CareyPang/LPPL/blob/60818b428396336fc99aae3076d4a918089a81d3/frontend/app/stock-header.js)、[stock-view.js:802](https://github.com/CareyPang/LPPL/blob/60818b428396336fc99aae3076d4a918089a81d3/frontend/app/stock-view.js#L802) | 头部实际成交价、模型截止和旧结果状态已有实现 | 继续统一单位/复权口径，无需再写报价组件 |
| 图上定位与历史模式分开 | [stock.html:1253](https://github.com/CareyPang/LPPL/blob/60818b428396336fc99aae3076d4a918089a81d3/frontend/stock.html#L1253)、[stock-view.js:432](https://github.com/CareyPang/LPPL/blob/60818b428396336fc99aae3076d4a918089a81d3/frontend/app/stock-view.js#L432) | “图上查看”只定位；“回到当时”选兼容历史帧、截断未来行情；横幅标历史补算非当时发布 | 复用；不通过改版本元数据强行让不兼容历史可用 |
| 首次可见的基础记录 | [stock-visibility.js:23](https://github.com/CareyPang/LPPL/blob/60818b428396336fc99aae3076d4a918089a81d3/frontend/app/stock-visibility.js#L23) | 浏览器可见、在视口、两帧后写本地`first_visible_at_client`，标客户端时钟未验证 | 复用，不把它升级成公开发布时间或真实预测提前量证明 |

以上均为`VERIFIED · CODE`，不是完整生产闭环验收。

## 3. 两个演示资产的数据现状

### 上证指数

- `VERIFIED · DATA`：main的`web/mock/data/sh000001_latest.json`截至2026-10-30、版本`prereg_v1.7_v2`；不能据此断言线上停在10月30日。
- `VERIFIED · DATA`：[stock-results的index/sh000001_latest.json](https://github.com/CareyPang/LPPL/blob/b13639ca76eb719bd8c62ecb318e2d85cfe10124/index/sh000001_latest.json)截至2026-11-16、版本`prereg_v1.7_v2.1`；该文件仍没有`top.scale_clusters`，`scale_windows=[]`。独立复核还确认`top.window`两端为null、scenarios为空、六档box均为0；因此无当前区间的判断并非仅凭缺少分簇字段。
- `VERIFIED · CODE`：[build_site.sh:11](https://github.com/CareyPang/LPPL/blob/60818b428396336fc99aae3076d4a918089a81d3/scripts/build_site.sh#L11)构建会叠加stock-results，包含index最新数据。因此“代码已合并”“数据分支已有新文件”“本浏览器实际读到哪个文件”是三件事。B1必须记录响应数据hash和截止日，不只截页面。
- `PROPOSED`：本轮当前无候选也可以完成真实空态闭环；要演示图带与证据，另选已有、清楚标识日期和历史模式的固定结果。不得为了演示现造“今天的顶部区间”。

### 贵州茅台

- `VERIFIED · DATA`：[stock-results/stock/600519.json](https://github.com/CareyPang/LPPL/blob/b13639ca76eb719bd8c62ecb318e2d85cfe10124/stock/600519.json)截至2026-11-16，`mode=current`，`model_version=prereg_v1.7_v2.1+stk_lite`，`source_sha=60818b4…`，`generated_at=2026-11-16T20:01:59.870909+00:00`。六尺度`scale_clusters`均为空，`signal_status=no_qualified_fit`。这是已生成的空结果，不等于计算没完成，也不能称目前安全。
- `VERIFIED · DATA`：[stock/index.json](https://github.com/CareyPang/LPPL/blob/b13639ca76eb719bd8c62ecb318e2d85cfe10124/stock/index.json)的600519条目为`history_weeks=0`、`history_compatible=false`、`history_asof=null`。旧history在archive/jobs保留；main旧历史为104周且模型版本较旧。不能按旧报告“有104周文件”就开启兼容历史回放。
- `VERIFIED · CODE`：[stock-session.js:9](https://github.com/CareyPang/LPPL/blob/60818b428396336fc99aae3076d4a918089a81d3/frontend/app/stock-session.js#L9)检查symbol、模型/拟合/schema版本、variant、帧日期和历史输入hash。应保留这种保护，按钮禁用时给具体原因。
- `NOT_INSPECTED`：此审查未对生产Worker请求POST，也没有运行新的茅台历史任务。上述数据文件存在不证明用户网络下的完整加载已验收。

## 4. 重要口径差异：生产显示不能直接称“完整周期1.5”

这是实际调用链核验，不是只凭遗留说明推断：

| 规则／输出 | 源码 | 实际含义 |
|---|---|---|
| `TOP_RULE` / `p_top` | [core.py:81](https://github.com/CareyPang/LPPL/blob/60818b428396336fc99aae3076d4a918089a81d3/research/lppls/core.py#L81)、[core.py:99](https://github.com/CareyPang/LPPL/blob/60818b428396336fc99aae3076d4a918089a81d3/research/lppls/core.py#L99)、[lppls_rules.py:41](https://github.com/CareyPang/LPPL/blob/60818b428396336fc99aae3076d4a918089a81d3/research/features/lppls_rules.py#L41) | 存在以`ω/(2π)`定义的完整周期和1.5门槛，但不能据此认为所有生产输出都调用它 |
| `g_fco_standard` | [lppls_rules.py:27](https://github.com/CareyPang/LPPL/blob/60818b428396336fc99aae3076d4a918089a81d3/research/features/lppls_rules.py#L27)、[lppls_rules.py:94](https://github.com/CareyPang/LPPL/blob/60818b428396336fc99aae3076d4a918089a81d3/research/features/lppls_rules.py#L94) | `osc=(ω/2)ln|…|`、`n_osc=osc/π`；standard走`osc>=2.5`，与完整周期1.5不同；存在样本内部tc的绝对值处理 |
| 当前图上时间窗和逐尺度聚类 | [export_contract.py:503](https://github.com/CareyPang/LPPL/blob/60818b428396336fc99aae3076d4a918089a81d3/research/eval/export_contract.py#L503)、[export_contract.py:541](https://github.com/CareyPang/LPPL/blob/60818b428396336fc99aae3076d4a918089a81d3/research/eval/export_contract.py#L541) | 输入`q`取`r.box`，不是`p_top`或`g_fco_standard` |
| `box` | [lppls_rules.py:51](https://github.com/CareyPang/LPPL/blob/60818b428396336fc99aae3076d4a918089a81d3/research/features/lppls_rules.py#L51) | `B<0`、`m∈[0.1,0.9]`、`ω∈[6,13]`、`ahead∈[0,90]`；本规则未加振荡数和阻尼门槛 |

因此生产记录包含多种统计口径：standard合格拟合数、box时间窗和box簇不能无说明并称同一个“通过1.5周期的信号”。B1应增加/补齐**实际`filter_id`、`filter_version`、`oscillation_unit`、`min_cycles`可空、拟合代码hash、模型版本与区间来源**；先由导出层根据实际路径填写，前端只读。没有振荡门槛就写“本输出未使用该门槛”，不可填1.5或0.8作统一标签。

**不在B1里改算法。** 用户已选的完整周期1.5作为独立研究基线继续保留，迁移生产必须有单独对照、版本和旧结果保留。0–4日候选不因“至少提前5日”被隐藏；该目标作为评价切片。发现生产与研究不同不意味着应立即重算全市场。

## 5. 真正还缺的连续流程

### 5.1 返回目录不是一句“浏览器后退”即可

`VERIFIED · CODE`：[stock-catalog.js:71](https://github.com/CareyPang/LPPL/blob/60818b428396336fc99aae3076d4a918089a81d3/frontend/app/stock-catalog.js#L71)把筛选、排序、密度存在mount内部；没有序列化读写。[stock-view.js:880](https://github.com/CareyPang/LPPL/blob/60818b428396336fc99aae3076d4a918089a81d3/frontend/app/stock-view.js#L880)选股用`replaceState`；目录点击股票采用同页submit，原目录隐藏。所审模块没有返回目录动作把结果关闭并恢复目录选择。页面被刷新、指数跳转再返回、BFCache不可用时都没有应用层明确恢复契约。

`PROPOSED`：补一个版本化`ReturnContext`，含目录来源、筛选、排序、选中资产、滚动锚点；点击目录资产时记录。工作站有“返回标的目录/返回自选”的真实按钮；浏览器Back同义。只将公开筛选编码进URL，私有自选不放共享URL。优先保持现有页面结构，不要求改SPA。单页来回可复用已挂载目录状态，跨页/刷新通过安全session存储恢复。

### 5.2 已合并 #121 的切股事件隔离应复用，过时失败仍需验收

`VERIFIED · CODE`：原审查基线 `60818b4…` 的 [stock-view.js:764](https://github.com/CareyPang/LPPL/blob/60818b428396336fc99aae3076d4a918089a81d3/frontend/app/stock-view.js#L764)切code时没有无条件清空events；“最近股票”按钮直接`select(code)`，不经过search submit。新股没有current结果时，renderResult也不会触发重载事件。此基础缺口已由封包前合并的 #121 修改，不能继续把旧源码描述当作当前 main 的缺口。

[PR #121](https://github.com/CareyPang/LPPL/pull/121)已于 `2026-11-17T03:25:24Z` 合并。新 main [stock-view.js](https://github.com/CareyPang/LPPL/blob/b69384656210cc3610e58733426ce22bc8a69d6e/frontend/app/stock-view.js)添加清空events/focusEvent与`onCodeChange`回调，[stock.html](https://github.com/CareyPang/LPPL/blob/b69384656210cc3610e58733426ce22bc8a69d6e/frontend/stock.html)统一`syncEventsFor`；第三个变化文件为stock-chart.test.cjs。B1直接复用该实现，不再等待该PR或另写竞争补丁。本轮只核验外部合并后的状态，没有执行合并。

另一个仍应加的反例：资产A事件请求未完成→切资产B→B事件成功→A请求失败。封包前新 main [stock.html:1281](https://github.com/CareyPang/LPPL/blob/b69384656210cc3610e58733426ce22bc8a69d6e/frontend/stock.html#L1281)的catch仍只对eventsCode复位使用serial条件，第1283行清events及第1284行隐藏panel没有同一条件保护。此次完整文件重读确认 #121 未改这一段。因此应验证过时失败是否会清掉新股成功事件；这是由代码导出的竞争风险，本轮未进行浏览器重现，状态`NOT_ESTABLISHED`，不能写成已复现线上故障。

### 5.3 图带与证据需要可定位身份

`VERIFIED · CODE`：[export_contract.py:97](https://github.com/CareyPang/LPPL/blob/60818b428396336fc99aae3076d4a918089a81d3/research/eval/export_contract.py#L97)簇只输出rank/share/n/n_scale/q20/q80；[top-clusters.js:21](https://github.com/CareyPang/LPPL/blob/60818b428396336fc99aae3076d4a918089a81d3/frontend/app/top-clusters.js#L21)会按share重新排列。当前没有该导出对象自带的稳定cluster_id或成员拟合行引用。用“第一个簇”当跨修订身份会在排名变化时错连。

`PROPOSED`：在已有结果上追加结果hash/结果ID、簇ID与成员引用或可验证摘要，保留原字段；簇跨版本关系单独记录，不把新排名等同于旧簇。图带、摘要和证据面板使用同一键；面板显示区间来源、尺度/窗口长度、合格数与总尝试数、实际过滤口径、支持/分歧、修订。底层成员尚未导出时明确“尚未提供逐窗记录”，不由前端反推。

### 5.4 当前空态也必须是一条完整流程

上证和茅台最新固定样本均没有可展示当前box区间，验收应包含“行情→分析完成但无候选→为什么没有→证据→返回”。另用已存在的历史候选验证“候选→图带→证据”。两组不能混成一张“当前命中”截图。历史回放不强制新跑104周；缺兼容历史明确给出缺口即可。

### 5.5 历史补算不自动成为当时证据

`VERIFIED · CODE`：事件读取仍是[LPPL.events()的最新快照](https://github.com/CareyPang/LPPL/blob/60818b428396336fc99aae3076d4a918089a81d3/frontend/stock.html#L1226)。截断K线或按事件日期隐藏未来标记，不足以证明该事件文字、金额、修订版本在过去已可见。B1保持“历史补算”标签，不声称严格当时资讯；B3再将事件版本/available_at接入统一时间轴，已有#114版本库应复用。

## 6. 首次可见与版本记录的真实边界

- `VERIFIED · CODE`：[Worker observeResult:786](https://github.com/CareyPang/LPPL/blob/60818b428396336fc99aae3076d4a918089a81d3/workers/stock-query/src/index.js#L786)按结果hash保存首次读取时间；明确返回`evidence=worker_read_observation_only`、`first_visible_at=null`、`public_first_published_at=null`。这不是缺字段可随便回填，而是语义保护。
- `VERIFIED · CODE`：[stock-visibility.js:43](https://github.com/CareyPang/LPPL/blob/60818b428396336fc99aae3076d4a918089a81d3/frontend/app/stock-visibility.js#L43)为本浏览器观察，`client_clock_trust=unverified`、`publication_evidence=NOT_ESTABLISHED`。其记录可以帮助排查体验，不能当公开提前预警时间。
- `VERIFIED · DATA`：[forward_log/ledger.jsonl](https://github.com/CareyPang/LPPL/blob/60818b428396336fc99aae3076d4a918089a81d3/forward_log/ledger.jsonl)确有2026-11-16六指数记录，上证`sealed_at=2026-11-16T12:07:14+00:00`。这确认封存记录存在；[seal实现](https://github.com/CareyPang/LPPL/blob/60818b428396336fc99aae3076d4a918089a81d3/research/pipeline/forward_log.py#L40)复制结果并写hash、封存时点，没有测量对公众可读时间。
- `VERIFIED · CODE`：#114的[publish_versioned.py:273](https://github.com/CareyPang/LPPL/blob/60818b428396336fc99aae3076d4a918089a81d3/scripts/publish_versioned.py#L273)已有不可变压缩版本、hash、fetched_at、published_at、run_id、backfilled_from_git。该时间字段存在不等于每个来源提供真实发布时间；不能以generated_at作为未经说明的发布时间替代。

`PROPOSED`：B1最小账本补的是来源明确的发布可读收据与界面引用关系，不能覆盖旧封存记录。至少分开`computed_at / stored_at / server_read_observed_at / audience_available_at / client_render_observed_at`；未知就null。新增公开可读探测需明确受众和URL、结果hash、探测时点；本轮不启用线上探测或调度。

## 7. Devin近期PR逐项判定

| PR | 状态与已读改动 | B1处理 |
|---|---|---|
| #108 | 已合并；报价/模型时间分开、成交价主显示、无合格拟合完成态、滚轮语义 | 复用；回归不重写 |
| #112 | 已合并；后端future_trading_days、前端trading-days、future_calendar元数据 | 复用日期换算；该JSON引用国务院假期通知，本轮没有独立对照交易所公告，不能额外宣称“交易所逐日已核验” |
| #113 | 已合并；指数六尺度条和图带联动 | 复用；与个股统一选中态语义 |
| #114 | 已合并；多类日更数据只追加版本、manifest及回补标识 | 复用版本保存；尚不能据保存层推定前端已有严格当时回放 |
| #115 | 已合并；个股K线+成交量、未来空位、尺度区间 | 复用，不引入第二张行情主图 |
| #116 | 已合并；图上查看/回到当时分开、历史截断和兼容性 | 复用；已合并 #121 补基础切股清事件，但过时失败反例仍待验收；作者展示有预览数据，不能替代真实茅台路径验收 |
| #117 | 已合并；周度提醒episode表、首次区间与事后高点关系、点击定位 | 复用为历史补算明细，不冒充真实发布/修订账本 |
| #119 | 已合并；市场快讯区块与二级导航提前 | 保持，不再按旧报告恢复事件日历优先顺序 |
| #120 | 已合并；逐尺度主次簇导出与显示、旧字段保留 | 复用；补具体filter身份与证据引用，不能把旧数据自动称已分簇 |
| #121 | 已合并至 `b693846…`；切股清事件、统一事件加载回调，3个文件 | 已满足代码依赖，直接复用；仍加异步过时失败反例；合并由外部执行 |
| #118 | open；5个新增实验文件，固定LWC 5.2.1，生产导航未接入 | 独立试验保留；与B1业务文件无直接修改重叠。作者结论是继续Canvas，本轮不换库、不新增依赖 |

B1在 `b693846…` 之后改动的同文件冲突重点为`frontend/stock.html`、`frontend/app/stock-view.js`及stock-chart测试；实施时仍应重新读取当前 main，保留已合并 #121 的清理与回调。#118不应成为B1的依赖，也不要把它在旧head上的日期/结果选择行为拿来覆盖#120之后的生产实现。

## 8. 本轮验证与剩余验收

### 独立完成

- `VERIFIED · TEST`：从初次固定 main `60818b428396336fc99aae3076d4a918089a81d3` 通过GitHub读取源码到D盘一次性审查副本，使用已有Node内建测试运行`stock-session.test.cjs`、`stock-visibility.test.cjs`、`stock-summary-evidence.test.cjs`、`stock-chart.test.cjs`：**85 passed、0 failed、0 skipped**。没有新增测试或改被测代码，没有运行模型；这不是浏览器E2E，也不是对封包前 `b693846…` 的测试。命令、保留下来的真实摘要、日志保留边界见 `TEST_EVIDENCE.json`；原测试清单未修改。
- 这些测试覆盖已有的行情先呈现、慢历史不阻塞、当前请求0周历史、stale保留、请求身份、兼容性、事件定位/历史截断、聚类摘要、首次可见等。目录跨页返回闭环并不在这85项已验证范围内。
- `VERIFIED · CI`：[原 main CI 43913805653](https://github.com/CareyPang/LPPL/actions/runs/43913805653)success；[#121 head CI 44001164719](https://github.com/CareyPang/LPPL/actions/runs/44001164719)success，相关smoke success、collect skipped；[#118 CI 43899713939](https://github.com/CareyPang/LPPL/actions/runs/43899713939)success。为本轮读取的远端状态，不等于对应功能全部实测；没有据此宣称新合并提交 `b693846…` 的 CI 或本地测试已通过。
- PR作者的137/143/158/167/190/191等测试计数属于不同提交和测试集，不能累加或当成本轮独立测试数。

### B1交付必须补的验收（全部NOT_RUN）

1. **B1-01 基线**：记录代码SHA、实际Pages构建版本、Worker版本、数据分支/响应hash；本轮不假定三者同步。
2. **B1-02 上证路径**：目录筛选→上证→行情与最新结果→空态/已有候选的证据→返回；资产身份始终为`sh000001`。
3. **B1-03 茅台路径**：相同流程，`600519/sh600519`映射一致；当前无候选明确完成，缺历史不锁主图。
4. **B1-04 已有候选路径**：选择一个现有且可追溯的历史结果，不新拟合；主/次簇摘要、图带、证据使用同一身份和日期。永久标历史补算或真实发布来源。
5. **B1-05 返回**：浏览器Back、显式返回、刷新后返回、从指数跨页返回；筛选/排序/密度/滚动锚点/选中资产恢复。
6. **B1-06 任务**：冷缓存仅当前计算；热缓存不重复计算；历史只在显式操作时创建；切股/返回期间任务继续且不重复POST。
7. **B1-07 异步隔离**：A→B快速切换，A行情、结果、事件成功与失败分别迟到；均不得覆盖或清空B。
8. **B1-08 证据缺口**：无分簇旧结果、空簇、未知filter、缺逐窗证据、权限/超时分别说明；不虚构支持概率。
9. **B1-09 时间**：报价/日线/分析/封存/Worker读取/客户端可见分别呈现；不存在公开可读收据时不能填first_public。
10. **B1-10 390px/桌面**：1440与390宽分别完成全过程，键盘可达、抽屉关闭焦点恢复、无整页横溢；当前均NOT_INSPECTED。

验收产物应含机器可读步骤结果、关键请求模式/次数、响应身份和hash、必要截图或短录屏、失败说明。真实生产数据路径与fixture测试分栏；不把“测试通过”升级成阶段顶预测已有效。

## 9. 建议拆分给Devin的最小提交

1. 基线差异表与实际口径字段：已确认 #121 合并至 `b693846…`；实施开始仍刷新 main 与生产读取版本，列复用组件；不改拟合。
2. 导航/返回上下文：接现有目录与两类资产路由，实现可恢复返回。
3. 候选→证据联动：复用主次簇UI，补稳定身份和证据缺口显示；实际box/standard/1.5研究配置分开。
4. 异步边界与验收：复用StockSession，覆盖快速切股及过时失败；完成上证和茅台真实路径、现有历史候选路径与390px验收。

不将小工具、新宏观源、图表换库或模型算法改造塞进这一提交。它们可以另列任务，由同一数据入口与资产上下文接入；不影响B1先形成可用闭环。

## 10. 封包前增量复核：#121 已由外部合并

`VERIFIED · CODE / GitHub 元数据`：[固定区间比较](https://github.com/CareyPang/LPPL/compare/60818b428396336fc99aae3076d4a918089a81d3...b69384656210cc3610e58733426ce22bc8a69d6e)为 ahead 2、behind 0；功能提交 `dcaef225…` 的父提交为 `60818b4…`，合并提交 `b693846…` 的两个父提交为 `60818b4…` 与 `dcaef225…`。#121 的 GitHub 元数据为 closed、merged=true、`merged_at=2026-11-17T03:25:24Z`。只比较、读取并记录现状；本审查未执行合并或任何部署。

| 变化文件 | 差异 | 复核结果 |
|---|---|---|
| [frontend/app/stock-view.js](https://github.com/CareyPang/LPPL/blob/b69384656210cc3610e58733426ce22bc8a69d6e/frontend/app/stock-view.js) | +3 / −1 | 切换code无条件清events/focusEvent，增加`onCodeChange`通知；Git blob `8f2e84a028de4295906eacd0f6007ef1b82ef6ed` |
| [frontend/stock.html](https://github.com/CareyPang/LPPL/blob/b69384656210cc3610e58733426ce22bc8a69d6e/frontend/stock.html) | +18 / −22 | 增加共用`syncEventsFor`，串联切code、结果、搜索与初始载入；过时失败catch仍需第5.2节的反例验收；Git blob `0599417de2cf2a2d8ce05af17246d47d4eb4e532` |
| [frontend/tests/stock-chart.test.cjs](https://github.com/CareyPang/LPPL/blob/b69384656210cc3610e58733426ce22bc8a69d6e/frontend/tests/stock-chart.test.cjs) | +28 / −1 | 新增切股且新股无current时清旧事件测试；已读测试文本，本轮未执行；Git blob `dfdb0d355dfd2f546217a84ee4ca965a14930ccf` |

三个文件均重新读取完整内容，独立对UTF-8字节计算Git blob SHA与GitHub返回值一致；对应SHA256、比较结果、PR状态、风险和测试归属保存在 `FINAL_BASELINE_DELTA.json`。这次增量没有修改拟合规则、导出、Worker、结果分支或首次可见模块，因此不消除本文记录的生产口径、证据身份、返回状态和公开可见时间边界。

`NOT_RUN / NOT_INSPECTED`：新 main 没有重跑测试，没有浏览器E2E，也没有验证对应线上部署版本。原 `TEST_EVIDENCE.json` 与 `SOURCE_SNAPSHOT_MANIFEST.json` 保留原样，85项通过结论仅属于 `60818b4…`。#118仍按已核验的开放实验PR处理，本次增量不引入换库依赖。
