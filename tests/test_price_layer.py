"""P1 回撤情景表：事件定义、分桶分位与契约字段（描述性，不含预测值）。"""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from research.price_layer import drawdown_table as dt

ROOT = Path(__file__).resolve().parents[1]


def _synthetic() -> pd.Series:
    idx = pd.bdate_range("2000-01-03", periods=3200)
    x = np.zeros(len(idx))
    # 200 日跌 −20%（让起点不落在首日）→ 400 日涨 +120% → 300 日跌 −45% → 200 日涨 +50% → 300 日涨 +10% → 300 日跌 −40% → 200 日涨 +40% → 300 日涨 +30%（最后一个顶不计）
    seg = [(200, np.log(0.8)), (400, np.log(2.2)), (300, np.log(0.55)), (200, np.log(1.5)), (300, np.log(1.1)), (300, np.log(0.6)), (200, np.log(1.4)), (1300, np.log(1.3))]
    i = 0
    for n, lr in seg:
        x[i : i + n] = x[i - 1 if i else 0] + np.linspace(lr / n, lr, n)
        i += n
    return pd.Series(x, idx)


def test_top_events_synthetic():
    lp = _synthetic()
    ev = dt.top_events("TEST", lp)
    assert len(ev) == 1  # 第二个顶之后没有新的合格顶，不计
    assert abs(ev[0]["run_up"] - 1.2) < 0.03 and abs(ev[0]["max_dd"] + 0.45) < 0.03
    assert 390 <= ev[0]["dur_days"] <= 410 and 290 <= ev[0]["days_to_trough"] <= 310
    assert ev[0]["dd120"] is not None and ev[0]["dd120"] < 0


def test_summarize_buckets_and_min_n():
    ev = pd.DataFrame([{"market": "A", "run_up": 1.2, "dur_days": 400, "max_dd": -0.4, "days_to_trough": 200, "dd120": -0.2}] * 3
                      + [{"market": "ext", "run_up": 0.3, "dur_days": 100, "max_dd": -0.2, "days_to_trough": 100, "dd120": -0.1}] * 2)
    t = dt.summarize(ev)
    assert t["all"]["n"] == 5 and t["all"]["n_a"] == 3
    assert t["by_run_up"]["100–200%"]["n"] == 3 and t["by_run_up"]["100–200%"]["a_share"] is None  # A 股 n<5 不给
    assert t["by_run_up"]["<50%"]["max_dd"]["q50"] == -0.2
    assert set(t["all"]["max_dd"]) == {"q20", "q50", "q80"}


@pytest.mark.skipif(not dt.OUT_JSON.exists(), reason="需要已生成的情景表")
def test_generated_table_contract():
    rec = json.loads(dt.OUT_JSON.read_text(encoding="utf-8"))
    assert rec["evidence"] == "descriptive" and rec["n_events"] >= 30
    for e in rec["events"]:
        assert e["max_dd"] <= -dt.MIN_DD and e["days_to_trough"] > 0 and e["dur_days"] > 0
    for cell in rec["table"]["by_run_up"].values():
        if cell["n_a"] < dt.MIN_N_A:
            assert cell["a_share"] is None
    for f in rec["valuation_floor"].values():
        if f and "trough_pe" in f:
            assert f["floor_band_points"][0] <= f["floor_band_points"][1]
            assert "预测" not in json.dumps(f, ensure_ascii=False).replace("不是预测", "")


@pytest.mark.skipif(not dt.OUT_JSON.exists(), reason="需要已生成的情景表")
def test_price_band_contract_field():
    from research.eval.export_contract import _price_band

    pb = _price_band("sh000001", {"size_realized": 1.3, "duration_days": 300, "t1_qualified_standard": True})
    assert pb["value"] is None and pb["evidence"] == "descriptive"
    assert pb["n"] >= dt.MIN_N_A and pb["max_dd"]["q20"] <= pb["max_dd"]["q80"] <= 0
    assert pb["valuation_floor"]["n"] >= 3
    assert _price_band("sh000001", {})["bucket"] == "全部"
    assert _price_band("sh000001", {"size_realized": 1.3, "duration_days": 300, "t1_qualified_standard": False})["bucket"] == "全部"
    assert pb["bucket"] != "全部"
