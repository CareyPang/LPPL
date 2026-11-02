# 给 Open Design 的前端 prompt：个股页 + 市场页（草案，等 PR #23–#25 合并后发出）

```
任务：在 frontend/ 新增两页，风格与 index.html / backtest.html 一致（深色终端）。规则同 frontend/AGENTS.md：不改 app/lppl-data.js，不在前端算模型，所有数据只读静态 JSON；必须在浏览器验证后再 push。

一、个股页 frontend/stock.html（替换现在的"映射到所属指数"版本）
数据：/lab/mock/data/stock/index.json（已算过的代码列表）、/lab/mock/data/stock/<code>.json、<code>_history.json、<code>_error.json（字段见 docs/frontend_contract.md 个股节；参考实现 web/stock.html）。
1. 顶部：6 位代码输入 + 已算代码的下拉/搜索（来自 index.json，显示名称、截止日、计算时间）。
2. 证据条：固定显示 research_candidate 徽章 +"个股未经样本外检验；开发段横截面个股置信度无预测信息"。不得省略或弱化。
3. 主图：后复权收盘 3 年，叠加历史截止日 6–12 月/12–24 月置信度柱（右轴）、当时情景区间 q20–q80 色带（透明度=share）、事后确认顶蓝三角；缩放/拖动沿用 backtest.html。
4. 六尺度表：窗口数、standard/early/box 置信度、状态、尺度证据。缺值显示"—"，不能显示 0%。
5. 当前泡沫段卡：起点、持续、t_c（标注"理论临界时间，不是顶部日期"）、风险窗口或"无合格拟合"。
6. 状态：stock_meta.status ≠ eligible（insufficient_history / degenerate / ST）时显示红色徽章和 eligibility_note；只有 _error.json 时显示失败原因和 run_url；完全没有时显示"未计算"+ 链接 https://github.com/CareyPang/LPPL/actions/workflows/stock_query.yml。
7. 同时保留"所属指数风险"小卡（沿用现有映射逻辑），链到终端。
禁止：目标价、单一顶部日期、"买入/卖出"字样、个股排名。

二、市场页 frontend/market.html
数据：/lab/mock/data/market/market_latest.json（契约见 docs/frontend_contract.md 市场节）。每节右上角显示 evidence: descriptive 和 sources.<name>.ok / fetched_at；源失败就显示"该源本次未取到：<error>"，不能留空白，也不能沿用旧数据。
1. 板块资金流热力图（行业/概念/地域切换 × 今日/5日/10日）：方块面积=|主力净额|，颜色=涨跌幅；悬停显示超大/大/中/小单。标注"东财按单笔金额估算，非交易所数据"。
2. 涨停情绪：涨停/炸板/跌停家数、炸板率、最高连板、连板分布柱，前 20 列表。
3. 北向：只显示成交额、成交笔数、ETF 成交额。全页不得出现"净流入/净买入"。注明"港交所 2024-08 起不再公布买卖净额"。
4. 估值：沪深300/中证500/上证50/中证1000 的 PE（静态/滚动）、股息率；10 年分位为 null 时显示"—（源文件只有近期数据）"。
5. 两融：融资余额（沪/深/合计）、20 日变化、数据日与可用日（T+1）、stale 徽章。
全页底部固定一行："市场背景只作描述，不进入 LPPLS 报警或任何模型。"
验收：1440 宽和 390 宽各截图；源失败的情况可以把 sources.board_flow_industry.ok 改成 false 在本地模拟；控制台无 JS 错误。
```
