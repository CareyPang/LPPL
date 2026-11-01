# 前端数据契约（Open Design 交接）

目的：外部前端（Open Design，目录 `frontend/`）只通过本文列出的静态 JSON 与后端对接。后端不提供 API 服务（规划 2027-H2），仓库数据源位于 `web/mock/data/`，GitHub Pages 发布路径为 `lab/mock/data/`（例如 `https://careypang.github.io/LPPL/lab/mock/data/…`）。字段含义以 `docs/product_contract.md` 和 `research/eval/export_contract.py` 为准，本文只是索引；字段改名放在前端适配层，后端 JSON 不为前端改名。

## 1. 文件清单

| 路径（相对站点根） | 内容 | 生成者 | 更新 |
|---|---|---|---|
| `lab/mock/data/<sym>_latest.json` | 单指数最新契约（6 个：sh000001 上证、sh000016 上证50、sh000300 沪深300、sh000905 中证500、sz399001 深证成指、sz399006 创业板指） | `research/pipeline/daily.py` → `build_record` | 日更（`scripts/daily_update.sh`） |
| `lab/mock/data/sh000001_<date>.json` | 开发段回放（2007-10-12、2015-06-12），同结构，多一个 `movie` 帧数组 | `research/eval/export_contract.py` | 不更新 |
| `lab/mock/data/price_layer/drawdown_table.json` | P1 全样本情景表（报告用；页面**不要**直接读它，读记录内的 `top.drawdown_price`） | `research/price_layer/drawdown_table.py` | 随冻结数据重生成 |
| `lab/mock/data/catalog.json`、`stock_names.json` | 资产目录（316 标的：代码、名称、交易所、板块、所属指数） | 日更脚本 | 日更 |
| `lab/mock/data/universe_*.json` | 指数成分（当前 / 历史 PIT） | 日更脚本 | 日更 |
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
