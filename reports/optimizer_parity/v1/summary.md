# 优化器一致性审计：v1

- 生成：2026-11-26T08:52:06+00:00　代码：`e18697d05ac91dd8709e2eb52a8f29a7b6833432`
- 数据：冻结 `v20261024`；标的 sh000001, sh000300, sz399006；网格步长 120 个交易日
- 窗口：primary（75 个）；判据 sha256 `b5260713afd0`

## g3 vs tcgrid（常规网格日期）：**pass**

| 判据 | 值 | 门槛 | 结果 |
|---|---|---|---|
| sse_worse_share | 0.0000 | <= 0.05 | pass |
| 6-12m.conf_mae | 0.0030 | <= 0.02 | pass |
| 6-12m.conf_p95 | 0.0020 | <= 0.08 | pass |
| 6-12m.alarm_agreement | 0.9875 | >= 0.95 | pass |
| 6-12m.alarm_jaccard | 0.9375 | >= 0.8 | pass |
| 12-24m.conf_mae | 0.0015 | <= 0.02 | pass |
| 12-24m.conf_p95 | 0.0000 | <= 0.08 | pass |
| 12-24m.alarm_agreement | 1.0000 | >= 0.95 | pass |
| 12-24m.alarm_jaccard | 1.0000 | >= 0.8 | pass |

窗口级：配对 6000；SSE 更差 0.0%，更好 5.8%；box 一致 99.8%（κ=0.970）；box 通过率 ref 3.4% / alt 3.4%

锚点日期（不进裁决）：
- 6-12m：9 个日期，MAE 0.000，报警 ref 7 / alt 7
- 12-24m：9 个日期，MAE 0.011，报警 ref 5 / alt 5

## de_trf vs tcgrid（常规网格日期）：**fail**

| 判据 | 值 | 门槛 | 结果 |
|---|---|---|---|
| sse_worse_share | 0.0248 | <= 0.05 | pass |
| 6-12m.conf_mae | 0.0080 | <= 0.02 | pass |
| 6-12m.conf_p95 | 0.0800 | <= 0.08 | pass |
| 6-12m.alarm_agreement | 0.9500 | >= 0.95 | pass |
| 6-12m.alarm_jaccard | 0.7647 | >= 0.8 | fail |
| 12-24m.conf_mae | 0.0020 | <= 0.02 | pass |
| 12-24m.conf_p95 | 0.0000 | <= 0.08 | pass |
| 12-24m.alarm_agreement | 1.0000 | >= 0.95 | pass |
| 12-24m.alarm_jaccard | 1.0000 | >= 0.8 | pass |

窗口级：配对 6000；SSE 更差 2.5%，更好 5.9%；box 一致 99.6%（κ=0.939）；box 通过率 ref 3.4% / alt 3.3%

锚点日期（不进裁决）：
- 6-12m：9 个日期，MAE 0.000，报警 ref 7 / alt 7
- 12-24m：9 个日期，MAE 0.002，报警 ref 5 / alt 5

## de_trf vs g3（常规网格日期）：**pass**

| 判据 | 值 | 门槛 | 结果 |
|---|---|---|---|
| sse_worse_share | 0.0295 | <= 0.05 | pass |
| 6-12m.conf_mae | 0.0050 | <= 0.02 | pass |
| 6-12m.conf_p95 | 0.0400 | <= 0.08 | pass |
| 6-12m.alarm_agreement | 0.9625 | >= 0.95 | pass |
| 6-12m.alarm_jaccard | 0.8125 | >= 0.8 | pass |
| 12-24m.conf_mae | 0.0005 | <= 0.02 | pass |
| 12-24m.conf_p95 | 0.0000 | <= 0.08 | pass |
| 12-24m.alarm_agreement | 1.0000 | >= 0.95 | pass |
| 12-24m.alarm_jaccard | 1.0000 | >= 0.8 | pass |

窗口级：配对 6000；SSE 更差 2.9%，更好 0.8%；box 一致 99.8%（κ=0.969）；box 通过率 ref 3.4% / alt 3.3%

锚点日期（不进裁决）：
- 6-12m：9 个日期，MAE 0.000，报警 ref 7 / alt 7
- 12-24m：9 个日期，MAE 0.013，报警 ref 5 / alt 5

## 解读

- pass：在本审计范围内，线上优化器与评测优化器给出相同的报警结论，可以继续沿用开发段证据。
- fail：线上数字不再受开发段评测覆盖。应回退到 tcgrid，或把 de_trf 当作新方法重新走预登记评测。
- 本审计只覆盖主尺度窗口；其他四档未比较。
