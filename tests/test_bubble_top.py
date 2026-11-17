import numpy as np
import pandas as pd

from research.labels.bubble_top import BubbleTopParams, bubble_tops, known_tops


def _dates(n):
    return pd.bdate_range("2020-01-01", periods=n)


def _prices(n=40, top_idx=5, top=160, hit_after=10, hit_price=128):
    close = np.full(n, 100.0)
    close[top_idx] = top
    close[top_idx + 1 : top_idx + hit_after] = 130
    close[top_idx + hit_after] = hit_price
    close[top_idx + hit_after + 1 :] = hit_price
    return close


def test_hit_at_ten_days_confirms_only_after_dedup_window():
    dates = _dates(40)
    params = BubbleTopParams(look=3, rise=0.50, dd=0.20, horizon=20, dedup=12)
    tops = bubble_tops(dates, _prices(), params)

    assert len(tops) == 1
    top = tops.iloc[0]
    assert top.top_date == dates[5]
    assert top.dd_hit_date == dates[15]
    assert top.confirm_date == dates[17]
    assert top.status == "confirmed"


def test_new_high_inside_dedup_window_disqualifies_candidate():
    dates = _dates(150)
    close = _prices(n=len(dates))
    close[95:] = 161
    tops = bubble_tops(
        dates,
        close,
        BubbleTopParams(look=3, rise=0.50, dd=0.20, horizon=20, dedup=120),
    )

    assert dates[5] not in set(tops.top_date)


def test_rise_threshold_requires_at_least_fifty_percent():
    dates = _dates(40)
    params = BubbleTopParams(look=4, rise=0.50, dd=0.20, horizon=8, dedup=10)
    below = _prices(top=145, hit_after=1, hit_price=100)
    above = _prices(top=155, hit_after=1, hit_price=100)

    assert dates[5] not in set(bubble_tops(dates, below, params).top_date)
    assert dates[5] in set(bubble_tops(dates, above, params).top_date)


def test_incomplete_dedup_window_exports_pending_top_not_known_at_any_asof():
    dates = _dates(106)
    tops = bubble_tops(
        dates,
        _prices(n=len(dates)),
        BubbleTopParams(look=3, rise=0.50, dd=0.20, horizon=20, dedup=120),
    )

    assert len(tops) == 1
    assert tops.iloc[0].status == "pending"
    assert pd.isna(tops.iloc[0].confirm_date)
    assert known_tops(tops, dates[-1]).empty


def test_unreached_drawdown_with_incomplete_horizon_is_pending():
    dates = _dates(20)
    close = np.full(len(dates), 130.0)
    close[:5] = 100
    close[5] = 160
    tops = bubble_tops(
        dates,
        close,
        BubbleTopParams(look=3, rise=0.50, dd=0.20, horizon=20, dedup=120),
    )

    assert len(tops) == 1
    assert tops.iloc[0].status == "pending"
    assert pd.isna(tops.iloc[0].dd_hit_date)
    assert pd.isna(tops.iloc[0].confirm_date)


def test_known_tops_starts_on_confirmation_date():
    dates = _dates(40)
    tops = bubble_tops(
        dates,
        _prices(),
        BubbleTopParams(look=3, rise=0.50, dd=0.20, horizon=20, dedup=12),
    )
    confirm = tops.iloc[0].confirm_date

    assert known_tops(tops, confirm - pd.Timedelta(days=1)).empty
    assert len(known_tops(tops, confirm)) == 1


def test_stock_preset_requires_one_hundred_percent_rise_and_thirty_percent_drawdown():
    params = BubbleTopParams.stock()
    dates = _dates(400)

    def prices(top):
        close = np.full(len(dates), 100.0)
        close[250] = top
        close[251:260] = top * 0.90
        close[260:] = top * 0.70
        return close

    assert params.rise == 1.00
    assert params.dd == 0.30
    assert params.preset == "stock"
    assert dates[250] not in set(bubble_tops(dates, prices(199), params).top_date)
    stock_tops = bubble_tops(dates, prices(200), params)
    assert dates[250] in set(stock_tops.top_date)
    assert np.isclose(stock_tops.loc[stock_tops.top_date == dates[250], "dd_pct_60"].iloc[0], 0.30)


def test_look500_detects_slow_rise_missed_by_look250():
    dates = _dates(700)
    close = np.concatenate((np.linspace(100, 180, 501), np.full(9, 180.0), np.full(190, 144.0)))
    main = bubble_tops(dates, close, BubbleTopParams())
    look500 = bubble_tops(dates, close, BubbleTopParams(look=500))

    assert main.empty
    assert len(look500) == 1
    assert look500.iloc[0].top_date == dates[500]
    assert look500.iloc[0].status == "confirmed"


def test_equal_tops_within_dedup_keep_the_earlier_day():
    dates = _dates(40)
    close = _prices()
    close[6] = close[5]
    tops = bubble_tops(
        dates,
        close,
        BubbleTopParams(look=3, rise=0.50, dd=0.20, horizon=20, dedup=12),
    )

    assert list(tops.top_date) == [dates[5]]
