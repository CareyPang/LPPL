# LPPL 后端与同类产品功能缺口深度审计

- 审计日期：2026-11-13（Asia/Singapore）
- 仓库：[CareyPang/LPPL](https://github.com/CareyPang/LPPL)
- 远程基线：main @ fd11186da8a6028a05ec4efab667dee1e80127a1，最近合并 PR #56
- 范围：后端、Worker、GitHub Actions、Pages、研究/数据层、当前前端数据入口、同类产品公开能力、缺口与路线
- 约束：只提交文档；不合并、不部署、不购买数据服务，不把研究结果升级为预测能力

## 证据标签

- VERIFIED：直接读取当前 main 源码、工作流、PR 状态或本地仓库结构后确认。
- PR_AUTHOR_REPORT：PR 描述、提交说明或作者验收文字中报告的结果；本次没有重新运行。
- NOT_ESTABLISHED：代码或文档存在，但部署、授权、稳定性、生产数据或效果尚未证明。
- NOT_INSPECTED：本次没有重新检查的运行时、真实手机、生产域名、长时间任务或外部系统。
- INFERENCE：根据已核对结构推断的工程风险，不能当作生产事实。

## 一、当前结论

1. VERIFIED：远程 main 是可运行的研究原型和静态 Pages 数据产品，已具备 LPPLS 研究层、A 股个股批量/按需计算、市场日终快照、国家队 ETF 看板、GitHub Actions 发布链路和一个公开查询 Worker 的代码。
2. VERIFIED：main 不包含本地 PR #50 的完整异步工作站、market-context Worker、投资者资讯统一契约和腾讯云兼容层；这些仍在 PR #50/本地工作区一侧。
3. VERIFIED：个股查询采用当前结果先出、历史回测再跑的两阶段设计；Worker 负责排队、状态和结果读取，Worker 本身不执行 LPPLS。
4. NOT_ESTABLISHED：Worker 是否部署、GH_TOKEN/KV 是否配置、真实用户是否能稳定完成行情→当前结果→历史结果链路，没有足够生产证据。
5. VERIFIED：市场日更已有单一快照入口，但数据落在 stock-results 分支和静态 JSON；它不是用户账户数据库，也没有统一 append-only 事件账本。
6. VERIFIED：PR #52、#53、#56 已合并，市场复盘、国家队 ETF、板块强度回退已进入主线；PR #58–#65 属于后续增量，不能当成当前主线功能。
7. VERIFIED：LPPLS 研究结果仍需要按研究候选/描述性证据使用。当前产品不应声称稳定预测顶部日期、底部日期、回撤幅度或收益。
8. INFERENCE：当前最大产品风险是用户把研究区间、历史回放、描述性市场背景理解为实时预测、投资建议或已验证告警。

## 二、当前后端与数据流

### 2.1 个股查询 Worker

VERIFIED：主线文件为 [workers/stock-query/src/index.js](https://github.com/CareyPang/LPPL/blob/main/workers/stock-query/src/index.js)，接口为：

- POST /query：校验六位 A 股代码，向 GitHub Actions 发 repository_dispatch。
- GET /status：读取 stock_query.yml 工作流状态，支持按首次派发时间过滤。
- GET /result：从 stock-results/stock/ 读取 latest、history、error。
- OPTIONS/CORS：按 ALLOWED_ORIGIN 限制来源。
- 可选 KV 限流：同一 IP 十分钟最多五次，同一代码十五分钟去重；没有 KV 时响应 ratelimit=disabled。

VERIFIED：Worker 不运行 Python、SciPy 或 LPPLS，计算在 [stock_query.yml](https://github.com/CareyPang/LPPL/blob/main/.github/workflows/stock_query.yml) 中完成。

VERIFIED：README 提供 Cloudflare Worker、KV、secret 和 wrangler deploy 步骤；源码和 README 不能证明资源已经部署。

NOT_ESTABLISHED：没有本次可复核的 Worker URL 健康检查、Cloudflare deployment ID、KV 绑定、secret 配置证明、真实跨域浏览器链路和生产耗时分位数。

### 2.2 GitHub Actions 个股链路

VERIFIED：stock_query.yml 的当前任务固定先执行 research.pipeline.stock --history-weeks 0，上传当前 artifact；非 PR 事件发布当前结果；随后按 history_weeks 运行独立历史任务。

VERIFIED：Worker 默认派发 history_weeks=104，所以用户可先拿当前结果，104 周历史在后台继续运行。

VERIFIED：工作流包含输入校验、Python 3.12、市场数据端点探测、失败 JSON、artifact、发布和 Pages 重触发。

VERIFIED：stock_nightly.yml 对 CSI300/CSI500 使用固定 asof、分片和广度摘要，支持 workflow_dispatch 和工作日定时任务。

NOT_ESTABLISHED：Actions 不是稳定用户计算服务。当前没有用户级队列、SLA、取消/重试策略、租户隔离、持久任务数据库，也没有 P50/P95 运行时间验收。

### 2.3 个股研究与输出

VERIFIED：research/pipeline/stock.py 支持 A 股代码、后复权日线、stk_lite/stk_full、固定 asof、停牌/退市状态、样本数、ST/一字板退化标记、数据源和模型版本字段。

VERIFIED：stock_batch.py 以共同 asof 批量计算，单只失败写 error JSON，不把失败填成零。

VERIFIED：个股输出包含 LPPLS 顶部结构、情景/置信度、行情历史、数据版本和证据字段；底部/价格层许多结果仍是描述性或未校准。

NOT_ESTABLISHED：没有证据证明顶部时间区间在独立样本、严格 as-of、同一报警次数约束下达到可承诺准确率，也没有证明底部和价格层可作为交易信号。

### 2.4 市场日终数据

VERIFIED：主线 market_base.py 与 market_daily.yml 已形成工作日日终快照链路，包含：

- 东财行业/概念/地域板块资金流和 5/10 日字段；东财失败后的新浪板块流回退；
- 涨停、炸板、跌停池及昨日池/晋级摘要；
- 北向类快照、中证指数估值、上交所/深交所融资融券；
- 板块历史资金字段顺序校验；
- 板块强度、市场情绪、连板天梯、强势股/人气、盘后龙虎榜和快讯等 PR #52 复盘模块；
- 每段独立 source metadata，失败不拖垮整体；涨停池失败时保留上一份已发布快照。

PR_AUTHOR_REPORT：PR #56 报告东财板块强度非 JSON/502 时按 push2delay→新浪概念板块回退；本次没有重新跑真实日终采集。

NOT_ESTABLISHED：免费网页/接口是否允许持续抓取、保存、派生统计和公开展示没有授权证明；接口频率、反爬稳定性和大陆网络长期可达性也没有合同或 SLA。

### 2.5 国家队 ETF

VERIFIED：PR #53 已合并，主线增加国家队 ETF 日终看板、申赎估算、持有人基准和中信期货股指持仓数据路径。

PR_AUTHOR_REPORT：PR #65 报告追加东财 F10 机构持有结构和异常大额申赎标记；该 PR 仍开放，不能视为主线功能。

NOT_ESTABLISHED：不能把机构比例解释为国家队比例，也没有证明长期公开展示许可。

### 2.6 Pages 与静态数据

VERIFIED：[pages.yml](https://github.com/CareyPang/LPPL/blob/main/.github/workflows/pages.yml) 在 main 的 web、frontend、构建脚本变更或手动触发时构建 _site、上传 Pages artifact 并调用 deploy-pages；构建前尝试获取 stock-results。

VERIFIED：Pages 是静态站点；用户状态、自选、任务、历史回放和结果主要依赖浏览器缓存、静态 JSON 或 Worker。

NOT_ESTABLISHED：本次没有重新验证生产 URL、最后一次 deployment、域名、缓存刷新、移动端真实设备、低带宽和大陆网络访问。

### 2.7 远程 main 与 PR #50 的分叉

VERIFIED：远程 main 为 fd11186；本地 D:\LPPL-development\async-stock-20261106 仍是 od/stock-async-20261106 @ 7f7fe93，且有大量未提交前端演示改动。PR #50 仍开放，不能当作 main 功能。PR #50 一侧的 market-context Worker、投资者资讯 schema、P1/P2/P3 文档和腾讯兼容层不应写入当前线上后端。

## 三、同类产品公开能力对照

下表只比较公开页面宣称的能力，不把页面文案当成准确率证明。

| 能力 | LPPL main | 东方财富 | iFinD/同花顺 | 开盘啦 | TradingView |
|---|---|---|---|---|---|
| A 股行情/自选 | 个股查询、部分市场页；账户自选未进入主线 | 行情中心、自选、条件选股 | 多市场行情、组合管理 | 自定义版面和热点入口 | 跨设备 watchlist |
| K 线/回放 | 静态个股图和研究回放，交互有限 | 完整行情图和条件筛选 | 多周期行情、数据浏览器 | 区间统计、复盘啦 | 多周期图、Bar Replay、脚本 |
| 涨跌停四池 | 主线日更包含涨停/炸板/跌停 | 涨停、昨日涨停、强势、炸板 | 涨跌停分析 | 涨停复盘、原因 | 通用筛选，非 A 股四池 |
| 连板/题材 | #52 合并后有复盘模块；历史 PIT 仍需验证 | 主题投资和板块导航 | 事件精选、题材/企业图谱 | 连板梯队、题材库、核心股、原因 | 自定义脚本/筛选器 |
| 板块热力/资金 | 板块资金流、强度和回退；历史分位不完整 | 大盘星图、行业/概念/地域、资金流 | 市场全景、板块热点 | 板块强度、区间强度、板块叠加 | Heatmap、筛选器 |
| 公告/F10/财务/股东/解禁 | 缺统一个股资讯闭环 | 完整 F10/公告/财务/解禁等 | 150+资料节点、3000+指标、事件驱动 | 机构、龙虎榜、公告/题材 | 财报、分红、经济日历 |
| 龙虎榜/历史资金 | #52 盘后模块已合并，历史覆盖仍需复验 | 净买额、买卖额、换手、原因和后 1/2/5/10 日表现 | 融资融券、龙虎榜、资金流向 | 实时/深度龙虎榜 | 全球市场数据和脚本 |
| 宏观/全球 | #59 仍开放，main 暂无完整宏观页 | 全球指数、债券、黄金、外汇 | 全球概览和事件数据 | 北向、外围和盘中内容 | 经济/财报/分红日历、收益率曲线、400+经济指标 |
| 告警/订阅/账户 | 公开排队，不是用户告警中心 | 自选和行情提醒 | 组合/投资助手/事件驱动 | 自定义版面、盘中盯盘 | watchlist alerts、跨设备同步 |
| 证据/时点 | LPPL 的差异化方向，main 未形成统一账本 | 传统行情产品 | 数据平台/投研工具 | 复盘工作流 | 图表和策略研究 |

公开参考：

- [东方财富行情中心](https://quote.eastmoney.com/center/)
- [东方财富大盘星图](https://quote.eastmoney.com/stockhotmap/)
- [东方财富涨停板行情](https://quote.eastmoney.com/ztb/?from=center)
- [东方财富龙虎榜](https://data.eastmoney.com/Stock/TradeDetail.html)
- [同花顺 iFinD 帮助中心](https://ft.10jqka.com.cn/index.php?a=helpCenter)
- [开盘啦功能时间线](https://www.kaipanla.com/omain/index.html?ifurl=https%3A%2F%2Fwww.kaipanla.com%2Fdownload%2Findex.html)
- [开盘啦复盘啦说明](https://www.kaipanla.com/article/35181)
- [TradingView Features](https://www.tradingview.com/features/)
- [TradingView Watchlist Alerts](https://www.tradingview.com/support/solutions/43000739708-watchlist-alerts-your-trading-edge/)

## 四、当前缺失与优先级

### P0：先让结果可用且可信

1. 统一任务状态：queued、running、current_ready、history_running、history_ready、partial、failed、stale；每个状态带 asof、source、fetched_at、run_id、error、retry_after。
2. 真实闭环验收：输入 600519 和 000001，验证行情先出、当前结果先出、历史结果后出、失败可重试、首次可见时间可追溯。
3. 部署契约：Worker URL、KV、GH_TOKEN、Actions 权限、Pages URL、允许来源和密钥轮换。
4. 证据文案：顶部区间显示研究区间/历史回放/当前观察状态，禁止“保证逃顶”“精准预测”。
5. 结果存储边界：短期可保留 GitHub branch，任务状态和用户意图应进入最小持久化层。

### P1：个股工作站

- 自选股、最近分析、修订日志、数据截止日、来源、哈希和模型版本；
- K 线、成交量、LPPL 区间与事件在同一时间轴；
- 重试、stale、缓存命中和历史回放；
- 先用匿名浏览器本地状态，付费版再迁移腾讯云数据库/COS。

### P2：A 股复盘

- 交易所验证日历、asof/prior_asof；
- append-only 日终 bundle；
- 完整四池、涨停原因、题材标签、历史题材、次日晋级；
- 行业/概念/地域热力和 5/10/20 日资金历史分位；
- 公告、研报、财务、股东、解禁、龙虎榜、资金历史；
- 日期切换只读取当日或此前封存资料，禁止当前资料补造过去。

### P3：全球与资讯

- Treasury、NY Fed、BIS、ECB、BLS、EIA 等官方宏观源；
- VIX、DXY、黄金、原油、美元兑人民币逐源记录 source/asof/fetched_at/stale；
- 全球新闻只保留标题、来源、时间、链接和 hash；
- 预测市场隐含概率须有书面许可，注明来源、时点、流动性和 stale，不称官方 FedWatch，也不喂入 LPPLS。

## 五、架构债务与产品冲突

- GitHub Actions 兼作在线计算服务：成本低、可追溯，但冷启动、排队、并发和取消控制弱。
- Git 分支兼作数据库：适合少量静态结果，不适合用户任务、重复提交、局部更新和保留期管理。
- 免费网页/接口可读不等于获得再分发许可。
- main 与 PR #50 双轨，容易出现页面已改、后端未部署。
- 市场背景、公告、题材和宏观只能作为信息展示，未经登记不能喂入 LPPLS 或改变告警阈值。
- 顶部研究比底部成熟；底部事件库和价格层必须保留失败/未校准标签。
- 缺少请求成功率、stale 时长、数据延迟、任务 P50/P95、首屏耗时和错误类型的统一观测。
- 缺少账户、隐私、留存、删除、免责声明和商业数据授权的运营方案。

## 六、建议目标架构

浏览器 → 静态 Pages + market-context API + stock-query API；
腾讯云迁移目标 → API Gateway/CloudBase Functions、任务表、COS immutable bundles、当前/历史队列、定时任务和观测系统；
研究层 → LPPLS 只接收 PIT 行情与预登记参数；资讯层单独保存，不进入 LPPLS；
输出契约 → 每个结果都带 evidence、source、asof、fetched_at、status、hash。

迁移顺序：

1. 先在现有 Worker 接口补 run_id 和状态协议，保持前端兼容。
2. 将 GitHub branch 结果复制为 COS immutable bundle，GitHub 保留公开静态镜像。
3. 把 Actions 计算包裹成可替换的队列消费者，不改模型。
4. 加失败重试、超时、死信、配额和匿名速率限制。
5. 双写对账两周后，再决定是否关闭 GitHub Actions 在线入口。

## 七、路线图

### 一周

- 完成 600519/000001 真实链路验收并记录三阶段首次可见时间；
- 固化 stock-query.v1 状态协议；
- 为市场源增加 source/asof/fetched_at/status/stale_reason/hash；
- 重新验证 #52/#53 真实日终快照，不修改 LPPLS；
- 清理“预测/保证/准确率”文案。

### 一个月

- 交付 P0 工作站：自选、最近分析、修订账本、时间轴、重试；
- 交付 PIT append-only 日终 bundle 和两日/多日回放；
- 迁移任务状态到腾讯云数据库，结果和证据写 COS；
- 完成免费源许可、频率、保存、派生、展示和大陆网络核验；
- 建立任务与数据质量看板。

### 三个月

- 接入官方宏观源和全球新闻元数据；
- 交付公告、财务、股东、解禁、龙虎榜、资金历史闭环；
- 账号、配额、订阅和跨设备自选；
- 评估预测市场概率，未取得书面许可则继续关闭；
- 重新登记并样本外评估顶部/底部评价器，保持研究与产品告警分层。

## 八、执行验收清单

### 个股工作站

- [ ] 输入 600519 后显示已有行情缓存或明确加载状态；
- [ ] 当前分析和 104 周历史是两个任务，互不阻塞；
- [ ] 显示 asof、来源、模型版本、任务 ID、状态、首次可见时间；
- [ ] 顶部区间区分观察、正式提醒、修订、新提醒；
- [ ] K 线、成交量、LPPL 区间和事件时间轴日期一致；
- [ ] 失败可重试，stale 有原因和上一次成功时间；
- [ ] 不显示保证逃顶、精准预测或收益承诺。

### Worker、stock_query、stock_nightly

- [ ] POST /query 返回可追踪 query_id/run_id；
- [ ] status 区分 pending/running/current_ready/history_running/history_ready/failed/stale；
- [ ] result 对 404、错误 JSON、旧结果和新结果有明确边界；
- [ ] KV 限流、重复提交、取消、超时和重试有真实验收；
- [ ] 批量结果共享同一 asof，单只失败写 error JSON；
- [ ] P50/P95、失败率和 stale 时长进入观测。

### 市场日更与 Pages

- [ ] 四池、原因、题材、晋级按日封存；
- [ ] 日更失败保留上一份快照并标 stale；
- [ ] 历史回放只读取当日或当时已知资料；
- [ ] Pages deployment、URL、commit、artifact 可追溯；
- [ ] stock-results 与 Pages 构建版本一致；
- [ ] 390px、真实手机、低带宽和大陆网络完成验收；
- [ ] Pages 不承载密钥，不暴露 GitHub token。

### 治理

- [ ] main 开启分支保护并设置 required checks；
- [ ] 报告、数据源许可和模型登记与代码变更绑定；
- [ ] PR 作者报告不升级成 VERIFIED；
- [ ] 模型参数变化有版本号、回放报告和独立样本结果。

## 九、证据边界

- 同类产品页面证明公开宣称/展示的功能，不证明准确率、授权范围或内部实现。
- PR 描述中的样本数量、截图和测试结果属于 PR_AUTHOR_REPORT，除非本次重新运行不升级为 VERIFIED。
- LPPLS 顶部、底部和价格层必须继续遵守严格 as-of、样本外、预登记和多重比较边界。
- 腾讯云购买、部署、域名、备案、数据供应商采购和 Pages 正式发布都需要单独授权和验收。