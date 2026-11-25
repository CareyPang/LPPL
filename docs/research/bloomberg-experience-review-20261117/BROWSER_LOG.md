# Bloomberg computer-use 操作与证据日志

日期：2026-11-17，Asia/Singapore。环境：用户 Windows 桌面 Chrome，1920×1032 窗口截图。本次新建 Bloomberg 标签页，保留原有标签。可见 Sign In，未登录 Bloomberg。仅通过桌面 UI 操作，没有用隐藏 DOM、CDP 或接口绕过页面限制。

此文件是操作记录，不是站点性能基准。没有导出浏览器私人标签、桌面通知或账户截图到报告包。

| ID | 操作 | 观察 | 证据状态 |
|---|---|---|---|
| B01 | 打开 bloomberg.com | 出现条款更新提示及首页 | VERIFIED/UI |
| B02 | 接受普通条款提示 | 首页可浏览；未发生订阅或购买 | VERIFIED/UI |
| B03 | 查看并滚动首页 | 黑色站头、主题导航、行情条；主要新闻与指数比较图相邻；视频、播客、Latest 列表可见 | VERIFIED/UI |
| B04 | 尝试 Markets 箭头悬停/点击 | 未观察到预期展开；点击 Markets 文本可进入栏目 | 操作 VERIFIED/UI；未展开原因 NOT_ESTABLISHED |
| B05 | 打开 /markets | Markets 标题与 Deals、Fixed Income、ETFs、FX Center、Newsletter、Markets Wrap、Private Markets 二级导航可见 | VERIFIED/UI |
| B06 | 打开行情条分类，选 Rates & Bonds | 原位置换成 US 5Yr、US 10Yr、JPN 10Yr、UK 10Yr、Fra 10Yr、Bund 10Yr 项目 | VERIFIED/UI；报价真实性/实时性未独立核验 |
| B07 | 点击全局搜索 | 空态提供主题建议；输入 AAPL 后出现证券和建议两列 | VERIFIED/UI |
| B08 | 点击 AAPL:US | 进入 /quote/AAPL:US；Apple 标题、代码、Follow 入口可见，订阅墙阻挡进一步完整测试 | VERIFIED/UI；图表/保存 NOT_INSPECTED |
| B09 | 浏览器返回 | 返回市场页并恢复搜索内容；关闭搜索后行情条仍显示此前利率类别 | VERIFIED/UI；仅此会话，不证明跨设备持久化 |
| B10 | 点击 Markets Wrap | 进入 /news/articles/2026-11-16/stock-market-today-dow-s-p-live-updates | VERIFIED/UI |
| B11 | 检查文章并刷新一次 | 曾出现未正常样式化内容，刷新后等待恢复；大广告区、标题、视频区域、订阅墙可见 | 现象 VERIFIED/UI；根因 NOT_ESTABLISHED |
| B12 | 正常滚动文章 | 可见栏目、标题、视频及部分说明；没有完整付费正文体验 | VERIFIED/UI；完整阅读 NOT_INSPECTED |
| B13 | 返回市场页并点击 More | 成功展开 News / Work & Life / Media / Explore / Tools / Sponsored Content 分组 | VERIFIED/UI |
| B14 | 点击 Explore 下 Graphics | 进入 /graphics；主专题与下方多列内容可见 | VERIFIED/UI |
| B15 | 打开 SpaceX 图解专题 | 进入 /graphics/2026-spacex-starship-rocket-future/；深色首屏媒体由空白等待至照片可见 | VERIFIED/UI；未量化加载耗时 |
| B16 | 滚动专题 | 可见 Technology / Explainer、标题、作者、日期、图片来源，出现订阅限制 | VERIFIED/UI；完整图解与滚动交互 NOT_INSPECTED |

注意：外部桌面通知、浏览器翻译提示及 computer-use 鼠标光晕不属于网站，不计作 Bloomberg UI。未点击账户、订阅购买、分享发送或 Follow 保存操作。

未测试项目：390px、真实手机、Safari、完整键盘与读屏、性能指标、长时间稳定性、Terminal、付费正文/报价图表、策略回测、关注保存、提醒送达、报价延迟、数据许可。

交叉核验：另外阅读 Bloomberg Media 2024 首页和 2023 阅读体验官方说明；这些仅用于识别产品设计意图，不能替代上表的当前 UI 证据。
