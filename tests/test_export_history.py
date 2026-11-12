import json
from pathlib import Path

import numpy as np
import pytest

from research.eval import export_contract
from research.price_layer.drawdown_table import LOOK, load_logp

_HISTORY_INPUTS_READY = all(
    (folder / "sh000001.parquet").exists()
    for folder in export_contract.HISTORY_SCANS.values()
) and Path("web/mock/data/sh000001_2015-06-12.json").exists()


@pytest.mark.skipif(not _HISTORY_INPUTS_READY, reason="需要三段 LPPLS 扫描数据")
def test_history_contract_and_replay_window_consistency():
    rec = export_contract.history("sh000001")
    frames = rec["frames"]
    asofs = [frame["asof"] for frame in frames]
    assert asofs == sorted(asofs)
    assert set(frame["split"] for frame in frames) <= {"dev", "cal", "test"}

    for frame in frames:
        for value in frame["conf"].values():
            assert value is None or 0 <= value <= 1
        for window in frame["w"].values():
            assert window is None or (len(window) == 2 and window[0] <= window[1])

    tops = [top["date"] for top in rec["tops"]]
    assert tops == sorted(tops)
    assert "2021-09-13" in tops
    logp_series = load_logp("sh000001")
    logp = logp_series.to_numpy()
    positions = {str(date.date()): i for i, date in enumerate(logp_series.index)}
    for top in rec["tops"]:
        i = positions[top["date"]]
        assert i + LOOK <= len(logp) - 1
        expected = round(float(np.exp(logp[i + 1 : i + LOOK + 1].min() - logp[i]) - 1), 3)
        assert top["max_dd"] == expected

    frame_2015 = next((frame for frame in frames if frame["asof"] == "2015-06-12"), None)
    assert frame_2015 is not None
    replay = json.loads(Path("web/mock/data/sh000001_2015-06-12.json").read_text(encoding="utf-8"))
    scale_window = next(window for window in replay["top"]["scale_windows"] if window["scale"] == "6-12m")
    assert frame_2015["w"]["6-12m"] == [scale_window["q20_date"], scale_window["q80_date"]]
    assert frame_2015["close"] == round(replay["price_history"]["close"][-1], 2)


def test_to_cal_extrapolates_beyond_calendar_end():
    """as-of 为最后一个交易日时，未来 t_c 不能被截到 as-of 当天，而要按工作日外推。"""
    import pandas as pd

    from research.eval.export_contract import _to_cal

    cal = pd.bdate_range("2024-01-01", periods=300)
    assert _to_cal(cal, cal[200], 30.0) == str(cal[230].date())
    assert _to_cal(cal, cal[-1], 0.0) == str(cal[-1].date())
    assert _to_cal(cal, cal[-1], 1.0) == str(pd.bdate_range(cal[-1], periods=2)[-1].date())
    assert _to_cal(cal, cal[-1], 30.0) == str(pd.bdate_range(cal[-1], periods=31)[-1].date())
    assert _to_cal(cal, cal[-1], 29.6) == _to_cal(cal, cal[-1], 30.0)
    assert _to_cal(cal, cal[5], -10.0) == str(cal[0].date())


def _fits_frame(rows):
    """rows: (n, m, w, ahead)；其余列取能通过/不通过规则无关的固定值。"""
    import pandas as pd

    recs = []
    for n, m, w, ahead in rows:
        recs.append({"date": pd.Timestamp("2024-06-28"), "n": n, "tc": n - 1 + ahead, "m": m, "w": w, "A": 5.0, "B": -0.3,
                     "C1": 0.02, "C2": 0.01, "sse": 0.01 * n, "r2": 0.8, "pow_tc": n - 1 + ahead, "pow_m": m, "pow_B": -0.3,
                     "pow_sse": 0.02 * n, "lomb_w": w, "lomb_pn": 10.0, "df_t": -3.0, "y_std": 0.1})
    return pd.DataFrame(recs)


def test_current_and_history_representative_uses_adjusted_sse_and_keeps_index(
    monkeypatch,
):
    import pandas as pd

    from research.eval.export_contract import FCO_SETS, _derived

    date = pd.Timestamp("2024-06-28")
    fits = _fits_frame(
        [(30, 0.4, 8.0, 10.0), (40, 0.7, 8.0, 20.0), (50, 1.0, 8.0, 30.0)]
    )
    fits["sse"] = [30.0, 6.6, 30.0]
    d = _derived(fits)
    d.index = [11, 37, 92]
    r = pd.DataFrame({"box": [True, True, True]}, index=d.index)
    cal = pd.bdate_range("2022-01-03", periods=800)
    ohlc = pd.DataFrame({"date": cal, "close": 100.0})
    seen = []
    real_scenarios = export_contract.scenarios

    def tracked_scenarios(q):
        seen.append((list(q.columns), list(q.index)))
        return real_scenarios(q)

    monkeypatch.setattr(export_contract, "scenarios", tracked_scenarios)
    monkeypatch.setattr(
        export_contract,
        "grid_rules",
        lambda rows: pd.DataFrame(
            {column: False for column in FCO_SETS.values()}, index=rows.index
        ),
    )
    monkeypatch.setattr(
        export_contract,
        "_conf",
        lambda *_args: {scale: None for scale in export_contract.HISTORY_SCALES},
    )
    monkeypatch.setattr(export_contract, "scale_windows", lambda *_args: pd.DataFrame())
    monkeypatch.setattr(export_contract, "regime_bands", lambda *_args: pd.DataFrame())
    monkeypatch.setattr(export_contract, "_indicators", lambda *_args: {})
    monkeypatch.setattr(export_contract, "_bubble", lambda *_args: {})
    monkeypatch.setattr(export_contract, "_bottom_objects", lambda *_args: {})
    monkeypatch.setattr(export_contract, "_combo", lambda *_args: {})
    monkeypatch.setattr(export_contract, "_tc_distribution", lambda *_args: {})
    monkeypatch.setattr(export_contract, "_negative", lambda *_args: {})
    monkeypatch.setattr(export_contract, "_price_band", lambda *_args: {})
    monkeypatch.setattr(export_contract, "_price_history", lambda *_args: {})
    monkeypatch.setattr(export_contract, "_curve", lambda *_args: {})

    current = export_contract.build_record("sh000001", str(date.date()), d, r, cal, ohlc)
    historical = export_contract._history_frame(
        d, r, date, cal, 100.0, "dev", include_scenarios=True
    )

    assert seen == [
        (["n", "ahead", "sse"], [11, 37, 92]),
        (["n", "ahead", "sse"], [11, 37, 92]),
    ]
    for scenarios in (current["top"]["scenarios"], historical["scenarios"]):
        representative = scenarios[0]["representative"]
        assert scenarios[0]["representative_rule"] == "minimum_sse_over_n_minus_7"
        assert representative["m"] == 0.7
        assert representative["loss"] == round(6.6 / (40 - 7), 6)


def test_indicators_boundary_share_and_display_only():
    import pandas as pd

    from research.features.lppls_rules import _derived, grid_rules, rules
    from research.features.lppls_scan import BOX, BOXES

    bx = BOXES[BOX]
    assert BOX == "v2" and bx["tc"] == (-0.2, 0.2)
    cal = pd.bdate_range("2022-01-03", periods=700)
    date = pd.Timestamp("2024-06-28")
    assert date in cal
    # 6–12m 档 4 窗：一窗 m 撞上界 2.0、一窗 t_c 撞 +0.2dt、一窗 ω 撞下界 1.0、一窗在域内；2–4w 档 2 窗
    rows = [(127, 2.0, 8.0, 10.0), (152, 0.5, 8.0, 0.2 * 151), (177, 0.5, 1.0, 5.0), (202, 0.5, 8.0, 5.0),
            (10, 0.5, 8.0, 1.0), (20, 0.5, 8.0, 1.0)]
    dd = _derived(_fits_frame(rows))
    rr, gg = rules(dd), grid_rules(dd)
    ind = export_contract._indicators(dd, rr, gg, cal, date)

    b = ind["6-12m"]["boundary_share"]
    assert b["m_hi"] == 0.25 and b["tc_hi"] == 0.25 and b["w_lo"] == 0.25 and b["any"] == 0.75
    assert b["m_lo"] == 0.0 and b["tc_lo"] == 0.0 and b["w_hi"] == 0.0 and b["tol"] == export_contract.BOUNDARY_TOL
    assert ind["6-12m"]["display_only"] is False
    assert ind["6-12m"]["signal_status"] in ("signal", "no_qualified_fit")

    assert ind["2-4w"]["display_only"] is True
    assert ind["2-4w"]["signal_status"] == "display_only"
    assert ind["2-4w"]["n_windows"] == 2 and "confidence" in ind["2-4w"]
    assert ind["2-6y"] == {"signal_status": "not_computed", "direction": "positive", "display_only": False}


def test_null_fpr_reads_calibration_table(tmp_path, monkeypatch):
    import pandas as pd

    tbl = pd.DataFrame([
        {"scale": "6-12m", "kind": "gbm0", "standard": 0.053, "box": 0.03, "asof_standard_gt0": 0.14},
        {"scale": "6-12m", "kind": "block_boot", "standard": 0.09, "box": 0.026, "asof_standard_gt0": 0.26},
        {"scale": "6-12m", "kind": "gbm_drift", "standard": 0.31, "box": 0.082, "asof_standard_gt0": 0.53},
        {"scale": "6-12m", "kind": "powerlaw", "standard": 0.384, "box": 0.114, "asof_standard_gt0": 0.72},
    ])
    p = tmp_path / "null.csv"
    tbl.to_csv(p, index=False)
    monkeypatch.setattr(export_contract, "NULL_FPR_PATH", p)
    monkeypatch.setattr(export_contract, "_NULL_FPR_CACHE", {})
    out = export_contract._null_fpr("6-12m")
    assert out["standard"] == {"gbm0": 0.053, "block_boot": 0.09, "gbm_drift": 0.31}
    assert out["box"]["gbm_drift"] == 0.082 and out["asof_standard_gt0"]["block_boot"] == 0.26
    assert export_contract._null_fpr("2-6y") is None

    monkeypatch.setattr(export_contract, "NULL_FPR_PATH", tmp_path / "missing.csv")
    monkeypatch.setattr(export_contract, "_NULL_FPR_CACHE", {})
    assert export_contract._null_fpr("6-12m") is None
