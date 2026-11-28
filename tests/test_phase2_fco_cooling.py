import numpy as np
import pandas as pd

from research.eval import episode_backtest, export_contract
from research.features import lppls_scan
from research.optim.optimizers import METHODS, de_trf


def _synthetic_lppls(n: int = 160) -> np.ndarray:
    t = np.arange(n, dtype=float)
    dt = n + 12.0 - t
    y = 5.0 - 0.02 * dt**0.5 * (1 + 0.05 * np.cos(8.0 * np.log(dt)))
    return y + np.random.default_rng(7).normal(0, 0.002, n)


def test_de_trf_deterministic_and_registered():
    assert "de_trf" in METHODS
    assert lppls_scan.OPTIMIZER_NAMES["de_trf"] == "de_trf"

    y = _synthetic_lppls()
    row1 = lppls_scan.fit_one(y, opt="de_trf")
    row2 = lppls_scan.fit_one(y, opt="de_trf")

    np.testing.assert_allclose(row1[1:4], row2[1:4], rtol=0, atol=1e-12)
    assert np.isclose(row1[8], row2[8], rtol=0, atol=1e-12)
    assert row1[8] < 0.02

    # 支持 warm_starts 且结果不劣于无热启动
    t = np.arange(len(y), dtype=float)
    lo = np.array([len(y) - 1 + 0.5, 0.1, 6.0])
    hi = np.array([len(y) - 1 + 32.0, 0.9, 13.0])
    base = de_trf(t, y, lo, hi, seed=0)
    warm = de_trf(t, y, lo, hi, seed=0, warm_starts=[base.theta])
    assert warm.sse <= base.sse + 1e-12


def test_daily_fit_asof_de_trf_uses_adjacent_warm_starts(monkeypatch):
    from research.pipeline import daily

    dates = pd.bdate_range("2024-01-02", periods=160)
    logp = pd.Series(np.linspace(1.0, 2.0, len(dates)), index=dates)
    seen = []

    def fake_fit_one(y, opt=None, warm_starts=None):
        seen.append((len(y), opt, warm_starts))
        n = len(y)
        base_row = [n, float(n - 1 + 10.0), 0.5, 8.0]
        return tuple(base_row + [0.0] * (len(daily.COLS) - 1 - len(base_row)))

    monkeypatch.setattr(daily, "fit_one", fake_fit_one)
    daily.fit_asof(logp, dates[-1], (60, 80, 100), opt="de_trf")

    assert seen[0] == (60, "de_trf", None)
    assert seen[1][0] == 80 and seen[1][1] == "de_trf"
    assert seen[1][2] == [(89.0, 0.5, 8.0)]
    assert seen[2][0] == 100 and seen[2][1] == "de_trf"
    assert seen[2][2] == [(109.0, 0.5, 8.0)]


def test_fco_intensity_and_cooling_state_pit():
    intensity0, active0 = export_contract._fco_intensity({"6-12m": 0.0, "12-24m": 0.0}, {"6-12m": [], "12-24m": []})
    assert intensity0 == 0.0 and active0 == 0

    intensity1, active1 = export_contract._fco_intensity(
        {"6-12m": 0.30, "12-24m": 0.25},
        {"6-12m": [{"share": 0.8}], "12-24m": [{"share": 0.6}]},
    )
    assert 0.5 <= intensity1 <= 1.0
    assert active1 == 2

    cal = pd.bdate_range("2025-01-02", periods=90)
    # 前 60 天上涨到 150，随后急跌（余震）
    prices = np.concatenate([
        np.linspace(100.0, 150.0, 60),
        np.array([144.0, 138.0, 132.0, 128.0, 125.0, 121.0, 118.0, 117.0, 116.0, 115.0]),
        np.linspace(115.0, 112.0, 20),
    ])
    ohlc = pd.DataFrame({"date": cal, "close": prices})
    asof_aftershock = cal[66]

    # 1) 顶部聚类活跃 -> active_top
    cs_active = export_contract._cooling_state(
        ohlc,
        cal,
        asof_aftershock,
        {"6-12m": {"confidence": {"box": 0.22}}, "12-24m": {"confidence": {"box": 0.0}}},
        {"start": "2025-04-10", "end": "2025-05-01"},
        None,
        {"bucket": "mid"},
    )
    assert cs_active["phase"] == "active_top"
    assert cs_active["reentry_ready"] is False

    # 2) 顶部置信度归零但处于余震冷却期 -> cooling_after_top
    cs_cool = export_contract._cooling_state(
        ohlc,
        cal,
        asof_aftershock,
        {"6-12m": {"confidence": {"box": 0.0}}, "12-24m": {"confidence": {"box": 0.0}}},
        {"start": None, "end": None},
        None,
        {"bucket": "mid"},
    )
    assert cs_cool["phase"] == "cooling_after_top"
    assert cs_cool["top_conf_cleared"] is True
    assert cs_cool["omori_aftershock_active"] is True
    assert cs_cool["reentry_ready"] is False

    # 3) 严格 Point-in-Time：修改 asof 之后的价格不影响 asof 当天的 cooling_state
    ohlc_mut = ohlc.copy()
    ohlc_mut.loc[ohlc_mut["date"] > asof_aftershock, "close"] = 500.0
    cs_cool_mut = export_contract._cooling_state(
        ohlc_mut,
        cal,
        asof_aftershock,
        {"6-12m": {"confidence": {"box": 0.0}}, "12-24m": {"confidence": {"box": 0.0}}},
        {"start": None, "end": None},
        None,
        {"bucket": "mid"},
    )
    assert cs_cool == cs_cool_mut

    # 4) 经过 >20 交易日且低波动阴跌后 -> reentry_watch
    cs_watch = export_contract._cooling_state(
        ohlc,
        cal,
        cal[-1],
        {"6-12m": {"confidence": {"box": 0.0}}, "12-24m": {"confidence": {"box": 0.0}}},
        {"start": None, "end": None},
        None,
        {"bucket": "deep"},
    )
    assert cs_watch["phase"] == "reentry_watch"
    assert cs_watch["reentry_ready"] is True


def test_episode_backtest_extract_and_null_baseline():
    frames = [
        {"asof": "2024-01-05", "split": "test", "w": {"6-12m": None}, "clusters": {"6-12m": []}, "fco_intensity": 0.0},
        {"asof": "2024-01-12", "split": "test", "w": {"6-12m": ["2024-02-01", "2024-03-01"]}, "clusters": {"6-12m": []}, "fco_intensity": 0.62},
        {"asof": "2024-01-19", "split": "test", "w": {"6-12m": ["2024-02-05", "2024-03-05"]}, "clusters": {"6-12m": []}, "fco_intensity": 0.78},
        {"asof": "2024-01-26", "split": "test", "w": {"6-12m": None}, "clusters": {"6-12m": []}, "fco_intensity": 0.0},
        {"asof": "2024-05-03", "split": "test", "w": {"6-12m": ["2024-05-20", "2024-06-15"]}, "clusters": {"6-12m": []}, "fco_intensity": 0.55},
        {"asof": "2024-05-10", "split": "test", "w": {"6-12m": None}, "clusters": {"6-12m": []}, "fco_intensity": 0.0},
    ]
    tops = [
        {"date": "2024-02-20", "max_dd": -0.18},
        {"date": "2024-06-25", "max_dd": -0.22},
    ]

    res = episode_backtest.evaluate_episodes(frames, tops, scale="6-12m", buffer_days=15, n_perm=100, seed=42)
    assert res["n_episodes"] == 2
    assert res["hit_rate_exact"] == 0.5
    assert res["hit_rate_buffered"] == 1.0
    assert res["median_days_to_top"] == 46.0
    assert 0.0 <= res["null_hit_rate_buffered"] <= 1.0
    assert 0.0 < res["p_value_buffered"] <= 1.0
    assert res["episodes"][0]["first_asof"] == "2024-01-12"
    assert res["episodes"][0]["weeks"] == 2
    assert res["episodes"][0]["max_fco_intensity"] == 0.78


def test_bottom_dashboard_pit_and_three_layers(tmp_path):
    """模块二六维说人话仪表盘：验证严格 PIT（不读取未来快照）、死猫跳拦截与三层达标合成。"""
    import json

    from research.eval.bottom_dashboard import build_bottom_dashboard

    cal = pd.bdate_range("2024-01-02", periods=140)
    # 阶段 1: 涨到 150 -> 急跌到 110 -> 缩量企稳并站上 20 日线
    prices = np.concatenate([
        np.linspace(100.0, 150.0, 60),
        np.linspace(146.0, 110.0, 15),
        np.linspace(110.0, 111.0, 45),
        np.linspace(111.5, 118.0, 20),
    ])
    vols = np.concatenate([
        np.full(60, 1000.0),
        np.full(15, 1600.0),
        np.full(55, 350.0),  # 缩量地量（含近 20 日内）
        np.full(10, 650.0),  # 最近 10 日温和放量站上20日线
    ])
    ohlc = pd.DataFrame({"date": cal, "close": prices, "amount": vols})
    asof = cal[-1]
    close_pit = pd.Series(prices, index=cal)

    # 1. 构造合规 PIT 快照（asof 与当前日一致），三层全部绿灯
    bs_path = tmp_path / "bs.json"
    bs_path.write_text(json.dumps({
        "asof": asof.strftime("%Y-%m-%d"),
        "current": {"erp": 6.8, "erp_pct": 0.90, "pbn_pct": 0.14},
    }), encoding="utf-8")
    etf_path = tmp_path / "etf.json"
    etf_path.write_text(json.dumps({
        "asof": asof.strftime("%Y-%m-%d"),
        "categories": [{"category": "沪深300", "d5_bn": 12.5, "d21_bn": 28.0}],
    }), encoding="utf-8")
    br_path = tmp_path / "br.json"
    br_path.write_text(json.dumps({
        "asof": asof.strftime("%Y-%m-%d"),
        "latest": {"above_ma20": 0.55},
    }), encoding="utf-8")

    dash = build_bottom_dashboard(
        ohlc, close_pit, asof, has_active_top=False,
        bottom_signal_path=bs_path, nt_etf_path=etf_path, breadth_path=br_path,
        margin_path=tmp_path / "missing_margin.parquet",
    )
    assert len(dash["dimensions"]) == 6
    assert dash["layers"]["odds"] is True
    assert dash["layers"]["clearing"] is True
    assert dash["layers"]["right_side"] is True
    assert dash["verdict"] == "reentry_green"
    assert dash["verdict_light"] == "green"
    # 缺失的两融缓存应优雅降级为 gray，而非报错
    margin_dim = next(d for d in dash["dimensions"] if d["id"] == "margin")
    assert margin_dim["light"] == "gray"

    # 2. 严格 PIT：若快照日期晚于 asof，必须被拒绝（不得发生未来泄漏）
    future_bs = tmp_path / "bs_future.json"
    future_bs.write_text(json.dumps({
        "asof": (asof + pd.Timedelta(days=5)).strftime("%Y-%m-%d"),
        "current": {"erp": 7.5, "erp_pct": 0.98, "pbn_pct": 0.20},
    }), encoding="utf-8")
    dash_pit = build_bottom_dashboard(
        ohlc, close_pit, asof, has_active_top=False,
        bottom_signal_path=future_bs, nt_etf_path=tmp_path / "none.json",
        breadth_path=tmp_path / "none2.json", margin_path=tmp_path / "none3.parquet",
    )
    erp_dim = next(d for d in dash_pit["dimensions"] if d["id"] == "erp")
    assert erp_dim["light"] == "gray"
    assert erp_dim["passed_bottom"] is False


def test_bottom_dashboard_dead_cat_bounce_blocked(tmp_path):
    """死猫跳二次破底必须被 Omori 防线拦截为 red / cooling_aftershock。"""
    from research.eval.bottom_dashboard import build_bottom_dashboard

    cal = pd.bdate_range("2024-01-02", periods=95)
    # 急涨 -> 急跌 -> 小幅反抽（死猫跳） -> 再次急杀破前低
    prices = np.concatenate([
        np.linspace(100.0, 160.0, 55),
        np.linspace(155.0, 125.0, 15),
        np.linspace(126.0, 134.0, 15),  # 死猫跳反抽
        np.array([130, 127, 124, 122, 121, 119, 117, 115, 113, 110], dtype=float),  # 再次破底
    ])
    ohlc = pd.DataFrame({"date": cal, "close": prices, "amount": np.full(len(cal), 800.0)})
    asof = cal[-1]
    dash = build_bottom_dashboard(
        ohlc, pd.Series(prices, index=cal), asof, has_active_top=False,
        bottom_signal_path=tmp_path / "x.json", nt_etf_path=tmp_path / "y.json",
        breadth_path=tmp_path / "z.json", margin_path=tmp_path / "m.parquet",
    )
    assert dash["omori"]["dead_cat_risk"] is True
    assert dash["omori"]["active"] is True
    assert dash["verdict"] == "aftershock_block"
    assert dash["verdict_light"] == "red"


def test_summarize_history_episodes_with_splits():
    """模块三：summarize_history_episodes 输出 6-12m/12-24m 与 dev/cal/test 分段摘要。"""
    from research.eval import episode_backtest

    frames = [
        {"asof": "2015-04-10", "split": "dev", "w": {"6-12m": ["2015-05-15", "2015-06-20"]}, "clusters": {"6-12m": []}},
        {"asof": "2015-04-17", "split": "dev", "w": {"6-12m": None}, "clusters": {"6-12m": []}},
        {"asof": "2024-01-12", "split": "test", "w": {"6-12m": ["2024-02-01", "2024-03-01"]}, "clusters": {"6-12m": []}},
        {"asof": "2024-01-19", "split": "test", "w": {"6-12m": None}, "clusters": {"6-12m": []}},
    ]
    tops = [
        {"date": "2015-06-12", "max_dd": -0.42},
        {"date": "2024-02-20", "max_dd": -0.18},
    ]
    summary = episode_backtest.summarize_history_episodes(frames, tops, n_perm=50, seed=42)
    assert "6-12m" in summary and "12-24m" in summary
    s6 = summary["6-12m"]
    assert s6["n_episodes"] == 2
    assert s6["hit_rate_exact"] == 1.0
    assert s6["by_split"]["dev"]["n_episodes"] == 1
    assert s6["by_split"]["test"]["n_episodes"] == 1


def test_fco_neg_intensity_strict_pit_and_red_green_mutex():
    """FCO 绿色底部强度柱：严格 PIT（修改未来帧不影响历史帧）且与活跃顶部红柱互斥。"""
    from research.eval.bottom_dashboard import compute_fco_neg_intensity_series

    # 构造先涨到 4000 再腰斩到 2600 后横盘企稳的周度序列
    closes = [3000 + i * 50 for i in range(20)] + [4000 - i * 100 for i in range(15)] + [2600 + i * 20 for i in range(12)]
    dates = pd.date_range("2020-01-03", periods=len(closes), freq="W-FRI")
    frames = [
        {"asof": str(d.date()), "close": float(c), "w": {"6-12m": None}}
        for d, c in zip(dates, closes, strict=True)
    ]
    # 第 40 帧若存在活跃 6-12m 顶部红柱，则绿柱必须归零
    frames[40]["w"] = {"6-12m": ["2020-03-01", "2020-04-01"]}

    cheap = pd.DataFrame({"erp_pct": [0.95], "pbn_pct": [0.95]}, index=pd.to_datetime(["2019-01-01"]))
    out_a = compute_fco_neg_intensity_series(frames, valuation_df=cheap)
    # 深跌且估值便宜的区间应出现正的底分
    assert any((f.get("fco_neg_intensity") or 0) > 0 for f in out_a[30:40])
    # 红绿互斥：有活跃顶部红柱时绿柱强制为 0
    assert out_a[40]["fco_neg_intensity"] == 0.0
    assert out_a[40]["bottom_first_alert_flag"] is False

    # 严格 PIT：剧烈篡改最后 5 帧的收盘价，前 42 帧的结果必须完全一致
    frames_b = [dict(f) for f in frames]
    for i in range(42, len(frames_b)):
        frames_b[i]["close"] = 9999.0
    out_b = compute_fco_neg_intensity_series(frames_b, valuation_df=cheap)
    for i in range(42):
        assert out_a[i]["fco_neg_intensity"] == out_b[i]["fco_neg_intensity"]
        assert out_a[i]["bottom_first_alert_flag"] == out_b[i]["bottom_first_alert_flag"]


def test_summarize_bottom_backtest_computes_win_rate_and_baseline():
    """四维底部事件级回测：正确计算 50 周上涨胜率、收益中位数与基线对比。"""
    from research.eval.bottom_dashboard import summarize_bottom_backtest

    frames = []
    for i in range(80):
        # 20 周跌到 2500，第 25 周触发底部关注，随后 50 周稳步涨到 3500
        c = 4000.0 - i * 60.0 if i < 25 else 2500.0 + (i - 25) * 20.0
        frames.append(
            {
                "asof": f"2020-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}",
                "split": "dev",
                "close": c,
                "fco_neg_intensity": 0.72 if i == 25 else 0.0,
                "bottom_first_alert_flag": i == 25,
            }
        )
    summary = summarize_bottom_backtest(frames)
    assert summary["n_events"] == 1
    assert summary["win_rate_50w"] == 1.0
    assert summary["median_ret_50w"] > 0.35






def test_phase_and_bottom_score_v2():
    """阶段判定与底分 V2：估值 60% + 回撤深度 40%，估值分项 <0.3 记 0，绿柱门槛 60。"""
    from research.eval.bottom_dashboard import compute_fco_neg_intensity_series, phase_of

    assert phase_of(False, -0.05) == "top"
    assert phase_of(False, -0.12) == "pullback"
    assert phase_of(True, -0.30) == "top"
    assert phase_of(False, None) is None
    assert phase_of(True, None) == "top"

    def val(pct):
        return pd.DataFrame({"erp_pct": [pct], "pbn_pct": [pct]}, index=pd.to_datetime(["2019-01-01"]))

    # 涨到 4200 后逐周下跌：-13.5%、-24%、-30%、-40%
    closes = [3000 + i * 50 for i in range(25)] + [4200 * k for k in (0.865, 0.76, 0.70, 0.60)]
    dates = pd.date_range("2020-01-03", periods=len(closes), freq="W-FRI")
    frames = [
        {"asof": str(d.date()), "close": float(c), "w": {"6-12m": None}}
        for d, c in zip(dates, closes, strict=True)
    ]
    out = compute_fco_neg_intensity_series(frames, valuation_df=val(0.90))
    assert out[24]["phase"] == "top" and out[24]["dd_52w"] == 0.0 and "bottom_detail" not in out[24]
    # 估值满分、回撤未到 20%：60 分，刚好够绿柱，且是独立事件
    d = out[25]["bottom_detail"]
    assert out[25]["phase"] == "pullback" and d["version"] == "v2"
    assert (d["valuation"], d["clearing"], d["score"]) == (1.0, 0.0, 60.0)
    assert set(d) == {"score", "version", "dd_52w", "erp_pct", "pbn_pct", "valuation", "clearing"}
    assert out[25]["bottom_bar"] == "green" and out[25]["bottom_first_alert_flag"] is True
    assert out[27]["bottom_detail"]["score"] == 80.0 and out[28]["bottom_detail"]["score"] == 100.0
    assert out[28]["bottom_first_alert_flag"] is False  # 距上次事件不足 12 周

    # 估值中等（分项 0.5）、回撤 30%：0.6*0.5 + 0.4*0.5 = 50 分，灰柱
    mid = compute_fco_neg_intensity_series(frames, valuation_df=val(0.75))
    assert mid[27]["bottom_detail"]["score"] == 50.0 and mid[27]["bottom_bar"] == "weak"
    assert mid[27]["bottom_first_alert_flag"] is False

    # 估值分项低于 0.3：再深的回撤也记 0，不画柱，但分项照实输出
    rich = compute_fco_neg_intensity_series(frames, valuation_df=val(0.66))
    assert rich[28]["fco_neg_intensity"] == 0.0 and "bottom_bar" not in rich[28]
    assert rich[28]["bottom_detail"]["clearing"] == 1.0 and rich[28]["bottom_detail"]["score"] == 0.0

    # 估值未覆盖：不评分
    none = compute_fco_neg_intensity_series(frames, valuation_df=pd.DataFrame())
    assert none[28]["phase"] == "pullback" and "bottom_detail" not in none[28]
    assert none[28]["fco_neg_intensity"] is None

    # 有顶部区间时仍归顶部侧，不给底分
    frames[-1]["w"] = {"6-12m": ["2020-09-01", "2020-10-01"]}
    out_top = compute_fco_neg_intensity_series(frames, valuation_df=val(0.90))
    assert out_top[-1]["phase"] == "top" and "bottom_detail" not in out_top[-1]
    assert out_top[-1]["dd_52w"] == out[-1]["dd_52w"]


def test_bottom_score_meta_reads_registered_results():
    from research.eval.bottom_dashboard import bottom_score_meta

    meta = bottom_score_meta()
    assert meta["version"] == "v2" and meta["green_min"] == 60
    assert meta["weights"] == {"valuation": 0.6, "clearing": 0.4}
    assert set(meta["segments"]) == {"dev", "cal", "test"}
    assert meta["segments"]["test"]["lift_50w"] == 0.327 and meta["segments"]["test"]["old_lift_50w"] == 0.257
    assert meta["segments"]["cal"]["shift_p"] is None


def test_phase_rule_summary_counts_only_requested_split():
    from research.eval.bottom_dashboard import summarize_phase_rule

    def frame(close, split="dev"):
        return {"close": close, "split": split}

    warm = [frame(100, "warm") for _ in range(20)]
    frames = warm + [
        frame(100), frame(87.9), frame(70), frame(101),  # 一轮：最终 -30%，触发后再跌 20.4%
        frame(87), frame(85), frame(101),  # 一轮：最终 -15.8%
        frame(50, "test"),
    ]
    out = summarize_phase_rule(frames)
    assert out["n_episodes"] == 2 and out["threshold"] == -0.12
    assert out["share_reaching_20pct"] == 0.5
    assert out["median_further_decline"] == round(float(np.median([70 / 87.9 - 1, 85 / 87 - 1])), 3)
    # -11.96% 不算触发（帧上四舍五入后的 -0.12 不能当门槛用）
    assert summarize_phase_rule(warm + [frame(100), frame(88.04), frame(100)])["n_episodes"] == 0
    # 一轮满 104 周仍在门槛以下：不重复计成新的一轮
    long_dd = warm + [frame(100)] + [frame(80 - 0.01 * k) for k in range(130)]
    assert summarize_phase_rule(long_dd)["n_episodes"] == 1
    assert summarize_phase_rule([])["n_episodes"] == 0


def test_bottom_score_v2_threshold_edges_and_missing_valuation():
    """门槛按未四舍五入的分数判定；估值 0.69 含端点；回落中缺估值是未评分而不是 0 分。"""
    from research.eval.bottom_dashboard import compute_fco_neg_intensity_series

    def run(last_ratio, val):
        closes = [3000 + i * 50 for i in range(25)] + [4200 * last_ratio]
        dates = pd.date_range("2020-01-03", periods=len(closes), freq="W-FRI")
        frames = [
            {"asof": str(d.date()), "close": float(c), "w": {"6-12m": None}}
            for d, c in zip(dates, closes, strict=True)
        ]
        return compute_fco_neg_intensity_series(frames, valuation_df=val)[-1]

    def val(pct):
        return pd.DataFrame({"erp_pct": [pct], "pbn_pct": [pct]}, index=pd.to_datetime(["2019-01-01"]))

    # 估值满分 + 回撤 19.98%：原始分 0.6，仍是 60；估值 0.8998 时原始分 59.96，不能进位成 60
    near = run(0.85, val(0.8998))
    assert near["fco_neg_intensity"] == 0.599 and near["bottom_bar"] == "weak"
    assert near["bottom_first_alert_flag"] is False and near["bottom_detail"]["score"] == 59.9

    # (0.69 − 0.60) / 0.30 的浮点值略小于 0.3，按登记应计分：0.6 × 0.3 = 18 分
    edge = run(0.85, val(0.69))
    assert edge["fco_neg_intensity"] == 0.18 and edge["bottom_bar"] == "weak"

    missing = run(0.85, pd.DataFrame({"erp_pct": [], "pbn_pct": []}, index=pd.to_datetime([])))
    assert missing["phase"] == "pullback" and missing["fco_neg_intensity"] is None
    assert "bottom_detail" not in missing and "bottom_bar" not in missing


def test_backfill_fco_intensity_uses_live_formula_and_keeps_published_values():
    from research.eval.export_contract import _fco_intensity
    from research.pipeline.history_extend import backfill_fco_intensity

    cluster = [{"rank": "main", "share": 1.0}]
    frames = [
        {"asof": "2015-06-05", "conf": {"6-12m": 0.35, "12-24m": 0.0}, "clusters": {"6-12m": cluster, "12-24m": []}},
        {"asof": "2016-01-08", "conf": {"6-12m": 0.0, "12-24m": 0.0}, "clusters": {"6-12m": [], "12-24m": []}},
        {"asof": "2026-07-17", "conf": {"6-12m": 0.4}, "clusters": {"6-12m": cluster}, "fco_intensity": 0.123, "fco_scales_active": 1},
    ]
    assert backfill_fco_intensity(frames) == 2
    assert (frames[0]["fco_intensity"], frames[0]["fco_scales_active"]) == _fco_intensity(frames[0]["conf"], frames[0]["clusters"])
    assert frames[0]["fco_intensity"] == 0.438
    assert (frames[1]["fco_intensity"], frames[1]["fco_scales_active"]) == (0.0, 0)
    assert frames[2]["fco_intensity"] == 0.123
