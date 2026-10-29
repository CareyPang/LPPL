# 证据总表（三段 × 模块）

产品每个 badge 的唯一依据。三段：开发段 2000–2018（选模型）、校准段 2019–2021（固定模型前推，只报告）、最终测试段 2022-01–2025-08（固定模型前推，只跑一次、只报告）。判据见 `docs/dev_freeze.md`：(i) ΔBrier 块 bootstrap 90% 区间上界 <0；(ii) ≥4/6 指数 A1 循环平移随机对照 p≤0.05 且 A2≥0.5（H=120）；(iii) 留出任一指数/年份不翻转。
来源报告：`reports/ladder_dev_full_v2.md`、`reports/ladder_bottom_dev.md`、`reports/calibration_2019_2021.md`、`reports/final_test_2022_2025.md`。

| 模块 | 契约字段 | 开发段 | 校准段 | 最终测试段 | 最终等级 | 产品处置 |
|---|---|---|---|---|---|---|
| 顶部 p20（R2 GSADF bsadf500_psy C=1.0） | `top.p20` | ΔBrier −0.0077，90% 上界 −0.00159 ✔ | ΔBrier +0.00077，[−0.00131,+0.00297] ✘(i)；Platt 斜率 −0.866 方向反 | ΔBrier −0.00158，[−0.00231,−0.00003] 点过线；留出 7 指数中 4 次上界转正 ✘(iii)；固定 Platt 使 Brier 0.04808→0.04855 变差 | **dev_only / fail_i_iii** | 不显示概率数字，仅标"开发段模型·校准/测试未通过" |
| 底部 B1 dd_nodur_z | `bottom.p_*` | ΔBrier −0.00914，上界 −0.00531 ✔ | +0.0012 含 0 ✘ | +0.00349 区间 >0 ✘ | **fail_i** | 不显示 |
| 底部 B2 amt_only_z | 同上 | −0.00081，上界 −0.0005 ✔ | +0.0013 ✘ | +0.00468 ✘ | **fail_i** | 不显示 |
| 底部 B3 omori25 | 同上 | −0.00059，上界 −0.00001 ✔ | +0.0014 ✘ | +0.00461 ✘ | **fail_i** | 不显示 |
| LPPLS 置信度 END 6–12m（报警 q=5%） | `top.indicators.6-12m.confidence.end` | A1 0.87 vs 随机 0.24（6 档重测，最强） | 1/7 指数，A1 0.31 vs 0.28 ✘(ii) | 0 报警日（无法评价）✘ | **dev_only** | 泡沫状态分级显示，标开发段证据 |
| LPPLS 置信度 STANDARD 6–12m | `…confidence.standard` | A1 0.56 | ✘(ii) | 24 报警日 A1=0 ✘ | **dev_only** | 同上 |
| LPPLS 置信度 box 6–12m | `…confidence.box` | ≈随机（0.31 vs 0.23） | 4/7 名义过 (ii)；Holm 后 3/7；LOCO 最小 3 ✘(iii) | 1/7（A1 中位 0 vs 0.14）✘(ii) | **dev_only** | 同上 |
| LPPLS 12–24m 各集 | `…12-24m` | 部分报警有效 | 全部 ✘(ii) | 全部 ✘(ii)（box 1/7，END 0 报警） | **dev_only** | 同上 |
| LPPLS 1–3m | `…1-3m` | 无证据 | 未评价 | 未评价 | **descriptive** | 显示但标无证据 |
| t_c 20–80% 分位窗 | `top.window` | 覆盖率低（见 fco_indicator_audit） | 未单独评价 | 未单独评价 | **descriptive** | 标"情景，非时点" |
| t_c 分布稳定性（收敛/不再后漂，§17.6-2 stab3 与漂移速度两种定义） | 未进契约 | 叠加在 box 6–12m ≥50% 之上无增量：A1 0.58 vs 单独 0.61、严格同报警数对照 0.67，A2 0.44→0.19；收敛出现在顶当日或之后（2015-06-12/19、2007-10-19），见 `reports/tc_stability_dev.md` | 未评价 | 未评价 | **dev_only / no_increment** | 不显示，不加入顶部卡 |
| 泡沫大小（模型/实际）、持续时间、进度 | `top.bubble.*` | 定义核对一致 | — | — | **descriptive** | 标"模型外推非目标价" |
| Combo p=0.1/1/10 | `top.combo` | 未评价 | — | — | **descriptive / 研究版** | 显示，标研究版 |
| 负泡沫置信度 | `top.negative_bubble` | 开发段无效 | — | — | **no_evidence** | 不显示或标无证据 |
| 月度体制带 | `regime` | 公开定义实现 | — | — | **descriptive** | 显示 |
| 估值分位 | `valuation` | 描述性 | — | — | **descriptive** | 显示 |
| 分批减仓规则（<5/5–20/≥20/≥50%） | `top.bubble.rule` | 开发段 END 6–12m 阈值证据 | 不适用 | 不适用 | **dev_rule** | 显示为规则，不作预测 |
| 个股自身 LPPLS 排名 | stock.html | 横截面无信息 | — | — | **no_evidence** | 不显示排名信号 |
| EFE 支撑阱 / 临界慢化 / 首达概率 / 二波 | 老版模块 | 无证据 | — | — | **no_evidence** | 产品层不给结论 |

等级定义（契约 `evidence_levels`）：`pass`（三段均过）、`dev_only`（开发段有信号，校准/测试未通过）、`cal_fragile`（历史：校准段名义过但不稳健）、`fail_i`、`fail_i_iii`、`dev_rule`、`descriptive`、`no_evidence`。
最终测试段 LPPLS 行已于 2026-10-28 填入（`reports/final_test_2022_2025.md` §3）。本表为契约 `validation`/`evidence_levels` 与 dashboard badge 的依据；三段历史评价关闭，后续只由前瞻日志更新。
