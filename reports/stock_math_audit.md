# 个股引擎数学/数值审计报告（stock_math_audit）

- 日期：2026-11-02；分支 `devin/1793628985-stock-math-audit`；基线 `main`（含 PR #22–#25、#27）。
- 范围：`research/pipeline/stock.py` 的 `predict()` / `history()` 所依赖的 LPPLS 拟合链路（窗口与 t₁ 网格、六尺度、v2 参数框、线性化、`tcgrid_lm`、FCO 过滤、Confidence、Trust、t_c 情景区间）及其与 `research/lppls/`、`research/pipeline/daily.py` 指数链路的一致性；数据口径对数学的影响；`stock_batch.breadth`。
- 文献依据：`docs/literature_stock_math.md`（本 PR 新增，41 篇全文，含 Ising/羊群、LPPLS 前沿、其他临界预警、华尔街尾部模型）。
- 硬性规则（遵守）：个股证据等级一律 `research_candidate`；**t_c 不是顶部日期**（JLS 2000 p.2/p.6：t_c 是崩盘"最可能"时间，崩盘可在此前任何时刻发生或不发生）；不改 `docs/preregistration*.md` 判据，只在 §7 提建议；未引入任何新模型。
- 环境：Python 3.10.12（`pyproject` 要求 ≥3.11，未改）；需额外安装 `pytest ruff cma akshare`（基线缺失，属环境问题）。CI 命令 `ruff check research tests` + `pytest -m "not network"`，结果见 §8。
- 复现脚本：`scripts/audit_stock_math/exp1..exp6*.py`（输出目录由 `AUDIT_OUT` 指定，默认 `/home/ubuntu/audit`；均需 `PYTHONPATH=.`，运行前 `export LPPLS_BOX=v2`，600519 等真实数据用仓库自带腾讯 fqkline + 新浪 hfq 因子取数，每只 ≥3 s 间隔，仅 5 只）。

## 0. 结论摘要

| 编号 | 严重度 | 发现 | 状态 |
|---|---|---|---|
| F1 | **中** | `tcgrid_lm` 的 t_c 网格阶段不评估 t₂ 之前（窗内）的半个 v2 搜索域，与 `core.ALLOW_INSIDE=True` 的设计矛盾；600519 stk_full 181 个窗口中 44 个（24%）在修复后 SSE 严格下降（最大相对下降 52%），幂律基线 42 个窗口下降 | **已修** + 测试 |
| F2 | **高（展示层）** | `export_contract._to_cal` 把超出已知交易日历的 t_c 折算日期**截断到 as-of 当天**；`predict()` 传入的日历止于 as-of，因此发布 JSON 里 `bubble.tc`、窗口 start/end、`q20/q80_date`、`tc_distribution` 分箱在"t_c 在未来"时全部坍缩为 as-of 日期（实例：`web/mock/data/index/sh000001_latest.json` 的 `bubble.tc == asof`） | **已修** + 测试 |
| F3 | 低 | `stk_lite`（127..502 步 25）与 `stk_full`（125..750 步 5 ∪ 短/超长档）**没有任何公共窗口**，与指数链路 `IDX_WINDOWS` 亦无交集；6–12 月档 lite 只有 6 个窗口（Confidence 分辨率 1/6）而 full 有 25 个 | 只建议 |
| F4 | 低 | `stock_batch._qualified` 的"confidence ≥ 0.5"用的是 `lppls_confidence`（`box` 规则比例），"有合格拟合"用的是 `g_fco_standard`——两个不同规则集混在同一张 breadth 表；逻辑本身符合任务口径（`standard>0`、`≥0.5` 分开计、只计 `in_stats`、dev 档 6–12/12–24 月） | 只建议 |
| F5 | 低 | `trust.window_trust` 对 100 个 bootstrap 复制样本一律用原始 y 的 std 作 `y_std`（p.21 文献未规定；影响 `rel_err` 过滤的方向偏保守），且 `trust()` 的多进程依赖 fork 继承 `ALLOW_INSIDE` | 只建议 |
| F6 | 低 | `history()` 的 ST 标记来自**当前**名称（非 PIT）；`_to_cal` 对历史 as-of 使用真实未来交易日历折算（仅日历，不含价格，无数学泄漏） | 只建议 |
| F7 | 信息 | 2–4 周档用 10–20 个点拟合 7 参数模型（预登记 17.6 曾写"不做"），600519 该档 r² 中位 0.91 但 `rel_err` 中位 0.30，数值上接近过拟合 | 只建议 |
| F8 | 信息 | 合成序列：v2 链路在 t_c 位于窗外 +5%dt 时 t_c MAE 0.26/0.53/1.10 bar（σ=0.5%/1%/2%），m/ω 无撞边界；t_c 位于窗内 −5%dt 时旧代码 MAE 0.89/4.03/12.27 bar，修复后见 §3.1 | 证据 |
| F9 | 信息 | 零假设误报：GBM(无漂移)/GARCH 窗口级 `box` 2.3%/3.0%、`standard` 6.6%/5.3%；**强漂移 GBM 与纯幂律分别 42.8%、34.2% 的窗口通过 STANDARD**，as-of 级"standard ≥0.5"误报 42.5%/32.5%（6–12 月）——与 Brée–Joseph 2013、Troude 等 2024 的批评一致 | 证据 |
| F10 | 信息 | 真实 600519（as-of 2025-06-30，stk_full 181 窗）：m 撞下界 14.4%、撞上界 12.7%、ω 撞下界 11.6%、t_c 撞 ±0.2dt 搜索边界 30.9%、m>1 39%；所有尺度 box/standard = 0；PIT 与指数链路一致性最大差 0.0 | 证据 |

未发现：未来数据泄漏（价格层）；后复权方向错误；未收盘 bar 进入拟合；停牌插值进入个股拟合；breadth 分母错误。

## 1. 拟合链路核对（与文献和指数链路）

| 项目 | 实现位置 | 核对结果 |
|---|---|---|
| v2 参数框 | `research/features/lppls_scan.py:30–37`；`stock.py:12` `os.environ.setdefault("LPPLS_BOX","v2")`，`_ensure_v2_box()` 拒绝非 v2 | 搜索域 m∈[0.01,2]、ω∈[1,50]、t_c∈[t₂−0.2dt, t₂+0.2dt]，与 Zhang–Zhang–Sornette 2016 Table 3（m∈[0,2]、ω∈[1,50]、t_c∈[t_end−0.2dt,t_end+0.2dt]）一致；`fit_one` 的 lo/hi（`lppls_scan.py:108–109`）在 tc_lo<0.5 时按比例 `tc_lo*dt` 展开，正确。无 v1 回退路径（`_ensure_v2_box` 单元测试已覆盖）。 |
| 线性化 | `research/lppls/core.py:28–60` `design()`/`lin_fit()` | A,B,C₁,C₂ 用 `np.linalg.lstsq`（SVD）求解，与 Filimonov–Sornette 2013 式 (13)–(16) 等价；比正规方程更稳（无需 XᵀX）。`design()` 在 `ALLOW_INSIDE` 下用 `max(|t_c−t|, MIN_DT)`，MIN_DT=1e-3。 |
| 优化器 | `research/optim/optimizers.py:92–190` `grid_profile` + `tcgrid_lm` | t_c 网格 × (m,ω) 网格批量 SVD 剖面 → top-k + 随机起点 LM。**F1：`grid_profile` 不遵守 `ALLOW_INSIDE`**（见 §2.1）。秩判据 `sv[-1] > sv[0]·n·eps` 与 lstsq 默认 rcond 同量级，病态点返回 inf，未见 NaN 外泄（exp4/exp6 全部 sse 有限）。 |
| 窗口/六尺度 | `stock._variant_windows`（`stock.py:251`）；`universe.WINDOWS`（`universe.py:28`）= 127..502 步 25；`lppls_scan.py:47–60` | 六尺度划分 `SCALES_FCO6`（`lppls_rules.py:63`）= 10–20/21–63/64–126/127–252/253–504/505–1500，lite 只覆盖 6–12 月与 12–24 月（各 6、10 个窗口），full 覆盖六档（181 窗，600519）。F3：lite/full/指数三套窗口两两无交集。 |
| FCO 过滤 | `lppls_rules.rules()`/`grid_rules()`（`lppls_rules.py:34–120`） | `box`（m∈(0,1)、B<0、ahead≥0、…）、`g_fco_standard/early/end/pure`；`_derived` 的 D=m\|B\|/(ω\|C\|)、振荡数 osc=(ω/2)ln(\|t_c\|/\|t_c−t₂\|)、`n_osc=osc/π` 与 `core.Fit.n_osc` 一致；与 ZZS 2016 条件 1/2 对应（条件 2 的 O≥2.5 用 ln 比值定义，仓库同）。 |
| Confidence | `export_contract._conf`（:36）、`_indicators`（:167） | 每尺度合格窗口比例（box 与四套 FCO 分别给出），`n_qualified_standard` 为计数；定义与 Gerlach 2019 / ZZS 2016 一致。 |
| Trust | `research/lppls/trust.py:35–60` | 残差 iid bootstrap B=100 → 加回拟合值 → `fit_one` → 条件 2 比例 → 窗口中位数；与 ZZS 2016 p.21 一致（F5 两点小差异）。输出 `evidence="descriptive"`。 |
| t_c 情景区间 | `export_contract` 的 q20/q80/q025/q975 与 `tc_distribution`；`research/lppls/intervals.py` | `predict()` 输出的是**跨窗口 t_c 分位**（情景），不是 Filimonov–Demos–Sornette 2017 的（修正）剖面似然区间；`intervals.profile_interval` 为未修正版、`bootstrap_interval` 为块 bootstrap，二者均未接入个股输出。建议统一命名为"情景分位"（§7）。 |
| 与指数链路一致性 | `stock._fit_worker` → `daily.fit_asof` → `lppls_scan.fit_one` | 同一函数；实测 600519、000858 等 lite/full 窗口上 `stock._fit_pairs` 与 `daily.fit_asof` 的 tc/m/ω/sse 最大绝对差 **0.0**（exp4/exp6 `consistency_maxdiff`）。 |

## 2. 发现与修复

### F1（中）`grid_profile` 跳过 t_c ≤ t₂ 的网格点 —— 已修
- 位置：`research/optim/optimizers.py:102–106`（修复前 `dt = tc - t; if np.any(dt <= 0): continue`）。
- 机理：v2 的 t_c 搜索域为 [t₂−0.2dt, t₂+0.2dt]，`core.design()` 在 `ALLOW_INSIDE=True` 时用 \|t_c−t\| 处理窗内 t_c；但网格阶段直接把所有 t_c≤t₂ 置为 inf，于是 top-k 起点全部落在 t₂ 之后，窗内解只能靠 LM 漂移或 10 个随机起点"碰到"。幂律基线（`K_POWER`）同样受影响。文献（Filimonov–Sornette 2013 §4 subordination；ZZS 2016 Table 3）对 t_c 的剖面覆盖整个搜索区间。
- 证据：
  - `exp1_grid_inside.py`：合成序列（n=240，真 t_c=224.1 在窗内）网格 40 个 t_c 中 20 个 ≤t₂ 全为 inf。
  - `exp5_grid_fix_impact.py 2025-06-30`（600519，stk_full 181 窗，旧 vs 新网格，其余完全相同）：44 个窗口 SSE 严格下降（相对下降 >1e-6），0 个上升，最大相对下降 0.524；变化窗口中 t_c 位移中位数 18.3 bar，m 位移中位 0.039；受影响窗口遍布 10–1275 全部尺度；幂律 SSE 下降 42 窗。窗内 t_c 占比 0.514 → 0.564；边界/合格统计：m 撞下界 14.4%→13.8%，ω 撞下界 11.6%→13.3%，t_c 撞 ±0.2dt 边界 30.9%→38.1%（更多解落到窗内一侧边界），box/standard 仍为 0（该日 600519 无合格形态）。
  - 合成回收（§3.1）：修复后窗内 t_c（−5%dt）的 MAE 明显下降。
- 修复：`grid_profile` 读取运行时 `core.ALLOW_INSIDE`，为 True 时 `dt = max(|tc−t|, MIN_DT)`（与 `design()` 同式），否则保持旧行为（v1 不变）。
- 测试：`tests/test_core.py::test_grid_profile_covers_inside_tc_when_allow_inside`（v1 下窗内点 inf；v2 下全部有限、最小值落在真 t_c、与 `lin_fit` 同解、幂律亦有限）。

### F2（高，展示层）`_to_cal` 将未来 t_c 截断到 as-of 日 —— 已修
- 位置：`research/eval/export_contract.py:44–47`（修复前 `j = clip(round(i+ahead), 0, len(cal)-1)`）。调用点 :84（窗口 t1/t2/tc）、:98–100（q20/q80/q025/q975/mode 日期）、:118–119、:154、:194（`tc_distribution` 分箱）、:288（`bubble.tc`）、:364（窗口 start/end）。
- 机理：`stock.predict()`（`stock.py:391–398`）与 `daily.run` 传入的 `cal = logp.index` 止于 as-of；任何 `ahead>0` 的 t_c 都被截到 `cal[-1]` = as-of。于是"t_c 情景在未来 30 个交易日"被显示为"t_c = 今天"，并使 q20_date == q80_date（区间坍缩）。`history()` 对历史 as-of 用全序列日历，仅最后一个 as-of 受影响。
- 证据：`python -c` 直接调用 `_to_cal(bdate_range(300), cal[-1], 30.0)` 返回 `cal[-1]`；现有产物 `web/mock/data/index/sh000001_latest.json` 中 `bubble.tc == asof == 2026-10-30`。
- 修复：超出日历的部分按工作日外推（`pd.bdate_range`），j<0 仍截到 `cal[0]`；注释写明是情景展示而非顶部日期。限制：节假日未剔除（外推误差 ≤ 法定节假日数，展示层可接受；精确做法见 §7）。
- 测试：`tests/test_export_history.py::test_to_cal_extrapolates_beyond_calendar_end`。

### F3（低）窗口集合无交集；lite 的 Confidence 分辨率低 —— 建议
- `universe.WINDOWS` = {127,152,…,502}（16 个）；`stk_full` = XS{10..20 步2} ∪ SHORT{30..120 步5} ∪ IDX{125..750 步5} ∪ XL{525..1500 步25}，二者与 `IDX_WINDOWS` 两两无公共元素。因此"lite vs full vs 指数链路同参数比较"只能按**尺度聚合**比较（§4），无法逐窗口比较。6–12 月档 lite 6 窗 → Confidence 取值只能是 k/6。建议 lite 改为 full 在 6–12/12–24 月档的子集（如 125..500 步 25），使 lite ⊂ full（需预登记备注，不改判据）。

### F4（低）breadth 混用两套规则 —— 建议
- `stock_batch.py:105–120 _qualified`：`fit_scales` 用 `indicators[scale].confidence.standard > 0`（FCO STANDARD）；`conf_scales` 用 `confidence[scale] ≥ 0.5`（`box` 规则比例）。`breadth()`（:122–165）先过滤 `meta.in_stats`（:148）再计入分母，dev 档 `DEV_SCALES=("6-12m","12-24m")`（:24）。逻辑与任务口径一致；建议在报表列名写明规则来源（`box_conf≥0.5` / `standard_n>0`），避免被解读为同一指标的两档阈值。现有 `tests/test_stock_batch.py` 已覆盖 in_stats 过滤与计数。

### F5（低）Trust 细节 —— 建议
- `trust.py:45` 对所有 bootstrap 复制样本用同一 `np.std(y)`；复制样本的 std 略有差异（残差方差相同、趋势相同，差异 <1%），对 `rel_err` 过滤影响可忽略，但更严格做法是逐样本计算。`trust()` 用 `Pool(procs)` 且依赖 fork 继承 `ALLOW_INSIDE`（Linux 默认 fork，可行；若改 spawn 会回退到 v1 语义——建议加 initializer）。预登记草案禁止在 Q-STK1 评价中跑 Trust，本审计仅核对实现未用于评价。

### F6（低）PIT 旁路 —— 建议
- `history()`（`stock.py:630`）用 `_name_and_st(code)` 当前名称判断 ST，历史 as-of 的 ST 状态非 PIT（只影响 in_stats 标记，不影响拟合）。`_to_cal` 对历史 as-of 使用真实未来交易日历（仅日历，不含价格）。价格层 PIT 核验：对 600519/000858/… 用含未来 bar 的全序列与截断序列在同一 as-of 拟合，tc/m/ω/sse 最大差 0.0（exp4/exp6 `pit_maxdiff`）。

### F7（信息）2–4 周档数值可疑 —— 建议
- 10–20 点拟合 7 参数：600519 as-of 2025-06-30 该档 r² 中位 0.91、`rel_err` 中位 0.30（其余尺度 r² 0.54–0.61）。文献中最短窗口通常 ≥ 30 个交易日（Gerlach 2019 短泡沫亦以月计）。建议仅展示、不计入任何 breadth 或合格统计（当前 `DEV_SCALES` 已排除）。

## 3. 合成序列与零假设

### 3.1 参数回收（`exp2_synth_recovery.py <procs> <CF>`；n∈{127,…,502}（6 窗）× 64 个种子，m=0.5、ω=9、B<0，C₁=C₂=CF·\|B\|，σ∈{0.5%,1%,2%}，t_c 相对窗长 ±5%）

| 代码 | CF | t_c 位置 | σ | t_c MAE (bar) | m MAE | ω MAE | box | standard | end | cond2 |
|---|---|---|---|---|---|---|---|---|---|---|
| 修复前 | 0.1 | +5%dt | .005/.01/.02 | 0.26 / 0.53 / 1.10 | ≤0.023 | ≤0.12 | 1.0 | 0 | 0 | 0 |
| 修复前 | 0.1 | −5%dt | .005/.01/.02 | 0.89 / 4.03 / 12.27 | ≤0.038 | ≤0.92 | .05/.19/.45 | 0 | 0 | 0 |
| 修复后 | 0.1 | +5%dt | .005/.01/.02 | 0.26 / 0.53 / 1.10（与修复前逐位相同） | ≤0.023 | ≤0.12 | 1.0 | 0 | 0 | 0 |
| 修复后 | 0.1 | −5%dt | .005/.01/.02 | **0.04 / 0.40 / 3.14**（修复前 0.89 / 4.03 / 12.27） | ≤0.015 | ≤0.27 | 0/.02/.13 | 0 | 0 | 0 |
| 修复后 | 0.03 | +5%dt | .005/.01/.02 | 0.84 / 1.88 / 7.55 | ≤0.047 | ≤0.65 | 1/1/.94 | 1.0 | 1.0 | 1/1/.06 |
| 修复后 | 0.03 | −5%dt | .005/.01/.02 | 0.06 / 0.16 / 0.33 | ≤0.013 | ≤0.20 | 0 | 1.0 | 1.0 | 1/1/.95 |

- F1 修复效果：窗外 t_c 的结果逐位不变；窗内 t_c 的 MAE 下降 20×/10×/4×（σ=0.5%/1%/2%），ω MAE 从 0.10/0.34/0.92 降到 0.015/0.06/0.27；修复前窗内情形的 `box` 通过率 5–45% 来自被错误推到 t₂ 之后的解（ahead≥0 成立），修复后降到 0–13%——即修复前的 box Confidence 在窗内 t_c 情形是**虚高**的。
- 解读：CF=0.1 时 D=m\|B\|/(ω C)=0.39<1，合成序列本身不满足 STANDARD 的阻尼条件，故 standard=0 是**过滤正确**而非 bug；CF=0.03（D≈1.3）时 STANDARD/END 全部通过，σ=2% 时 cond2（含振荡数/相对误差）通过率降到 6%。`box` 对窗内 t_c 为 0 是设计使然（box 要求 ahead≥0）。m/ω 无撞边界。t_c MAE 随 σ 线性放大，σ=2% 时达 7.5 bar（约 3%dt），这是"t_c 情景区间宽度"的数值下限参照。

### 3.2 零假设误报率（`exp3_null.py 4 40`：每类 40 条独立序列 × lite 16 窗 = 640 窗；GBM σ=2%/日，漂移 0 或 0.4%/日；纯幂律 m=0.5 无振荡 t_c=+5%dt σ=1%；GARCH(1,1) α=0.1 β=0.85）

| 零假设 | box | STANDARD | END | EARLY | lit2 | as-of 级 standard≥0.5（6–12m / 12–24m） | as-of 级 standard>0 |
|---|---|---|---|---|---|---|---|
| GBM 无漂移 | 0.023 | 0.066 | 0.023 | 0.289 | 0 | 0.075 / 0.050 | 0.20 / 0.15 |
| GARCH | 0.030 | 0.053 | 0.031 | 0.322 | 0 | 0.050 / 0.025 | 0.15 / 0.125 |
| **GBM 强漂移** | 0.114 | **0.428** | 0.334 | 0.491 | 0.214 | **0.425 / 0.425** | 0.725 / 0.825 |
| **纯幂律（无振荡）** | 0.105 | **0.342** | 0.342 | 0.342 | 0.202 | **0.325 / 0.450** | 0.625 / 0.725 |

边界撞击（零假设）：GBM/GARCH 下 m 撞下界 9–10%、撞上界 16–18%、ω 撞下界 10–11%、t_c 撞 ±0.2dt 边界 33%；纯幂律 ω 撞上界 7%。
- 解读：（i）无漂移噪声下 STANDARD 误报 5–7%，与 JLS 2000 的 GARCH 替代序列 6.6%（p.23–24）同量级；（ii）**强趋势或无振荡幂律即可让 1/3–2/5 的窗口通过 STANDARD**，说明 STANDARD（无 Lomb/振荡数硬约束）主要识别"超指数趋势"而非对数周期——这正是 Brée–Joseph、Geraskin–Fantazzini 批评的识别性问题；（iii）`box` 规则（含 ahead≥0、D 等）对趋势零假设更稳健（10–11%），`lit2` 为 0/20%。**建议**（§7）：个股 breadth 的"有合格拟合"应同时报告"趋势零假设误报率"或改用含振荡数条件的规则，但这属预登记判据，本 PR 不改。

## 4. 真实股票（限速取数：腾讯 fqkline + 新浪 hfq 因子，5 只，各 1 次）

as-of 2025-06-30（开发段内固定日，避免最新日）：

| 代码 | n_bars(PIT) | in_stats | 变体 | 窗数 | 耗时 | 链路一致性 max\|Δ\| | PIT max\|Δ\| | m 撞下界 | m 撞上界 | ω 撞下界 | t_c 撞边界 | 窗内 t_c | r² 中位 | rel_err 中位 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 600519 | 5751 | True | lite | 16 | 10 s | 0.0 | 0.0 | — | — | — | — | — | — | — |
| 600519 | 5751 | True | full | 181 | 51 s | 0.0 | 0.0 | 0.144 | 0.127 | 0.116 | 0.309 | 0.514 | 0.61（6–12m） | 0.62 |
| 000858 | 6391 | True | lite | 16 | 18 s | 0.0 | 0.0 | 0 | 0.188 | 0 | 0.063 | 0.375 | 0.62 | 0.62 |
| 000858 | 6391 | True | full | 181 | 87 s | 0.0 | 0.0 | 0.011 | 0.265 | 0.055 | 0.083 | 0.580 | 0.67 | 0.57 |
| 300750 | 1651 | True | lite | 16 | 12 s | 0.0 | 0.0 | 0 | 0.250 | 0.188 | 0.562 | 0.875 | 0.85 | 0.39 |
| 300750 | 1651 | True | full | 181 | 82 s | 0.0 | 0.0 | 0.011 | 0.215 | 0.133 | 0.392 | 0.702 | 0.78 | 0.47 |
| 601318 | 4329 | True | lite | 16 | 12 s | 0.0 | 0.0 | 0 | 0.312 | 0.062 | 0.250 | 0.812 | 0.86 | 0.38 |
| 601318 | 4329 | True | full | 181 | 93 s | 0.0 | 0.0 | 0.066 | 0.177 | 0.099 | 0.276 | 0.685 | 0.82 | 0.42 |
| 002594 | 3328 | True | lite | 16 | 17 s | 0.0 | 0.0 | 0 | 0.125 | 0.062 | 0.188 | 0.875 | 0.89 | 0.33 |
| 002594 | 3328 | True | full | 181 | 107 s | 0.0 | 0.0 | 0.033 | 0.199 | 0.077 | 0.398 | 0.575 | 0.87 | 0.37 |

各尺度合格率（box / STANDARD / END）：
| 代码 | 变体 | 6–12m（n / box / STD / END） | 12–24m | 2–4w | 1–3m | 3–6m | 2–6y |
|---|---|---|---|---|---|---|---|
| 600519 | lite / full | 6 / 0 / 0 / 0 ; 25 / 0 / 0 / 0 | 10 / 0 / 0 / 0 ; 50 / 0 / 0 / 0 | 6 / 0 / 0 / 0 | 7 / 0 / 0 / 0 | 13 / 0 / 0 / 0 | 80 / 0 / 0 / 0 |
| 000858 | lite / full | 6 / 0 / 0 / 0 ; 25 / 0 / 0 / 0 | 10 / .20 / 0 / 0 ; 50 / .12 / 0 / 0 | 6 / 0 / 0 / 0 | 7 / 0 / 0 / 0 | 13 / 0 / 0 / 0 | 80 / 0 / 0 / 0 |
| 300750 | lite / full | 6 / 0 / 0 / 0 ; 25 / 0 / 0 / 0 | 10 / 0 / 0 / 0 ; 50 / 0 / 0 / 0 | 6 / 0 / 0 / 0 | 7 / 0 / 0 / 0 | 13 / 0 / 0 / 0 | 80 / 0 / 0 / 0 |
| 601318 | lite / full | 6 / 0 / 0 / 0 ; 25 / 0 / 0 / 0 | 10 / 0 / 0 / 0 ; 50 / 0 / 0 / 0 | 6 / 0 / .33 / 0 | 7 / 0 / .57 / .57 | 13 / .23 / 0 / 0 | 80 / .01 / 0 / 0 |
| 002594 | lite / full | 6 / 0 / **.17** / 0 ; 25 / 0 / **.08** / 0 | 10 / 0 / **.30** / 0 ; 50 / 0 / **.24** / .06 | 6 / 0 / 0 / 0 | 7 / 0 / 0 / 0 | 13 / 0 / 0 / 0 | 80 / 0 / 0 / 0 |

（600519 行取自 exp4，其余 exp6；`n` 为该档窗口数。）

- 结论：5 只个股、lite+full 共 10 组，个股链路与指数链路在相同窗口上**逐位一致**（Δ=0），PIT 无价格泄漏；lite 与 full 在重叠尺度（6–12m、12–24m）的合格率同向（002594：STANDARD lite .17/.30 vs full .08/.24；000858：box .20 vs .12；其余均为 0），差异来自窗口数与网格粒度而非数学；601318 只在 2–4w/1–3m 短档出现 STANDARD 合格（.33/.57，窗口 10–63 点，见 F7），长档为 0；m 撞 2.0 上界与 ω 撞 1.0 下界在个股上各占 10–19%——这些解是"无振荡的近线性/凸趋势"，会被 STANDARD 的 m<1 或 box 的 m∈(0,1) 过滤掉，但说明搜索域上沿 m=2 对个股并非摆设；t_c 撞 ±0.2dt 边界 30%+（600519）表明搜索域边界在个股上经常被触及，相关窗口的 t_c 不应作为情景分位输入（建议 §7）。

## 5. 数据口径对数学的影响（核对，未发现 bug）

| 口径 | 位置 | 核对 |
|---|---|---|
| 后复权 | `tencent_sina.apply_factors`（:121–129）hfq 为 **乘** 因子；`load_stock`（`stock.py:144`）优先腾讯 fqkline，回退 kline×新浪 hfq 因子，明确不用腾讯 qfq 等差口径 | 方向正确（`tests/test_stock_engine.py` 已有 HFQ 方向测试）；log 价差分在乘法复权下不变，拟合不受因子尺度影响。 |
| 未收盘 bar | `_close_cutoff`（:123）15:30 前不纳入当日；`_drop_unclosed_bars`（:135） | 600519/000858 加载元数据 `dropped_unclosed_bar` 正常；拟合输入 `available = full_logp[index ≤ asof]`。 |
| 停牌不插值 | `load_stock` 只保留真实 bar；`_trading_days_stale` 用上证参考日历计算停牌缺口 | 个股拟合直接用 bar 序列（t 为 bar 序号），无插值。`export_contract._close()`（:81–83）有 `reindex(cal).ffill()`，但 `predict/history` 传入的 `cal=logp.index` 即 bar 日期本身，reindex 无新增点，ffill 为空操作；仅在他处以外部日历调用时才会前向填充（指数链路行为，非个股）。 |
| 一字板 degenerate | `_eligibility`（:278–292）最近 505 bar 中 high==low 占比 >20% → `degenerate`，`in_stats=False` 但仍拟合 | 合理；一字板序列在 log 价上是阶梯函数，LPPLS 线性系统仍满秩（时间基不退化），只是经济含义失真——用 in_stats 排除是正确层级。 |
| 上市满 500 日 | `_eligibility` `n_bars ≥ 500`；`predict` 在 <500 时 `windows=()`；`history` 只对 ≥500 可用 bar 的 as-of 拟合；上市首 60 bar 丢弃 | 与 12–24 月档上限 504 对应：n=500–504 时该档只有 ≤1 个窗口，Confidence 分辨率极低（建议 §7：对 n<505 的个股把 12–24m 档标 `insufficient`）。 |
| `in_stats` | `in_stats = n_bars ≥ 500 and not degenerate and st is not True`（:292） | 与 breadth 分母口径一致。 |
| PIT | `predict`（:432–460）先按 asof 截断 logp，再截 ohlc，再算 eligibility；`history` 缓存 key 含 `data_version`/`code_version` | 价格层无泄漏（§4 Δ=0）；F6 两个非价格旁路。 |

## 6. 数值稳定性

- 病态矩阵：`grid_profile` 批量 SVD 秩判据 + `lin_fit` lstsq；exp3/exp4/exp6 全部窗口 sse 有限，无 NaN/inf 外泄；m→0.01 时 f=(t_c−t)^m≈1 与常数列近共线，正是 m 撞下界 9–14% 的来源——这些解的 B 与 A 高度相关、`C` 近 0，`D` 判据会将其过滤。
- t_c 边界：窗外上沿 +0.2dt 与窗内下沿 −0.2dt 是**硬搜索边界**，零假设与真实个股均有 30%+ 窗口撞边；修复 F1 后窗内一侧撞边增加（600519 30.9%→38.1%），因为此前这些窗口的 t_c 被人为推到 t₂ 之后。
- `MIN_DT=1e-3`：窗内 t_c 恰在样本点上时 ln(1e-3)=−6.9，(t_c−t)^m 对 m∈[0.01,2] 取值 0.93…1e-6，矩阵仍满秩；未见数值溢出。
- m/ω 撞边界比例（个股 full）：m 下界 14%、上界 13%、ω 下界 12%、ω 上界 0%；（零假设）m 上界 16–18%。ω=50 上界从不触及，ω=1 下界常触及（接近"无振荡"退化），与 Filimonov–Sornette 2013 的"ω 小时 C 项与 B 项共线"一致。

## 7. 建议（不改预登记判据，仅记录）

1. **命名**：把 `predict/history` 的 q20/q80/q025/q975 与 `tc_distribution` 统一称为"跨窗口 t_c 情景分位"，字段注释引用 JLS 2000 p.2/p.6；不得出现"预计顶部日期"字样。
2. **F3**：预登记备注中把 `stk_lite` 定义为 `stk_full` 的子集（125..500 步 25），使 lite 的 Confidence 为 full 的无偏子抽样。
3. **零假设对照**：个股 breadth 报表旁附"强漂移 GBM / 纯幂律 STANDARD 误报率"（本报告 42.8%/34.2%），或在 Q-STK1 评价阶段比较 `box`、`g_fco_end`、`lit2` 的 OOS 表现后再定（预登记流程）。
4. **撞边界窗口**：t_c 落在 ±0.2dt 搜索边界 1 bar 内的窗口在计算情景分位时标记 `at_bound`，分位统计给出剔除前后两版（描述性）。
5. **2–4 周档**：仅展示、永不计入 breadth；或最短窗 ≥30。
6. **n∈[500,504]** 的个股：12–24 月档标 `insufficient_windows`。
7. **Trust**：逐 bootstrap 样本算 `y_std`；`Pool` 加 initializer 设置 `ALLOW_INSIDE`。
8. **`_to_cal` 精确化**：用 `research/data` 的交易日历（上证参考日历）外推而非工作日；本 PR 用工作日是最小改动。
9. **文献层可做草案**（详见 `docs/literature_stock_math.md` §5）：Lagrange t₁* 作描述性字段；GARCH-EVT 条件 ES / CAViaR 分位作并列"尾部层"；负泡沫 B>0 镜像情景；均需新预登记。

## 8. 验证

- `ruff check research tests` → All checks passed!
- `pytest -m "not network"` → 142 passed, 10 skipped, 1 deselected（含 2 个新增测试）
- 新增测试：`tests/test_core.py::test_grid_profile_covers_inside_tc_when_allow_inside`、`tests/test_export_history.py::test_to_cal_extrapolates_beyond_calendar_end`。
- 复现：
  ```bash
  export LPPLS_BOX=v2 PYTHONPATH=. AUDIT_OUT=/tmp/audit
  python scripts/audit_stock_math/exp1_grid_inside.py            # F1 网格覆盖
  python scripts/audit_stock_math/exp2_synth_recovery.py 4 0.1   # 合成回收（CF=C/|B|）
  python scripts/audit_stock_math/exp3_null.py 4 40              # 零假设误报（约 10 min/8 核）
  python scripts/audit_stock_math/exp4_real_600519.py 2025-06-30 # 600519 lite/full/一致性/PIT
  python scripts/audit_stock_math/exp5_grid_fix_impact.py 2025-06-30  # F1 修复前后对比（需 exp4 的 600519 parquet）
  python scripts/audit_stock_math/exp6_real_multi.py 000858,300750,601318,002594 2025-06-30 3
  python - <<'EOF'
  import pandas as pd; from research.eval.export_contract import _to_cal
  cal = pd.bdate_range("2024-01-01", periods=300); print(_to_cal(cal, cal[-1], 30.0))   # 修复前返回 cal[-1]
  EOF
  ```

## 9. 下一步
- 合并后重新生成 `web/mock/data/**/*_latest.json`，核对 `bubble.tc`/`window.start/end` 不再等于 as-of。
- 按 §7.2–7.4 在预登记流程中提出修订，再决定是否调整 lite 窗口与 breadth 规则。
- 用 `scripts/audit_stock_math/exp3_null.py` 加入更多零假设（AR(1) 趋势、跳跃扩散）扩展误报基线。
