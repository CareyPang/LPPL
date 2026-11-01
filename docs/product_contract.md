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
    "drawdown_price": {"value": null, "evidence": "descriptive", "table_version": "p1_v20261031", "table_asof": "2015-06-12",
      "n_events": 30, "n_events_a": 12, "bucket": "涨幅 100–200%", "n": 8, "n_a_share": 4,
      "bucket_basis": {"size_realized": 1.552, "duration_days": 240, "t1_qualified_standard": true},
      "max_dd": {"q20": -0.565, "q50": -0.466, "q80": -0.422}, "days_to_trough": {"q20": 212, "q50": 386, "q80": 720}, "a_share": null,
      "table": {"all": {"n": 30, "n_a": 12, "max_dd": {}, "days_to_trough": {}, "a_share": {}}, "by_run_up": {}, "by_duration": {}, "by_run_up_x_duration": {}},
      "valuation_floor": {"n": 6, "trough_pe": {"q20": 15.23, "q50": 17.96, "q80": 34.0}, "pe_latest": 22.55, "pe_date": "2015-04-30",
        "close_ref": 5166.35, "close_date": "2015-06-12", "floor_band_points": [3489, 4114], "evidence": "descriptive"},
      "rule": "P1 顶后价格带：同类泡沫（PS 标签，A 股 6 指数 + 外部 4 指数）历史顶→谷回撤/时长 20/50/80 分位，只用 as-of 当日已确认（顶、谷、下一合格顶均已过 168 日窗）的事件；A 股单独 n<5 不给；估值地板 = 历次 PS 底部 PE 20–50% 分位 × as-of 收盘 / as-of 可用 PE（1 个月发布滞后）；深证/创业板 PE 口径与价格指数不一致，不给地板；描述性，不是预测，value 恒为 null"},
    "drawdown_time": {"value": null, "evidence": "none"},
    "second_wave": {"value": null, "evidence": "none"}
  },
  "regime_band": {"month": "2015-05", "state": "RALLY", "channel": null, "rule": "FCO 公开定义：月收益/月内最大回撤相对自身前 60 个月的分位（§16.16）", "evidence": "descriptive"},
  "bottom": {
    "state_p": {"value": 0.31, "evidence": "dev", "notes": ["B1 回撤深度在留出年/分层下稳健"]},
    "thrust_p": {"value": 0.12, "evidence": "dev", "notes": ["宽度确认；未做完整留出年"]},
    "entry_rule": {"value": null, "evidence": "none", "fallback": "波动率目标加仓节奏"},
    "cheap": {
      "evidence": "descriptive", "dd_now": 0.0, "peak_date": "2015-06-12", "peak_close": 5166.35,
      "dd_rank": {"all": {"pct": 0.0, "n": 30}, "a_share": {"pct": 0.0, "n": 12}, "note": "历史 30 次顶→谷回撤中，0% 比当前回撤浅（历史分位，不是预测）"},
      "pe_pct": {"value": 0.708, "n_months": 120, "pe_date": "2015-04-30"},
      "floor_ref": "top.drawdown_price.valuation_floor"
    },
    "confirm": {
      "evidence": "rule", "rule": "Lunde–Timmermann 2004：自牛市高点跌 20% 确认熊市；自熊市低点涨 15% 确认熊市结束（滞后确认，不是预测）",
      "state": "bull", "ref_date": "2015-06-12", "ref_close": 5166.35, "threshold": 0.15, "confirmed": true,
      "last_trough_date": "2012-12-03", "last_trough_close": 1959.77, "confirmed_date": "2012-12-31"
    },
    "rebound": {
      "evidence": "descriptive", "n": 150, "recovery": {"q20": 0.483, "q50": 0.82, "q80": 1.628},
      "days_to_high": {"q20": 33.0, "q50": 110.5, "q80": 235.8},
      "a_share": {"n": 86, "recovery": {"q20": 0.47, "q50": 0.879, "q80": 1.892}, "days_to_high": {"q20": 31.0, "q50": 83.0, "q80": 216.0}},
      "current": null, "note": "历史分位，不是预测"
    }
  },
  "evidence_levels": {"dev": "开发段 2000–2018 CPCV 通过", "cal": "校准段 2019–2021 固定校准后成立", "test": "最终测试 2022–2025.08 一次性通过", "none": "预登记检验未通过，仅描述", "rule": "执行规则，非预测", "dev_pending": "开发段评估进行中", "descriptive": "描述已完成月份的状态，非预测"}
}
```

`price_history` 是截至 `asof` 的 OHLCV 序列：`dates`、`open`、`high`、`low`、`close`、`volume` 为等长数组；OHLC 保留 3 位小数，`volume` 为整数或源数据缺失时为 `null`。所有日期均不晚于记录的 `asof`。

`bottom.cheap`、`bottom.confirm`、`bottom.rebound` 是价格层描述量，均按记录自己的 `asof` 截断；它们不调用模型、不作预测，也不提供目标价。`cheap.dd_rank` 只比较当时已确认的 P1 顶→谷事件；PE 分位取满足 1 个月发布滞后的最近 120 个月，至少需要 36 个月。`confirm` 是 LT 规则状态，显示时标注“规则状态，滞后确认，不是预测”。`rebound` 使用 LT 顶→谷对和谷后完整 250 个交易日窗口；所有描述性数字必须同时显示样本数 `n` 与“历史分位，不是预测”。估值地板只通过 `floor_ref` 指向 `top.drawdown_price.valuation_floor`，不得复制或重算。

约束：
1. `asof` 之后的数据不得参与任何字段；前端显示 as-of 与数据冻结版本。
2. 校准段/最终测试段字段在授权运行前一律为 `null` + `evidence: "pending"`。
3. 历史验证面板只展示按样本段汇总的命中率/误报率/Brier；单案例"预测 vs 真实"只能作为图表回放。

4. `regime_band` 只描述上一个已完成月，前端必须标注“描述性、非预测”，不得与顶部/底部概率合并成一个分数（研究层 `research/features/regime_bands.py`）。
