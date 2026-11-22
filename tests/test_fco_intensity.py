import pandas as pd

from research.eval import export_contract


def _synthetic_history_frame(monkeypatch, ns, box, scale_windows):
    date = pd.Timestamp("2024-06-28")
    d = pd.DataFrame({
        "date": [date] * len(ns),
        "n": ns,
        "ahead": [1.0] * len(ns),
        "sse": [0.01] * len(ns),
    })
    r = pd.DataFrame({"box": box}, index=d.index)
    sw = pd.DataFrame(scale_windows, columns=["scale", "q20", "q80"])
    monkeypatch.setattr(export_contract, "scale_windows", lambda *_args: sw)
    monkeypatch.setattr(
        export_contract,
        "_scale_cluster_records",
        lambda *_args: {scale: [] for scale in export_contract.HISTORY_SCALES},
    )
    cal = pd.bdate_range(date, periods=20)
    return export_contract._history_frame(d, r, date, cal, 100.0, "dev")


def test_history_frame_fco_intensity_uses_all_qualified_windows_in_range(monkeypatch):
    frame = _synthetic_history_frame(
        monkeypatch,
        [125, 127, 130, 252, 253, 255, 500, 505],
        [True, False, True, True, False, True, False, True],
        [{"scale": "6-12m", "q20": 1.0, "q80": 2.0}],
    )

    assert frame["fco_intensity"] == 0.5
    assert frame["conf"] == {"6-12m": 0.667, "12-24m": 0.333}
    assert frame["fco_scales_active"] == 1


def test_history_frame_fco_intensity_is_none_without_in_range_windows(monkeypatch):
    frame = _synthetic_history_frame(
        monkeypatch,
        [126, 505],
        [True, True],
        [],
    )

    assert frame["fco_intensity"] is None
    assert frame["fco_scales_active"] == 0


def test_first_alert_fields_mark_only_new_consecutive_scale_runs():
    frames = [
        {"w": {"6-12m": None, "12-24m": None}},
        {"w": {"6-12m": ["a", "b"], "12-24m": None}},
        {"w": {"6-12m": ["a", "b"], "12-24m": ["c", "d"]}},
        {"w": {"6-12m": None, "12-24m": None}},
        {"w": {"6-12m": None, "12-24m": ["c", "d"]}},
    ]

    export_contract._add_first_alert_fields(frames)

    assert [frame["first_alert_flag"] for frame in frames] == [False, True, True, False, True]
    assert [frame["first_alert_scales"] for frame in frames] == [
        [],
        ["6-12m"],
        ["12-24m"],
        [],
        ["12-24m"],
    ]
