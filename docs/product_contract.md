# 产品输出契约 v0.1（研究层 → 前端；2026-10-25 草案）

每个标的、每个 as-of 日期一条记录。所有数值字段都带 `evidence`（证据等级）；前端不得把 `evidence = "none"` 的字段渲染成预测。

```json
{
  "symbol": "sh000001",
  "asof": "2015-06-12",
  "data_version": "frozen_v20261024",
  "model_version": "prereg_v1.7",
  "top": {
    "p20": {"value": 0.52, "evidence": "dev", "notes": ["依赖 2015 型杠杆牛", "剔除 2015 后无增量"]},
    "window": {"start": "2015-06-12", "end": "2015-07-10", "rule": "p20 首次≥阈值起 20 个交易日", "evidence": "dev"},
    "lppls_confidence": {"1-3m": 0.41, "6-12m": 0.67, "12-24m": 0.24, "evidence": "dev", "scale_evidence": {"1-3m": "none", "6-12m": "dev", "12-24m": "dev"}},  // §17.14 FCO 标签档；1–3 月仅描述性
    "scenarios": [
      {"share": 0.40, "dt_range": [185, 260], "ahead_mean": 42, "ahead_sd": 5, "q20": 39, "q80": 47},
      {"share": 0.30, "dt_range": [125, 180], "ahead_mean": 27, "ahead_sd": 6, "q20": 21, "q80": 34}
    ],
    "scenarios_note": "簇间不平均；簇占比<5% 不列",
    "invalidation": {"rule": "p20 连续 10 日<阈值 或 6–12 月与 12–24 月档置信度均<5%", "evidence": "rule"},
    "drawdown_price": {"value": null, "evidence": "descriptive", "table_version": "p1_v20261031", "bucket": "100–200% × 1–2 年",
      "n": 9, "n_a_share": 8, "max_dd": {"q20": -0.49, "q50": -0.47, "q80": -0.39}, "days_to_trough": {"q20": 155, "q50": 159, "q80": 414},
      "a_share": {"max_dd": {"q20": -0.48, "q50": -0.46, "q80": -0.37}, "days_to_trough": {"q20": 155, "q50": 159, "q80": 414}},
      "valuation_floor": {"n": 11, "trough_pe": {"q20": 12.9, "q50": 15.1, "q80": 19.9}, "pe_latest": 16.1, "pe_date": "2026-10-23", "floor_band_points": [2954, 3464], "evidence": "descriptive"},
      "rule": "P1 顶后价格带：同类泡沫（PS 标签，A 股 6 指数 + 外部 4 指数）历史顶→谷回撤/时长 20/50/80 分位；A 股单独 n<5 不给；估值地板 = 历次 PS 底部 PE 20–50% 分位 × 最新 PE；描述性，不是预测，value 恒为 null"},
    "drawdown_time": {"value": null, "evidence": "none"},
    "second_wave": {"value": null, "evidence": "none"}
  },
  "regime_band": {"month": "2015-05", "state": "RALLY", "channel": null, "rule": "FCO 公开定义：月收益/月内最大回撤相对自身前 60 个月的分位（§16.16）", "evidence": "descriptive"},
  "bottom": {
    "state_p": {"value": 0.31, "evidence": "dev", "notes": ["B1 回撤深度在留出年/分层下稳健"]},
    "thrust_p": {"value": 0.12, "evidence": "dev", "notes": ["宽度确认；未做完整留出年"]},
    "entry_rule": {"value": null, "evidence": "none", "fallback": "波动率目标加仓节奏"}
  },
  "evidence_levels": {"dev": "开发段 2000–2018 CPCV 通过", "cal": "校准段 2019–2021 固定校准后成立", "test": "最终测试 2022–2025.08 一次性通过", "none": "预登记检验未通过，仅描述", "rule": "执行规则，非预测", "dev_pending": "开发段评估进行中", "descriptive": "描述已完成月份的状态，非预测"}
}
```

约束：
1. `asof` 之后的数据不得参与任何字段；前端显示 as-of 与数据冻结版本。
2. 校准段/最终测试段字段在授权运行前一律为 `null` + `evidence: "pending"`。
3. 历史验证面板只展示按样本段汇总的命中率/误报率/Brier；单案例"预测 vs 真实"只能作为图表回放。

4. `regime_band` 只描述上一个已完成月，前端必须标注“描述性、非预测”，不得与顶部/底部概率合并成一个分数（研究层 `research/features/regime_bands.py`）。
