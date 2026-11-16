# 固定 main 图表引擎核验

核查日期：2026-11-16。只读经 GitHub 插件检查 CareyPang/LPPL 的固定 commit `4a5e1375e6dbd9a5b442d16c876b69ccaff7d0b5`，不以移动中的 main 代替该基线；不控制 Chrome，不改项目代码或远端。

## 结论

**VERIFIED — SOURCE_ONLY：指数页和个股页的主要图表均为项目自行编写的 Canvas 2D，不是 Lightweight Charts 4、5，也不是 Advanced Charts。因而不存在可为这两条入口填写的 LWC 版本号。** 本次只证明代码存在和调用关系，未执行页面、测试性能或证明生产运行正常。

此前官方笔记里的“LWC 5.x”指当前官方文档能力及可选技术路线，不是本项目当前依赖。技术建议须写成“比较改进原生 Canvas 与引入 LWC 的成本和表现”，不可写成“升级当前 LWC 4 至 5”。

## 源码证据

以下链接均固定到完整 commit SHA。行号来自插件取回的完整文件。

| 页面/能力 | 源码定位 | 静态核验结果 |
|---|---|---|
| 指数图表宿主 | [index.html L325–326](https://github.com/CareyPang/LPPL/blob/4a5e1375e6dbd9a5b442d16c876b69ccaff7d0b5/frontend/index.html#L325-L326) | 原生 `canvas#cv`，含键盘操作说明 |
| 指数引擎 | [index.html L494–504](https://github.com/CareyPang/LPPL/blob/4a5e1375e6dbd9a5b442d16c876b69ccaff7d0b5/frontend/index.html#L494-L504) | `getContext('2d')`；共享时间轴的价格、成交量、一致度分区；颜色读 CSS 变量 |
| 指数 K 线 | [index.html L656–667](https://github.com/CareyPang/LPPL/blob/4a5e1375e6dbd9a5b442d16c876b69ccaff7d0b5/frontend/index.html#L656-L667) | 自行绘制 high/low 影线、open/close 实体；绘制上限为截止日 T |
| 指数成交量 | [index.html L699–713](https://github.com/CareyPang/LPPL/blob/4a5e1375e6dbd9a5b442d16c876b69ccaff7d0b5/frontend/index.html#L699-L713) | 同一 Canvas 内按 volume 绘制柱状图 |
| 指数当前情景区间 | [index.html L633–641](https://github.com/CareyPang/LPPL/blob/4a5e1375e6dbd9a5b442d16c876b69ccaff7d0b5/frontend/index.html#L633-L641) | 将 topW/altW 下标转换成 x 坐标，整段价格区填色并写日期文案 |
| 指数历史情景区间 | [index.html L619–630](https://github.com/CareyPang/LPPL/blob/4a5e1375e6dbd9a5b442d16c876b69ccaff7d0b5/frontend/index.html#L619-L630)、[scen-style.js L12–25](https://github.com/CareyPang/LPPL/blob/4a5e1375e6dbd9a5b442d16c876b69ccaff7d0b5/frontend/app/scen-style.js#L12-L25) | Canvas 连接线及区间线，不是第三方图表 primitive |
| 指数交互 | [index.html L759–780](https://github.com/CareyPang/LPPL/blob/4a5e1375e6dbd9a5b442d16c876b69ccaff7d0b5/frontend/index.html#L759-L780) | 自己管理可视下标范围、hover、缩放和 pointer 拖拽 |
| 个股行情画布 | [stock.html L348](https://github.com/CareyPang/LPPL/blob/4a5e1375e6dbd9a5b442d16c876b69ccaff7d0b5/frontend/stock.html#L348)、[stock-view.js L91–139](https://github.com/CareyPang/LPPL/blob/4a5e1375e6dbd9a5b442d16c876b69ccaff7d0b5/frontend/app/stock-view.js#L91-L139) | `market-plot` 原生 Canvas 2D；日 K 线、成交量、选中日竖线及价格读数 |
| 个股历史画布 | [stock.html L389](https://github.com/CareyPang/LPPL/blob/4a5e1375e6dbd9a5b442d16c876b69ccaff7d0b5/frontend/stock.html#L389)、[stock.html L569–633](https://github.com/CareyPang/LPPL/blob/4a5e1375e6dbd9a5b442d16c876b69ccaff7d0b5/frontend/stock.html#L569-L633) | 独立 `plot` Canvas；后复权收盘折线，以及 q20_date–q80_date 的历史情景横条 |
| 入口依赖 | [index.html L406–418](https://github.com/CareyPang/LPPL/blob/4a5e1375e6dbd9a5b442d16c876b69ccaff7d0b5/frontend/index.html#L406-L418)、[stock.html L277–285](https://github.com/CareyPang/LPPL/blob/4a5e1375e6dbd9a5b442d16c876b69ccaff7d0b5/frontend/stock.html#L277-L285) | 相关图表由本地 ui/lppl-data/scen-style/stock-view 等脚本组成；未见这两条图表入口的 LWC/Advanced Charts 引入 |

个股 `stock-page.js` 是目录、头部与选股装配，不能因名字把它当图表引擎。[stock-page.js L1–48](https://github.com/CareyPang/LPPL/blob/4a5e1375e6dbd9a5b442d16c876b69ccaff7d0b5/frontend/app/stock-page.js#L1-L48)

## 两项应先修的结构风险

1. **未来日期存在交易日历缺口（VERIFIED — SOURCE_ONLY）。** 指数 `CP.dateAt` 对未来只跳过星期六、星期日；`idxOf` 也只计算工作日，因此节假日可能把模型日期映射到错误位置。应以交易所交易日历转换 date ↔ logical index，保持原始区间日期不变；不可把该问题误归因于 LWC。[dateAt L408–412](https://github.com/CareyPang/LPPL/blob/4a5e1375e6dbd9a5b442d16c876b69ccaff7d0b5/frontend/index.html#L408-L412)、[idxOf L445–451](https://github.com/CareyPang/LPPL/blob/4a5e1375e6dbd9a5b442d16c876b69ccaff7d0b5/frontend/index.html#L445-L451)

2. **个股主 K 线与模型时间区间没有在已检视代码中形成同一图层（VERIFIED — SOURCE_ONLY；整站其他路径不据此断言不存在）。** `stock-view.js` 的 x 轴仅按已有 `prices.length` 铺满，其 draw 函数绘制行情和选中日，没有接受或绘制未来 q20/q80 区间；模型历史条在 `stock.html` 另一画布。应优先建立统一图表视图数据契约，再决定引擎。个股历史画布以历史首末日期为 x 域，未来情景可能在画布外，不能据当前代码宣称支持完整未来空间。[stock-view.js L100–137](https://github.com/CareyPang/LPPL/blob/4a5e1375e6dbd9a5b442d16c876b69ccaff7d0b5/frontend/app/stock-view.js#L100-L137)、[stock.html L590–614](https://github.com/CareyPang/LPPL/blob/4a5e1375e6dbd9a5b442d16c876b69ccaff7d0b5/frontend/stock.html#L590-L614)

## 迁移评估的边界与验收

- PROPOSED：先抽象统一的 bars、exchange calendar、asof、candidate windows、revisions 和事件数据契约。可视范围、图表分辨率、拟合窗口与研究采样频率分别保存；切换 6M 不得暗改模型为 2h 数据。
- PROPOSED：同一组数据分别在现有 Canvas 和 LWC 小型试验页绘制，比较未来日期定位、主图与成交量同步、十字光标、移动触控、缩放、键盘与可访问读数。不要仅因 TradingView 成品体验好就承诺 LWC 会自动带来完整功能。
- PROPOSED：跨春节/国庆的未来 tc 区间必须精确按交易日历落点；没有真实 OHLC 的未来日期只能承载区间，不造未来价格线。
- PROPOSED：未来区间出现在 K 线上时，仍要区分原始拟合候选、聚类区间、正式提醒与事后标签；领先少于 5 日的合格区间不能被纯评价阈值隐藏。
- NOT_INSPECTED：此轮未运行 LPPL 页面、未做 390px/桌面性能验收、未证明 GitHub Pages 正在服务这一 commit、未比较 Canvas 与 LWC 实测性能。

