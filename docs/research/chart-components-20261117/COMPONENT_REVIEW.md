# 组件复用清单：哪些能直接用，哪些需要改造

状态：源码/发布/许可证已检查；所有运行验证为 NOT_RUN。引用均固定到本次审查 SHA。许可条款核验不等于完成全部依赖和权利来源审计。

## A. 官方 Lightweight Charts：优先采用

**VERIFIED / docs + code。** 核心 v5.3.0 于 2026-11-10 发布；LPPL #118 仍为 5.2.1。官方于 11 月 13 日发布独立插件，不能把它们和 plugin-examples 下的概念示例混为一谈。

- [核心 v5.3.0](https://github.com/tradingview/lightweight-charts/releases/tag/v5.3.0)
- [插件发布批次](https://github.com/tradingview/lightweight-charts/releases/tag/plugins-2026-11-13)
- [LICENSE](https://github.com/tradingview/lightweight-charts/blob/aebdfc8f0d85b95e43467ae79516753158d60e61/LICENSE)、[NOTICE](https://github.com/tradingview/lightweight-charts/blob/aebdfc8f0d85b95e43467ae79516753158d60e61/NOTICE)
- [官方署名要求](https://tradingview.github.io/lightweight-charts/docs)

### A1. 已发布插件，可锁版本试用

下列 npm 版本已核验，声明 peerDependency 为 `lightweight-charts: ^5.0.0`，涵盖 5.2.1；实际运行兼容 **NOT_RUN**。均为 Apache-2.0，保留 LICENSE/NOTICE、修改说明及所需署名。表中“直接”指有正式包/API，不是无需编程。

| 精确包版本 | 已有能力 | 没有替我们完成的能力 | LPPL 采用 |
|---|---|---|---|
| `@tradingview/lwc-plugin-user-price-lines@1.0.0` | 浮动加号添加水平价格线；addLine/lines/removeLine/removeAll；新增/删除事件 | 横线拖动、撤销重做、保存、账户同步；删除按钮还需应用接线 | 第一批，手工研究线 |
| `@tradingview/lwc-plugin-vertical-line@1.0.1` | 垂线、时间标签、badge、draggable、setTime、变化事件 | 交易日历、不可变模型证据、对象存储 | 第一批，事件/asof 标线；模型对象禁拖动 |
| `@tradingview/lwc-plugin-anchored-text@1.0.0` | 固定在图表边角的文字 | 绑定时间/价格、端点拖动的自由文字工具 | 第一批，代码、日期、历史补算标签 |
| `@tradingview/lwc-plugin-accessibility@1.0.1` | 键盘、焦点、读屏、数据表、帮助、高对比适配 | 中文内容、LPPL语义和实际辅助技术验收 | 第一批，无须启用声音 |
| `@tradingview/lwc-plugin-background-shade-series@1.0.0` | 按已有柱显示全高底色，不影响价格 autoscale | 连续未来 tc 时间带、未来交易日生成 | 后续历史状态背景；不替换 #118 区间 primitive |
| `@tradingview/lwc-plugin-session-highlighting@1.0.0` | 根据已有 bar 时间返回高亮色 | 日历、市场会话识别、预测区间 | 后续按需；日线产品不优先 |
| `@tradingview/lwc-toolkit@1.1.0` | 插件基类、生命周期、坐标/命中等工具 | 工具栏和完整研究工作区 | 随选定插件审查依赖 |

固定源码：
[价格线](https://github.com/tradingview/lightweight-charts/blob/aebdfc8f0d85b95e43467ae79516753158d60e61/packages/lwc-plugin-user-price-lines/src/user-price-lines.ts#L184)、
[日期线](https://github.com/tradingview/lightweight-charts/blob/aebdfc8f0d85b95e43467ae79516753158d60e61/packages/lwc-plugin-vertical-line/src/vertical-line.ts#L190)、
[锚定文字](https://github.com/tradingview/lightweight-charts/blob/aebdfc8f0d85b95e43467ae79516753158d60e61/packages/lwc-plugin-anchored-text/README.md)、
[无障碍](https://github.com/tradingview/lightweight-charts/blob/aebdfc8f0d85b95e43467ae79516753158d60e61/packages/lwc-plugin-accessibility/README.md)、
[底色](https://github.com/tradingview/lightweight-charts/blob/aebdfc8f0d85b95e43467ae79516753158d60e61/packages/lwc-plugin-background-shade-series/README.md)、
[时段高亮](https://github.com/tradingview/lightweight-charts/blob/aebdfc8f0d85b95e43467ae79516753158d60e61/packages/lwc-plugin-session-highlighting/README.md)。

公开包入口：
[user-price-lines](https://www.npmjs.com/package/@tradingview/lwc-plugin-user-price-lines)、
[vertical-line](https://www.npmjs.com/package/@tradingview/lwc-plugin-vertical-line)、
[accessibility](https://www.npmjs.com/package/@tradingview/lwc-plugin-accessibility)。

**接入方式建议：** #118 目前加载 standalone IIFE；不要把 ESM 插件代码直接当普通 script 加载，也不要让插件再打包第二份不同版本的图表核心。选择一个隔离构建入口，核心与插件共享同一锁定依赖；编译产物可自托管。无需为接插件把整个 LPPL 网站迁移成 React/Svelte。

### A2. 官方可提取代码

以下固定到 v5.3.0，移植至 5.2.1 时按实际 API 核对，不整份复制 gallery 的随机数据、全局颜色变量和定时器。

| 功能 | 直接代码入口 | 适配重点 |
|---|---|---|
| PNG 截图 | [data/screenshot.js](https://github.com/tradingview/lightweight-charts/blob/0bad38a070220e6315aa779bb80483fe97cf6d1b/website/examples/data/screenshot.js#L42) | takeScreenshot/toBlob/下载及释放 URL；补证据页脚 |
| K 线 | [series-types/candlestick.js](https://github.com/tradingview/lightweight-charts/blob/0bad38a070220e6315aa779bb80483fe97cf6d1b/website/examples/series-types/candlestick.js) | 接真实 OHLC，统一复权/日历；#118 已有 |
| 成交量 | [price-scales/price-and-volume.js](https://github.com/tradingview/lightweight-charts/blob/0bad38a070220e6315aa779bb80483fe97cf6d1b/website/examples/price-scales/price-and-volume.js) | 示例价格为 Area，LPPL 用 Candlestick；量能 Histogram |
| 多 pane | [panes/multiple-panes.js](https://github.com/tradingview/lightweight-charts/blob/0bad38a070220e6315aa779bb80483fe97cf6d1b/website/examples/panes/multiple-panes.js) | addSeries 的 paneIndex；共享时间轴 |
| 多资产比较 | [compare-multiple-series.js](https://github.com/tradingview/lightweight-charts/blob/0bad38a070220e6315aa779bb80483fe97cf6d1b/website/examples/series-types/compare-multiple-series.js) | 基准日、百分比、币种、日期交集 |
| 双图十字线 | [sync-crosshairs.js](https://github.com/tradingview/lightweight-charts/blob/0bad38a070220e6315aa779bb80483fe97cf6d1b/website/examples/crosshair/sync-crosshairs.js) | 不同日历按日期映射，不直接照搬索引 |
| 公告/事件标记 | [series-markers.js](https://github.com/tradingview/lightweight-charts/blob/0bad38a070220e6315aa779bb80483fe97cf6d1b/website/examples/markers-and-lines/series-markers.js#L777) | 接 event_id、首次可得时间，不泄漏未来事件 |
| 悬停明细 | [floating-tooltip.js](https://github.com/tradingview/lightweight-charts/blob/0bad38a070220e6315aa779bb80483fe97cf6d1b/website/examples/tooltips-and-legends/floating-tooltip.js#L222) | 手机边缘避让、中文、读屏；DOM 不自动进入截图 |
| 历史按需加载 | [infinite-history.js](https://github.com/tradingview/lightweight-charts/blob/0bad38a070220e6315aa779bb80483fe97cf6d1b/website/examples/data/infinite-history.js#L124) | 只取可见范围触发思路，换真实缓存/API；不是自动回测 |
| 未来留白 | [whitespace.js](https://github.com/tradingview/lightweight-charts/blob/0bad38a070220e6315aa779bb80483fe97cf6d1b/website/examples/data/whitespace.js) | 只有交易日占位，无未来 OHLC；#118 已有基础 |

**更正上一轮待核问题：5.2.1 已支持 `takeScreenshot(addTopLayer?, includeCrosshair?)`，不必为截图立即升级。** [固定 5.2.1 接口](https://github.com/tradingview/lightweight-charts/blob/b2ce010e4ad59f6556c9ed60e2b2b30feccdd2d1/src/api/ichart-api.ts#L314)。可先试验 `takeScreenshot(true, false)`，但 DOM 证据侧栏不会自动纳入，必须合成并打开最终 PNG 检查。

### A3. 不能误当成完整工具的 PoC

[plugin-examples 说明](https://github.com/tradingview/lightweight-charts/blob/c29c51e1e5bc61981da5832c97797cb8283d120f/plugin-examples/README.md) 区分正式插件和 PoC。

- [trend-line](https://github.com/tradingview/lightweight-charts/blob/c29c51e1e5bc61981da5832c97797cb8283d120f/plugin-examples/src/plugins/trend-line/trend-line.ts#L130)：已有两点线条、标签、autoscale 渲染；没有完整点击放置、端点编辑、对象选择、保存与 undo/redo。
- [rectangle-drawing-tool](https://github.com/tradingview/lightweight-charts/blob/c29c51e1e5bc61981da5832c97797cb8283d120f/plugin-examples/src/plugins/rectangle-drawing-tool/rectangle-drawing-tool.ts#L355)：已有两次点击、预览、选色、事件清理；仍需对象选择、删除、拖动、保存、撤销。示例按钮 20px，不能直接作为手机触控交付。
- 普通 MA/相关/比率示例是指标计算代码，不是完整指标市场；不因此修改 LPPL 模型或越过前端契约。

## B. OpenCharts：绘图管理有价值，整站搬入不合适

基线 `399e27538d8150796571dbdecbe920a54b771de4`。**VERIFIED / code**：React 终端，依赖声明 LWC ^4.2.0，锁文件实际 4.2.3；有 React Query/Zustand 等应用依赖。自有代码 MIT；部分插件由官方 Apache-2.0 示例派生，不能只保留 MIT。[package.json](https://github.com/dylanpersonguy/OpenCharts/blob/399e27538d8150796571dbdecbe920a54b771de4/package.json)、[LICENSE](https://github.com/dylanpersonguy/OpenCharts/blob/399e27538d8150796571dbdecbe920a54b771de4/LICENSE)、[NOTICE](https://github.com/dylanpersonguy/OpenCharts/blob/399e27538d8150796571dbdecbe920a54b771de4/NOTICE)。

| 候选 | 具体源码 | 采用判断 |
|---|---|---|
| 几何与命中基础 | [geometry.ts](https://github.com/dylanpersonguy/OpenCharts/blob/399e27538d8150796571dbdecbe920a54b771de4/src/lib/chart-plugins/drawing-tools/geometry.ts) | 小型纯函数，可提取候选；仍补边界测试 |
| 绘图生命周期 | [manager.ts](https://github.com/dylanpersonguy/OpenCharts/blob/399e27538d8150796571dbdecbe920a54b771de4/src/lib/chart-plugins/drawing-tools/manager.ts#L134) | 含放置/选择/拖动/锁定/磁吸/快捷键/清理；需移植 LWC5 坐标/API |
| 绘图渲染与命中 | [hit-test](https://github.com/dylanpersonguy/OpenCharts/blob/399e27538d8150796571dbdecbe920a54b771de4/src/lib/chart-plugins/drawing-tools/hit-test.ts)、[renderers](https://github.com/dylanpersonguy/OpenCharts/blob/399e27538d8150796571dbdecbe920a54b771de4/src/lib/chart-plugins/drawing-tools/renderers.ts)、[primitive](https://github.com/dylanpersonguy/OpenCharts/blob/399e27538d8150796571dbdecbe920a54b771de4/src/lib/chart-plugins/drawing-tools/drawings-primitive.ts) | 和 types/resolve 形成依赖闭包，不是单文件插件 |
| undo/redo 与资产切换 | [useChartDrawings.ts](https://github.com/dylanpersonguy/OpenCharts/blob/399e27538d8150796571dbdecbe920a54b771de4/src/hooks/useChartDrawings.ts#L44) | 借状态操作；脱离 React hook 或明确隔离组件 |
| 对象树 | [ObjectTreePanel.tsx](https://github.com/dylanpersonguy/OpenCharts/blob/399e27538d8150796571dbdecbe920a54b771de4/src/pages/trading/ObjectTreePanel.tsx) | 参考选择/锁定/隐藏/删除；不强迫迁移整个前端 |
| 只读 adapter | [adapter/types.ts](https://github.com/dylanpersonguy/OpenCharts/blob/399e27538d8150796571dbdecbe920a54b771de4/src/adapter/types.ts#L36) | marketData 必需、trading/storage 可选；加入 LPPL 来源与证据字段 |
| 安全存储辅助 | [safe-storage.ts](https://github.com/dylanpersonguy/OpenCharts/blob/399e27538d8150796571dbdecbe920a54b771de4/src/lib/safe-storage.ts) | 可提取候选；必须把失败返回到 UI |

### B1. 采用前必须修复

1. **未来日期外推不适合直接用于 A 股。** [resolve.ts:88](https://github.com/dylanpersonguy/OpenCharts/blob/399e27538d8150796571dbdecbe920a54b771de4/src/lib/chart-plugins/drawing-tools/resolve.ts#L88) 按固定 intervalSec 推时间；需换成经过验证的交易日映射，处理周末、休市、停牌，不能把 5 根日 K 当成 5 个自然日。
2. **保存失败仍可能显示成功。** [api.ts:72](https://github.com/dylanpersonguy/OpenCharts/blob/399e27538d8150796571dbdecbe920a54b771de4/src/services/api.ts#L72) 吞 storage 异常，保存接口继续返回 saved:true；上层 hook 也吞 catch。必须改成实际持久化回执。原 key 只有 symbol，须加入用户、交易所、复权和 schema 版本。
3. **演示行情不能接真实链路。** [candles.ts:123](https://github.com/dylanpersonguy/OpenCharts/blob/399e27538d8150796571dbdecbe920a54b771de4/src/services/demo/candles.ts#L123) 平移历史时间到当前；[Root.tsx:45](https://github.com/dylanpersonguy/OpenCharts/blob/399e27538d8150796571dbdecbe920a54b771de4/src/Root.tsx#L45) 在 Binance 失败时回退 demo。禁止导入这些 fallback、模拟盘口与样例新闻。
4. **多实例尚需隔离。** [registry.ts:11](https://github.com/dylanpersonguy/OpenCharts/blob/399e27538d8150796571dbdecbe920a54b771de4/src/adapter/registry.ts#L11) 为单全局 adapter；两台终端不能直接保证不同 asof/数据版本隔离。
5. **不要顺带引入钱包和实盘交易。** 当前代码含 Hyperliquid 相关选择与操作，超出本项目只读研究范围。[adapterChoice.ts](https://github.com/dylanpersonguy/OpenCharts/blob/399e27538d8150796571dbdecbe920a54b771de4/src/adapterChoice.ts)

**VERIFIED / CI：** 当前提交的 [CI run 42921799034](https://github.com/dylanpersonguy/OpenCharts/actions/runs/42921799034) 中 Typecheck/Lint 成功、Test 失败，后续 Build、安全头、体积与库构建检查跳过。失败根因 NOT_INSPECTED，不猜测；不能称当前 head 已完整验收。

**NOT_ESTABLISHED：** 已查核心图表、工具栏及截图关键词，未发现可确认的截图导出实现；不要把 OpenCharts 接入等同于获得 Take a snapshot。已有会话回放/穿线 toast 不能替代 LPPL 多年 as-of 评价器或离线告警服务。未确认有完整 Pine 引擎。

## C. Timelk/open-tradingview

基线 `50d7b7db90c4fffeac7ec83626aaec2778d9bdf2`。**VERIFIED / code**：MIT，Svelte5 + TypeScript + Vite6，Node要求≥24，自研WebGL2/Canvas2D，没有LWC依赖。因此不是给#118安装一个插件即可接入。[package.json](https://github.com/Timelk/open-tradingview/blob/50d7b7db90c4fffeac7ec83626aaec2778d9bdf2/package.json)、[LICENSE](https://github.com/Timelk/open-tradingview/blob/50d7b7db90c4fffeac7ec83626aaec2778d9bdf2/LICENSE)、[第三方通知](https://github.com/Timelk/open-tradingview/blob/50d7b7db90c4fffeac7ec83626aaec2778d9bdf2/THIRD_PARTY_NOTICES.md)。

| 候选 | 固定源码 | LPPL 判断 |
|---|---|---|
| 绘图协议与注册表 | [types](https://github.com/Timelk/open-tradingview/blob/50d7b7db90c4fffeac7ec83626aaec2778d9bdf2/src/lib/drawing/types.ts)、[registry](https://github.com/Timelk/open-tradingview/blob/50d7b7db90c4fffeac7ec83626aaec2778d9bdf2/src/lib/drawing/registry.ts) | 时间/价格锚点、Projection、DrawingHost可借鉴；转接LPPL |
| 手势与基础图形 | [gestures](https://github.com/Timelk/open-tradingview/blob/50d7b7db90c4fffeac7ec83626aaec2778d9bdf2/src/lib/drawing/gestures.ts)、[primitives](https://github.com/Timelk/open-tradingview/blob/50d7b7db90c4fffeac7ec83626aaec2778d9bdf2/src/lib/drawing/primitives.ts)、[builtins](https://github.com/Timelk/open-tradingview/blob/50d7b7db90c4fffeac7ec83626aaec2778d9bdf2/src/lib/drawing/builtins.ts#L82) | 可选少量工具移植；需theme/DPR/坐标适配，不再引入第三套图表引擎 |
| 撤销/锁定/隐藏 | [engine](https://github.com/Timelk/open-tradingview/blob/50d7b7db90c4fffeac7ec83626aaec2778d9bdf2/src/lib/drawing/engine.ts#L64)、[scene/store](https://github.com/Timelk/open-tradingview/blob/50d7b7db90c4fffeac7ec83626aaec2778d9bdf2/src/lib/scene/store.ts#L44) | 有实际命令与80步历史；依赖scene/model/commands/serialization，非单文件即插即用 |
| 导入校验与版本迁移 | [drawing/store](https://github.com/Timelk/open-tradingview/blob/50d7b7db90c4fffeac7ec83626aaec2778d9bdf2/src/lib/drawing/store.ts)、[serialization](https://github.com/Timelk/open-tradingview/blob/50d7b7db90c4fffeac7ec83626aaec2778d9bdf2/src/lib/scene/serialization.ts) | 对象/点数、有限数值和样式限制值得参考；禁止覆盖模型对象 |
| PNG/JPEG合成 | [controller:948](https://github.com/Timelk/open-tradingview/blob/50d7b7db90c4fffeac7ec83626aaec2778d9bdf2/src/lib/chart/controller.ts#L948)、[chart-adapter:349](https://github.com/Timelk/open-tradingview/blob/50d7b7db90c4fffeac7ec83626aaec2778d9bdf2/src/lib/agent/chart-adapter.ts#L349) | 真有canvas合成；原实现不含DOM图例/按钮，LPPL仍须补证据页脚 |
| 命名布局与面板 | [workspace/layout](https://github.com/Timelk/open-tradingview/blob/50d7b7db90c4fffeac7ec83626aaec2778d9bdf2/src/lib/workspace/layout.ts#L82) | 本地布局参考，不是云同步 |
| AI读图和可撤销标注 | [chart-adapter:130](https://github.com/Timelk/open-tradingview/blob/50d7b7db90c4fffeac7ec83626aaec2778d9bdf2/src/lib/agent/chart-adapter.ts#L130) | 后续独立研究；本次不引入代理执行或公网写工具 |

### C1. 明确不能直接带入的部分

1. **模拟价格回退。** A股连接器默认auto；真实网关和浏览器接口失败后可能返回模拟K线，connect还会先发送ok。[默认配置](https://github.com/Timelk/open-tradingview/blob/50d7b7db90c4fffeac7ec83626aaec2778d9bdf2/src/lib/market/connector-config.ts#L46)、[生成样本](https://github.com/Timelk/open-tradingview/blob/50d7b7db90c4fffeac7ec83626aaec2778d9bdf2/src/lib/market/connectors.ts#L416)、[失败回退](https://github.com/Timelk/open-tradingview/blob/50d7b7db90c4fffeac7ec83626aaec2778d9bdf2/src/lib/market/connectors.ts#L499)。不评价作者演示意图；但LPPL真实数据链路必须失败即显式error/stale，禁止采用该默认行为。
2. **连续时间外推。** [coordinates.ts](https://github.com/Timelk/open-tradingview/blob/50d7b7db90c4fffeac7ec83626aaec2778d9bdf2/src/lib/drawing/coordinates.ts#L3) 在已载入范围外按固定毫秒延伸，需改交易日映射。A股周期映射与统一交易规则也不能覆盖沪深京所有情况。
3. **不是完整历史数据后端。** 连接器明确不支持日期范围历史/回填；不能用它替代LPPL as-of数据与历史重放。[连接器能力](https://github.com/Timelk/open-tradingview/blob/50d7b7db90c4fffeac7ec83626aaec2778d9bdf2/src/lib/market/connectors.ts#L698)
4. **本地服务不能直接暴露公网。** agent bridge采用loopback/same-origin且没有用户认证；单独static dist也没有Vite本地API/SQLite/MCP服务。[agent-bridge](https://github.com/Timelk/open-tradingview/blob/50d7b7db90c4fffeac7ec83626aaec2778d9bdf2/server/agent-bridge.ts#L37)、[vite.config](https://github.com/Timelk/open-tradingview/blob/50d7b7db90c4fffeac7ec83626aaec2778d9bdf2/vite.config.ts#L22)。本次只读组件复用不涉及部署该后端。
5. **没有可用Pine编辑器/通用回测引擎。** 仓库说明已删除PineTS、Monaco、执行worker和回测账本；MA交叉/RSI只做信号标记，不是盈利验证。[范围核验](https://github.com/Timelk/open-tradingview/blob/50d7b7db90c4fffeac7ec83626aaec2778d9bdf2/docs/native-scope-validation-2026-10-01.md#L3)

**维护证据：** 本次main只有3个可见提交，未找到release或.github工作流；源码树有176个.test.ts文件。作者所述1771通过、百万样本60fps属于**作者报告**，不能外推为LPPL或390px表现。运行、长期稳定性和真实数据可靠性均未建立。小仓库并非不可用，但不能据此称成熟替代品。

## D. 对抗性复核后的最终取舍

| 容易误判的说法 | 核验后的结论 |
|---|---|
| “名字叫open-tradingview，所以能拿到官方完整网站” | 两个第三方项目均非TradingView官方完整源码 |
| “MIT就能免费展示所有行情” | 代码许可与第三方行情、新闻及转展示权不同 |
| “有画线截图，就能直接替换LPPL图表” | 坐标、数据合同、价格口径、模型叠层与对象持久化仍需适配 |
| “官方插件全是PoC” | 已有正式发布包；趋势线/矩形等部分示例仍是PoC |
| “5.2.1不能截图，必须升级” | 已读5.2.1接口，截图参数已存在 |
| “OpenCharts保存接口返回true就写入成功” | 实现可能吞异常后返回saved:true，必须修复 |
| “网络失败也能显示K线，所以稳” | 可能进入模拟fallback，LPPL必须排除 |
| “接库就有Pine、策略回测和离线告警” | 图表库、页面交互和服务器研究/告警是不同能力 |
| “多窗格=多个独立资产终端” | pane共享图表时间轴；多实例、不同asof和数据隔离仍需实现 |
| “换图表让顶部更准” | 只能改表达与操作，模型效果必须独立评价 |

推荐方案因此为：**官方核心/正式插件优先，OpenCharts做最小绘图闭包移植，open-tradingview做交互/命令/截图参考。** 完整仓库迁入、模拟行情、交易后端、AI自动交易和新指标预测均不在本轮采用范围。

