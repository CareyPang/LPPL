import pandas as pd
import pytest

from research.features import lppls_scan
from scripts.merge_scan_parts import merge


def test_shard_dates_interleave_and_cover_everything():
    ds = list(pd.bdate_range("2010-01-01", periods=23))
    assert lppls_scan._shard_dates(ds, "") == (ds, "")
    parts = [lppls_scan._shard_dates(ds, f"{i}/4") for i in range(4)]
    assert [p[1] for p in parts] == ["__part0of4", "__part1of4", "__part2of4", "__part3of4"]
    assert sorted(d for p in parts for d in p[0]) == ds
    assert parts[0][0] == ds[0::4]
    with pytest.raises(ValueError):
        lppls_scan._shard_dates(ds, "4/4")


def test_merge_scan_parts_requires_all_parts_and_sorts(tmp_path):
    cols = ["date", "n", "tc"]
    a = pd.DataFrame([(pd.Timestamp("2010-01-08"), 125, 1.0), (pd.Timestamp("2010-01-08"), 130, 1.0)], columns=cols)
    b = pd.DataFrame([(pd.Timestamp("2010-01-01"), 130, 2.0), (pd.Timestamp("2010-01-01"), 125, 2.0)], columns=cols)
    a.to_parquet(tmp_path / "sh000001__part1of2.parquet")
    with pytest.raises(SystemExit):
        merge(tmp_path)
    b.to_parquet(tmp_path / "sh000001__part0of2.parquet")
    out = merge(tmp_path)
    assert out == {"sh000001": 4}
    m = pd.read_parquet(tmp_path / "sh000001.parquet")
    assert list(m.date.dt.strftime("%Y-%m-%d")) == ["2010-01-01", "2010-01-01", "2010-01-08", "2010-01-08"]
    assert list(m.n) == [125, 130, 125, 130]
