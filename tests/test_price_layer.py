"""P1 回撤情景表：事件定义、分桶分位与契约字段（描述性，不含预测值）。"""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from research.price_layer import drawdown_table as dt

ROOT = Path(__file__).resolve().parents[1]
_PE_CACHES_READY = all(
    (ROOT / "data/cache/valuation" / f"{sym}.parquet").exists()
    for sym in dt.A_SHARE
    if sym not in dt.FLOOR_MISMATCH
)


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


@pytest.mark.skipif(not _PE_CACHES_READY, reason="需要已有估值 PE 缓存")
def test_asof_build_uses_only_confirmed_events_and_pit_pe():
    asof = "2015-06-12"
    rec = dt.build(asof)
    assert rec["n_events"] < dt.build()["n_events"]
    for event in rec["events"]:
        lp = dt.load_logp(event["sym"])
        lp = lp.loc[lp.index <= pd.Timestamp(asof)]
        peaks, _ = dt.qualified_turns(lp.to_numpy())
        peaks = peaks[peaks + dt.TURN_WINDOW <= len(lp) - 1]
        top = lp.index.get_loc(pd.Timestamp(event["top"]))
        trough = lp.index.get_loc(pd.Timestamp(event["trough"]))
        next_top = next(i for i in peaks if i > top)
        cutoff = lp.index[-dt.TURN_WINDOW - 1]
        assert lp.index[top] <= cutoff
        assert lp.index[trough] <= cutoff
        assert lp.index[next_top] <= cutoff

    floor = rec["valuation_floor"]["sh000001"]
    if floor and "pe_date" in floor:
        assert pd.Timestamp(floor["pe_date"]) + pd.DateOffset(months=dt.LAG_MONTHS) <= pd.Timestamp(asof)
        assert pd.Timestamp(floor["close_date"]) <= pd.Timestamp(asof)


@pytest.mark.parametrize("sym", ["sz399006", "sz399001"])
def test_mismatched_index_pe_has_no_floor(sym):
    floor = dt.valuation_floor(sym, _synthetic())
    assert floor["n"] == 0 and floor["evidence"] == "none"
    assert "floor_band_points" not in floor
    assert "口径不一致" in floor["note"]


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


def test_price_band_contract_field(monkeypatch):
    from research.eval import export_contract

    cell = {
        "n": 7, "n_a": 6,
        "max_dd": {"q20": -0.6, "q50": -0.5, "q80": -0.4},
        "days_to_trough": {"q20": 80, "q50": 120, "q80": 160},
        "a_share": None,
    }
    table = {
        "all": cell,
        "by_run_up": {"100–200%": cell},
        "by_duration": {"1–2 年": cell},
        "by_run_up_x_duration": {"100–200%|1–2 年": cell},
    }
    source = {
        "version": "p1_test", "n_events": 7, "n_events_a": 6,
        "definition": {"min_n_a_share": dt.MIN_N_A},
        "table": table, "valuation_floor": {"sh000001": {"n": 4}},
    }
    monkeypatch.setattr(export_contract, "build_drawdown_table", lambda asof=None: source)

    pb = export_contract._price_band("sh000001", {"size_realized": 1.3, "duration_days": 300, "t1_qualified_standard": True}, "2015-06-12")
    assert pb["value"] is None and pb["evidence"] == "descriptive"
    assert pb["table_asof"] == "2015-06-12"
    assert pb["n_events"] == 7 and pb["n_events_a"] == 6
    assert pb["table"] == table and "events" not in pb["table"]
    assert pb["n"] >= dt.MIN_N_A and pb["max_dd"]["q20"] <= pb["max_dd"]["q80"] <= 0
    assert pb["valuation_floor"]["n"] >= 3
    assert export_contract._price_band("sh000001", {}, "2015-06-12")["bucket"] == "全部"
    assert export_contract._price_band("sh000001", {"size_realized": 1.3, "duration_days": 300, "t1_qualified_standard": False}, "2015-06-12")["bucket"] == "全部"
    assert pb["bucket"] != "全部"
    source["n_events"] = 0
    assert export_contract._price_band("sh000001", {}, "2015-06-12")["evidence"] == "none"


@pytest.mark.skipif(not _PE_CACHES_READY, reason="需要已有估值 PE 缓存")
def test_asof_before_any_event_gives_empty_table_and_no_floor():
    from research.eval.export_contract import _price_band

    rec = dt.build("1981-01-02")
    assert rec["n_events"] == 0 and rec["table"]["all"]["n"] == 0
    pb = _price_band("sh000001", {}, "1981-01-02", 300.0)
    assert pb["value"] is None and pb["evidence"] == "none" and pb["bucket"] == "全部"
    floor = pb["valuation_floor"]
    assert floor is None or (floor["evidence"] == "none" and "floor_band_points" not in floor)


def test_floor_with_fewer_than_three_troughs_is_no_evidence(monkeypatch):
    monkeypatch.setattr(dt, "load_pe", lambda sym: pd.Series([10.0], index=pd.DatetimeIndex(["2000-01-31"])))
    floor = dt.valuation_floor("sh000001", _synthetic())
    assert floor["evidence"] == "none" and floor["n"] < 3 and "floor_band_points" not in floor
