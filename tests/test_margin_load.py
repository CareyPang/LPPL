import pandas as pd

from research.data.margin import load_margin


def test_load_margin_merges_and_lags(tmp_path):
    d = pd.to_datetime(["2015-01-05", "2015-01-06", "2015-01-07"])
    pd.DataFrame(dict(date=d, fin_balance=[1.0, 2.0, 3.0], fin_buy=[1, 1, 1], sec_qty=0, sec_balance=0, sec_sell_qty=0,
                      total_balance=[1.0, 2.0, 3.0])).to_parquet(tmp_path / "sse_margin.parquet")
    pd.DataFrame({"date": d[:2], "融资余额": [10.0, 20.0], "融资买入额": [1, 1], "融券卖出量": 0, "融券余量": 0,
                  "融券余额": 0, "融资融券余额": [10.0, 20.0]}).to_parquet(tmp_path / "szse_margin.parquet")
    m = load_margin(tmp_path)
    assert m.fin_balance_all.tolist()[:2] == [11.0, 22.0]
    assert pd.isna(m.fin_balance_all.iloc[2])
    assert m.avail_date.iloc[0] == d[1] and pd.isna(m.avail_date.iloc[2])
