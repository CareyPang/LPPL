# Open Design 前端 ↔ LPPL 后端字段映射（v1，基于 frontend-for-LPPL.zip）

## 0. 总结论

导出包不是"套在我们后端上的界面"，而是一套**自带的第二模型**：`engine.js` + `critical.js` + `fco-core.js`（自己的 38 窗口 LPPLS、比原文放宽的过滤、t_c 聚类、阶段机、底部 6 项、交易模拟），外加用这套模型预算的快照 `fco-snapshot.js`、`tape-snapshot.js`、`data-snapshot.js`（东方财富 2026-10-23）。`docs/api-contract.md` 描述的是 `CP.run` 的输出，不是我们的契约。

所以大部分字段不是"改名"问题，而是**换数据源 + 删掉后端没有证据的卡**。
（实测：代码里没有 `tcOffset`、`bubbleScore`、`bubbleProgress` 字样；`fco-core.js` 定义了 `tcDensity` 但页面未调用。违规点见 §3。）

标记：**✅ 有对应**（适配层改名）· **🟡 部分对应**（含义不同，按我们的口径显示）· **🔵 后端待补**（纯数据，不新增模型，我来补）· **❌ 删除**（后端没有、按规则不能显示）

## 1. 字段映射（index.html / tv.html / mobile.html / ui.js 实际读取的字段）

| OD 字段 | OD 含义 | 我们的字段 | 处理 |
|---|---|---|---|
| `sym.label / code / isIndex / market` | 标的 | `symbol`、`name`；`catalog.json`（代码、名称、交易所、板块） | ✅ |
| `asof`、`latest` | 截止日 | `asof`；`latest` = 文件是 `<sym>_latest.json` | ✅ |
| `data.source / name / fetchError` | 数据来源 | `data_version`、`model_version` | ✅ |
| `bars[{date,open,high,low,close,volume}]`（含 T 之后） | K 线 | `price_history{dates[], close[]}`，近 756 日，**只到 as-of**，无 OHLV | 🔵 补 open/high/low/volume；T 之后的价格不提供（回放页用 `validation` 与回放文件） |
| `T`（下标） | 截止下标 | 无，用日期 | ✅ 适配层用 `dates.length-1` |
| `scan.total / nq / conf`（38 窗口单一尺度） | 窗口一致度 | `top.lppls_confidence.<6 档>` + `scale_evidence`；`top.indicators.<档>`（合格拟合数） | 🟡 换成六尺度显示 |
| `scan.fits[]` | 每窗口拟合参数 | `top.scenarios[].representative`（t1/t2/tc/m/ω/阻尼/振荡/曲线） | 🟡 只给每个情景的代表拟合 |
| `scan.clusters`、`rm.topW / altW`（t_c 聚类窗口，lo/hi 日期） | 见顶窗口 | `top.window{start,end,rule,evidence}`；`top.scenarios[]{share, q20_date, q80_date, q025_date, q975_date}`；`top.scale_windows[]` | 🟡 topW→`window`，altW→`scenarios[1]`，`conf`→`share`；不显示 `midDate`/`tc_mode_date` 当作单点日期 |
| `rm.level`（none/low/mid/high，阈 0.15/0.3） | 警报等级 | 无；有 `top.signal_status` + 证据徽章 | ❌ 删除自定阈值；显示 `signal_status` |
| `rm.topPx`（窗口中点 1σ 价格区间） | 见顶价位 | 无（契约禁止目标价） | ❌ |
| `rm.crash.depth/days`（q25/50/75，自身 zigzag） | 回落幅度/时间 | `top.drawdown_price.max_dd / days_to_trough`（q20/50/80）+ `n`、`bucket`、`a_share` | 🟡 改用我们的分位与 n，标"历史分位，不是预测" |
| `rm.crash.pxHi / pxLo / pxMid`、`botLoDate / botHiDate` | 回落价格区 / 底部日期 | `drawdown_price.valuation_floor.floor_band_points`（PE 地板带，仅上证/上证50/沪深300/中证500） | 🟡 价格区只能显示估值地板带；**底部日期删除**；前端不得用 max_dd×价格自己算点位 |
| `rm.crash.rebound`、`crash.wave2`（二波参考价） | 二波 | `top.second_wave{value:null, evidence:none}` | ❌ 显示"无有效预测"（W 卡未做） |
| `rm.stats.legs[]` | 历史回撤样本 | `drawdown_price.table`（按涨幅/时长分桶，每格 n、分位） | 🟡 画桶表，不画单条 legs |
| `rm.wellsBelow`（价格井） | 支撑位 | 研究层有，未进契约、无证据 | ❌ |
| `rm.sigma / hi60 / close` | 波动、60 日高 | `price_history` 可直接读收盘 | ✅ 只作图表辅助，不作信号 |
| `phase.k`（acc/accel/crit/crash/base/wave2） | 阶段机 | `regime_band{month,state,channel,rule}`（FCO 公开体制带，描述性）+ `top.signal_status` | ❌ 删阶段机；显示体制带 |
| `chk`（底部 6 项检查、pass） | 抄底条件 | `bottom.state_p / thrust_p`（`fail_i`，不显示）、`bottom.entry_rule`（`none`） | ❌ 显示"底部模型三段未通过 / 无证据"（B 卡做完后再接） |
| `tape[[T,total,nq,c0,c1]]` | 历史信号带 | 无 | 🔵 补 `<sym>_history.json`（每周 as-of 六档置信度 + 窗口，现有扫描导出，不新增模型） |
| `replay.peak / bottom / wave2 / topHit / firstSig` | 事后打分 | `validation[]{split,events,hit,false_alarm,brier,status,note}`；`sh000001_2007-10-12.json` / `_2015-06-12.json`（含 `movie`） | 🟡 回放只开放这两个日期；成绩用 `validation` |
| `replay.sim`（按计划操作净值、acts、ret vs bh、`CP.RULES`） | 交易策略回测 | 无（执行规则只有 dev_only 探索） | ❌ |
| `evalr.recall / precision / randPrecision / medErr` | 命中评估 | `validation[]` + `evidence_levels` | 🟡 |
| `/bench`、`CP.indexBench()`（s16/s19/s24 收益对比） | 策略收益 | 无 | ❌ |
| `/symbols?q=` | 搜索 | `catalog.json`（316 标的，前端本地过滤） | ✅ |
| `/health`、`ping()` | 健康检查 | 静态站无 | ❌ 或改为"数据日期 = asof" |

## 2. home.html

| OD 字段 | 我们的字段 | 处理 |
|---|---|---|
| `FCO_SNAP` 三尺度 s/m/l（7 窗口/档，自己的筛选） | `top.lppls_confidence` 六档（2-4w…2-6y） | 🟡 换成六档 |
| `FC.conf().comboTop / comboBot`（"本站合成规则，未校准"） | `top.combo["p0.1"/"p1"/"p10"]`（公开幂平均） | ❌ 删自定 combo，用我们的 |
| 负泡沫 `bot` 置信度 | `top.negative_bubble.signal_status`（只回放契约有数值） | 🟡 |
| 三大指数 | 我们 6 个 A 股指数 | ✅ |

## 3. 必须删的文件和代码

- `app/engine.js`、`app/critical.js`、`app/fco-core.js`：前端模型，全部移除（含 `api.js` 的 `fallback` 回退到 `CP.run`）。
- `app/fco-snapshot.js`、`app/tape-snapshot.js`、`app/data-snapshot.js`：第二模型的输出与另一份行情，移除。
- 所有"按计划操作 / 净值 / 跑赢持有"、`topPx`、二波价、底部日期、阶段标签、`level` 阈值。
- `review.html`（V2588 框架评审）是静态文档，不读数据；建议不放进产品导航。
- `assets/` 解压 50 MB：只留页面实际用到的那组帧。

## 4. 接入方式

1. 我在 `frontend/app/lppl-data.js` 写适配层（Devin 维护，Open Design 不改），提供：
   `loadSymbol(sym)`、`loadReplay(sym, date)`、`loadCatalog()`、`loadHistory(sym)`；返回我们 JSON 原样 + 少量派生（`latest`、`dates`），不计算任何模型值。
2. `api.js` 静态模式只调用这个适配层；失败显示"数据未加载"。
3. Open Design 按 §1 的 ✅/🟡 重做卡片，❌ 的卡删掉或换成"无证据"状态卡；显示规则见 `docs/frontend_contract.md` §3。
4. 我同时补 🔵 两项：`price_history` 加 OHLCV、`<sym>_history.json` 历史时间轴。
