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
