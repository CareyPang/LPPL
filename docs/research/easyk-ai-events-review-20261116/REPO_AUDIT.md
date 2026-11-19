# LPPL 当前仓库能力核查：EasyK AI 与事件研究的增量落点

核查日期：2026-11-16。固定基线：`CareyPang/LPPL@4a5e1375e6dbd9a5b442d16c876b69ccaff7d0b5`。本文件由只读源码审计产生；未控制浏览器，未运行模型、测试、来源抓取或部署。本文件不是 EasyK 实际交互体验记录。

证据口径：**VERIFIED** 表示本轮已核实的仓库事实；**CODE_ONLY** 表示静态实现存在，不能据此证明线上成功、来源授权或预测有效；**NOT_ESTABLISHED** 表示所检查范围没有足够证据。以下代码链接均固定到上述提交。

## 1. 结论：主要缺口是研究操作层，不是再增加一张长信息页

- **VERIFIED / CODE_ONLY**：LPPL 已有行情优先、当前/历史任务分离、异步指数回放、多个市场背景模块、公告事件日历和宏观卡。不能把全部规划功能描述成“尚未做”。
- **NOT_ESTABLISHED**：在本轮检查的 `home/index/stock/market` 页面、统一适配层、Worker 全部路由及目录树中，没有确认 AI 会话接口、通用事件规则编辑器、跨资产合成公式执行器、用户面板布局持久化或统一事件—LPPL 修订时间轴。
- **建议**：AI 第一版应围绕“解释当前图表、查找已知事件、列出所有顶部候选区间、说明为何没有正式提醒、打开相应日期”闭环。直接生成长篇市场评论不能解决工作站信息埋得深的问题。

## 2. 已有能力、边界与准确落点

| 领域 | 仓库中的实际能力 | 未建立的部分 / 新增落点 |
|---|---|---|
| AI 问答 | **VERIFIED** Worker 路由清单是 `/health /market /news /quote /query /status /result /replay /replay/result`；没有 AI 路由。[Worker L1010–1051](https://github.com/CareyPang/LPPL/blob/4a5e1375e6dbd9a5b442d16c876b69ccaff7d0b5/workers/stock-query/src/index.js#L1010) | **NOT_ESTABLISHED** 上下文问答、工具调用、引用核验、会话存档。建议新建受控研究服务，经现有前端适配层接入；不能把大模型直接放到模型任务协调对象里。 |
| 行情与计算分离 | **CODE_ONLY** `/query` 默认 `current`，history 独立，默认历史104周仅在显式history模式；行情使用独立 `market:<code>` 协调对象。[L1096–1106](https://github.com/CareyPang/LPPL/blob/4a5e1375e6dbd9a5b442d16c876b69ccaff7d0b5/workers/stock-query/src/index.js#L1096) | AI 解释已有结果不得自动触发历史104周任务。涉及新重算时先展示参数、预算与任务卡，用户主动启动。 |
| 结果状态与缓存 | **CODE_ONLY** 会话控制器有 current/history 独立任务、stale、刷新失败保留旧结果、source_sha匹配；Worker有结果索引复用、任务去重与额度。[stock-session L88–157](https://github.com/CareyPang/LPPL/blob/4a5e1375e6dbd9a5b442d16c876b69ccaff7d0b5/frontend/app/stock-session.js#L88)、[Worker L830–864](https://github.com/CareyPang/LPPL/blob/4a5e1375e6dbd9a5b442d16c876b69ccaff7d0b5/workers/stock-query/src/index.js#L830) | AI必须复用这些状态和数据身份，不能另起一套不含数据版本的“聊天缓存”。 |
| 指数历史回放 | **CODE_ONLY** 支持按symbol+asof查缓存、检查在途GitHub任务并按需dispatch；允许7个指数，其中含科创50。[Worker L308–399](https://github.com/CareyPang/LPPL/blob/4a5e1375e6dbd9a5b442d16c876b69ccaff7d0b5/workers/stock-query/src/index.js#L308)；前端有回放滑条与按周播放。[index L1136–1202](https://github.com/CareyPang/LPPL/blob/4a5e1375e6dbd9a5b442d16c876b69ccaff7d0b5/frontend/index.html#L1136) | 当前是价格/模型as-of回看，不等于“任意用户事件公式→所有触发日→同口径事件研究”。须区分已有历史结果与当前补算的历史重放。 |
| 公告事件日历 | **CODE_ONLY** 来源适配器含未来30日解禁、除权除息及近30日业绩预告，独立失败后保留旧节并标stale。[events.py L382–473](https://github.com/CareyPang/LPPL/blob/4a5e1375e6dbd9a5b442d16c876b69ccaff7d0b5/research/data/events.py#L382)；市场页有时间轴、解禁前20、分红与预告分类。[market L896–926](https://github.com/CareyPang/LPPL/blob/4a5e1375e6dbd9a5b442d16c876b69ccaff7d0b5/frontend/market.html#L896) | 不可称“没有事件”。但这主要是公告事实日历，尚非复合条件事件引擎，也未建立完整PIT公告修订历史。解禁/分红对象没有统一published_at/first_seen_at/revision链。 |
| 个股事件 | **CODE_ONLY** stock页读取统一事件数据并筛选当前个股，展示近期公告事件。[stock L1070–1106](https://github.com/CareyPang/LPPL/blob/4a5e1375e6dbd9a5b442d16c876b69ccaff7d0b5/frontend/stock.html#L1070) | 建议事件点选联动K线、来源原文、当时是否已知；优先复用，不重复抓取。 |
| 异动 | **CODE_ONLY** 有交易所异常波动距离计算，明示“规则距离描述，不是预测或交易信号”。[abnormal.py L126–169](https://github.com/CareyPang/LPPL/blob/4a5e1375e6dbd9a5b442d16c876b69ccaff7d0b5/research/data/abnormal.py#L126)、[L315–321](https://github.com/CareyPang/LPPL/blob/4a5e1375e6dbd9a5b442d16c876b69ccaff7d0b5/research/data/abnormal.py#L315) | 可作为事件类型，但不能因接口名含“提醒”就当LPPL顶部预测。市场覆盖取候选池而非全A股逐一保证。 |
| 涨停复盘 | **CODE_ONLY** 四池数据入口、连板梯队、昨日池与今日池配对，按昨日层级统计下一板，炸板率为炸板/(涨停+炸板)。[market_base L805–907](https://github.com/CareyPang/LPPL/blob/4a5e1375e6dbd9a5b442d16c876b69ccaff7d0b5/research/data/market_base.py#L805) | 单次API配对不能替代逐日封存完整性审计；仍需前日原始池版本、缺失成员、停牌/退市与未知结果保留。来源可返回不证明再分发许可。 |
| 市场面板 | **CODE_ONLY** 已有行业/概念/地域热力图、市场情绪、连板、题材、强势与人气、龙虎榜、快讯；页面对应section已存在。[market L175–229](https://github.com/CareyPang/LPPL/blob/4a5e1375e6dbd9a5b442d16c876b69ccaff7d0b5/frontend/market.html#L175)；另有区间复合涨幅与流量累计，缺历史/来源不一致会跳过。[L1130–1146](https://github.com/CareyPang/LPPL/blob/4a5e1375e6dbd9a5b442d16c876b69ccaff7d0b5/frontend/market.html#L1130) | 缺跨模块上下文与交互组合。先做“选一个事件→定位日期/股票→看当时LPPL区间”，不先扩展十张低使用率卡。 |
| 宏观 | **CODE_ONLY** 当前宏观采集器实际启用Treasury、NY Fed、Fed H.10，失败独立保留旧数据。[global_macro L410–454](https://github.com/CareyPang/LPPL/blob/4a5e1375e6dbd9a5b442d16c876b69ccaff7d0b5/research/data/global_macro.py#L410) | 不得把BIS/ECB/BLS/EIA全部规划写成已接通；本轮未验证那些额外适配器。AI可解释当前已存在卡，不能补造实时数值。 |
| 自选 | **CODE_ONLY** 存在浏览器自选抽屉与行情结果复用。[od-watch L145–178](https://github.com/CareyPang/LPPL/blob/4a5e1375e6dbd9a5b442d16c876b69ccaff7d0b5/frontend/app/od-watch.js#L145) | **NOT_ESTABLISHED** 账户级多端同步、私有面板/会话权限、共享研究面板。 |
| 指数前瞻封存 | **CODE_ONLY** `forward_log.seal`按(asof,symbol)跳过已封存对象，写SHA256/封存时刻/版本；workflow拒绝非当日补封。[forward_log L39–60](https://github.com/CareyPang/LPPL/blob/4a5e1375e6dbd9a5b442d16c876b69ccaff7d0b5/research/pipeline/forward_log.py#L39)、[workflow L41–53](https://github.com/CareyPang/LPPL/blob/4a5e1375e6dbd9a5b442d16c876b69ccaff7d0b5/.github/workflows/forward_log_seal.yml#L41) | 不应描述为“完全没有日志”。但这不等于通用公告事件、个股提醒修订或公共首次发布时间账本。固定main树中只见10/27–10/30的24份指数档案，不能据此保证每日持续运行。 |
| 首次可见时间 | **CODE_ONLY** 结果进入可视区、浏览器可见、两帧渲染后记录 `first_visible_at_client`；明确本浏览器、客户端时钟未核验、publication_evidence未建立。[stock-visibility L1–53](https://github.com/CareyPang/LPPL/blob/4a5e1375e6dbd9a5b442d16c876b69ccaff7d0b5/frontend/app/stock-visibility.js#L1) | AI不得把它回答成“系统当时已公开预测”。需服务端发布证据、观察日志、历史重放分别建账。 |

## 3. 回放之前必须补的证据结构

**VERIFIED**：现有 `events_<asof>.json`、`macro_<asof>.json`、`market_<asof>.json` 都使用直接 `write_text` 覆写同日文件：分别见 [events L477–483](https://github.com/CareyPang/LPPL/blob/4a5e1375e6dbd9a5b442d16c876b69ccaff7d0b5/research/data/events.py#L477)、[macro L457–463](https://github.com/CareyPang/LPPL/blob/4a5e1375e6dbd9a5b442d16c876b69ccaff7d0b5/research/data/global_macro.py#L457)、[market L2329–2341](https://github.com/CareyPang/LPPL/blob/4a5e1375e6dbd9a5b442d16c876b69ccaff7d0b5/research/data/market_base.py#L2329)。Git提交历史可以帮助追踪，但它并不自动为每次抓取提供稳定记录ID、原包hash、首次可知或修订链。

**建议**：保留latest物化视图，新增不可覆盖的 `dataset_snapshot` 与 `event_revision`；一份revision至少记录：

```text
event_id, revision_id, supersedes_revision_id,
entity_ids, event_type, effective_at, published_at,
first_seen_at, fetched_at, available_at,
source_id, source_url, payload_hash, source_snapshot_id,
status, stale_reason, evidence_status, license_policy_id
```

- `effective_at`是事件发生/实施日；`published_at`是来源公开日；`first_seen_at`是本系统首次实际见到。三者不可互换。
- 历史补抓可知道旧公告日，但不证明本系统当时持有该版本。回放“来源当时公开可知”和“本系统当时实存可知”两模式分开，默认标清证据。
- 未来解禁是已公开的未来事件，不能因为effective_at晚于回放日就全部隐藏；判断是否可用应使用当时可知时刻与版本。
- 盘后公告不能回填成当日收盘前已知；交易日映射必须使用相应交易所日历。
- 历史修订不覆盖旧条目；首次空数据、刷新失败与未知结果均留在覆盖分母里。

**CODE_ONLY / 风险**：市场页 freshness 的工作日差计算明确“不扣节假日”，见 [market L1185–1195](https://github.com/CareyPang/LPPL/blob/4a5e1375e6dbd9a5b442d16c876b69ccaff7d0b5/frontend/market.html#L1185)。不能直接复用为事件回放的交易日历。日终日期工具已有reference calendar入口，见 [trading_date.py L6–13](https://github.com/CareyPang/LPPL/blob/4a5e1375e6dbd9a5b442d16c876b69ccaff7d0b5/research/data/trading_date.py#L6)。本轮未重新核验其外部交易所来源链，不能称交易所验证已经完成。

## 4. AI层可执行增量设计

以下是建议，不是已实现：

1. **上下文包**：固定symbol、asof、source_snapshot_ids、result_id、model_version、selected_chart_range、selected_cluster_ids、当前任务状态。用户切股票/回放日后旧回答必须显式标旧上下文。
2. **只读工具**：`get_asset_context`、`list_top_candidates`、`explain_model_status`、`list_events`、`get_event_revision`、`evaluate_registered_rule`、`get_replay_snapshot`、`get_sources`。工具应读结构化结果，不让LLM读整个长网页猜数。
3. **导航动作**：`focus_chart_range`、`highlight_event`、`open_source`可由白名单动作结果驱动；与改规则、启新计算、分享发布动作分开。第一版不授予模型下单、发布、修改LPPL参数权限。
4. **回答结构**：两句直接回答 → 证据卡/数值与时点 → 候选区间与未满足项 → 图上查看按钮 → 数据缺口。不要用全屏免责声明挤走有效结论，也不允许无证据给顶部概率。
5. **确定性统计**：收益、分位、计数、交易日跨度、条件真假由后端计算，LLM只解释。每个数值携带计算表达式、输入数据版本与样本量。
6. **输出核验**：回答引用必须指向返回的evidence_id；数值允许范围验证；没有来源时输出无法核验的字段，不补造。新闻、公告、站外页面一律作为不可信数据，不能改变系统规则或获得工具权限。
7. **缓存**：按工具参数+asof+数据/模型/规则版本缓存；相同上下文可复用结构化证据。生成文案另缓存，避免“行情更新了但回答仍引用旧日期”。私有会话缓存隔离用户，公共数据缓存只共享允许共享的证据。
8. **轻重任务分离**：优先立即返回现有行情/模型证据；等待新回放时流式返回“读取完成/计算排队/缺数”状态，不生成假进度百分比。取消AI回答不取消已有独立模型任务。

## 5. 事件引擎与LPPL分离

建议第一批支持四类：公告事实、市场描述条件、LPPL候选/正式/修订状态、数据质量事件。每类独立图层和证据色，不能统一叫“顶部信号”。

用户此前提出的“沪深300近20日涨幅>0 + 东方财富近20日涨幅>证券ETF近20日涨幅 + 融资买入额252交易日分位>0.7”，可以做**研究规则草稿**；但证券ETF代码、融资买入额范围（全市场/个股）、分位窗口是否含当日、并列排名/缺数、收盘与公布滞后仍需冻结。不能默认为可验证顶部预测，也不能由AI擅自填默认后称已核实。

实现建议：

- 类型化AST/JSON规则而非执行任意Python/JS；白名单 `return`、`rolling_percentile`、`gt`、`and`，显式交易日、币种、复权与单位。
- 先输出可阅读的精确规则及缺失参数。提交规则版本后才计算，规则hash不随之后修改改变。
- 条件真/假/未知三态；停牌、缺数、历史不足、不同市场假期不能默认为false。
- 从false→true的首次触发与持续true分开，设置事件episode/cooldown以免一个持续窗口算几十次独立事件。
- 事件研究呈现全部触发日、重叠处理、基准、前后窗口、未成熟样本与分布。区间顶部覆盖、时间误差、提前量分别评分；≥5交易日保留诊断分层，不作为隐藏全部邻近顶部候选的硬门。
- 先保持LPPL拟合、完整周期1.5研究基线与旧结果不动；事件工具作为信息层。是否把因子作为LPPL过滤/融合另行登记并对照，不能悄悄进入模型。

## 6. 接口与页面的最小实施顺序

| 阶段 | Devin交付 | 必须验收 |
|---|---|---|
| A 证据适配 | 统一图表上下文、规范化事件revision、顶部候选清单API；新增结果字段但兼容旧结果 | 同symbol/asof版本稳定；unknown与0分开；旧数据不覆盖 |
| B 只读AI | 4个入口：解释当前区间、查事件、为何没正式提醒、回到指定日 | 回答所有数字可从工具结果复算；引用点击可定位；没有新模型运行副作用 |
| C 事件与回放 | 白名单规则编辑、单规则事件列表、图上标记、按日期可知版本切换 | 盘后公告/迟报/修订/跨时区/缺数/持续触发去重全部可测 |
| D 研究面板 | 多资产同图、归一化/单位轴、规则与LPPL平行展示、保存面板 | 不混单位，不因双轴视觉相似误称相关；390px优先图表+折叠AI |
| E 扩展 | 经许可的更多来源、宏观、可分享研究摘要 | 来源许可/版本/数据留存条件完整；不自动公开用户会话 |

## 7. 仓库协作与CI边界

- **VERIFIED** 固定提交完整tree无根`AGENTS.md`及`docs/**/AGENTS.md`。存在 `frontend/AGENTS.md`，前端改动需参考其数据入口/证据显示约束。本次只交文档时不触碰前端所属文件。
- **VERIFIED** 前端所有业务数据应经 `frontend/app/lppl-data.js`。当前入口已经包含market/events/abnormal/bottomSignal/rangeStats/macro/ntEtf/news等；不能为了AI在每个页面直接抓外部源。[lppl-data L223–294](https://github.com/CareyPang/LPPL/blob/4a5e1375e6dbd9a5b442d16c876b69ccaff7d0b5/frontend/app/lppl-data.js#L223)。
- **VERIFIED** `frontend/AGENTS.md` 和 `docs/frontend_contract.md`仍有旧“禁止趋势/动量指标”以及固定证据数值门控。用户后续明确想要信息研究工具，实施前应更新信息层与模型层的界限契约；不能把老限制悄悄删掉，也不能误把研究信息层强行禁止。新目标是独立信息展示，LPPL证据约束继续保持。
- **VERIFIED** `.github/workflows/ci.yml`在push/pull_request都会跑Python/Node契约测试，没有docs-only跳过。仅文档PR也可能有普通CI成本。
- **VERIFIED** Pages仅`main`指定web/frontend路径push或显式workflow_dispatch触发；docs分支push或Draft PR不满足自动部署条件。[pages.yml L3–11](https://github.com/CareyPang/LPPL/blob/4a5e1375e6dbd9a5b442d16c876b69ccaff7d0b5/.github/workflows/pages.yml#L3)。
- **VERIFIED** market_daily只在非PR事件collect；docs不在其PR paths中。[market_daily L3–36](https://github.com/CareyPang/LPPL/blob/4a5e1375e6dbd9a5b442d16c876b69ccaff7d0b5/.github/workflows/market_daily.yml#L3)。stock_query的PR paths也不包含docs。
- **NOT_ESTABLISHED** 本轮没有验证站外GitHub Apps/自动化会不会跟随PR触发写操作；新报告PR创建后仍应看实际checks，不把Draft当成所有外部系统的绝对防线。

## 8. 未完成验收与严谨表述

本轮没有浏览器体验LPPL线上/本地新主页，没有调用模型、AI或事件运行接口，没有拉行情，没有运行测试，没有检查生产Worker版本与部署日志。因此静态实现只能标CODE_ONLY。EasyK的真实体验由主任务另行记录，不能用此文件替代。

不建议写：AI能预测顶部、多个尺度一致即概率更高、已有快照文件即历史当时已知、Git日志等于首次公开、规则触发收益等于交易收益。建议写：AI整理可核验结果；事件与LPPL并排研究；顶部候选区间与正式提醒分层；提前量单列；历史重放和真实首次发布分账。
