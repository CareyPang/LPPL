"""§21.4 (d) Ising 代理与 §21.5 (e) 价格层开发段评价的单元测试（离线、合成数据）。"""
import numpy as np
import pandas as pd

from research.features import ising
from research.price_layer import e_dev


def test_chi_mean_pairwise_correlation_identical_and_independent():
    td = pd.bdate_range("2015-01-01", periods=200)
    rng = np.random.default_rng(0)
    base = rng.normal(size=len(td)).cumsum()
    common = {f"s{i}": pd.Series(base, index=td) for i in range(5)}
    indep = {f"s{i}": pd.Series(rng.normal(size=len(td)).cumsum(), index=td) for i in range(5)}
    for series, lo, hi in ((common, 0.99, 1.01), (indep, -0.3, 0.3)):
        import research.features.ising as m

        orig = m.price_series
        m.price_series = lambda s, series=series: series[s]
        try:
            c = ising.chi(list(series), td, win=60, min_names=3).dropna()
        finally:
            m.price_series = orig
        assert len(c) == len(td) - 60
        assert lo <= c.mean() <= hi


def test_phi_ffill_is_pit_and_fraction(tmp_path, monkeypatch):
    # 两只股票、两个 as-of；只有 s1 在 6–12m 有 STANDARD 窗口（B<0, m∈(0,1], ω∈[2,25], D≥0.5, osc≥2.5）
    cols = ["date", "n", "tc", "m", "w", "A", "B", "C1", "C2", "sse", "r2", "pow_tc", "pow_m", "pow_B", "pow_sse", "lomb_w", "lomb_pn", "df_t"]
    good = dict(n=200, tc=205, m=0.5, w=8.0, A=1, B=-1.0, C1=0.01, C2=0.01, sse=1, r2=0.9, pow_tc=205, pow_m=0.5, pow_B=-1, pow_sse=1, lomb_w=8, lomb_pn=0, df_t=0)
    bad = dict(good, B=1.0)
    d0, d1 = pd.Timestamp("2015-01-05"), pd.Timestamp("2015-02-02")
    for name, row in (("s1", good), ("s2", bad)):
        rows = [dict(row, date=d0), dict(row, date=d1), dict(bad, date=d0, n=300, tc=305), dict(bad, date=d1, n=300, tc=305)]
        pd.DataFrame(rows)[cols].to_parquet(tmp_path / f"{name}.parquet")
    monkeypatch.setattr(ising, "STK", tmp_path)
    td = pd.bdate_range("2015-01-01", "2015-03-01")
    p = ising.phi(td)
    assert np.isnan(p.loc[pd.Timestamp("2015-01-02"), "phi_6_12"])  # 第一个 as-of 之前无值
    assert p.loc[d0, "phi_6_12"] == 0.5 and p.loc[d0 + pd.Timedelta(days=7), "phi_6_12"] == 0.5  # 前向填充
    assert p.loc[d0, "phi_12_24"] == 0.0


def test_q_none_bm_limits_and_monotone():
    assert e_dev.q_none_bm(1e-6) < 1e-6
    assert e_dev.q_none_bm(6.0) > 0.999
    ks = np.linspace(0.2, 3, 15)
    v = [e_dev.q_none_bm(k) for k in ks]
    assert all(0 <= x <= 1 for x in v) and np.all(np.diff(v) > 0)
    # 与蒙特卡洛比对（k=1）
    rng = np.random.default_rng(1)
    W = rng.normal(size=(20000, 2000)).cumsum(axis=1) / np.sqrt(2000)
    mc = (np.abs(W).max(axis=1) < 1).mean()
    assert abs(mc - e_dev.q_none_bm(1.0)) < 0.02


def test_ft_panel_outcomes_on_synthetic_path(tmp_path, monkeypatch):
    td = pd.bdate_range("2001-01-01", periods=600)
    rng = np.random.default_rng(3)
    close = 100 * np.exp(rng.normal(0, 0.01, len(td)).cumsum())
    df = pd.DataFrame(dict(date=td, open=close, high=close * 1.004, low=close * 0.996, close=close))
    (tmp_path / "f").mkdir()
    df.to_parquet(tmp_path / "f" / "x_qfq.parquet", index=False)
    pd.DataFrame(dict(well_F=1.0, well_depth=0.1, well_dist_below=0.05), index=td).to_parquet(tmp_path / "x.parquet")
    monkeypatch.setattr(e_dev, "FROZEN", tmp_path / "f")
    monkeypatch.setattr(e_dev, "WELLS", tmp_path)
    monkeypatch.setattr(e_dev, "START", td[0])
    monkeypatch.setattr(e_dev, "END", td[-1])
    H = 20
    f = e_dev.ft_panel("x", 1, H)
    assert set(f.outcome.unique()) <= {-1, 0, 1, 2} and len(f) > 50
    assert (f.yend <= td[-1]).all()
    # 手工复核一个 as-of 的结果
    t = f.index[10]
    i = td.get_loc(t)
    U, L = close[i] * np.exp(f.sig.iloc[10] * np.sqrt(H)), close[i] * np.exp(-f.sig.iloc[10] * np.sqrt(H))
    exp = 2
    for j in range(i + 1, i + H + 1):
        up, dn = close[j] * 1.004 >= U, close[j] * 0.996 <= L
        if up and dn:
            exp = -1
            break
        if up or dn:
            exp = 0 if up else 1
            break
    assert f.outcome.iloc[10] == exp
