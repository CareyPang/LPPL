# Devin 可执行任务：复用开源组件，补齐专业图表闭环

本文件是待执行计划。全部任务初始状态为 TODO / NOT_RUN。本报告不表示源码已移植、功能已上线或测试已通过。

## 0. 不重复做、不扩大范围

基于审查时 main `bf8bbf7` 重新比较最新 main 与 #118。已有独立终端、Canvas 交互、区间、回放、策略报告和本地自选必须复用。图表引擎实验继续在 #118 工作范围内完成，不再开第二套同类 demo。

生产代码通过既有数据入口读取，不从第三方 repo 的 Binance、A 股 demo 或 mock 接口加载数据；不运行其交易/钱包功能。完整周期 1.5、拟合与评分均保持原样。

若需要实现代码，采用 `od/<topic>` 分支及 Draft PR。当前只授权准备并提交可审查结果；不合并、部署、发布、购买资源或触发全量回测。不要把新依赖直接引入首页全局脚本。

## T00：先冻结复用来源与构建选择

依赖：无。交付：更新本目录 manifest，建立源码来源/许可清单和可重复构建记录。

- 核心实验基线继续锁 5.2.1，插件用表中精确版本；5.3.0 为独立对照，不能同时换核心、行情与数据合同。
- official 包使用正式发布 SHA/版本；OpenCharts 拆取文件保留 MIT，派生部分保留 Apache LICENSE/NOTICE；记录修改的文件及内容。
- 核对依赖闭包、锁文件 integrity、source hash、浏览器支持、依赖漏洞；本轮报告不是已完成供应链审计。
- #118 现有 standalone IIFE 与插件 ESM 统一通过一个隔离构建入口解决。核心不得打包两份；无需全站 React/Svelte 重构。
- 自托管精确构建产物，保留用户可见的 TradingView 署名。大陆网络性能单独测，不根据 CDN 可访问一次就判定稳定。

隔离试验工程的候选安装清单（本报告未执行）：

```sh
npm install --save-exact lightweight-charts@5.2.1 \
  @tradingview/lwc-plugin-user-price-lines@1.0.0 \
  @tradingview/lwc-plugin-vertical-line@1.0.1 \
  @tradingview/lwc-plugin-anchored-text@1.0.0 \
  @tradingview/lwc-plugin-accessibility@1.0.1
```

必须核对生成的 lockfile，不把上面的版本约束等同于运行验收。

验收：来源、许可证、精确依赖及构建产物一一对应；不加载模拟行情或交易依赖；没有浮动 master/@latest。

## T01：打通任意资产的完整图表入口

依赖：无，可与 T00 并行。交付：上证、贵州茅台两条完整用户旅程。

当前 `stock-header.js` 仅在 LPPL.SYMS 命中时显示“完整图表”，非指数个股隐藏。不要只删除 hidden 条件：先确保目标完整图表能消费同一资产的实际数据合同。

统一上下文至少包含：

```text
assetId + exchange + symbol + interval + adjustment
asof + scale + predictionId + focusEventId
returnContext (same-origin allowlisted route, filters, scroll position)
```

其中 assetId 应由已有目录规范化，不把 sh000001 上证指数和 sz000001 平安银行混淆。不在 URL 放账户凭据。returnTo 不接受任意外站 URL。

流程：列表 → 资产页 → 完整图表 → 点击区间 → 证据 → 返回。进入图表不新触发历史104周计算；当前分析仍与历史回放独立。

验收：上证、茅台均可完成；重新打开链接资产与 asof 一致；浏览器返回恢复列表筛选和滚动；已有结果先显示，失败不永久转圈。

## T02：以 #118 做绘图引擎对照及功能补齐

依赖：T00。交付：同一数据载荷下原 Canvas 与 LWC 试验的截图/交互/性能对照记录。

检查 main 与 #118 的功能差异，而不是仅比较K线是否画出来：main已有主/次簇、尺度强调、历史情景、事件，#118 当前的 scale band 实验不代表全部迁移完成。

- 必须保留主/次区间、历史补算标签、证据状态、当前/历史读数、成交量原始单位。
- 保留 #118 的未来交易日留白及 LPPL 区间 primitive。background-shade/session 包只着色已有 bar，不替代连续未来区间。
- 未来位置通过交易日历映射；未知日历不能静默按自然日生成。绘图遇到非交易日期保留原始日期并解释显示位置，不能修改证据日期。
- 缺失成交量不能填0伪装成交；未复权行情与模型后复权数据不能共用无标识价格对象。
- 手动线条按 time+price 保存，不按像素；切换复权隔离或显式迁移，不静默重贴。

验收：同资产/日期/口径数据完全一致；缩放拖动和窗口变化后区间锚点正确；交易所休市、跨年、停牌、未来空白有固定案例；没有未来OHLC。

## T03：先接正式插件，再补完整绘图操作

依赖：T02。交付：可真正完成研究操作的最小工具集。

第一批：
1. UserPriceLines：添加/删除水平研究线；删除UI自行接线。若需要拖动横线，另补交互，不宣称插件已经支持。
2. VerticalLine：事件/asof垂线；仅用户对象允许拖动，模型区间及历史证据不可编辑。
3. AnchoredText：固定图表标识与证据标签；不冒充可拖自由文字工具。
4. Accessibility：中文帮助、键盘操作和数据表；不加声音素材，不默认发声。

下一批：
- 趋势线与矩形优先评估官方 primitive/PoC；若所需编辑流程较多，再移植 OpenCharts drawing-tools 的最小依赖闭包。
- OpenCharts 的 geometry 可先单独提取；manager/hit-test/renderers/types/resolve 需要一起审查和适配。
- 不降级回 LWC4.2.3；重写固定秒数外推、接口类型及 4→5 差异；按 migration 文档和编译检查逐项记录。
- 每个工具必须具备选择、取消、编辑、删除、锁定/隐藏及必要的undo/redo。只画出线条不算交付。

验收：切资产时不串线；滚动/缩放/调整大小后对象正确；按 Esc 可取消放置；删除与undo/redo可逆；模型原始记录不能被用户拖改。

## T04：先交付证据 PNG，再考虑分享链接

依赖：T02，可与T03并行。

5.2.1 已支持 `chart.takeScreenshot(true, false)`。使用此接口取得图表画布，再在导出专用画布合成必要信息；这是实施起点，不是已测试代码。

PNG 至少包含：
- 资产代码/交易所、K线周期、复权口径；
- 成交量和选中的主/次顶部区间、所选拟合尺度；
- 数据来源、data_asof、model_version、prediction_id；
- 当前是历史补算还是实际记录；
- 证据状态、区间性质，以及首次可见时间的来源/可信度。

DOM 侧栏、tooltip、页脚不会自动进入图表库截图，必须显式合成。没有可信首次发布时间时写“未记录/未验证”，不把导出时间当原预测发布时间。

处理 toBlob 返回 null、画布被跨域资源污染、字体未就绪、下载失败；失败不提示“导出成功”。下载后释放 objectURL。默认不生成公开图片链接。

验收：打开最终 PNG 检查主图、成交量、区间、中文、页脚；桌面与390px都可读；旧导出图片不受随后模型修订影响。仅检测下载文件存在不够。

## T05：绘图、布局、研究证据分开保存

依赖：T03。交付：本地保存与失败恢复；云端同步后续另立任务，不需本次部署资源。

推荐对象合同（设计建议）：

```text
Drawing {
  id, schemaVersion, assetId, exchange, symbol, adjustment,
  type, anchors[{sessionDate, price}], style, locked, hidden,
  origin:"user", revision, createdAt, updatedAt
}
ViewState {
  assetId, interval, adjustment, asof, scale, visibleTimeRange, panes
}
ResearchRecord {
  predictionId, modelVersion, dataVersion, dataAsOf,
  generatedAt, firstVisibleAt, visibilityClockSource,
  evidenceStatus, supersedesPredictionId
}
```

- 用户对象可编辑；模型对象根据 predictionId只读，修订生成新记录。
- 原 OpenCharts storage 可能吞错后回 saved:true，不可沿用。保存返回明确 persisted/error/revision；只有写入完成才提示成功。
- 隔离用户、资产、交易所、复权与schema；加载校验JSON、数量上限、文本长度、数值有限性，渲染不执行对象内脚本/HTML。
- 存储满、禁用、损坏、迁移失败均保留当前会话，提示未保存并提供重试/导出；不能谎称云同步。
- 不把手绘对象写入模型账本；截图ID、布局ID、预测ID使用不同命名空间。

验收：新增两条线→撤销→恢复→刷新→重开一致；写入拒绝时明确未保存；切换上证与平安银行不串对象；旧研究记录不被覆盖。

## T06：390px、交互、性能和事件清理

依赖：T01–T05。

- 独立图表可让滚轮缩放；嵌在长页面的图表可用 Ctrl/⌘+滚轮，提供提示。两种模式必须有明确场景，避免用户无意锁住页面。
- 390px 使用折叠工具栏/底部面板；按钮至少44px；手势处理 pointercancel、双指缩放、屏幕旋转、键盘弹出。
- 底部面板/tooltip 不盖住当前选中点和关键证据；无法图形操作时可用日期/价格输入和数据表。
- 复用现有行情与任务缓存；用可见时间范围分页请求历史行情，不把滚动到左边等同于重新拟合104周。
- 切资产取消/忽略旧请求；热更新不能将A资产结果写进B资产。普通最新bar增量用update；历史更正、复权变化按数据版本重新校验，不能盲目增量拼接。
- detach时移除监听、ResizeObserver、订阅和插件；多次进入退出不累积对象。
- 记录设备、浏览器、bar数、总下载体积、首次可交互时间、帧时间、内存和失败率。未经测试不承诺“60fps”或“零卡顿”。

验收环境：桌面Chrome/Edge、390px模拟器；真实安卓/iOS、Safari、弱网、大陆网络另列 NOT_INSPECTED，直到实际测完。评价吞吐不替代坐标正确性。

## T07：再评估5.3与对外能力

依赖：前述验收通过。

5.3修复历史数据更新和拖动时新bar等问题，可做独立升级对照；校验补零YYYY-MM-DD等输入要求。只在同一固定样本/设备上比较，不随手同时改变数据源。

后续“分享研究”“分享布局”“嵌入研究卡”分开设计：
- PNG是静态图片，布局是可恢复状态，研究记录是带版本的证据。
- 自建只读embed先核对数据展示/转授权范围，限制权限和消息来源，不输出后台密钥。
- 第三方TradingView Widget只能显示其支持的数据，不是LPPL自有模型叠层的通用容器。
- 不为图表体验引入实盘交易、Pine兼容层或任意脚本执行器。

## 交付验收清单

- [ ] T00 固定来源、LICENSE/NOTICE、版本、依赖、hash完整。
- [ ] 上证与茅台的列表→完整图表→区间→证据→返回均完成。
- [ ] 当前行情/分析不被历史104周任务阻塞。
- [ ] 主/次区间及事件与旧版对齐；新页面未改变模型输出。
- [ ] 自由绘图完整操作、撤销、保存失败提示均通过。
- [ ] 日期遵循交易所日历；数据口径不混用；无模拟数据fallback。
- [ ] PNG含完整证据，图片已实际打开检查。
- [ ] 390px、桌面、键盘、触摸、DPR/尺寸变化已记录。
- [ ] 布局与手绘隔离，模型修订不可变；没有假首次发布时间。
- [ ] 性能、内存与事件清理有实测记录；没测的环境如实标注。
- [ ] 只更新Draft PR；未合并、未部署、未发布。

任何一项失败，保留原Canvas入口和旧结果，先修复或缩小迁移范围，不能靠隐藏错误、删掉证据字段或自动填模拟行情过关。
