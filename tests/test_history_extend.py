"""历史延续口径：窗口与冻结帧一致（130–500 步长 5）、默认 g3、live 帧带 method 且同口径帧复用。"""
from __future__ import annotations

import copy
import json

import numpy as np
import pandas as pd
import pytest

from research.pipeline import history_extend as he


def _scale_count(lo: int, hi: int) -> int:
    return sum(1 for n in he.EXTEND_WINDOWS if lo < n <= hi)


def test_extend_windows_match_frozen_frames():
    assert he.EXTEND_WINDOWS == tuple(range(130, 501, 5))
    assert he.EXTEND_WINDOWS_LABEL == "130-500/5"
    # 6–12 月 (125, 250]、12–24 月 (250, 500]：与冻结帧相同的 25 / 50 个窗口
    assert _scale_count(125, 250) == 25
    assert _scale_count(250, 500) == 50
    # 阈值 0.05 下两档都至少要 2 / 3 个合格窗口，单个窗口不足以报警
    assert 1 / 25 < 0.05 <= 2 / 25
    assert 2 / 50 < 0.05 <= 3 / 50


def test_default_optimizer_is_g3():
    assert he.DEFAULT_OPT == "g3"


def _setup(tmp_path, monkeypatch, live_method):
    monkeypatch.setattr(he._core, "ALLOW_INSIDE", he._core.ALLOW_INSIDE)  # extend_history 会改这个全局开关，测试结束后还原
    src = json.loads(open("web/mock/data/sh000001_history.json", encoding="utf-8").read())
    base = [f for f in src["frames"] if f.get("split") != "live"][-40:]
    template = next(f for f in src["frames"] if f.get("split") == "live")
    last = pd.Timestamp(base[-1]["asof"])
    cal = pd.bdate_range("2015-01-01", last + pd.Timedelta(days=60))
    rng = np.random.default_rng(0)
    close = 3000 * np.exp(np.cumsum(rng.normal(0, 0.01, len(cal))))
    ohlc = pd.DataFrame({"date": cal, "open": close, "high": close, "low": close, "close": close, "volume": 1.0})
    picked = he._pick_extend_dates(cal, base[-1]["asof"], step=5)
    live = []
    for dt in picked:
        f = copy.deepcopy(template)
        f["asof"] = str(dt.date())
        f["close"] = round(float(close[cal.get_loc(dt)]), 2)
        f.pop("method", None)
        if live_method is not None:
            f["method"] = live_method
        live.append(f)
    payload = {**src, "frames": base + live}
    (tmp_path / "sh000001_history.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(he, "_load_live_ohlc", lambda sym, prefer_git_results=True: ohlc)
    return picked


def test_live_frames_with_same_method_are_reused(tmp_path, monkeypatch):
    picked = _setup(tmp_path, monkeypatch, {"optimizer": "g3", "windows": "130-500/5"})

    def boom(_):
        raise AssertionError("同口径 live 帧不应重算")

    monkeypatch.setattr(he, "_fit_one_date_worker", boom)
    out = json.loads(he.extend_history("sh000001", data_dir=tmp_path).read_text(encoding="utf-8"))
    live = [f for f in out["frames"] if f.get("split") == "live"]
    assert [f["asof"] for f in live] == [str(d.date()) for d in picked]
    assert all(f["method"] == {"optimizer": "g3", "windows": "130-500/5"} for f in live)


@pytest.mark.parametrize("old", [None, {"optimizer": "de_trf", "windows": "130-500/10"}, {"optimizer": "de_trf", "windows": "130-500/5"}])
def test_live_frames_with_other_method_are_recomputed(tmp_path, monkeypatch, old):
    picked = _setup(tmp_path, monkeypatch, old)
    seen = []

    class Stop(Exception):
        pass

    def spy(args):
        seen.append((args[1], args[2], args[3]))
        raise Stop

    monkeypatch.setattr(he, "_fit_one_date_worker", spy)
    with pytest.raises(Stop):
        he.extend_history("sh000001", data_dir=tmp_path)
    assert seen[0] == (picked[0], he.EXTEND_WINDOWS, "g3")


def test_published_live_weeks_survive_when_they_cannot_be_refit(tmp_path, monkeypatch):
    """切换优化器后，行情凑不满 500 日窗口的旧 live 周保留原帧，不从回测里消失。"""
    old = {"optimizer": "de_trf", "windows": "130-500/10"}
    picked = _setup(tmp_path, monkeypatch, old)
    full = he._load_live_ohlc("sh000001")
    short = full.iloc[-(he.EXTEND_WINDOWS[-1] - 50):].reset_index(drop=True)
    monkeypatch.setattr(he, "_load_live_ohlc", lambda sym, prefer_git_results=True: short)

    def boom(_):
        raise AssertionError("窗口不满的截止日不应拟合")

    monkeypatch.setattr(he, "_fit_one_date_worker", boom)
    out = json.loads(he.extend_history("sh000001", data_dir=tmp_path).read_text(encoding="utf-8"))
    live = [f for f in out["frames"] if f.get("split") == "live"]
    assert [f["asof"] for f in live] == [str(d.date()) for d in picked]
    assert all(f["method"] == old for f in live)


def test_superseded_interim_close_is_dropped(tmp_path, monkeypatch):
    """上一轮的临时收盘帧（不在周度采样日上）不留在序列里。"""
    method = {"optimizer": "g3", "windows": "130-500/5"}
    picked = _setup(tmp_path, monkeypatch, method)
    path = tmp_path / "sh000001_history.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    interim = copy.deepcopy(payload["frames"][-1])
    interim["asof"] = str((picked[0] - pd.tseries.offsets.BDay(1)).date())
    payload["frames"].insert(len(payload["frames"]) - len(picked), interim)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    out = json.loads(he.extend_history("sh000001", data_dir=tmp_path).read_text(encoding="utf-8"))
    live = [f["asof"] for f in out["frames"] if f.get("split") == "live"]
    assert live == [str(d.date()) for d in picked]


def test_published_weeks_beyond_a_lagging_feed_are_kept(tmp_path, monkeypatch):
    """行情比已发布帧旧时，行情之后的已发布周不删。"""
    method = {"optimizer": "g3", "windows": "130-500/5"}
    picked = _setup(tmp_path, monkeypatch, method)
    full = he._load_live_ohlc("sh000001")
    lagging = full[full["date"] <= picked[-3]].reset_index(drop=True)
    monkeypatch.setattr(he, "_load_live_ohlc", lambda sym, prefer_git_results=True: lagging)
    out = json.loads(he.extend_history("sh000001", data_dir=tmp_path).read_text(encoding="utf-8"))
    live = [f["asof"] for f in out["frames"] if f.get("split") == "live"]
    assert live == [str(d.date()) for d in picked]


def test_midweek_lagging_feed_does_not_add_a_week(tmp_path, monkeypatch):
    """行情停在周中、其后已有发布帧时，不把行情末日当成多出来的一周。"""
    method = {"optimizer": "g3", "windows": "130-500/5"}
    picked = _setup(tmp_path, monkeypatch, method)
    full = he._load_live_ohlc("sh000001")
    midweek = picked[-3] + pd.tseries.offsets.BDay(2)
    lagging = full[full["date"] <= midweek].reset_index(drop=True)
    monkeypatch.setattr(he, "_load_live_ohlc", lambda sym, prefer_git_results=True: lagging)
    monkeypatch.setattr(he, "_fit_one_date_worker", lambda task: (_ for _ in ()).throw(AssertionError("不应拟合")))
    out = json.loads(he.extend_history("sh000001", data_dir=tmp_path).read_text(encoding="utf-8"))
    live = [f["asof"] for f in out["frames"] if f.get("split") == "live"]
    assert live == [str(d.date()) for d in picked]
