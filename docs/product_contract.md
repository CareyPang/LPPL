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
    "lppls_confidence": {"S": 0.41, "M": 0.67, "L": 0.24, "evidence": "dev_pending"},
    "scenarios": [
      {"share": 0.40, "dt_range": [185, 260], "ahead_mean": 42, "ahead_sd": 5, "q20": 39, "q80": 47},
      {"share": 0.30, "dt_range": [125, 180], "ahead_mean": 27, "ahead_sd": 6, "q20": 21, "q80": 34}
    ],
    "scenarios_note": "簇间不平均；簇占比<5% 不列",
    "invalidation": {"rule": "p20 连续 10 日<阈值 或 三尺度置信度均<5%", "evidence": "rule"},
    "drawdown_price": {"value": null, "descriptive": [-0.18, -0.35], "evidence": "none"},
    "drawdown_time": {"value": null, "evidence": "none"},
    "second_wave": {"value": null, "evidence": "none"}
  },
  "bottom": {
    "state_p": {"value": 0.31, "evidence": "dev", "notes": ["B1 回撤深度在留出年/分层下稳健"]},
    "thrust_p": {"value": 0.12, "evidence": "dev", "notes": ["宽度确认；未做完整留出年"]},
    "entry_rule": {"value": null, "evidence": "none", "fallback": "波动率目标加仓节奏"}
  },
  "evidence_levels": {"dev": "开发段 2000–2018 CPCV 通过", "cal": "校准段 2019–2021 固定校准后成立", "test": "最终测试 2022–2025.08 一次性通过", "none": "预登记检验未通过，仅描述", "rule": "执行规则，非预测", "dev_pending": "开发段评估进行中"}
}
```

约束：
1. `asof` 之后的数据不得参与任何字段；前端显示 as-of 与数据冻结版本。
2. 校准段/最终测试段字段在授权运行前一律为 `null` + `evidence: "pending"`。
3. 历史验证面板只展示按样本段汇总的命中率/误报率/Brier；单案例"预测 vs 真实"只能作为图表回放。
