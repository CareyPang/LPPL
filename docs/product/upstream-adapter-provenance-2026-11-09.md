# P1 上游参考、独立适配与证据边界

记录日期：2026-11-09。范围是 PR #50 的有限 P1 数据适配：登记来源、解析已保存响应、形成可追溯的离线证据。本次没有复制两个上游仓库的实现，没有引入 AI 依赖，也没有启用新网络抓取、购买、部署、合并或发布。

## 本次选择与未做事项

**VERIFIED（代码结构）**：新增 `research/data/p1_source_catalog.json` 和只读 accessor。目录只选 8 项 P1 已有/候选来源，`source_count=8` 只描述这份目录，不能扩展成“Vibe 全部接口已接通”或供应商完整覆盖。

| source_id | 本地实现入口 | 本次状态 |
| --- | --- | --- |
| `ths_limit_up_pool` | `research.data.market_p1:fetch_ths_reasons_topics` | 已有取数/解析函数；本次只登记 |
| `eastmoney_yesterday_zt_pool` | `research.data.market_p1:fetch_yesterday_pool` | 已有取数/解析函数；本次只登记 |
| `eastmoney_limit_pools` | `research.data.market_base:limit_pools` | 已有取数/解析函数；本次只登记 |
| `eastmoney_board_flow` | `research.data.market_base:board_flow_snapshot` | 已有取数/解析函数；本次只登记 |
| `eastmoney_fund_flow_history` | `research.data.p1_provider_parsers:parse_provider_payload` | 独立编写的离线解析器，接收已保存响应 |
| `eastmoney_dragon_tiger` | 同上，按 source_id 分派 | 独立编写的离线解析器，接收已保存响应 |
| `eastmoney_lockup_expiry` | 同上，按 source_id 分派 | 独立编写的离线解析器，接收已保存响应 |
| `eastmoney_stock_news` | 无 | 仅候选登记；`implemented=false` |

`implemented=true` 只表示本地有对应函数，不表示源已授权、生产可达或历史数据为 PIT。资金历史、龙虎榜和解禁的共同入口是 `parse_provider_payload(source_id, payload, *, asof, subject=None)`；它们没有网络调用。**没有全源自动启用；新目录的禁用开关也不等于已有抓取已停用。**已有四项函数的默认抓取行为没有被这份目录修改或拦截，目录策略只有被新调用边界显式检查时才生效。新浪板块资金备用源不在这 8 项范围内，不能借东方财富条目的许可状态覆盖它。

**NOT_INSPECTED（本轮实时执行）**：没有对这 8 项进行新一轮实时抓取或大陆网络探测。测试输入是离线样例，不得作为“真实两日日终快照”“每日更新已上线”或“真实首次可见预测”的证据。

**NOT_ESTABLISHED**：逐源自动化访问许可、公开/商用再分发权、供应商认可的频率、代表性大陆网络稳定性、历史信息首次可用时点。所有源的 `fetch_enabled` 和 `publish_enabled` 均为 `false`。

## 固定上游版本与代码许可

| 上游 | 本次固定 revision | 仓库代码许可证 | 本次使用方式 |
| --- | --- | --- | --- |
| Vibe-Research | `84c141b86b5e7540b29f5f4cd5457dc0ebd6052e` | MIT | 阅读目录、数据解析形态、原始响应/哈希/状态规范；独立实现 |
| TradingAgents-astock | `3a9171182304e87042743dde245c64922e04ed96` | Apache-2.0 | 阅读 `tradingagents/dataflows/a_stock.py` 数据函数；独立实现 |

证据固定到 commit：[Vibe LICENSE](https://github.com/simonlin1212/Vibe-Research/blob/84c141b86b5e7540b29f5f4cd5457dc0ebd6052e/LICENSE)、[Vibe 数据目录](https://github.com/simonlin1212/Vibe-Research/blob/84c141b86b5e7540b29f5f4cd5457dc0ebd6052e/datasources/registry.json)、[Vibe Eastmoney 代码](https://github.com/simonlin1212/Vibe-Research/blob/84c141b86b5e7540b29f5f4cd5457dc0ebd6052e/.agents/skills/data-access/scripts/sources/eastmoney.py)、[Vibe 同花顺代码](https://github.com/simonlin1212/Vibe-Research/blob/84c141b86b5e7540b29f5f4cd5457dc0ebd6052e/.agents/skills/data-access/scripts/sources/ths.py)、[TradingAgents LICENSE](https://github.com/simonlin1212/TradingAgents-astock/blob/3a9171182304e87042743dde245c64922e04ed96/LICENSE)、[TradingAgents A 股数据函数](https://github.com/simonlin1212/TradingAgents-astock/blob/3a9171182304e87042743dde245c64922e04ed96/tradingagents/dataflows/a_stock.py)。

**VERIFIED（固定源码）**：上述是代码许可证，不能替代东方财富、同花顺或新闻原作者的数据授权。目录把 `code_provenance` 与 `data_policy` 分开。`copied_in_this_change=false` 只描述本次实现方式；不替既有仓库全部文件出具版权结论。

Vibe 的[上游对账单](https://github.com/simonlin1212/Vibe-Research/blob/84c141b86b5e7540b29f5f4cd5457dc0ebd6052e/datasources/UPSTREAM.md)说明部分数据实现是从其他项目移植，更新不会自动同步。本次不跟随浮动 `main`、不整包覆盖 LPPL。未来若改为直接复制代码，应再次核对许可证、NOTICE 和实际复制范围；Vibe 的回测目录另含 HKUDS/Vibe-Trading 来源，不在本次范围内。

## 目录策略如何拒绝不确定状态

`get_source(source_id)` 返回独立副本，未知 ID 抛 `KeyError`，不选择备用源、不动态导入或执行登记函数。`policy_problems(source_id, purpose="fetch" | "publish")` 只检查本地策略；只有返回空列表才通过这一道检查：

- 未知 ID 返回 `unknown_source`；非法 purpose 和损坏目录直接报错。
- 本地没有解析器时返回 `parser_not_implemented`。
- 开关必须是 JSON 布尔值 `true`；字符串 `"true"`、数字 `1` 不算授权。
- 自动抓取要求 access、frequency_review、mainland_network 都为 `verified`，并各自带非空 `evidence_refs`。
- 公开展示还要独立通过 redistribution 并明确开启 `publish_enabled`。
- 只有标签而无证据引用，或结构缺失、未知状态，一律拒绝。

`evidence_refs` 是人工审核结论的记录入口，accessor 本身不能判定条款是否有效，不能保证引用文件真实或仍未过期。因此空 blocker 列表也不是发布操作：调用边界仍须检查原始响应哈希、日期、首次可用时点、stale、追加写入冲突和正式发布授权。

目录的限速是 **LPPL 本地待实现策略**：每 provider host 并发 1、请求至少间隔 2 秒、最多 2 次尝试、遇 429 遵守 Retry-After 并受预算限制、遇 403 停止复核。它标为 `proposal_not_enforced` 和 `provider_guarantee=false`，既不是供应商频率承诺，也不表示限速已经部署。供应商频率审核仍是 pending。

## 日期、历史回放与证据规则

1. **涨停原因/题材**：接口接受 date 不代表返回内容在当时已可获取。只能使用真实封存响应，不拿当前原因补填历史。
2. **前日涨停池/晋级率**：T 日返回的昨日池不能替代 T-1 当时的封存池。晋级率仍需两个真实交易日快照与已验证交易日历。
3. **行业/概念/地域资金**：今日、5 日、10 日是当前滚动快照，不是历史 vintage。历史回放只能展示当时封存版本。
4. **日级资金历史**：历史行的交易日期不等于首次可用日期。当日补取过去 120 日的序列，仍属于当日可见的历史序列，不自动具备过去时点的 PIT 资格。
5. **龙虎榜**：TRADE_DATE 是事件日，须另存抓取/封存时点与分页完整性。缺失响应不等于“未上榜”。
6. **解禁**：FREE_DATE 是预计解禁事件日，可以晚于 asof；它不是公告日。今天看到的未来解禁表不能回填为过去已知。没有可用时点证据时，PIT 状态保持未知。
7. **新闻候选**：只规划标题、来源、时间、链接、哈希；不保存正文，不让模型补造日期，不把当前搜索结果当成完整历史新闻库。

离线证据使用 `p1-source-evidence.v1`，独立保存原始字节、哈希、源 URL、asof、抓取时间、实际归档时间、解析器版本/源码哈希和目录快照。实际结构分为：

```text
archive/
  raw/<raw_sha256>.json                 原始响应字节
  records/<record_sha256>.json           带来源、解析结果、状态与哈希的记录
  observations/<observation_sha256>.json 同次观测到首次记录的索引
```

**VERIFIED（离线契约）**：同次观测在相同 raw、来源、asof、声明抓取时间、标的、解析器与目录版本下重复导入，复用首次记录，即使本地时钟前进也保留首次 `available_at`。输入或版本变化产生新观测，不覆盖旧记录。`fetched_at` 仍标为 `caller_declared`；`available_at` 仅表示首次本地归档可见时间，**不是供应商首次公开时间，更不是网站对用户首次发布预测的时间**。`public_first_published_at=null`、`pit_status=NOT_ESTABLISHED`、`publication_eligible=false` 始终保留。索引与内容哈希用于完整性校验，不是对抓取声明的第三方认证。

读取记录时重验原始字节、记录、解析器和目录证据哈希，重新解析已保存响应并核对结果、日期与可用时点。JSON 的重复键和非有限数一律拒绝，读取大小有上限。URL 必须匹配登记的 HTTPS host/path；显式的 secid、日线频率、fields2 顺序/宽度、reportName 或 SECURITY_CODE 过滤冲突会被拒绝。缺失请求参数证据的响应降为 partial，不因用户填写了 source_id 就认定请求范围完整；匹配的 query 仍是调用者声明，不升级为自动验证的实际请求。

导入上下文的 `run_mode=research_import`，只在 `p1.supplemental_sources` 增补；键包含 source_id 和标的，未指定标的时叫 `observed_set`，不称为全市场。不能把个股资金历史覆盖成市场资金，也不替换旧来源、旧快照、晋级率或 LPPL 输入。解禁数量/比例字段暂保留原始值，单位未核验时不换算为股数或百分比。

`available_at_cutoff` 会同时约束补充证据与基础 payload。晚于截止时点的补充数据隐藏；普通 base payload 没有可信的历史可用回执，最早只认本次构建时刻。截止时点早于本次构建时，整份 base 数据也会遮挡，并输出 `base_availability_status=not_available_at_cutoff`。不能只隐藏补充卡片，却让当前抓取的行情、题材或资金数据进入旧时点回放。

**VERIFIED（发布门槛代码）**：Worker seed/refresh、append-only bundle 校验及两日真实快照 gate 均拒绝研究导入标记和 supplemental sources。fixture 与手工导入不能计作 live 日终样本；当前离线数据只支持研究检查，不能拿来宣称历史重放具有当时真实发布的预测成绩。

## 验证范围

`tests/test_p1_source_catalog.py` 的 27 项离线测试与 Ruff 检查已通过，覆盖：8 项有限范围、固定 SHA、未知 ID 拒绝、开源代码许可与数据许可分离、无证据的 verified 不放行、布尔开关严格校验、返回副本不可改变策略、目录重复 ID/错误计数/浮动 revision/未知 host/来源引用拒绝、重复 JSON 键/非有限数拒绝，以及当前 vintage/事件日边界。

测试通过只证明离线契约行为。解析器、证据归档和集成回归有各自测试；汇总结果以该 PR 当次实际检查为准。没有运行 LPPL 模型或新的回测，不对顶部、底部、提前量或价格层准确率作新增承诺。

## 下一步

1. 按这 8 项逐源补充可审阅的访问、缓存/再分发、供应商频率和大陆网络证据；未通过的源继续禁用。
2. 对获准来源小规模保存真实原始响应，核对字段单位、交易日期、分页完整性、空值和错误形态，再封存连续两日样本。离线 fixture 不计入真实快照。
3. 把证据与交易所日历、append-only bundle、历史复盘和 stale/轮询验收连接起来；独立记录首个可见时间。
4. 经过现有 Worker seed 前验收与用户的部署/发布授权后，才考虑线上写入。当前 PR 更新不等于上述授权。
5. P2 官方宏观和 P3 概率保持独立计划。新闻、资金、龙虎榜、解禁、LLM 解释和预测市场概率均不进入 LPPLS；新增变量必须另做预注册与无泄漏验证。
