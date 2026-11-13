# P0：个股当前分析先返回，历史按需计算

日期：2026-11-13。基线：`main@fd11186da8a6028a05ec4efab667dee1e80127a1`。交付范围：Draft PR；未部署、未合并、未运行正式数据发布。

## 结论与证据边界

- **VERIFIED（代码与离线验收）**：普通查询从默认附带104周历史改为 `mode=current, history_weeks=0`。历史是用户主动点击后创建的另一个任务。
- **VERIFIED（代码与离线验收）**：行情、已有当前分析及历史读取并行；历史不在当前结果的等待条件中。新旧结果按资产、任务、源码、模型及数据兼容性核对。
- **VERIFIED（代码与离线验收）**：任务有稳定身份、持久协调、重复请求复用、错误与旧结果分离、首次服务器读取和浏览器可见记录。
- **NOT_ESTABLISHED**：线上实际等待时间、并发成本、供应商授权/稳定性、大陆网络性能、提前至少5个交易日提醒的模型实用价值。本次不是预测准确率实验。
- **NOT_INSPECTED**：真实移动设备、Safari、生产 Worker migration、腾讯云部署与生产首次可见证据。浏览器本地时间不证明公开首发。

## 旧问题与改动

旧 Worker 把普通 `POST /query` 固定派发为104周。主线 workflow 虽先算当前、再算历史，但旧 `/status` 只看整个工作流和股票代码；无法可靠区分“当前可读”与“历史还在运行”。旧页面最长持续轮询40分钟，使用时间戳推测任务归属，且首次打开缺少独立行情阶段。

新链路：

```text
输入代码
 ├─ GET /market                       → 日线 OHLCV，不启动模型
 ├─ 静态/远端已有当前结果              → 可立即阅读；显示各自 asof
 ├─ 当前缺失或较旧 → POST /query current → job_id → queued → current_running → current_ready
 └─ 点击生成历史回放 → POST /query history → 另一个 job_id → queued → history_running → history_ready
```

`stock_query.yml` 只计算所请求的 phase；历史任务不再重算当前结果。结果写入 `stock/jobs/<job_id>/` 的不可变路径，再更新不会倒退的兼容指针。失败保存任务专属错误，保留旧成功数据。nightly 同步使用任务身份与相同发布器，避免另一路写入破坏兼容性。当前与历史复用相同输入/日期/配置/代码哈希的拟合缓存，缓存只节省重复执行，不增加预测证据。

主线已有的腾讯名称与ST识别、v2参数约束和证据显示规则保留。此次不改变振荡数门槛、窗口选择、拟合算法、聚类或顶底评分。

## 状态契约

`status/conclusion` 保留底层任务状态，`workflow_status/workflow_conclusion` 单独保留 Actions 状态；产品使用 `phase`。当前和历史分别保存状态，不把二者压成一个不可解释的“完成率”。

| phase | 含义 | 页面行为 |
|---|---|---|
| queued | 已受理、尚未确认开始；包含派发回执不确定 | 保留 job_id，继续显示行情和旧结果 |
| current_running | 当前分析正在运行 | 股票可切换，不禁用整个页面 |
| current_ready | 当前任务的目标产物已读到且身份匹配 | 立即展示，不等待历史 |
| history_running | 显式历史任务在运行 | 当前分析继续可用 |
| history_ready | 历史任务产物已就绪 | 与当前版本兼容后并排展示 |
| publishing | Actions结束后的短暂结果可见性缓冲 | 最多2分钟，不假报成功 |
| stale | 更新失败，但旧成功结果可读 | 保留旧 asof、last_success_at、stale_reason，允许重试 |
| failed / dispatch_failed / publish_failed | 已知失败或计算成功但没有目标产物 | 显示错误；不将缺失结果补零或虚构分析 |

`current_ready/history_ready` 布尔值只说明**该 job**，旧公共指针不能使新任务变成 ready。报告中的“部分完成”不是额外服务器状态：前端表达为当前可读，同时历史排队/计算/失败。`reconciliation_required=true` 表示超过30分钟仍没有可核实运行或产物；后台可能已接收请求，不能自动重派导致重复扣费。

分析 stale 与行情 stale 分开：前端比较实际行情 asof/预期源码与分析版本；行情 stale 表示缓存刷新失败，不证明最后交易日。未核验交易所日历时，行情明确返回 `asof_freshness=not_established`。

## 首次可见时间不是一个混用字段

| 字段 | 来源与含义 | 不得声称 |
|---|---|---|
| requested_at | Worker 创建任务的UTC时间 | 预测已公开 |
| generated_at | Python生成产物时间 | 用户已看到 |
| first_worker_observed_at | Worker首次核对到该内容哈希，DO持久保存 | 全球首次公开、浏览器可见 |
| first_visible_at_client | 本浏览器可见页面、结果进入视口并经过两帧后记录 | 可信服务器时钟、跨设备首次可见、真实提前公开 |
| public_first_published_at | 当前为 null | 用历史重放冒充提前发布 |

浏览器记录标记 `client_clock_trust=unverified, scope=this_browser, publication_evidence=NOT_ESTABLISHED`，只保留最近200个身份；清理浏览器存储会丢失，尚非账户级审计账本。同一结果再次加载不重置时间。历史任务与当前任务分别标识，历史计算时点不会回填到过去。

## 本地验收

本轮使用纯合成行情与任务响应，浏览器测试拦截所有非localhost请求；没有把合成示例写入正式数据目录。详细运行结果在PR描述与本节最终记录中同步。

- Worker：37项fixture测试通过。覆盖默认0周、显式104周、全局额度/重启去重、回执丢失、独立行情、准确任务身份、stale保留、冲突资产拒绝、首次结果观察持久化。
- Python P0：71项通过，3项未纳入该快速集合（2个网络测试、1个实际串并行拟合对照）。完整回归另行记录，不能以此称全部通过。
- 浏览器：1440×1000、390×844，行情先出现、当前分析独立、历史运行时已有结果保留、无横向溢出、无页面JS异常；首次可见在滚入结果后才创建。同样本历史完成不重置时间。
- 全量前端与Worker：`node --test frontend/tests/*.test.cjs workers/stock-query/test/*.test.mjs`，**141 passed**。其中个股前端72项，其余含已有首页回归和37项Worker测试。
- 全量Python：`python -X utf8 -m pytest -m 'not network' -o addopts='' -r a`，**275 passed，2 skipped，3 deselected**；两项skip分别为缺少历史扫描数据与网络门控。未进行实盘拟合或预测能力重评分。
- 全仓 `ruff check research tests` 与 `git diff --check`：通过。
- 首次全量运行发现缓存指纹改变全局 `ALLOW_INSIDE`，已改为纯指纹读取并加回归；未放宽数值一致性断言。Windows旧代码的中文输出需要UTF-8运行模式，上述全量记录已明确启用。
- 额外修复主线摘要的证据文案：缺少可展示尺度不再写成0/6；缺失、仅开发或失败证据不再写成“不在风险窗口”。该变化只影响显示，不改变任何模型判断。

浏览器结构化记录：[正常异步链路](p0-20261113-evidence/p0-browser-acceptance.json)、[失败保留旧结果](p0-20261113-evidence/p0-stale-browser-acceptance.json)。它们全部来自合成fixture，时间字段是本次测试观察，不是历史预测证据。

### 可执行验收清单

- [x] 默认 `POST {code}` 的派发是 `current/0`；恶意传入历史周数不能隐式升级。
- [x] 显式 `history/104` 得到独立 job；不重新计算当前 phase。
- [x] 未经允许的源、非法代码、错误 job、互相矛盾的 code/symbol/source 被拒绝。
- [x] 连点、并发请求、DO重建不重复派发同一活动任务；额度持久保存。
- [x] current_ready来自本任务可读产物，而非整个 Actions 的绿色状态。
- [x] 历史运行/失败期间，已有当前分析仍可读；页面可切换代码。
- [x] stale不改写旧数据截止日；没有数据时显示失败，不造空模型成功。
- [x] 浏览器后台/未滚到结果时，不记录首次可见；重复查看不重置。
- [x] 保留顶部时间区间和证据约束，未显示预测概率、精确顶日或目标价。
- [ ] 获得部署授权后，用独立测试后端验收真实DO迁移、密钥权限、来源许可、大陆网络和重启恢复。
- [ ] 用实际当前任务测量行情首屏/队列/计算/结果可读各阶段p50/p95；本轮不编造秒数或降幅。
- [ ] 确认未来腾讯云接口仍满足相同JSON和任务语义；当前只保留平台中立API边界，未实现腾讯云持久队列。
- [ ] 建立受保护的服务器发布/可见回执账本后，才能评估“真实提前发布”。

## 与竞品功能对齐的后续清单

下面是产品待办和拆分方案，并非本PR已交付。

| 层 | 对标需求 | 下一份独立交付 | 必须验收的边界 |
|---|---|---|---|
| P0剩余 | 自选、最近分析、告警与恢复 | 账户/浏览器自选分层、顶部观察/正式提醒/修订/新提醒账本 | 浏览器历史不冒充服务器留痕；提醒有效性仍需研究 |
| P1日终复盘 | 开盘啦情绪、连板梯队、题材库、涨停原因、龙虎榜、板块强度 | 交易所日历、完整四池封存、原因/历史题材、次日晋级、行业/概念/地域热力图 | append-only两日真实样本→历史日期切换→日更；不以当前数据补造过去 |
| P1个股资料 | iFinD/Eastmoney公告、研报、F10、财务、股东、解禁、资金历史 | 逐源接口与元数据卡、公告/资料时间轴 | 保存与展示许可、发布时间/可得时间/修订分离；不进LPPL |
| P2市场工具 | 条件选股、全球资产、图表回放、事件驱动 | 描述性筛选器、经济/央行日历、全球资产卡、统一行情/事件/LPPL时间轴 | 不重新计算未授权信号；官方宏观优先；复权、时区、交易日历明确 |
| P2盘中 | 盘口异动、情绪变化、资金分位、连板晋级 | 先六时点采样、再考虑连续盘中；配额/预算可观测 | 数据延迟和供应商估算标签；日终采样不能冒充实时逐笔 |
| P3资讯与概率 | 金十式全球资讯、预测市场概率 | 新闻只存标题/来源/时间/链接/hash；有书面许可才开概率六小时刷新 | Polymarket/Kalshi隐含概率不称FedWatch；流动性/stale可见；不喂入LPPL |
| 后续专业工具 | iFinD估值/组合、TradingView云告警/筛选/回放 | 先组合观察与条件通知，再单独评估估值与模拟交易 | 不能用未通过模型生成买卖承诺，交易/资金功能不纳入本轮 |

公开功能参考：[东方财富行情中心](https://quote.eastmoney.com/center/)、[iFinD帮助中心](https://ft.10jqka.com.cn/index.php?a=helpCenter)、[开盘啦](https://www.kaipanla.com/omain/index.html)、[复盘啦教程](https://kaipanla.com/article/35181)、[题材库教程](https://kaipanla.com/article/38490)、[TradingView功能](https://www.tradingview.com/features/)。它们只证明对方公开介绍这些功能，不证明数据可免费再分发或本项目已有等价能力。

## 发布与合并边界

本轮从当前main隔离开发，借鉴已有PR50分支的异步任务实现，并保留主线后续的个股名称/数据版本处理；没有把PR50的设计演示、P1来源代码或模型研究整段覆盖到main。为完成用户授权的端到端状态协议，同步更新了既有数据入口 `lppl-data.js`，页面没有增加直接fetch或本地模型。

PR只运行离线CI。`stock_query`、`stock_nightly`移除了自动派发Pages；stock-results结果写入代码保留，但本轮未调用它对远端写入。新Worker需两个Durable Object绑定；旧部署不会因提交Draft PR自动获得这些能力。不得在新workflow/Worker未就绪时单独上线前端。正式部署、合并、域名和购买均等待用户另行明确授权。
