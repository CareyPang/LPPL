# TradingView 官方能力与可集成边界核验

核查日：2026-11-16。仅核验官方帮助、官方开发文档与官方开源库；本文件没有控制用户浏览器，不代表本轮账户的交互实测、权限、速度或移动体验。浏览器体验由主报告另行记录。

证据分类：`VERIFIED/DOC` 为本轮官方说明；`PROPOSED` 为针对LPPL的设计推论；`NOT_ESTABLISHED` 为未证明性能、效果或授权成立；`NOT_RUN` 为未执行集成测试。官方功能说明不等于独立质量或准确率验证。

## 1. 应学习的是高频操作组织

`VERIFIED/DOC`：Supercharts将标的、周期、图形、指标与布局放在上方，绘图放左侧，辅助研究与列表放右侧，底部承载扩展工作区。标的可通过点击名称或直接键入搜索；另有工具快速搜索、比较资产、撤销/重做、图表保存与同步等入口。[Supercharts入门](https://www.tradingview.com/support/solutions/43000746464-getting-started-with-supercharts/)

`PROPOSED`：LPPL不必照搬四周所有工具。优先做稳定的四个区域：上方资产与时间、中央K线及顶部区间、右侧自选/证据/AI按需切换、下方事件与修订时间轴。资产搜索、返回最新、重置视图、定位候选区间应在任何页面都容易找到。新增能力应成为一个清楚的动作，而不是一张不可操作的长卡片。

`VERIFIED/DOC`：布局是保存的工作区；其中图表的设置可以独立保留，也可选择同步。保存、模板与布局概念帮助用户复用研究环境。[布局说明](https://www.tradingview.com/support/solutions/43000746975-tradingview-layouts-a-quick-guide/)

`PROPOSED`：LPPL第一版保存少量有意义状态——资产、显示周期、价格尺度、模型图层、回放日期和面板折叠。后续再加双图比较，不先做任意复杂多窗。用户刷新回来应继续原研究，不必重走首页叙事。

## 2. 图表的可配置性应服务判断

`VERIFIED/DOC`：官方设置允许调整背景、网格、十字光标、尺度文字、轴标签和边距，也有时区、会话、价格数据调整等选项。设置既可从齿轮，也可从图形对象打开；周期变化时有保持图表位置的选项。[图表设置](https://www.tradingview.com/support/solutions/43000748166-how-to-configure-your-supercharts/)

`PROPOSED`：LPPL应优先实现少量稳定默认值和准确数据含义：

- 主图同时呈现K线与成交量；OHLC、复权、交易所时区及截止日清晰。
- 十字光标的日期/价格/成交量联动，不因缩放而丢失候选区间与事件坐标。
- 日/周切换、显示范围和模型拟合窗口是三个不同概念，不能一个按钮同时暗改三者。
- 区间与K线叠加时使用低透明度底色和边界，选中后才强化；支持隐藏与逐项查看依据。
- 返回最新、适配全部、恢复自动价格尺度、撤销视图操作提供明确入口。
- 不因刷新数据重新调用fitContent把用户正在观察的历史位置拉回全图。

这些是设计建议，实测FPS、低配设备、390px手势与大陆加载时间均 `NOT_RUN`。不能把“使用TradingView库”当作性能已经优秀的证据。

## 3. 筛选、图表与热力图应共享研究对象

`VERIFIED/DOC`：TradingView筛选器覆盖多类资产，可切换结果视图；筛选结果热力图与独立热力图不是同一数据范围。筛选器中的表格、图表、热力图切换保留同一筛选集合。[筛选器说明](https://www.tradingview.com/support/solutions/43000718885-tradingview-screeners-walkthrough/)、[筛选结果热力图](https://www.tradingview.com/support/solutions/43000794279-heatmap-view-mode/)

`VERIFIED/DOC`：热力图用面积、颜色与分组表达不同维度；支持等面积模式、行业下钻、悬停数值与多种显示选项。颜色图例本身可充当过滤入口，单向指标与有正负指标采用不同色标。[热力图参数](https://www.tradingview.com/support/solutions/43000707144-how-to-set-up-a-heatmap-what-is-size-by-and-color-by/)、[热力图导航](https://www.tradingview.com/support/solutions/43000766446-tradingview-heatmaps-from-global-trends-to-details/)

`PROPOSED`：LPPL的行业/概念/地域热力图应同步“同一市场集合”的列表、K线预览与自选操作。不要点击热图后跳到另一份无相同筛选条件的数据。面积/颜色/分组各有明确字段标签；资金、涨幅、LPPL结构支持强度不混用同一个色标。缺数用独立纹理/文字，不能把灰色同时解释为平盘和缺失。

`VERIFIED/DOC`：官方近期热力图产品说明提及色盲配色，以及切换视图不改变筛选对象。[官方热力图更新](https://www.tradingview.com/blog/en/heatmap-view-in-screener-60678/)

`PROPOSED`：我们的A股涨跌配色可采用用户熟悉的红涨绿跌，并提供可选模式；蓝紫仅用于选择/模型区间，不承担涨跌语义。任何关键状态同时给文字或线型，不能只用颜色。

## 4. 回放与提醒的边界比动画更重要

`VERIFIED/DOC`：Bar Replay支持选择起点、播放速度、单步推进、返回实时，以及多图同步回放；官方同时说明，回放时已有服务器提醒、交易面板和报价等仍可能按实时数据运行，新服务器提醒不能在回放内创建。[Bar Replay操作及限制](https://www.tradingview.com/support/solutions/43000474024-how-do-i-turn-bar-replay-on/)

`PROPOSED`：LPPL要借鉴清楚的播放控件，却应避免用户误把实时侧栏当历史证据。回放时由同一个as-of控制行情、事件、模型版本和AI上下文；实时数据若保留，必须有单独显著标识并不参与历史解释。价格回放并不自动证明公告、宏观和模型版本满足当时已知；还需要自己的版本账本。

提醒必须分为价格条件、信息事件、模型观察、正式区间、修订与新提醒。我们应单独保存触发条件、规则版本、数据截止、首次送达与阅读时刻。图上标记不等于真正发送过提醒；历史重算不等于当时发布。

## 5. 网站、Widget、Lightweight Charts与Advanced Charts不是一回事

| 产品 | 已核实官方边界 | 对LPPL的含义 |
|---|---|---|
| TradingView成品网站 | 账户、行情、服务端提醒/回放、社区及研究工具组成的完整服务 | 登录/订阅不等于取得组件源码或数据再分发权 |
| Widgets | 官方托管展示组件，通常连接TradingView提供的数据，按支持的配置嵌入 | 适合独立背景信息展示；不能假定可接入自有任意LPPL数据或控制其所有交互 |
| Lightweight Charts | 开源客户端图表，需要自己提供数据；没有整套网站功能或内置指标系统 | 更适合保留项目自身数据、证据和任务系统，再开发区间/事件叠层 |
| Advanced Charts | 自托管专业图表，需要自有datafeed与许可；不是完整TradingView网站 | 工具丰富，但仍需后端、会话、提醒、事件研究、数据授权等独立开发 |
| Trading Platform | 面向经纪商、另有许可费用与交易集成 | 当前研究网站不应为不需要的下单链路付出复杂度 |

来源：[官方产品比较](https://www.tradingview.com/charting-library-docs/latest/product-comparison/)、[官方FAQ](https://www.tradingview.com/charting-library-docs/latest/resources/Frequently-Asked-Questions/)。

`VERIFIED/DOC`：官方FAQ列出可集成库不支持的服务器能力，包括Pine、提醒、策略测试、Bar Replay、筛选/热力图/日历等；Pine指标不能直接迁移，需使用支持的JavaScript扩展或独立计算。网站与库更新节奏也不同。不能用网站演示推定库具有同样能力。

### 5.1 Lightweight Charts许可与扩展

`VERIFIED/DOC`：Lightweight Charts采用Apache2.0，文档要求保留NOTICE中的署名与TradingView链接。库本身不提供行情。[许可与署名](https://tradingview.github.io/lightweight-charts/docs#license-and-attribution)、[官方库比较](https://www.tradingview.com/free-charting-libraries/)

`VERIFIED/DOC`：series primitive可以向主画布、时间轴和价格轴添加图形/标签；pane primitive适合不绑定某条序列的图层，custom series适合拥有独立数据结构的图形。官方示例及插件目录不是“全部已生产发布”的承诺，目录中多项标为Release pending。[series primitives](https://tradingview.github.io/lightweight-charts/docs/plugins/series-primitives)、[pane primitives](https://tradingview.github.io/lightweight-charts/docs/plugins/pane-primitives)、[插件目录](https://tradingview.github.io/lightweight-charts/plugins)

`PROPOSED`：LPPL顶部时间带可先实现为跟随时间轴的primitive，绑定不可变result_id/cluster_id；事件点与修订层独立。不要把这类装饰层做成伪造OHLC序列。未来区间需要明确交易日映射，不能只靠往右留白后按自然日推算像素。

`VERIFIED/DOC`：WhitespaceData只含时间、不含价格，可表达没有行情值的时间槽；官方更新指南建议尾部增量用update，避免每次setData替换全量导致性能损失。[Whitespace示例](https://tradingview.github.io/lightweight-charts/tutorials/demos/whitespace)、[更新数据](https://tradingview.github.io/lightweight-charts/docs#updating-the-data-in-a-series)

`PROPOSED`：可以验证由交易所日历生成未来时间槽来承载区间边界，但必须测试当前库版本与timeToCoordinate行为；不能生成虚假未来K线，不能把缺数据变成价格不变。图表展示层不修改模型参数。

### 5.2 Advanced Charts许可与集成成本

`VERIFIED/DOC`：官方入口描述免费使用条件为保留署名、公开环境；申请说明限制个人兴趣/学习项目，授权面向公司公开项目。库由获批的官方私有仓库获取，不得把库文件放进公共代码仓库；项目以后收费还需要核对适用许可条款，而不能假定免费版允许所有付费部署。[产品介绍](https://www.tradingview.com/charting-library-docs/latest/introduction/)、[申请与安装](https://www.tradingview.com/charting-library-docs/latest/quick-start/)、[库申请FAQ](https://www.tradingview.com/free-charting-libraries/)

`VERIFIED/DOC`：Drawings API提供矩形、线、图标等绘图。官方说明若锚定时间没有对应数据点，库会调整到合适已有点；这种调整可能在切周期后仍保留。[Drawings API](https://www.tradingview.com/charting-library-docs/latest/ui_elements/drawings/drawings-api/)

`PROPOSED`：这对“精确顶部时间窗口”是必须测试的风险：周线/日线切换、无交易日、未来区间不能让边界悄悄漂移。即便换Advanced Charts，也需要我们的证据tooltip与时间映射测试，不能认为买/获批一个库就完成了模型展示。

### 5.3 数据授权和网站条款

`VERIFIED/DOC`：TradingView另列交易所实时数据购买，某些市场的默认源与直接交易所源不同；网站套餐不能概括成“所有市场实时数据已包含”。[附加行情说明](https://www.tradingview.com/support/solutions/43000471705-how-to-purchase-additional-market-data/)

`VERIFIED/DOC`：现行网站条款对自动抓取、数据再分发、非展示用途和竞争性复制等有约束。[网站条款](https://www.tradingview.com/policies/)。本文件不作具体法律适用判断；实施建议保持独立设计、使用许可库与单独取得的数据源，不搬运其私有脚本、页面素材或行情。用户登录授权不等于供应商授权。

## 6. 对LPPL的推荐顺序

以下为 `PROPOSED`，不是工程已经完成：

1. **先把单图做到可靠**：K线/成交量、十字光标、缩放、重置、数据截止、复权说明、顶部时间带、事件标记；每个交互保持上下文。
2. **再做工作台连续性**：全局资产搜索、收藏、最近资产、保存视图、候选卡定位、证据抽屉与AI问答。不要先复制几十种绘图工具。
3. **再做跨资产与市场发现**：双图、共享十字线/范围、收益归一化；筛选、热图、列表使用同一结果集合。
4. **之后做统一回放与规则事件**：维护自己的版本/触发账本，接入可审计AI，而不是误把TradingView回放或提醒组件当现成后端。
5. **保留当前库先验证缺口**：若现有图表层确实无法满足稳定交互，再做Lightweight/Advanced的同数据、同设备、同事件层比较。先验证许可证、体积、首屏、长历史、未来区间、触控/无障碍和维护成本，不凭演示外观决定迁移。

首页动画与营销页视觉不在本子任务的浏览器实测范围；应以主任务录得的当前页面为准。图表工作区的动效应帮助定位、切换和状态反馈，不能因为首页需要惊艳而让K线不断漂移或让价格变化与装饰运动混淆。

## 7. 最小验收建议

- 固定fixture核验日/周切换、停牌/节假日、未来时间带、复权与单位；区间日期不能漂移。
- 拖动与缩放后数据刷新不得重置视野；明确返回最新；自动尺度可恢复。
- 390px单指页面滚动与图表横拖不互相抢夺；长按检查行情、抽屉关闭后焦点/日期保留。
- 热图/列表/图表切换后标的集合、过滤条件、as-of相同。
- 回放状态下所有证据/AI回答采用同一as-of；实时侧栏隔离且不参与历史成绩。
- 图层开关、图例、色盲模式、键盘导航、reduced-motion与文本替代可用。
- 增量更新与全量更新分开；用桌面及低配手机测试时间轴、鼠标事件、内存与失联恢复；当前性能全部NOT_RUN。
- 许可文件、署名、数据来源展示、库代码可否进入公共仓库逐项核对。

以上改进提升的是研究与解释体验，不能据此声称LPPL预测准确率、提前量或抄底能力改善。
