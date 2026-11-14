# 临界点 2.0 · 整个项目完整详细方案（2026-11-02 v1）

> 本文件是**唯一入口**：项目目标 → 架构 → 每一层怎么做/怎么验 → 当前进度（带 PR 与文件路径）→ 后续路线与验收 → 待你拍板 → 换电脑继续。
> 下钻文档：战略规划 `docs/strategic_roadmap.md`、Web 应用规划与交接 `docs/webapp_master_plan.md`、时间层/价格层深化 `docs/time_price_layer_plan.md`、产品契约 `docs/product_contract.md` + `docs/frontend_contract.md`、预登记 `docs/preregistration*.md`、冻结规则 `docs/dev_freeze.md`。

---

## 0. 目标与边界

**目标**：做一个完整的泡沫预测 Web 应用。用户输入 A 股代码（指数或个股），系统自动取数、拟合、回测，输出：
1. 现在是不是泡沫、处在哪一段、风险几级（时间层）；
2. 见顶后大概跌多深、跌到哪个价格带、怎么分批减仓（价格层·顶后）；
3. 跌下来够不够便宜、是否已经止跌、怎么分批买（价格层·底）；
4. 二波反弹大概能收复多少、何时退出（价格层·二波）；
5. 这些结论在历史上准不准：命中率、虚警率、随机对照、样本数 n、证据等级（成绩单）。

**三条不变的原则**
- 只给**区间、概率等级、历史频率**，不给精确顶/底日期，不给目标价。`t_c` 是理论临界时间，不是顶部日期；"顶"是一段**顶区**（收盘价在峰值 3% 以内的那段），不是单日最高点。
- 任何规则进产品前：先预登记 → 冻结数据与参数 → 在从没用过的样本上一次性评价；失败就标失败，不换口径重讲。
- 每个数字都带证据等级 `evidence ∈ {replicated_oos, single_oos, dev_only, descriptive, research_candidate, none, fail}` 和 n；`none/fail` 只显示"无证据"。

**实话（当前证据）**
| 问题 | 现在的答案 | 依据 |
|---|---|---|
| 能否提前报警泡沫顶 | 开发段 50% 的顶被提前报警，但 70% 报警是虚警；剔除 2007/2015 后 A1 从 0.30 掉到 0.08；校准段、测试段未通过 → `dev_only` | `reports/by_year_lppls_v2_top.md`、`reports/final_test_2022_2025.md` |
| 顶部能否精确到一周 | 不能。t_c 聚类紧时顶区 ±5 日命中 11.1%，随机对照 10.0% | `reports/tc_cluster_dev.md`（PR #22） |
| 能否预测跌幅 | 不能给点值；24 月涨幅/加速度能把回撤分位区间收窄一点（样本外 q0.2 pinball 0.87–0.92），估值/两融不行 | `reports/price_layer/dd_conditioning_explore.md` |
| 能否预测底部 | 不能给日期；只能"便宜层（分位）+ 止跌层（事后确认，滞后 10–15%）" | `docs/literature_price_layer.md` |

**根本约束**：A 股 2000–2025 只有 2001/2007/2015 三次"加速翻倍后崩"。所以"更有效"的主路径是**加独立事件数**（外部市场、1990 年代 A 股、成分股横截面、前瞻日志）+ **事件级评价口径**，而不是在这三次上换拟合技巧。

---

## 1. 总体架构

```
数据层 research/data/          PIT 冻结（A 股 6 指数 + 外部 4 指数）、个股后复权、两融/估值/北向/资金流
   ↓
研究层 research/lppls/ eval/   LPPLS 拟合（六尺度×多窗口）、Confidence、Trust、R2 GSADF、三段评价、随机对照
   ↓
价格层 research/price_layer/   回撤情景表、估值地板、B 卡（便宜/止跌）、W 卡（收复比例）
   ↓
流水线 research/pipeline/      daily.py（指数日更）、stock.py（个股按需）、stock_batch.py（夜间预算库）、forward_log.py
   ↓
契约 docs/product_contract.md  每个标的一个 JSON：web/mock/data/<sym>_latest.json、stock/<code>.json、breadth_<idx>.json
   ↓
发布 GitHub Actions + Pages    main → Pages；stock_query / stock_nightly → stock-results 分支 → 叠加到 Pages
   ↓
前端 frontend/（Open Design）  主页 / 终端 / 回测页；所有数据只经 frontend/app/lppl-data.js 读取；/lab/ 旧版工作台
```

**后端选型（已定）**：拉取式，不备案。
- 一期（已做，PR #25/#27）：GitHub Actions 当计算机。用户在页面输入代码 → 跳 Actions 的 Run workflow → 约 1–3 分钟后结果出现在 Pages。零服务器、零备案。
- 二期（可选）：腾讯云大陆机做 worker，只出站拉任务（Cloudflare Worker + KV 做公网入口、HTTPS、限流），算完推回 GitHub/COS。服务器不开端口，不需要备案。
- 三期（可选）：要秒级实时再做 FastAPI 直连（需要域名 + 备案，或香港地域）。

---

## 2. 数据层

| 数据 | 来源（skill） | 口径 | 状态 |
|---|---|---|---|
| A 股 6 指数日线 | 腾讯为主，新浪/东财备用（a-stock-data） | PIT 冻结 + sha256，`data/frozen/` | 完成 |
| 外部 4 指数（恒生/标普500/纳指100/日经225） | Yahoo（global-stock-data） | 1990 起冻结，只冻结不评价 | 完成（PR #10） |
| 个股日线 | 腾讯 fqkline → 失败回退 kline/kline 原始价 × 新浪后复权因子 | **后复权**；剔除当天未收盘 bar；停牌/退市按参考交易日历识别 | 完成（PR #23） |
| 指数成分 | 中证/交易所 | PIT 快照 `web/mock/data/universe_*.json` | 沪深300 完成，中证500 待加 |
| 两融、PE/PB、北向、涨停池、板块资金流 | a-stock-data | descriptive，不进模型；两融深交所单位已修 | 完成（PR #24），东财板块接口待工作日复测 |
| 1990 年代 A 股（上证/深成指 1991–1999） | a-stock-data | 先冻结+核验（1996-12 涨跌停、1995 T+1） | **下一步** |
| 研究扫描结果（3.8 GB） | 本机生成 | GitHub Release `research-data-v20261101` | 完成 |

**易错点**：盘中跑批会用到未收盘 K 线（已发生过一次，整批作废）；前复权会被未来分红改写历史（所以用后复权）；退市股不剔除会产生幸存者偏差；同一批截止日不一致会让横截面统计失真（PR #27 修）。

---

## 3. 时间层（泡沫在哪一段、风险窗口在哪）

### 3.1 拟合什么
- **拟合对象**：对数价格的 LPPLS（Filimonov–Sornette 2013 线性化：4 个线性参数解析求解，m/ω/t_c 三个非线性参数数值优化），v2 参数框。
- **多窗口**：六个尺度 2–4 周 / 1–3 月 / 3–6 月 / 6–12 月 / 12–24 月 / 2–6 年，每个尺度多个起点 t1；指数日更 189 窗，个股 `stk_lite` 16 窗。
- **产品输出**：每尺度的 Confidence（合格窗口比例，FCO 过滤集 box/END/STANDARD）、Trust（残差 bootstrap 100 次的稳定性，只衡量"结构对噪声是否敏感"，不是命中率）、t_c 情景区间（只显示起止，个股不显示）。
- **概率模块**：R2 BSADF/PSY 给逐日"未来 H 日见顶"概率（测试段 Brier 略好于基率，但留出 4 个指数翻转 → 不显示）。

### 3.2 拟合怎样更有效（候选，每条单独登记，只在新样本上评价，只报告不选优）
| # | 改进 | 预期 | 判据 | 坑 |
|---|---|---|---|---|
| T1 | 事件级固定幅度标签（PS 15% / LT 20% 并列） | 命中/虚警不再被自适应门槛扭曲（旧标签漏掉 2001-06、2009-08、2018-01） | A1/A2 vs 循环平移，H∈{60,120} | 两套都报，不挑 |
| T2 | t1 的 Lagrange 正则化选择（Demos–Sornette 2017） | 降低起点依赖、置信度日间抖动 | A1/A2 不劣化 + 日间跳变减小 | 整条链重算 |
| T3 | 轮廓似然 / 分位回归 t_c 区间 | 有统计含义的风险窗口宽度 | 区间覆盖率 vs 朴素窗 | 区间可能宽到没用 |
| T4 | 半周期 / 整周期 oscillation 口径 | 过滤集稳健性 | 只并列报告 | — |
| T5 | 成分股广度 R8（成分股中有合格拟合的比例） | 指数报警的独立信息源；开发段 ΔBrier −0.0025 | 外部/前瞻 ΔBrier 区间上界 <0 | PIT 成分、同一截止日（PR #27 先做描述性） |
| T6 | 负泡沫置信度 vs 底标签 | 外部市场若通过，说明 A 股特殊 | 与顶部对称 | A 股 0/424 已失败 |
| T7 | 外部 4 市场同一流水线 | 事件数 ×3–4 | 每市场只跑一次 | 不得反过来调 A 股阈值 |
| T8 | 1990 年代 A 股 | 多 3 个顶（1992-05、1993-02、1997-05） | 开发段探索 | 早期数据质量 |

**不做**：Hawkes、局部 Hurst、临界慢化、Ising、波动率预警、用 t_c 聚类当顶部日期、放宽判据。

### 3.3 回测怎样更有效（口径）
1. **as-of 网格**：周度；每个 as-of 只用当时可得数据（PIT 成分、PIT 复权、未收盘 bar 剔除）。
2. **事件级计数**：一个顶只算一次命中；连续报警合并为一个"报警簇"再算虚警。
3. **对照**：循环平移随机对照（保留报警密度）、80 日块 bootstrap、留一指数 / 留一年 / 留一市场不翻转。
4. **三段冻结**：开发 2000–2018 / 校准 2019–2021 / 测试 2022-01–2025-08 各只跑一次；外部市场与 1990s 在登记时一次切分。
5. **指标**：A1（报警后 H 日内见顶的比例）、A2（顶被提前报警的比例）、Brier、log loss、ECE、PR-AUC、报警提前量分布、顶区宽度、区间覆盖率。
6. **前瞻日志**：每日签名写入 `forward_log/`，季度复盘是唯一真正的样本外；Round 2 打开条件之一是 ≥2 次季度复盘（最早 2027-04）。
7. **成绩单分组**：指数 / 行业 / 个股分开；个股一律 `research_candidate`，不借指数证据，按事件簇算置信区间，不展示"最好的股票"。

---

## 4. 价格层（跌多深、多便宜、能反弹多少、怎么分批）

### 4.1 能做到什么
没有方法能预测幅度点值。"尽可能预测"= 在**无条件经验分布**上，用少数经样本外证实的条件变量把区间收窄一点，并用覆盖率证明没有收窄过头。

### 4.2 顶后回撤（P1 → Q-DD2）
| 方法 | 输入 | 输出 | 评价 | 状态 |
|---|---|---|---|---|
| 无条件经验分布（基线） | 跨市场所有确认顶 | 顶→谷回撤 q20/50/80 + n | — | 上线（P1，PR #16） |
| 分桶情景表 | 泡沫涨幅、持续时间 | 分桶 q20/50/80 + n（A 股单桶 n<5 不显示） | 覆盖率 | 上线（P1） |
| **P-A 条件分位回归（Q-DD2 主候选）** | 24 月对数涨幅、加速度；估值/两融只作对照 | q20/50/80 | pinball vs 无条件、80% 区间覆盖率、CRPS、留一市场、块 bootstrap | 探索完成，**待登记（需你批准）** |
| P-B 尾部分布（拉伸指数/GPD） | 同上 | "跌超 X% 的概率"曲线 | 对数似然、PIT 校准 | 候选 |
| P-C 历史相似事件 | 涨幅/时长/加速度最近邻 k=5–10 | 最像的历史泡沫回撤范围 + 案例列表 | 覆盖率 | 候选（产品最直观） |
| P-D 杠杆/信贷 | 两融变化、社融 | 只作定性标注 | 不评分 | 候选 |
| 估值地板带 | 历次底部 PE/PB 分位 | 价格带 | 描述 | 上线 |

**不做**：LPPLS 参数（κ 不可识别）→ 幅度回归；波动率 → 幅度；目标价。

### 4.3 底部：便宜层 × 止跌层（B 卡，PR #21）
- 便宜层：当前回撤 vs 历史顶→谷回撤分布分位 + PE 分位。文案固定"历史分位，不是预测；n=…"。
- 止跌层：LT 15% 停时确认（底部过后上涨 15% 才确认，滞后是诚实代价）；候选第二确认 = 熊市体制（M1 跳跃模型）结束并持续 N 周。
- 评价（Round 2）：确认后 120 日不创新低比例 vs 随机；分批买入组合 MDD vs 一次性买入。
- **"便宜"≠"已止跌"**，两层分开显示。

### 4.4 二波反弹（W 卡，PR #21 → Q-W1）
- 主显示：价格收复比例 =（反弹高点 − 谷）/（顶 − 谷），100% = 回到前高；并列对数比例、谷底起涨幅、250 日内回前高比例（n=215，中位 81.6% / 84.9% / 34.2% / 39.1%）。
- Q-W1（待登记）：收复比例 ~ 回撤深度、下跌时长、下跌速度的分位回归，评价同 Q-DD2；预期深度是唯一稳定变量（Bec 等）。
- Q-W2：短档（1–3 月/3–6 月）报警在"二波子集"上的 A1/A2，回答"二波何时结束"，不回答幅度。

### 4.5 执行规则（D-TOP，`reports/dtop_dev.md`）
- 现行指南：置信度 ≥20% 减 1/3；≥50% 再减 1/3；报警确认结束前不加仓。
- 开发段保留候选：`d3_vt_x_linear_to0`（回撤改善 28.5pp，vs 波动率目标 +5.7pp [2.5, 6.7]）等 4 条，需外部市场 + 前瞻日志复核后才写进指南。

---

## 5. 个股引擎（PR #23；数学审计与研究方案见 PR #28）
- 数学/数值审计：`reports/stock_math_audit.md`（F1 `grid_profile` 窗内 t_c、F2 `_to_cal` 已修，§20 偏离登记，`MODEL_VERSION=prereg_v1.7_v2.1`）。文献：`docs/literature_stock_math.md`（两批共 63 篇全文）。
- **研究方案**：`docs/research_plan_stock_math.md`（WP0 基线收尾 → WP1 零假设误报率标定 → WP2 t_c 区间/Trust → WP3 = Q-STK1 执行计划 → WP4 广度 → WP5 尾部层草案 → WP6 背景层；个股维持 `research_candidate`，任何 WP 运行前不改判据）。
- 接口：`predict(code6, variant, asof)` 当前预测（秒级）；`history(code6, weeks)` 近 2 年周度回放（首次 3–4.5 分钟，缓存后 5–10 秒）。
- 规则：上市满 500 交易日；剔除上市首 60 日；停牌不插值；一字板比例 >20% 标 degenerate；退市/长期停牌 `in_stats=false`。
- 缓存键 `(code, asof, variant, data_version, code_version)` → `data/stock/<code>/<variant>/fits.parquet`，已有键永不重算。
- 显示：个股 `research_candidate`，不显示置信度数值和 t_c 日期，只显示"有/无合格拟合"。
- 实测（8 核）：取数 9–26 秒 + 轻量拟合 3–4.5 秒；GitHub Actions 端到端约 34 秒。

## 6. 发布与计算（PR #25、#27）
| 工作流 | 触发 | 做什么 | 产出 |
|---|---|---|---|
| `daily_update.sh` | 日更 Automation | 6 指数契约 + 前瞻日志 | `web/mock/data/*_latest.json`、`forward_log/` |
| `stock_query.yml` | 手动（页面链接） | 单只代码 predict + history | `stock-results` 分支 `stock/<code>.json` |
| `stock_nightly.yml` | 工作日 17:40 北京时间 | 沪深300 同一截止日、6 分片并行；生成成分股广度 | `stock/<code>.json`、`breadth_sh000300.json` |
| `pages.yml` | main 更新 / 上述完成后 | `scripts/build_site.sh` 叠加 stock-results | Pages 站点 |

缓存分层：浏览器内存 → Pages 静态 JSON → 拟合 parquet。结果分支与 main 分开，main 不被数据提交污染。

## 7. 前端（Open Design，`frontend/`）
- 页面：主页（PR #26 海洋视频，草稿）、终端（六尺度、情景、Movie）、回测页（PR #20）、个股页（/lab/stock.html，PR #25/#27）、教育页。
- 硬规则（`frontend/AGENTS.md`）：数据只经 `lppl-data.js`；不在前端重算 LPPLS；`drawdown_price.value` 恒为 null；不显示 bubbleScore/tcOffset/t_c 密度；descriptive 必带 n 和"不是预测"；视觉改动必须浏览器验证。
- 待做：正式个股页（把 /lab/ 的个股卡迁到 Open Design 终端）、市场基础信息页（行业资金流热力图、北向、两融、估值热力图、广度），prompt 在 `docs/od_prompt_stock_market.md`。

## 8. 治理与成绩单
- 流程：预登记 → 冻结 → 一次性评价 → `docs/evidence_table.md` 登记 → 契约 badge。
- 写进用户指南的规则必须有开发段 + 至少一个独立样本（外部市场或前瞻日志）证据。
- 前瞻日志扩容：6 指数 → 约 30 标的（行业、外部指数），两年内报警事件 ×5，2028-H1 第一次有统计意义的样本外结论。

---

## 9. 当前进度（2026-11-04）

| 阶段 | 内容 | 状态 | PR / 路径 |
|---|---|---|---|
| 研究层 0–3 | 数据 PIT、LPPLS 核心、三段评价、前瞻日志 | 已合并 | #1 #3 #4 #6 #8 |
| 外部数据 | 恒生/标普/纳指/日经冻结 | 已合并 | #10 |
| 价格层 P1 | 回撤情景表 + 估值地板 | 已合并 | #16，`research/price_layer/` |
| 价格层 B/W | 便宜层、LT 确认、收复比例 4 列 | 已合并 | #21 |
| 文献 | 价格层四问、回撤条件变量 | 已合并 | #18，`docs/literature_price_layer.md` |
| 前端 | Open Design 主页/终端/回测页、FCO 补全 | 已合并 | #11 #14 #15 #17 #19 #20 |
| A 规划 | 总规划、交接、t_c 聚类探索、时间/价格层方案、**本文件** | 待合并 | #22，`docs/` |
| B 个股引擎 | 后复权、PIT、未收盘剔除、停牌/退市、备用接口 | 待合并，CI 绿 | #23，`research/pipeline/stock.py` |
| C 市场背景数据 | 两融/北向/估值/涨停池/板块资金流 | 待合并，CI 绿 | #24，`research/data/market_base.py`、`research/data/margin.py` |
| D 按需计算 | Actions → stock-results → Pages；/lab/ 个股页 | 待合并，CI 绿 | #25，`.github/workflows/stock_query.yml` |
| E 夜间预算库 | 固定截止日、分片、成分股广度 | 待合并，CI 绿 | #27，`research/pipeline/stock_batch.py`、`.github/workflows/stock_nightly.yml` |
| 你的主页改动 | 海洋视频、首屏、可读性 | 草稿，待你决定 | #26，`frontend/home.html`、`frontend/assets/ocean/` |
| 沪深300 预算 | 300/300，298 可统计；截止日不一致 | 待 #27 合并后重跑 | 未发布 |
| F 个股数学审计 + 文献 + 研究方案 | F1/F2 修复、§20 偏离登记、63 篇文献、WP0–WP6 方案 | 已合并 | #28，`reports/stock_math_audit.md`、`docs/research_plan_stock_math.md` |
| G WP0 收尾 + WP1 零假设标定 | 撞边界比例字段、2–4 周档 display_only、展示日历交易日外推；六类零假设 × 六档 × 过滤集误报率表 | 待合并 | `reports/null_calibration_stock.md`、`scripts/audit_stock_math/exp7_null_calibration.py` |
| H 开发段 `_g2` 对照 + §21 (a)(b) 合成标定 + (c)(d)(e) 开发段 | `_g2` 重扫 6 指数（§19.1 结论不变）；Q2 0/24 可容许、MPL 覆盖 0.70/0.60、Ising 主链上界 +0.0097、价格层三项区间含 0 → **a/b/d/e 全部未通过**；1990s 冻结 `a90s_v20261104` | 已合并 | #38，`reports/sensitivity_dev_v2_g2.md`、`reports/q2_calibration.md`、`reports/mpl_calibration.md`、`reports/ising_dev_2010_2018.md`、`reports/price_layer_e_dev.md` |
| I §21.7/§21.8 登记 + 冻结修正版 | a–e 负面结果登记（不改判据）；`v20261104` 只替换 ≤2000 段、默认仍 `v20261024` | 已合并 | `44f0140`，`docs/preregistration.md` §21.7–21.8、`data/frozen/v20261104/` |
| J `v20261024` 缺陷标注 | sh000001 1990–92 段/sz399001 1995 错位写进 README，指向 a90s/v20261104 | 待合并 | 本 PR，`data/frozen/v20261024/README.md` |

合并顺序：#22 → #23 → #24 → #25 → #27（每合一个，把下一个的 base 改回 main）。

| K §22 Q3 + `_g3` 开发段 | Q3 合成门通过（box/α=0.10/无 f*，§22.2.1）；`_g3` 登记 §20.1；开发段重扫开关与四臂评价脚本；§22.3.1 门结果产出前写定 | 待合并；开发段重扫本机进行中 | #55，`reports/q3_calibration.md`、`scripts/audit_stock_math/exp18_dev_eval.py` |
| L Phase 0–4 精度计划 | 尺子、优化器、聚合、逃顶价格、抄底分型、底部链、日志硬化（总表） | 待合并 | #54，`reports/precision_program_summary.md` |
| M 前瞻日志定时封存 | `forward_log_seal.yml` 工作日封存并提交 main | 待合并（合并前 ledger 停在 2026-10-30） | #69 |

**2026-11-14 起的执行级计划（每步事先写死成功标准）见 `docs/plan_continuation_2026_11.md`。**

## 10. 后续路线（每步一个 PR，PR 上留评论写做了什么、路径、下一步）

| 序 | 时间 | 内容 | 验收 | 需要你 |
|---|---|---|---|---|
| 1 | 现在 | 合并 #22–#25、#27；手动跑一次 stock_query（600519） | 线上 `/lab/stock.html?code=600519` 出结果 | 说"合并" |
| 2 | 合并后当天 | 手动跑一次 stock_nightly | `breadth_sh000300.json` 的 `asof_consistent=true`、`n_missing=0` | — |
| 3 | ~~本周~~ 已完成（#38） | 冻结 1990s A 股（只冻结+核验） | `data/frozen/a90s_v20261104/` + sha256；§21.0 下只在确认阶段读取，本轮无模块进入确认，仍未评价 | — |
| 3b | 2026-11/12（WP0/WP1 已合并 #30；WP2 的 MPL 区间与 §21 a/b/d/e 已在 #38 得出负面结论，再试须新登记） | 个股研究方案 WP0–WP2（`docs/research_plan_stock_math.md`）：零假设误报率表、t_c 区间校准 | `reports/null_calibration_stock.md`、`reports/tc_interval_calibration.md` | 批准 Q-STK1 登记文本修订（λ_t、市值分层、Holm） |
| 4 | 本周 | 写 Q-DD2 / Q-W1 预登记（变量、目标、基线、指标、切分写死） | `docs/preregistration_price_layer.md` | **批准登记后一次性运行** |
| 5 | 11 月 | 中证500 成分加入夜间预算；个股页迁到 Open Design 终端；市场信息页 | Pages 上可查 800 只 | Open Design 出视觉 |
| 6 | 11–12 月 | 市场基础信息每日落盘，积累板块资金流历史 | 热力图可回看 | — |
| 7 | 2027-01 | 第一次季度复盘 | `forward_log/review/` | — |
| 8 | 2027-04 | 第二次季度复盘 → 打开 Round 2：T1+T7 外部市场成绩单 | 证据表更新 | 打开 Round 2 |
| 9 | 2027-05/06 | T2/T3/T4 变体、T5 广度评价、M1 体制、底部两层、二波子集、执行规则复核 | 各卡证据等级变更 | 按结果决定上线项 |
| 10 | 2027-H2 | Round 3：体制 × 信号两层、跨市场标定；可选腾讯云 worker | 产品 1.0 | 产品范围 |
| 11 | 2028-H1 | 前瞻日志 ≥6 季度 | 第一次有统计意义的样本外成绩单 | — |

## 11. 待你拍板
1. 合并 #22–#25、#27（说"合并"）。
2. #26 主页：是否转正式 PR；16 MB mp4 是否改走 Release/LFS；手机 390px 引言换行请真机确认。
3. 批准 Q-DD2 / Q-W1 登记（步 4）。
4. 个股研究方案 `docs/research_plan_stock_math.md` §7 三项：零对照字段进 JSON、Q-STK1 登记文本加 λ_t/市值分层、尾部层是否立项。
5. 腾讯云 worker 是否要做（不做也能用，只是要点一次 Run workflow、等 1–3 分钟）。

## 12. 主要风险
| 风险 | 应对 |
|---|---|
| 外部市场也不通过 | 产品定位为"泡沫形态描述 + 体制 + 价格带统计"，成绩单照常公开 |
| 事件太少 | 不放宽判据；加外部/1990s/前瞻；接受"未证明" |
| 数据源被封（已发生：腾讯 fqkline 501） | 多源回退 + 冻结版本 + sha256 |
| 过拟合 / 多重比较 | 预登记写死网格；Holm；LOCO |
| 用户把 t_c 当卖出日、把"便宜"当"要涨" | 固定文案模板；每个数字带等级与 n |
| GitHub Actions 额度/时长 | 夜间 6 分片约 30 分钟；超额时改腾讯云 worker |

## 13. 换电脑继续
```
git clone https://github.com/CareyPang/LPPL && cd LPPL
pip install -e ".[dev]"
pytest -m "not network"
pip install zstandard && python scripts/fetch_research_data.py   # 研究数据 3.8 GB，只有研究脚本需要
bash scripts/build_site.sh && python -m http.server 8000 -d _site
```
每个 PR 的评论区有"做了什么 / 文件路径 / 下一步"，按 §9 表从上往下看即可。
