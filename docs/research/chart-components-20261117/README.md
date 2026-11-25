# LPPL 专业图表与开源组件复用审查

审查日期：2026-11-17。交付性质：源码与官方文档审查、组件目录、Devin 执行任务；不是图表迁移完成报告。

## 结论

**建议采用“现有 LPPL 数据与证据层 + PR #118 图表试验 + 官方 Lightweight Charts 核心/插件”的路线。OpenCharts 选择性提取绘图对象管理思路；open-tradingview 参考命令、画布合成及交互分层，不整站替换。** 这是设计建议，尚未通过运行时对照。

三个仓库确实有可使用的代码，但“有代码”“许可允许复用”“适配 LPPL 后正确运行”是三件事。当前最值得直接试用的是官方 K 线/成交量/多面板/截图 API，以及已发布的标注插件；自由趋势线、对象树、撤销/重做和保存仍需要集成工作。没有任何一个仓库能直接赋予 LPPL 更准确的顶部预测能力。

- [逐仓库与组件审查](COMPONENT_REVIEW.md)：实际文件、许可、成熟度、已发现缺陷。
- [Devin 执行清单](DEVIN_TASKS.md)：按依赖实施、验收门、与现有 PR 去重。
- [机器可读来源目录](upstream-manifest.json)：固定 SHA、候选源码和采用状态。
- [TradingView 工作区增量报告](TRADINGVIEW_WORKSPACE.md)：承接上一轮截图、Widget、Full chart 研究及主线去重。

## 证据口径

| 标记 | 含义 |
|---|---|
| VERIFIED / code | 已在指定提交读取实现；不代表运行通过 |
| VERIFIED / docs | 官方文档或仓库许可、发布元数据已核对 |
| VERIFIED / CI | 已读取特定上游 Actions 结果；不代表本地复验 |
| 作者报告 | README、宣传性能或作者测试声明，未独立运行 |
| NOT_RUN | 本轮没有安装、构建或执行该第三方项目 |
| NOT_ESTABLISHED | 没有足够证据，例如生产成熟度、预测效果、完整数据展示授权 |
| NOT_INSPECTED | 未检查的浏览器、手机、生产环境或组件范围 |
| 建议 | 我们为 LPPL 提出的实现和验收要求，不是现有功能声明 |

本轮没有安装三个仓库的依赖、执行它们的启动脚本或运行其模型；没有进行性能排名。不存在“已在 390px 验收通过”的结论。许可证和 API 可读性不能替代代码、安全、数据与运行时验收。

## 冻结基线

| 仓库/分支 | 固定提交/版本 | 核验用途 |
|---|---|---|
| CareyPang/LPPL main | `bf8bbf782dd9031dfe18b574b275edb88f9b5d01` | 当前主线源码（线上部署状态本轮未核验） |
| LPPL PR #118 | `2e529af11d201ef61567a89ce86f9b08cd9e5309`，LWC 5.2.1 | 已有图表库对比试验，尚未并入 main |
| Timelk/open-tradingview | `50d7b7db90c4fffeac7ec83626aaec2778d9bdf2` | MIT；Svelte / 自研图表 |
| dylanpersonguy/OpenCharts | `399e27538d8150796571dbdecbe920a54b771de4` | MIT 项目；LWC 4.2.3 |
| tradingview/lightweight-charts | v5.3.0，`0bad38a070220e6315aa779bb80483fe97cf6d1b` | 最新稳定核心发布 |
| 官方插件发布 | plugins-2026-11-13，`aebdfc8f0d85b95e43467ae79516753158d60e61` | 已发布插件的来源 |

本次 fresh main 核验确认 #127 已由仓库其他操作者合并；这不是本轮助手执行的合并。旧 PR #110 仍保存先前 TradingView / 彭博等研究；本报告为新的增量审查，不覆盖旧实测记录。

## LPPL 已有什么，避免重复建设

以下均为 **VERIFIED / code**；浏览器行为本轮 **NOT_RUN**。

| 能力 | 当前状态 | 固定来源 |
|---|---|---|
| 独立图表终端 | 已有 index.html；生产采用原生 Canvas 2D，不是已采用 LWC | [主图代码](https://github.com/CareyPang/LPPL/blob/bf8bbf782dd9031dfe18b574b275edb88f9b5d01/frontend/index.html#L584) |
| K 线交互 | 十字光标、拖动、缩放、复位、键盘操作已有 | [终端工具栏](https://github.com/CareyPang/LPPL/blob/bf8bbf782dd9031dfe18b574b275edb88f9b5d01/frontend/index.html#L312)、[交互](https://github.com/CareyPang/LPPL/blob/bf8bbf782dd9031dfe18b574b275edb88f9b5d01/frontend/index.html#L902) |
| 模型区间叠层 | 主/次簇、跨尺度强调、历史区间已有 | [叠层](https://github.com/CareyPang/LPPL/blob/bf8bbf782dd9031dfe18b574b275edb88f9b5d01/frontend/index.html#L715) |
| 历史回放 | 截止日请求、逐周回放、个股历史定位已有；历史补算必须保持明确标识 | [回放](https://github.com/CareyPang/LPPL/blob/bf8bbf782dd9031dfe18b574b275edb88f9b5d01/frontend/index.html#L1432)、[个股](https://github.com/CareyPang/LPPL/blob/bf8bbf782dd9031dfe18b574b275edb88f9b5d01/frontend/app/stock-view.js#L461) |
| 策略报告 | 已有事前登记规则的指标/交易/属性报告；不是自由编程策略引擎 | [strategy-panel](https://github.com/CareyPang/LPPL/blob/bf8bbf782dd9031dfe18b574b275edb88f9b5d01/frontend/app/strategy-panel.js#L11) |
| 自选/最近分析 | 已有浏览器本地能力，不等于账户同步 | [od-watch](https://github.com/CareyPang/LPPL/blob/bf8bbf782dd9031dfe18b574b275edb88f9b5d01/frontend/app/od-watch.js#L163) |
| 轻量图表试验 | #118 已有 Candlestick/Histogram、未来交易日留白、区间 primitive、尺度选择 | [chart-lab](https://github.com/CareyPang/LPPL/blob/2e529af11d201ef61567a89ce86f9b08cd9e5309/frontend/app/chart-lab.js#L198) |

明确需要补全的链路：`stock-header.js` 当前只为命中指数目录的标的显示“完整图表”，贵州茅台等普通股票入口隐藏。[条件代码](https://github.com/CareyPang/LPPL/blob/bf8bbf782dd9031dfe18b574b275edb88f9b5d01/frontend/app/stock-header.js#L197)

在已检查的生产图表页面和相关模块中，尚未找到用户自由绘图对象管理、图表截图导出、布局持久化及 Widget 生成器。该结论限定检查范围，不能扩大成全仓绝无相似名称文件。

## 采用顺序

1. **先把上证和茅台完整链路接通。** 保留已有图表与数据合同，统一资产标识、截止日、尺度和返回上下文。
2. **在 #118 延续唯一图表引擎试验。** 固定 5.2.1，不在同一次对照中同时升级核心、换数据和换模型。
3. **试用官方价格线、垂直线、文字、底色等插件。** 精确锁定包版本；peerDependency 包含 5.2.1 只表示声明兼容，必须实际测试。
4. **做证据截图和少量完整绘图工具。** 截图需包含区间与页脚；绘图对象需具备撤销、重做、保存及失败提示。
5. **需要趋势线/矩形的完整对象生命周期时，再选择性移植 OpenCharts。** 不引入其模拟行情、旧图表封装或固定秒数推算未来交易日逻辑。
6. **最后再评估核心升级 5.3、跨设备同步、分享和嵌入。** 这些不是本轮已经实现的功能。

## 不改变的研究边界

图表重构不改变 LPPLS 参数、完整周期 1.5、选窗、聚类或评分。不能把形态识别、普通技术指标、合成数据或 UI 渲染成功计入预测命中率。

拟合尺度（例如 2–4 周、1–3 月）与 K 线周期（日/周）要分开；数据截止日、预测生成时间、浏览器首次看到时间、可信公开发布时间要分开。未复权行情与模型后复权输入不可无标识混用。

当前 [frontend/AGENTS.md](https://github.com/CareyPang/LPPL/blob/bf8bbf782dd9031dfe18b574b275edb88f9b5d01/frontend/AGENTS.md) 限制新增趋势/动量指标和模型概率显示。本报告记录第三方代码的存在，不据此把 RSI、MACD、形态分数等接入正式界面或 LPPL 输入；如另立通用技术分析产品任务，应明确更新相应合同。

## 本次变更边界

只提交此报告目录；不修改前端生产代码、数据、模型、工作流或任何上游库。只创建 Draft PR，不合并、不部署、不发布，不触发全量回测。不把第三方完整仓库复制进 LPPL。
