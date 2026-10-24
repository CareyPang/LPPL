import numpy as np
import pandas as pd

from research.eval.metrics import event_metrics


def _oof():
    dates = pd.date_range("2020-01-01", periods=100, freq="B")
    y = np.zeros(100)
    y[20:30] = 1
    y[60:70] = 1
    return pd.DataFrame(dict(date=dates, symbol="a", y=y, p=0.0))


def test_perfect_alerts_hit_all_with_full_lead():
    oof = _oof()
    oof.loc[oof.y == 1, "p"] = 1.0
    m = event_metrics(oof)
    assert m["n_events"] == 2 and m["hit_rate"] == 1.0 and m["lead_med"] == 9 and m["false_alarm_rate"] == 0.0


def test_late_alert_short_lead_and_miss():
    oof = _oof()
    oof.loc[28:29, "p"] = 1.0  # 第一段只在末尾两天报警，第二段漏报
    oof.loc[0:17, "p"] = 0.5  # 段外报警
    m = event_metrics(oof, alert_rate=0.2)
    assert m["hit_rate"] == 0.5 and m["lead_med"] == 1 and m["false_alarm_rate"] > 0


def test_paths_are_not_merged_into_long_segments():
    import pandas as pd

    base = _oof()
    oof = pd.concat([base.assign(path=0), base.assign(path=1)], ignore_index=True)
    oof.loc[oof.y == 1, "p"] = 1.0
    m = event_metrics(oof)
    assert m["n_events"] == 2 and m["lead_med"] == 9
