# 六站深度访问：浏览器证据日志（第一部分）

记录日期：2026-11-17（Asia/Singapore）。

范围：Koyfin、Fiscal.ai、FINVIZ 本轮已经发生的浏览器操作。记录依据为主代理在 Chrome 中的操作、工具截图和本次会话恢复摘要；本文件由子代理转写，子代理没有另行浏览、操作 Chrome 或访问 GitHub。

这是本轮有边界的覆盖记录，不是“六站全部页签验收通过”。窗口截图为桌面 Chrome，窗口尺寸约 1920 × 1032；内容视口、浏览器缩放、设备像素比没有独立测量。390px、真实手机、键盘完整路径、辅助技术和网络性能均为 **NOT_INSPECTED**。没有以工具调用耗时替代网页加载性能。

## 证据标签及边界

| 标签 | 本文含义 |
|---|---|
| **VERIFIED · OPENED** | 入口已点击，目标页面及至少部分相应内容在截图中可见；不代表该页所有功能可用。 |
| **VERIFIED · OPERATED** | 已操作一个具体控件，并看到相应状态、内容或路径变化；仅限该操作。 |
| **VERIFIED · BLOCKED** | 页面明确提示需要登录、升级或订阅；只确认限制存在，没有验证受限功能。 |
| **NOT_ESTABLISHED · LOAD_UNRESOLVED** | 已导航或尝试操作，但观察结束时仍在加载、空白或未显示目标结果；原因未建立。 |
| **NOT_INSPECTED** | 未操作、未完成验证，或仅在导航中看见名称。 |
| **PROPOSED** | 根据观察提出的 LPPL 设计建议，尚未实现或验收。 |

特别注意：Chrome 翻译弹窗、鼠标蓝色光圈和右下角钉钉提醒是浏览器、控制工具或其他应用的界面，不属于被测网站。钉钉提醒遮挡了部分页面右下区域，相关隐藏内容没有据此推断。本文不保存账户信息，不复制新闻正文或市场报价，也不将看到的数据视为已独立核对其准确性。

## Koyfin

### 实际路径

先进行：`官网首页 → Product / Features → Log In → app.koyfin.com/login → 稍后复查`。

同日后续补充：`重新访问官网 → For Financial Advisors → For Investors → Pricing → Annual 切 Monthly`。两段访问分别保留，后续官网成功加载不覆盖前次 Features 与终端加载记录。

| ID | 页面／入口与路径 | 实际动作与看到的结果 | 证据状态 |
|---|---|---|---|
| K01 | [官网](https://www.koyfin.com/) | 打开首页。白底、大标题、单一主要注册按钮；顶部可见 Product、For Financial Advisors、For Investors、Pricing，右侧为登录与注册。首屏下部有产品界面展示。没有验证展示内容是实时终端。 | **VERIFIED · OPENED** |
| K02 | 首页 Cookie 面板 | 点击 Reject，面板消失。 | **VERIFIED · OPERATED** |
| K03 | [Features](https://www.koyfin.com/features/) | 点击 Product 后进入 Features。多次观察中出现样式、图片加载不完整和部分文字布局异常。没有完成该页深层功能的浏览。 | 页面现象 **VERIFIED**；完整体验 **NOT_ESTABLISHED · LOAD_UNRESOLVED** |
| K04 | [终端登录入口](https://app.koyfin.com/login) | 点击官网 Log In。目标 URL 可见，但观察中为白底品牌旋转加载图。没有看到可操作的登录表单。 | **NOT_ESTABLISHED · LOAD_UNRESOLVED** |
| K05 | 同一终端登录页 | 完成一段 Fiscal.ai 体验后返回 Koyfin 标签，仍看到加载图。没有据此确定故障来自网络、浏览器、站点或其他环节。 | **NOT_ESTABLISHED · LOAD_UNRESOLVED** |
| K06 | [官网后续复访](https://www.koyfin.com/) | 2026-11-17 同日后续重新访问，本次所见官网页面成功显示，继续访问以下受众和价格页面。该次官网加载成功不代表终端已恢复。 | **VERIFIED · OPENED** |
| K07 | [For Financial Advisors](https://www.koyfin.com/for-financial-advisors/) | 点击后成功进入顾问页面，左侧为大标题和 Contact Sales，右侧为产品示意图。未联系销售，产品示意不视为终端实测。 | 官网 **VERIFIED · OPENED**；产品能力 **NOT_INSPECTED** |
| K08 | [For Investors](https://www.koyfin.com/for-investors/) | 点击后成功进入投资者页面，显示面向投资者的说明与注册 CTA；右侧主体图在本次观察中为空白。没有确定该图为空的原因。 | 页面文字 **VERIFIED · OPENED**；右侧图完成状态 **NOT_ESTABLISHED** |
| K09 | [Pricing](https://www.koyfin.com/pricing/) | 点击后成功打开五列方案：Free、Plus、Premium、Advisor Core、Advisor Pro。没有购买、试用或核对合同条件。 | **VERIFIED · OPENED** |
| K10 | Pricing / Annual → Monthly | 从年度计费切换到月度，看到价签随之变化；不抄录价格，也不据此判定最终税费、优惠或合同价。 | 计费显示切换 **VERIFIED · OPERATED** |

### 尚未实测

For Financial Advisors、For Investors、Pricing 在最初阶段尚未检查，现已由同日后续 K07–K10 补充覆盖。官网完整资源／帮助目录与这些页面的全部深层链接仍为 **NOT_INSPECTED**。

Koyfin 终端内的 Watchlists、Screens、Portfolio、Model Portfolios、News、Graphs、Dashboards、Analytics、Security Analysis、命令搜索及右侧工具栏：**NOT_INSPECTED**。帮助文档描述不能替代终端实测；本轮不能宣称这些页签已逐个体验。

### 对 LPPL 的设计启示（PROPOSED）

- 官网与工作终端应分工清楚：官网说明定位，进入终端后尽快给出可用资产和结果。
- 任何加载状态都应有超时说明、重试和返回路径；已有行情不能被一个无限旋转图整体遮住。
- 一次或一段会话中的加载异常不足以证明产品长期不稳定，也不足以判定大陆网络可用性。

## Fiscal.ai

### 从官网进入公开终端

`官网 → Products → Terminal → Tour The Platform → Alphabet 公司页`

| ID | 页面／入口与路径 | 实际动作与看到的结果 | 证据状态 |
|---|---|---|---|
| F01 | [官网](https://fiscal.ai/) | 全屏建筑主视觉、大标题、简短说明、Request Demo 与 View plans；顶部 Products、Pricing、Resources，右侧 Contact Sales 与 Login。 | **VERIFIED · OPENED** |
| F02 | Products 菜单 | 点击后出现三个带配图的产品入口：Terminal、Data Feed API、MCP Connectors。 | **VERIFIED · OPERATED** |
| F03 | [Terminal 产品页](https://fiscal.ai/products/terminal/) | 点击 Terminal，进入产品介绍首屏；可见 Get Started Free 与 Tour The Platform。 | **VERIFIED · OPENED** |
| F04 | Tour The Platform | 点击后直接打开 [Alphabet 公司页](https://fiscal.ai/company/NASDAQ_GOOG/)，出现实际终端导航及公司资料。没有注册或开通试用。 | **VERIFIED · OPERATED** |

Data Feed API、MCP Connectors、Pricing、Resources、Contact Sales 等官网入口的内部功能为 **NOT_INSPECTED**。这里仅确认产品菜单可展开，不是所有产品均已试用。

### Alphabet 公司上下文：11 个页签

公司身份条与横向页签在切换中持续保留。后续截图可见报价旁有延迟标识；本文未独立核对行情数值。

| ID | 页签与路径 | 实际动作与看到的结果 | 证据状态 |
|---|---|---|---|
| F05 | [Overview](https://fiscal.ai/company/NASDAQ_GOOG/) | 默认打开。公司说明及名称、管理层、网站、行业、成立年份等基本字段可见；Company Statistics 提示登录，右侧图表区域初次观察仍为加载占位。 | 基本资料 **VERIFIED · OPENED**；统计 **VERIFIED · BLOCKED**；该图表完成状态 **NOT_ESTABLISHED** |
| F06 | [Financials 年度](https://fiscal.ai/company/NASDAQ_GOOG/financials/income-statement/annual/) | 点击 Financials。可见报表、指标搜索、日期范围、币种、数量单位、Standardized/As Reported 与年度／季度等控制；具体数据格显示锁。 | 结构 **VERIFIED · OPENED**；数据明细 **VERIFIED · BLOCKED** |
| F07 | [Financials 季度](https://fiscal.ai/company/NASDAQ_GOOG/financials/income-statement/quarterly/) | 点击 Quarterly。URL、选中状态、日期范围和表头由年度切成季度，数据格仍受限。 | 周期切换 **VERIFIED · OPERATED**；数值读取 **BLOCKED** |
| F08 | [Investor Relations](https://fiscal.ai/company/NASDAQ_GOOG/investor-relations/) | 左侧显示按日期组织的财报及投资者活动目录；正文区明确提示升级以访问文字稿、音频和文件。未播放音频、未读受限正文。 | 目录 **VERIFIED · OPENED**；内容 **VERIFIED · BLOCKED** |
| F09 | [Research](https://fiscal.ai/company/NASDAQ_GOOG/research/) | 可见日期目录、Morningstar Report、AI Generated Report，以及右侧 AI Summary / Custom Prompt。主研报与 AI 摘要均提示升级。未生成 AI 报告。 | 结构 **VERIFIED · OPENED**；研报和 AI **VERIFIED · BLOCKED** |
| F10 | [Estimates](https://fiscal.ai/company/NASDAQ_GOOG/estimates/revenue/) | 可见 Revenue、EPS、Price Targets 等指标入口，年度／季度及单位控制；表头区分实际与预期，数据格显示锁。图表在该次截图中为占位。 | 结构 **VERIFIED · OPENED**；数值 **VERIFIED · BLOCKED**；图表结果 **NOT_ESTABLISHED** |
| F11 | [News](https://fiscal.ai/company/NASDAQ_GOOG/news/) | 顶部有关键词、日期、事件类型和重要性控制；少量新闻标题、标签和日期可见，更多内容锁定。点击 Event Type 后未观察到展开菜单或筛选结果变化，不能算筛选已验证。 | 列表 **VERIFIED · OPENED**；部分内容 **BLOCKED**；筛选操作结果 **NOT_ESTABLISHED** |
| F12 | [Ownership / Insiders](https://fiscal.ai/company/NASDAQ_GOOG/insiders/) | 可见 Insiders、Trades、Holders、Analysis、Politician Trades 子页签及持股表；部分示例行数值可见，其余受限。没有逐个操作子页签。 | 表结构 **VERIFIED · OPENED**；完整数据 **BLOCKED**；子页签 **NOT_INSPECTED** |
| F13 | [Industry](https://fiscal.ai/company/NASDAQ_GOOG/industry/) | 点击后明确提示登录以使用 Industry Comparisons。 | **VERIFIED · BLOCKED** |
| F14 | [Dividends](https://fiscal.ai/company/NASDAQ_GOOG/dividends/) | 点击后明确提示登录以使用 Dividends & Splits。 | **VERIFIED · BLOCKED** |
| F15 | [Modeling](https://fiscal.ai/company/NASDAQ_GOOG/modeling/reverse-dcf/) | 点击后进入 reverse-DCF 路径，页面提示登录以使用 Financial Modeling；没有验证估值计算。 | **VERIFIED · BLOCKED** |
| F16 | [Filings](https://fiscal.ai/company/NASDAQ_GOOG/filings/) | 文件列表、日期、类型及分类标签可见，部分条目有锁。 | **VERIFIED · OPENED** |
| F17 | [季度文件详情](https://fiscal.ai/company/NASDAQ_GOOG/filings/0001652044-26-000084/?source=internal) | 点击未显示锁的季度报告条目，进入详情页。两次观察正文均为加载旋转图；右侧 AI Summary 明确需要登录。没有确认正文成功载入。 | 详情导航 **VERIFIED · OPERATED**；正文 **NOT_ESTABLISHED · LOAD_UNRESOLVED**；AI **VERIFIED · BLOCKED** |

### 终端左侧 7 个主要业务入口

| ID | 入口与路径 | 实际动作与看到的结果 | 证据状态 |
|---|---|---|---|
| F18 | [Dashboard](https://fiscal.ai/dashboard/) | 初次为加载，随后出现默认示例组合及资产表。顶部有 Summary、Performance、News；指标、资产和持仓字段分区清楚。没有编辑或保存任何组合。 | **VERIFIED · OPENED** |
| F19 | Dashboard / Performance | 点击 Performance，弹出注册提示，要求注册以创建自己的 Dashboard 并保存进度；关闭提示返回原表。未得到组合表现页。 | **VERIFIED · BLOCKED**；返回 **VERIFIED · OPERATED** |
| F20 | Analysis | 通过公开导览进入公司分析工作区，并完成上表的 11 个公司主页签访问。 | 见 F05–F17；不代表所有分析工具通过 |
| F21 | [Markets](https://fiscal.ai/markets/) | 点击侧栏后进入市场总览；加载后可见热图、涨跌榜、新闻和财报模块。随后逐个打开 7 个市场主页签，见下一表。 | **VERIFIED · OPENED** |
| F22 | [Charting](https://fiscal.ai/fundamental-charting/) | 可见指标搜索、添加公司、币种、单位、频率与面板控制；空状态说明要先选择公司和指标。未添加公司或生成对比图。 | **VERIFIED · OPENED**；制图结果 **NOT_INSPECTED** |
| F23 | [Screener](https://fiscal.ai/screener/) | 点击后明确提示登录以使用 Stock Screener。 | **VERIFIED · BLOCKED** |
| F24 | [Query](https://fiscal.ai/document-search/) | 可见关键词查询、添加公司和文档类型控制，空状态提示先选择公司和搜索词。未执行查询、未验证命中或引用定位。 | **VERIFIED · OPENED**；查询结果 **NOT_INSPECTED** |
| F25 | [Earnings](https://fiscal.ai/earning-calendar/) | 加载后出现财报周历，按星期排列公司卡片，可见地区、国家、行业、状态及盘前／盘后等筛选。 | **VERIFIED · OPENED** |
| F26 | Earnings / Agenda | 从 Week 切到 Agenda。先出现加载，随后出现按日期分组的议程列表、公司及盘前／盘后／时段未知标记，日期范围随视图调整。 | **VERIFIED · OPERATED** |

Dashboard 的 News、Charting 的完整制图、Query 的全文检索、财报日历其他视图和筛选，以及 Resources、Settings、Updates 为 **NOT_INSPECTED**。没有把“看见输入框或菜单”当成实际功能验证。

### Markets 的 7 个主页签

| ID | 页签与路径 | 实际结果 | 证据状态 |
|---|---|---|---|
| F27 | [Overview](https://fiscal.ai/markets/) | 热图、涨跌榜、Top Stories、当周财报等模块共同构成市场扫描页，卡片附有更新时间或口径说明。 | **VERIFIED · OPENED** |
| F28 | [Heatmap](https://fiscal.ai/markets/heatmap/) | 点击后完成加载，出现全宽行业分组热图；可见面积代表市值、颜色代表价格变化的说明及色阶。未验证面积计算与成分完整性。 | **VERIFIED · OPERATED**（视图切换）；数据正确性 **NOT_ESTABLISHED** |
| F29 | [Top Stories](https://fiscal.ai/markets/news/) | 出现全市场事件列表、资产代码、事件类别、重要性标签和日期，少量项目公开、更多项目受限。未验证其重要性算法。 | **VERIFIED · OPENED**；完整内容 **BLOCKED** |
| F30 | [Gainers & Losers](https://fiscal.ai/markets/movers/) | 左右并列涨榜和跌榜，展示资产、价格、涨跌、规模等，并有更新时间和市场开放范围提示。未操作排序或筛选。 | **VERIFIED · OPENED** |
| F31 | [Fund Letters](https://fiscal.ai/fund-letters/) | 出现 Letters / Stocks / Investors 子页签、年份与季度等筛选、文档列表；列表分开展示报告期与发布日期。未阅读全文、未操作子页签或筛选。 | **VERIFIED · OPENED** |
| F32 | [Insider Trades](https://fiscal.ai/markets/insider-trades/) | 表格把交易日期与申报日期分列，另有交易人、公司、买卖类型、数量及金额；部分数据锁定。没有验证全市场覆盖或交易准确性。 | **VERIFIED · OPENED**；完整数据 **BLOCKED** |
| F33 | [Politician Trades](https://fiscal.ai/markets/politician-trades/) | 以人物卡片组织披露交易，展示最近交易、迟报情况和相关股票；页面有来源说明。未打开人物详情、未验证迟报计算。 | **VERIFIED · OPENED** |

### 对 LPPL 的设计启示（PROPOSED）

1. **先给可用示例。** 首页的“体验工作站”可以直达一只示例资产；应明确示例资产、数据截止日和结果性质，避免把产品视频冒充可操作页面。
2. **保留资产上下文。** 从图表切到事件、财务或证据时，资产身份、报价时间与分析截止日保持可见。全球导航与资产内页签分层，不能重复堆叠。
3. **区分指标口径。** 年度／季度、币种、数量单位、标准化／原始报告是独立控制。LPPL 的交易日、自然日、窗口长度与提醒提前量也需要明确区分。
4. **双时间与版本可追溯。** 报告期、发生日期、披露日期、系统可见日期不能合并成一个“日期”。事件回放必须保留当时已知状态。
5. **权限与可用性要早说明。** 展示真实结构有助理解产品，但大量锁定页会造成挫败。LPPL 未接通的能力不应装成可用页签；当前资产不适用、数据失败、权限不足需要不同提示。
6. **周历和议程是同一批事件的两种视图。** 切换时应保留筛选，并清楚解释日期范围变化；不能用视图变化悄悄改变事件口径。

## FINVIZ

### 主路径与一只股票的操作闭环

`Home → Stock Screener → Technology → Performance → AAPL → Weekly → Screener 返回`

| ID | 页面／动作 | 实际结果 | 证据状态 |
|---|---|---|---|
| V01 | [Home](https://finviz.com/) | 打开首页。可见搜索、全局页签和大幅促销区域，行情模块位于其下。没有浏览完整首页全部模块。 | **VERIFIED · OPENED** |
| V02 | [Stock Screener](https://finviz.com/screener/stocks) | 打开股票筛选器。可见多组筛选条件、结果视图、排序和股票表；条件区与结果列视图区是不同层级。 | **VERIFIED · OPENED** |
| V03 | Sector 下拉 | 展开后点击 Technology，第一次被促销浮层打断，筛选仍为 Any。关闭浮层、重新选择后，URL 出现 `f=sec_technology`，Sector 显示 Technology，结果列表缩小。 | 最终筛选 **VERIFIED · OPERATED**；第一次尝试不计成功 |
| V04 | [Performance 结果视图](https://finviz.com/screener/stocks?f=sec_technology&v=141) | 点击 Performance，科技筛选保持，结果列改为不同期限表现、波动率和成交量等。 | **VERIFIED · OPERATED** |
| V05 | [AAPL 日线](https://finviz.com/stock?t=AAPL&b=1&ty=c&p=d) | 点击筛选表中的 AAPL，进入个股页。资产头下可见 Overview、Compare、Short Interest、Financials、Options、Latest Filings、Dilution。向下滚动看到 K 线、成交量、技术线和事件标记。未操作这些资产子页签。 | 个股导航与主图 **VERIFIED · OPENED**；其他子页签 **NOT_INSPECTED** |
| V06 | [AAPL 周线](https://finviz.com/stock?t=AAPL&b=1&ty=c&p=w) | 点击 Weekly 后发生页面导航并再次出现促销浮层；关闭后 URL 为 `p=w`，Weekly 为选中状态，下方周线区域可见。没有进一步测量图表缩放、拖拽或指标计算。 | 周期切换 **VERIFIED · OPERATED** |
| V07 | 个股页的 Screener 返回链接 | 点击资产头上方返回筛选器链接，回到 `f=sec_technology&v=141`；Technology 条件和 Performance 结果视图均保留。没有验证跨会话持久化或任意滚动位置恢复。 | **VERIFIED · OPERATED** |

### 全局页签覆盖

| ID | 页签与路径 | 实际动作与看到的结果 | 证据状态 |
|---|---|---|---|
| V08 | [ETF Screener](https://finviz.com/screener/etf) | 打开 ETF 筛选页，可见专用条件、分类、标签和 ETF 列表；未应用 ETF 条件。 | **VERIFIED · OPENED** |
| V09 | [Maps](https://finviz.com/map) | 打开行业分组热图；左侧可选地图表现、面积口径、资产范围等，图例说明面积为市值。未操作全部模式与范围。 | **VERIFIED · OPENED** |
| V10 | Maps / AAPL 悬停 | 指针移至 Apple 区块，出现高亮边框及含小走势图、报价和涨跌的预览；其中“Why is it moving”明确提示该股票无相关数据。未点击预览进入新资产页。 | **VERIFIED · OPERATED** |
| V11 | Charts | 点击全局 Charts，出现高级多布局图表介绍及 Elite 试用入口。关闭后仍为热图。未开通试用、未验证高级图表。 | **VERIFIED · BLOCKED** |
| V12 | [News](https://finviz.com/news) | 出现 Market News / Market Pulse / Stocks News / ETF News / Crypto News 二级入口；默认页面左右分 News 与 Blogs，并显示时间和来源标识。未逐个切二级入口、未打开新闻正文。 | **VERIFIED · OPENED** |
| V13 | [Groups](https://finviz.com/groups) | 默认行业分组与 Performance Chart，出现不同期限表现横条图、Group 和 Order By 控制；未验证其他分组或计算。 | **VERIFIED · OPENED** |
| V14 | [Insider](https://finviz.com/insidertrading) | 默认内部人交易表，显示交易类型、日期、数量、金额及 SEC 文件时间；Managers 和 Funds 二级入口可见但未点。 | **VERIFIED · OPENED** |
| V15 | [Futures](https://finviz.com/futures) | 期货卡片按资产类别排列；可见 Prices / Performance / Charts / Maps、品种分类及周期控制。未操作具体合约或验证价格口径。 | **VERIFIED · OPENED** |
| V16 | [Forex](https://finviz.com/forex) | 多汇率小图卡片，显示价格、变化及区间走势；旁侧还出现关联资产卡。未切周期或打开货币对详情。 | **VERIFIED · OPENED** |
| V17 | [Crypto](https://finviz.com/crypto) | 多资产小图矩阵，卡片包含价格、变化与走势；未操作单资产详情。 | **VERIFIED · OPENED** |
| V18 | [Watchlist](https://finviz.com/watchlist) | 初次观察主体为空；后续点击 Start with Magnificent 7，出现 Advanced Watchlists 账户／Elite 提示。没有创建或保存自选。初次空白与后续权限提示分别记录，不能据此断言空白的原因。 | 入口及提示 **VERIFIED · OPERATED**；创建自选 **VERIFIED · BLOCKED** |
| V19 | [Portfolio 注册入口](https://finviz.com/register?poster=portfolio) | 点击 Portfolio 后进入注册墙，随后返回。没有创建账户或组合，没有验证组合管理。 | **VERIFIED · BLOCKED**；返回 **VERIFIED · OPERATED** |
| V20 | [Calendar / Earnings Preview](https://finviz.com/calendar/earnings/season-preview) | 打开财报日历预览，出现按周排列的公司 Logo 列，界面可见按规模／字母排序与 Tiles / List 控制。本记录不将看见控件视为排序和视图切换已验证。 | **VERIFIED · OPENED** |
| V21 | [Calendar / Economic](https://finviz.com/calendar/economic?dateFrom=2026-11-16) | 点击 Economic，进入经济日历，显示 Actual、Expected、Prior、Impact、For 等字段及周快捷选择。没有由这些字段推断来源或统计口径已核验。 | 导航 **VERIFIED · OPERATED**；日历结构 **VERIFIED · OPENED** |
| V22 | Economic / NY Empire State Manufacturing Index | 展开该行成功，出现历史柱状图、1Y / 3Y / 5Y / 10Y / Max 控制、NY Fed 来源、points 单位及 Open Detail 入口。未打开 Open Detail，未验证全部历史范围控件。 | 行展开 **VERIFIED · OPERATED**；深层详情和范围切换 **NOT_INSPECTED** |
| V23 | 同一经济日历展开行的时点一致性 | 行内 For 标为 Nov，说明文字谈 June 2026，图表末端可见 Oct。截图观察到三个区域的时期不一致；未判断各区域是否有独立的更新时间、预期定义或其他解释，也没有外部核对金融数据真伪。 | 时点差异 **VERIFIED（仅 UI 观察）**；原因、正确值及数据真伪 **NOT_ESTABLISHED** |

Pricing、Help、筛选器全部条件组与结果视图、个股全部二级页签、热图全部表示方式、实时刷新、保存自选、组合管理、新闻详情、提醒及导出均未完整验收，不能由上述访问推导为可用。**Watchlist 的创建路径和 Portfolio 已观察到权限／注册限制；这不等于自选或组合功能已经试用成功。** Calendar 只覆盖上述财报预览、经济日历和一条指标展开，不能称为全部事件类型和历史日期已验收。

### 对 LPPL 的设计启示（PROPOSED）

- **资产集合与视图分离。** 筛选条件决定“看哪些股票”，Performance 等视图决定“看这些股票的哪些列”。LPPL 自选可先提供行情、候选区间、事件三种固定列视图，切换不改资产集合。
- **返回路径保留研究上下文。** 本轮实测的 Technology → Performance → AAPL → 返回是可落地范例。LPPL 应明确保存筛选、排序、视图与来源页面，并另外验收滚动位置和历史模式。
- **热图先预览再深入。** 悬停的小趋势图帮助判断是否值得打开个股；手机应以单击预览卡承载同等信息，不能依赖 hover。该移动方案尚未实测。
- **缺失原因不用编造解释。** 异动说明不可得时，明确显示缺失，不用 AI 生成貌似确定的因果归因。
- **避免复制信息负担。** FINVIZ 的密度适合熟练用户，但 LPPL 面向普通投资者，不应照搬全部全局页签、筛选组、列视图和促销。主屏先保留关键任务，再逐层展开。
- **减少页面跳转造成的上下文变化。** 本次切周线触发页面导航并出现促销，增加了中断。LPPL 的周期切换应尽量局部更新，保留资产、选中区间和阅读位置。
- **涨跌颜色与功能强调色分开。** 图表红绿承载价格方向；选中页签、候选窗口、失败和 stale 状态使用独立语义。不能把市场涨跌颜色兼作“模型已核验”的含义。
- **展开详情必须显示各自时期并校验同步。** V23 暴露了一个可见的时点风险：列表时期、说明文案和图表末期不一致时，用户难以知道自己正在看哪次发布。LPPL 应把观测期、发布时间、历史序列截止日放入详情数据契约；异步切换事件或日期时清除旧详情或标出旧版本，不能把不同请求的内容拼在同一张卡里。本轮未建立 FINVIZ 该差异的原因。

## 截止本日志的覆盖结论

| 网站 | 已经建立的覆盖 | 明确未建立的部分 |
|---|---|---|
| Koyfin | 官网首屏、Cookie 拒绝、Features 入口、终端登录页加载尝试与复查；同日后续顾问／投资者页面、Pricing 及年度→月度切换 | 实际终端全部页签；加载异常原因；完整资源／帮助目录及深层分支 |
| Fiscal.ai | 公开导览；公司 11 个主页签；左侧 7 个主要业务入口；市场 7 个主页签；年度→季度、周历→议程等具体切换 | 受限财务/研报/AI/建模；全文与查询；全部深层子页签；完整交互、移动和性能验收 |
| FINVIZ | 股票筛选→表现视图→AAPL→周线→返回；ETF、热图悬停、News、Groups、Insider、Futures、Forex、Crypto；Watchlist／Portfolio 权限路径；Calendar 财报预览、经济日历及一条指标展开 | 自选保存与组合管理；高级图表；全部二级页签、日历事件类型／历史范围及完整图表操作；日历时点差异的原因和正确口径 |

Trading Economics、Quartr、金十的本轮观察另见 [第二部分](BROWSER_LOG_PART2.md)。浏览器测试没有执行注册、购买、交易、部署或发布；报告的 GitHub 文档更新另行记录，不计作网站体验操作。所有 LPPL 优化点均为 **PROPOSED / NOT_RUN**。
