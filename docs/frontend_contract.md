# 前端数据契约（Open Design 交接）

目的：外部前端（Open Design，目录 `frontend/`）只通过本文列出的静态 JSON 与后端对接。后端不提供 API 服务（规划 2027-H2），仓库数据源位于 `web/mock/data/`，GitHub Pages 发布路径为 `lab/mock/data/`（例如 `https://careypang.github.io/LPPL/lab/mock/data/…`）。字段含义以 `docs/product_contract.md` 和 `research/eval/export_contract.py` 为准，本文只是索引；字段改名放在前端适配层，后端 JSON 不为前端改名。

## 1. 文件清单

| 路径（相对站点根） | 内容 | 生成者 | 更新 |
|---|---|---|---|
| `lab/mock/data/<sym>_latest.json` | 单指数最新契约（6 个：sh000001 上证、sh000016 上证50、sh000300 沪深300、sh000905 中证500、sz399001 深证成指、sz399006 创业板指） | `research/pipeline/daily.py` → `build_record` | 日更（`scripts/daily_update.sh`） |
| `lab/mock/data/sh000001_<date>.json` | 开发段回放（2007-10-12、2015-06-12），同结构，多一个 `movie` 帧数组 | `research/eval/export_contract.py` | 不更新 |
| `lab/mock/data/price_layer/drawdown_table.json` | P1 全样本情景表（报告用；页面**不要**直接读它，读记录内的 `top.drawdown_price`） | `research/price_layer/drawdown_table.py` | 随冻结数据重生成 |
| `lab/mock/data/price_layer/rebound_table.json` | LT 顶→谷后 250 日恢复事件与分位汇总 | `research/price_layer/bottom_cards.py` | 随冻结价格数据重生成 |
| `lab/mock/data/catalog.json`、`stock_names.json` | 资产目录（316 标的：代码、名称、交易所、板块、所属指数） | 日更脚本 | 日更 |
| `lab/mock/data/universe_*.json` | 指数成分（当前 / 历史 PIT） | 日更脚本 | 日更 |
| `lab/mock/data/stock/breadth_<idx>.json` | 成分股广度（夜间预算库，`stock_nightly` 同一截止日）：`n`（可统计成分股数）、`n_qualified_fit_dev` / `share_qualified_fit_dev`（6–12 月 / 12–24 月任一尺度有合格拟合）、`n_confidence_ge_0_5_dev`、`per_scale_*`、`asof_consistent`。`evidence=descriptive`：只显示比例与 n，文案“描述性统计，不是预测，不进模型”；不得进入报警、置信度或任何模型特征（R8 横截面广度为 Round 2 候选，未登记） | `research/pipeline/stock_batch.py breadth` → `stock-results` 分支 | 工作日 17:40 北京时间 |
| `lab/mock/guide.md` | 用户指南副本（教育页渲染） | `docs/user_guide.md` 复制，CI 校验一致 | 随文档 |
| `forward_log/` | 前瞻日志（append-only，只读） | `research/pipeline/forward_log.py` | 日更 |

## 2. 记录结构 `<sym>_latest.json`

顶层：`symbol`、`name`、`asof`、`data_version`、`model_version`、`price_history{dates[],open[],high[],low[],close[],volume[],note}`、`top{…}`、`regime_band`、`bottom`、`validation[]`、`evidence_levels{}`（证据等级代码 → 中文说明）。

`price_history` 各数组与日期按索引严格对齐，且只包含不晚于记录 `asof` 的 bar。

| 路径 | 类型 | 可空 | 含义 | 显示规则 |
|---|---|---|---|---|
| `price_history.dates[]` | string (`YYYY-MM-DD`) | 否 | 交易日期 | 与所有 OHLCV 数组逐项对齐 |
| `price_history.open[]` | number \| null | 是 | 开盘价，保留 3 位小数 | 不晚于 `asof`；缺失时留空 |
| `price_history.high[]` | number \| null | 是 | 最高价，保留 3 位小数 | 不晚于 `asof`；缺失时留空 |
| `price_history.low[]` | number \| null | 是 | 最低价，保留 3 位小数 | 不晚于 `asof`；缺失时留空 |
| `price_history.close[]` | number | 否 | 收盘价，保留 3 位小数 | 不晚于 `asof` |
| `price_history.volume[]` | integer \| null | 是 | 成交量 | 有源数据时整数；缺失时留空 |
| `price_history.note` | string | 否 | 价格历史的说明文字 | 保留原说明 |

`top` 子树（每个对象都带 `evidence`，页面必须据它决定显示方式，见 §3）：

| 路径 | 含义 | 可为空 |
|---|---|---|
| `top.lppls_confidence.<scale>` | 六尺度 FCO 置信度（0–1），`<scale>` ∈ 2-4w / 1-3m / 3-6m / 6-12m / 12-24m / 2-6y；`scale_evidence` 给每档等级 | 是（未计算 null） |
| `top.indicators.<scale>` | 各档 pos/neg、合格拟合数、过滤集通过数 | 是 |
| `top.combo.p0.1 / p1 / p10` | Combo 幂平均（公开公式，p 可前端重算） | 是 |
| `top.tc_distribution.<scale>` | t_c 分布分位（交易日，相对 as-of） | 是 |
| `top.scenarios[]` | t_c 情景簇 `{share, dt_range, ahead_mean, ahead_sd, q20, q80}`；`scenarios_note` | 空数组 |
| `top.scale_windows[]` / `top.window` | 顶部时间**区间**（情景 q20–q80），无精确日期 | `window.start` null 表示无情景 |
| `top.bubble` | 当前泡沫：`start`（FCO 起点 t1）、`duration_days`、`size_realized`、`size_model`、`t1_qualified_standard`、`signal_status` | 是 |
| `top.p20` | GSADF/p20，`evidence=fail_i_iii`（不显示数值） | 是 |
| `top.trust` | DS Trust（bootstrap 稳定性） | 是 |
| `top.negative_bubble` | 负泡沫状态，仅 `signal_status`，不预测底部 | — |
| `top.invalidation` | 失效规则文字，`evidence=rule` | — |
| `top.signal_status` | `signal` / `no_qualified_fit` / `t1_not_qualified` | — |
| `top.drawdown_price` | **P1 顶后价格带**（下表） | — |
| `top.drawdown_time`、`top.second_wave` | 恒为 `{value:null, evidence:none}`，显示"无有效预测" | — |

`top.drawdown_price`（描述性，不是预测；全部按记录自身 `asof` 计算，回放不含未来事件）：

| 路径 | 含义 |
|---|---|
| `value` | 恒为 null（没有目标价） |
| `evidence` | `descriptive`；as-of 可用事件为 0 时 `none` |
| `table_asof`、`table_version` | 情景表截止日 = 记录 asof |
| `n_events`、`n_events_a` | 截至 asof 已确认的事件数（跨市场 / A 股） |
| `bucket`、`n`、`n_a_share` | 当前泡沫匹配到的桶（`全部` / `涨幅 X` / `X × 时长`）及样本数；`bucket_basis` 给匹配依据与 `t1_qualified_standard`（false 时只给 `全部`） |
| `max_dd.q20/q50/q80` | 该桶历史顶→谷回撤分位（负数） |
| `days_to_trough.q20/q50/q80` | 顶→谷交易日分位 |
| `a_share` | A 股单独分位；A 股 n<5 为 null → 显示"n<5 不显示" |
| `table.all / by_run_up / by_duration / by_run_up_x_duration` | 整张桶表（每格 `n, n_a, max_dd, days_to_trough, a_share`），供画表 |
| `valuation_floor` | 估值地板：`n`（底部样本）、`trough_pe{q20,q50,q80}`、`pe_latest`、`pe_date`（as-of 可用、1 个月发布滞后）、`close_ref`、`close_date`、`floor_band_points[q20,q50]`、`band_points`、`rule`；`evidence=none` + `note` 表示不给（深证、创业板：PE 口径与价格指数不一致；底部样本 <3） |

`bottom` 价格层对象（均只使用不晚于记录 `asof` 的数据；不含模型、预测或目标价）：

| 路径 | 含义与显示规则 |
|---|---|
| `bottom.cheap` | `evidence=descriptive`。`dd_now` 为当前收盘相对近 500 个交易日最高收盘的回撤，`peak_date`/`peak_close` 标记该高点；`dd_rank.all{pct,n}` 为截至 as-of 的 P1 已确认顶→谷事件中，回撤比当前更浅的比例与样本数；`a_share{pct,n}` 在 A 股样本 `n<5` 时为 null。`pe_pct{value,n_months,pe_date}` 为最近 120 个月中、按 1 个月发布滞后可用 PE 的经验分位（至少 36 个月）；口径不一致的指数给 null 和说明。`floor_ref` 指向 `top.drawdown_price.valuation_floor`，不复制地板带。数字旁必须显示对应 `n` 和“历史分位，不是预测”。 |
| `bottom.confirm` | `evidence=rule`。LT 状态机：`state`、参考日/收盘；熊市附 `peak_date`、`peak_close`、`rebound_from_low`、`threshold`、`confirmed=false`；已有确认熊市低点的牛市附 `last_trough_date`、`last_trough_close`、`confirmed_date`、`confirmed=true`。状态与反弹/阈值只能作为事实，标注“规则状态，滞后确认，不是预测”。 |
| `bottom.rebound` | `evidence=descriptive`（`n=0` 时为 `none`）。每个 LT 顶→谷事件按谷后完整 250 个交易日窗口计算：`recovery=(close_H-close_T)/(close_P-close_T)` 为主指标，可超过 1；另有 `recovery_log=ln(close_H/close_T)/ln(close_P/close_T)`、`rebound_ret=close_H/close_T-1`、`back_to_peak`（窗口最高收盘是否达到顶价）和 `days_to_peak`（首次达到顶价的交易日数，未达到为 null）。分布含 `recovery{q20,q50,q80}`、`recovery_log{q20,q50,q80}`、`rebound_ret{q20,q50,q80}`、`back_to_peak_share`（比例）及 `days_to_high{q20,q50,q80}`；`a_share` 同结构，样本 `n<5` 时为 null。符合条件时 `current` 含 `recovery_now`、`recovery_log_now`、`rebound_ret_now` 等值，`rank_pct` 始终按价格恢复比例计算。所有描述性数字旁必须显示对应 `n` 和“历史分位，不是预测”。 |

口径：主指标为价格回撤比例（技术分析 retracement 约定，ESWA 2021 / Shanaev–Gibson 2022；无预测力证据，ESWA 2021 三市场 Fibonacci 位与随机位无差异）；对数比例与反弹涨幅对应学术常用对数收益口径（MMS 2012、Goetzmann–Kim 2018、Bec et al. 2015 反弹与深度成正比）；回前高比例对应 Patel–Sarkar 1998 恢复定义。

## 3. 证据等级与显示规则

`evidence` 取值（`web/dashboard.html` 的 `EV` 表）：`dev` 开发段 · `cal` 校准段 · `test` 最终测试 · `none` 无证据 · `rule` 规则非预测 · `dev_failed` · `dev_only` · `fail_i_iii` · `fail_i` · `cal_fragile` · `descriptive` · `dev_pending` · `pending_cal` · `pending_test`。

- `none` / `fail*` / `dev_failed` / `dev_only`：**不显示裸数字**；显示状态文字（"无证据"、"开发段有信号·校准/测试未通过"等）。
- `descriptive`：显示数字时必须同屏显示 `n` 和"历史分位，不是预测"。
- `rule`：只显示规则文字。
- 任何卡不得合成新的分数或概率；后端没有的字段前端不得自己算（含后端请求失败时的"内置引擎"回退——失败就显示"数据未加载"）。

## 4. 禁止项

不显示、不新增、不在适配层合成：`bubbleScore`、`bubbleMultiScaleScore`、`bubbleProgress`、`tcOffset`、t_c 概率密度、精确顶部日期、目标价（`drawdown_price.value` 恒 null）、趋势/动量指标（只作研究对照基线，不进页面）。

## 5. 适配层约定

- 外部前端代码放 `frontend/`，只改该目录；后端只改 `research/`、`web/mock/data/`、`docs/`。
- 前端所有数据访问经 `frontend/app/lppl-data.js`：`loadSymbol(sym)`、`loadPriceLayer()`、`loadCatalog()` 从 `lab/mock/data/` 的静态 JSON 加载；页面组件不得直接 fetch 路径。
- 后端字段改动先改 `docs/product_contract.md` 与本文，再改 JSON；前端字段改名在适配层做。
- 示例：`web/mock/data/sh000001_latest.json`（最新）、`sh000001_2015-06-12.json`（回放，含 movie）。

## 6. 市场背景 market_latest.json

`web/mock/data/market/market_latest.json` 与 `market_<date>.json` 是描述性市场背景，不参与 LPPLS 拟合、报警或任何模型。每个来源独立记录 `url_host`、`fetched_at`、`ok` 和可选 `error`；单源失败时该节数据为空或为 null，其他来源仍写入。

| 路径 | 内容与单位 |
|---|---|
| `board_flow.industry / concept / region[]` | 东财行业、概念、地域板块；资金流列为人民币元，涨跌幅和资金流占比为百分数。包含当日、5 日、10 日口径；东财订单规模分类资金流是估算值，不是交易所官方数据。每日原始快照另存 `data/market/board_flow/<date>.csv.gz`，固定 15 列。 |
| `board_flow.history_sample` | 一个行业板块的日度历史样本；`date`、主力及超大/大/中/小单净额，单位人民币元。字段顺序以 `f51` 日期、`f52` 主力、`f53` 小单、`f54` 中单、`f55` 大单、`f56` 超大单解析；仅用于描述。 |
| `limit_pools` | 涨停 (`zt`)、炸板 (`zb`)、跌停 (`dt`) 数量；`break_rate=zb/(zt+zb)` 为比例；连板梯度与前 20 项包含代码、名称、连板数/时间。 |
| `northbound.data` | `sse_nb_turnover`、`szse_nb_turnover`、`sse_nb_trades`、`szse_nb_trades` 及 ETF 成交额；成交额保留 HKEX 原值、不缩放。2024-08 起北向数据不含买入、卖出或净额，不得称为“净流入”。缺少当日 HKEX 文件时为 null。 |
| `valuation.indices.<code>` | 中证指数 `000300`、`000905`、`000016`、`000852` 最新日期、PE1、PE2、股息率 DY1/DY2，以及文件历史可用时的滚动 10 年 PE1 分位。PE 倍数为倍，股息率为百分数。 |
| `margin.data` | 用 `research/data/margin.py` 的上交所/深交所官方 fetcher 刷新近期数据；`fin_balance_sse`、`fin_balance_szse`、`fin_balance_all` 和变化值统一为人民币元。包含 `latest_date`、T+1 `available_date`、`stale`（距 asof 超过 5 个交易日为 true）。刷新失败、stale 或 SZSE/SSE 融资余额比率超出 `[0.3, 3]` 时 `sources.margin.ok=false`，仍展示可用数据。 |

所有市场背景数值均带 `evidence: "descriptive"`；只能作为事实展示，不得转成预测、目标价或报警信号。

## 7. 独立 market-context.v1 快照

P1 的全市场背景读取与个股 Worker `/market` 分离。`workers/market-context` 只读取已封存的日终快照，前端不得直接跨域抓取上游源。

顶层必须包含：

| 字段 | 约束 |
| --- | --- |
| `schema_version` | 固定为 `market-context.v1` |
| `kind` / `snapshot_kind` | `market_context` / `eod` |
| `asof` | 实际封存交易日；不得把抓取日期当数据日 |
| `requested_at` / `generated_at` | 请求和生成时间分开保存 |
| `status` | `fresh`、`partial`、`stale`、`failed` 之一 |
| `stale_reason` / `last_good_asof` | 刷新失败时保留上一份证据并说明原因 |
| `evidence` | 固定为 `descriptive`，不进入 LPPLS |
| `snapshot_sha256` | 对快照内容做稳定哈希 |

每个 `sources.<source_id>` 至少包含 `source_id`、`source_url` 或 `url_host`、`fetched_at`、`status`、`stale_reason`、`raw_sha256`、`license_tier` 和 `error`；保留旧的 `ok` 字段以兼容 `market_latest.json`。

`limit_pools.reasons`、`limit_pools.topics` 和 `history.progression` 在来源没有提供时必须是 `status: "not_available"`、`rows: []`，不能使用 0 表示没有原因、题材或晋级。`history.progression` 若可用，行字段必须包含 `from_streak`、`to_streak`、`eligible_count`、`advanced_count`、`rate`、`asof` 和 `window`。

接口只允许读取对应日期的快照：`GET /context?date=latest|YYYY-MM-DD`、`GET /context/snapshot?date=YYYY-MM-DD`；没有该日期时返回 `CONTEXT_NOT_READY`，不能回退到当前数据。刷新由受保护的 `POST /context/refresh` 异步创建任务并返回 `job_id`，状态通过 `GET /context/status?job_id=...` 读取。
