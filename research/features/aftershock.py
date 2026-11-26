"""Point-in-time financial aftershock diagnostics, independent of LPPLS.

Daily rules are an explicitly different experiment from the archived 15-minute
IXIC/NDX study. Neither experiment is a calibrated bottom classifier. This
module reads inputs and optionally a hash-verified archive; it performs no I/O
mutations, network requests or trading actions.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.special import gammaln

SCHEMA = "aftershock_v1"
DAILY_VERSION = "daily_aftershock_v2"  # v2：日频 0/1 用 Bernoulli、20 日计数用 Binomial(20, p)，替换无界 Poisson
ARCHIVE_VERSION = "ixic_ndx_quake_20261123_v1"
RULES = {
    "return": "close-to-close log return",
    "sigma": "previous 63 returns, shift(1), sample std ddof=1",
    "mainshock_z": -3.0,
    "aftershock_absolute_z": 2.0,
    "horizon_sessions": 20,
    "historical_cooldown_sessions": 20,
    "current_anchor": "latest negative threshold breach; not suppressed by historical cooldown",
    "mature_training_only": True,
    "omori_min_observed_days": 10,
    "omori_min_events": 4,
    "omori_c": 1.0,
    "omori_p_bounds": [0.0, 3.0],
    "productivity_min_mature_events": 12,
    "productivity_ci": "approximate 95% year-cluster sandwich interval; at least two years",
    "omori_likelihood": "Bernoulli on the daily large-move indicator, p_t = 1-exp(-rate_t)",
    "productivity_likelihood": "Binomial(20, p) with complementary log-log link",
    "paper": "https://arxiv.org/abs/1006.1882",
    "paper_scope_difference": "Original study uses 1-minute observations across a stock basket; this daily-index adaptation is a separate descriptive experiment.",
}
COMMON_LIMITS = [
    "这是波动次数和幅度的研究统计，不能直接给出涨跌方向、底部概率或买卖价格。",
    "历史重建没有真实提前发布时间；观察、估计与实际交易效果需要分别验证。",
    "逐日独立的 Bernoulli / Binomial 近似没有完整描述波动聚集，参数和区间仅供研究。",
]


def _clean(value):
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, np.ndarray)):
        return [_clean(v) for v in value]
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, np.bool_):
        return bool(value)
    return value


def _hash(value):
    return hashlib.sha256(json.dumps(_clean(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def _frame(asset_id, frame, asof, metadata):
    identity = metadata.get("symbol", metadata.get("asset_id", metadata.get("code")))
    if identity is None or str(identity) != str(asset_id):
        raise ValueError("Aftershock input asset identity missing or mismatched")
    data = frame.copy()
    if "date" not in data.columns and isinstance(data.index, pd.DatetimeIndex):
        data["date"] = data.index
    if not {"date", "close"}.issubset(data.columns):
        raise ValueError("Aftershock input requires date and close")
    cutoff = pd.Timestamp(asof).date().isoformat()
    data["date"] = pd.to_datetime(data.date, errors="raise").dt.strftime("%Y-%m-%d")
    data = data[data.date <= cutoff].copy()
    if data.empty:
        return data, cutoff
    if data.date.duplicated().any() or data.date.tolist() != sorted(data.date):
        raise ValueError("Aftershock dates must be unique and sorted")
    for key in ("symbol", "asset_id"):
        if key in data.columns and not data[key].astype(str).eq(str(asset_id)).all():
            raise ValueError("Aftershock rows contain a different asset")
    data["close"] = pd.to_numeric(data.close, errors="raise")
    if not np.isfinite(data.close).all() or (data.close <= 0).any():
        raise ValueError("Aftershock close prices must be positive and finite")
    return data.reset_index(drop=True), cutoff


def _module(status, summary, reason, *, frequency="daily", mainshock_date=None,
            anchor_date=None, anchor_type=None, samples=None, parameters=None, **extra):
    return {"status": status, "frequency": frequency, "mainshock_date": mainshock_date,
            "anchor_date": anchor_date, "anchor_type": anchor_type, "samples": samples or {},
            "parameters": parameters, "summary": summary, "reason": reason,
            "limits": list(COMMON_LIMITS), **extra}


def _daily_table(frame):
    data = frame[["date", "close"]].copy()
    data["return"] = np.log(data.close).diff()
    data["sigma"] = data["return"].shift(1).rolling(63, min_periods=63).std(ddof=1)
    # Constant prices have zero sigma, not an infinite-confidence shock.
    data["z"] = data["return"] / data.sigma.where(data.sigma > 0)
    return data


def _episode(data, index):
    shock = data.iloc[index]
    tail = data.iloc[index+1:index+21]
    absolute = np.abs(tail["return"].to_numpy(dtype=float))
    mag = abs(float(shock["return"])) / float(shock.sigma)
    largest = float(absolute.max()) if len(absolute) else None
    gap = float(np.log10(abs(shock["return"])/largest)) if largest is not None and largest > 0 else None
    return {"date": str(shock.date), "index": int(index), "year": int(str(shock.date)[:4]),
            "magnitude_sigma": mag, "sigma_at_shock": float(shock.sigma),
            "mainshock_abs_log_return": abs(float(shock["return"])),
            "observed_after_days": len(tail), "elapsed_since_mainshock": len(data)-index-1,
            "mature": len(tail) == 20,
            "aftershock_count": int(np.sum(absolute >= 2*shock.sigma)),
            "counts": (absolute >= 2*shock.sigma).astype(int).tolist(),
            "dates": tail.date.tolist(), "largest_aftershock_abs_log_return": largest,
            "bath_gap_log10": gap, "later_larger": bool(largest > abs(shock["return"])) if largest is not None else None}


def _episodes(data):
    candidates = data.index[(data.z <= -3) & np.isfinite(data.z)].tolist()
    accepted, last = [], -1000
    for index in candidates:
        if index-last <= 20:
            continue
        accepted.append(_episode(data, index))
        last = index
    current = _episode(data, candidates[-1]) if candidates else None
    return accepted, current


def _hazard_probability(rate):
    """强度 λ 下一个交易日出现大波动的概率 1−exp(−λ)，夹在 (0, 1) 内防止 log(0)。"""
    return np.clip(-np.expm1(-np.asarray(rate, dtype=float)), 1e-15, 1-1e-15)


def _binomial_loss(y, rate, trials=1):
    """Binomial(trials, 1−exp(−λ)) 的负对数似然；trials=1 即逐日 0/1 的 Bernoulli。"""
    if not np.isfinite(rate).all() or np.any(rate <= 0):
        return float("inf")
    prob = _hazard_probability(rate)
    log_choose = gammaln(trials+1)-gammaln(y+1)-gammaln(trials-y+1)
    return float(-np.sum(log_choose+y*np.log(prob)+(trials-y)*np.log1p(-prob)))


def _daily_omori(current):
    if current is None:
        return _module("not_available", "尚无符合规则的负向冲击", "当前数据中未出现相对前63日波动低于负3倍的日线冲击。")
    samples = {"observed_after_days": current["observed_after_days"], "aftershock_events": current["aftershock_count"],
               "horizon_days": 20, "mature": current["mature"], "min_fit_days": 10, "min_fit_events": 4,
               "elapsed_since_mainshock": current.get("elapsed_since_mainshock", current["observed_after_days"])}
    common = {"mainshock_date": current["date"], "anchor_date": current["date"],
              "anchor_type": "latest_causal_negative_3sigma_breach", "samples": samples,
              "observations": {"dates": current["dates"], "counts": current["counts"]}}
    if samples["observed_after_days"] < 10 or samples["aftershock_events"] < 4:
        return _module("insufficient_data", "冲击后的样本还不够", "至少观察10个交易日且出现4个超阈值波动日后才拟合衰减；零后续样本不等于风险消失。", **common)
    y = np.asarray(current["counts"], dtype=float)
    t = np.arange(1, len(y)+1, dtype=float)
    bounds = [(-18., 0.), (-18., math.log(100.)), (0., 3.)]

    def rate(theta):
        return np.exp(theta[0])+np.exp(theta[1])/(t+1.)**theta[2]

    fits = [minimize(lambda theta: _binomial_loss(y, rate(theta)),
                     [math.log(max(y.mean()/2, 1e-4)), math.log(max(y[0], 1e-4)), p],
                     bounds=bounds, method="L-BFGS-B") for p in (.1, .5, 1., 2.)]
    usable = [fit for fit in fits if fit.success and np.isfinite(fit.fun)]
    if not usable:
        return _module("failed", "衰减拟合未收敛", "保留观察次数，本次没有可用的衰减参数。", optimizer_messages=[str(f.message) for f in fits], **common)
    best = min(usable, key=lambda result: result.fun)
    predicted = rate(best.x)
    const = float(y.mean())
    aic = 6+2*float(best.fun)
    const_aic = 2+2*_binomial_loss(y, np.full(len(y), -math.log1p(-min(const, 1-1e-12))))
    p = float(best.x[2])
    boundary = p <= 1e-5 or p >= 3-1e-5
    identified = bool(not boundary and predicted[0]-predicted[-1] > .02*const and aic+2 < const_aic)
    params = {"p": p, "c": 1., "background": float(np.exp(best.x[0])), "amplitude": float(np.exp(best.x[1])),
              "p_at_boundary": boundary, "decay_identified": identified, "constant_rate": const,
              "aic_omori": aic, "aic_constant": const_aic, "rate_unit": "large_move_days_per_trading_day",
              "optimizer_success": True, "optimizer_message": str(best.message), "predicted_rates": predicted.tolist(),
              "predicted_probabilities": _hazard_probability(predicted).tolist(),
              "likelihood": "bernoulli_daily_indicator, p_t = 1-exp(-rate_t)", "confidence_interval": None}
    summary = "观察段存在衰减形态，尚非见底信号" if identified else "尚未辨认出稳定的衰减"
    return _module("available", summary, "p贴边界、衰减项接近零或未优于恒定率时，不解释为风险消失。逐日是否出现大波动按Bernoulli似然拟合，属描述性近似。", parameters=params, **common)


def _daily_bath(current):
    if current is None:
        return _module("not_available", "尚无可比较的初始冲击", "先识别负3倍历史波动的冲击，再观察后续幅度。")
    samples = {"observed_after_days": current["observed_after_days"], "horizon_days": 20, "mature": current["mature"],
               "elapsed_since_mainshock": current.get("elapsed_since_mainshock", current["observed_after_days"])}
    common = {"mainshock_date": current["date"], "anchor_date": current["date"],
              "anchor_type": "latest_causal_negative_3sigma_breach", "samples": samples}
    if current["bath_gap_log10"] is None:
        return _module("insufficient_data", "还不能比较后续最大冲击", "尚无后续交易日，或后续收益全部为零，无法计算有限的对数幅度差。", **common)
    params = {"gap_log10": current["bath_gap_log10"], "mainshock_abs_log_return": current["mainshock_abs_log_return"],
              "largest_aftershock_abs_log_return": current["largest_aftershock_abs_log_return"],
              "later_larger": current["later_larger"], "formula": "log10(initial absolute log return / largest subsequent absolute log return)"}
    summary = "后续已出现更大的波动" if current["later_larger"] else "已记录初始与后续最大波动的幅度差"
    reason = "这是因果选择初始冲击后的金融类比，不是固定Båth常数或底价。"
    if not current["mature"]:
        reason += "20日观察期尚未结束，当前幅度差仍可能改变。"
    return _module("available", summary, reason, parameters=params, **common)


def _daily_productivity(episodes, current):
    mature = [e for e in episodes if e["mature"]]
    pending = [e for e in episodes if not e["mature"]]
    samples = {"mature_events": len(mature), "pending_events": len(pending), "min_mature_events": 12,
               "training_start": mature[0]["date"] if mature else None,
               "training_last_event": mature[-1]["date"] if mature else None,
               "horizon_days": 20}
    common = {"mainshock_date": current["date"] if current else None,
              "anchor_date": current["date"] if current else None,
              "anchor_type": "mature_deduplicated_causal_episodes", "samples": samples}
    if len(mature) < 12:
        return _module("insufficient_data", "成熟冲击样本不足", "至少12次完成后续20日观察的独立起始事件才拟合；未成熟事件不算零次余震。", **common)
    x = np.column_stack((np.ones(len(mature)), np.log([e["magnitude_sigma"] for e in mature])))
    y = np.asarray([e["aftershock_count"] for e in mature], dtype=float)
    if y.sum() == 0 or np.ptp(x[:, 1]) < 1e-6 or np.linalg.matrix_rank(x) < 2:
        return _module("insufficient_data", "样本尚不能识别产出率斜率", "事件次数全为零或冲击强度没有足够差异，不能给出有效α。", **common)

    horizon = 20.
    if np.any(y > horizon):
        return _module("failed", "事件计数超出观察期", "20日内的大波动日数不可能超过20，数据需要复核。", **common)

    # Binomial(20, p)，p = 1−exp(−exp(a+α·ln m))：α 仍是强度对冲击幅度的幂指数，次数均值不会超过 20。
    def rate(theta):
        return np.exp(np.clip(x @ theta, -30, 30))

    def score_weight(theta):
        lam = rate(theta)
        return lam/_hazard_probability(lam)

    start = -math.log1p(-min(y.mean()/horizon, 1-1e-6))
    fit = minimize(lambda theta: _binomial_loss(y, rate(theta), horizon), [math.log(start), 0.],
                   jac=lambda theta: -x.T @ ((y-horizon*_hazard_probability(rate(theta)))*score_weight(theta)),
                   method="BFGS")
    if not fit.success or not np.isfinite(fit.fun):
        return _module("failed", "产出率拟合未收敛", "没有可用的产出率参数。", optimizer_message=str(fit.message), **common)
    lam = rate(fit.x)
    prob = _hazard_probability(lam)
    mu = horizon*prob
    info = x.T @ ((horizon*lam**2*(1-prob)/prob)[:, None]*x)
    if np.linalg.matrix_rank(info) < 2 or np.linalg.cond(info) > 1e12:
        return _module("insufficient_data", "产出率参数不可稳定识别", "信息矩阵退化，保留事件样本，不展示不可靠的参数。", **common)
    years = np.asarray([e["year"] for e in mature])
    unique_years = np.unique(years)
    samples["training_years"] = len(unique_years)
    interval, standard_error = None, None
    if len(unique_years) >= 2:
        scores = x*((y-mu)*lam/prob)[:, None]
        clustered = np.stack([scores[years == year].sum(axis=0) for year in unique_years])
        bread = np.linalg.inv(info)
        covariance = bread @ (clustered.T @ clustered) @ bread * len(unique_years)/(len(unique_years)-1)
        standard_error = float(np.sqrt(max(0., covariance[1, 1])))
        interval = [float(fit.x[1]-1.96*standard_error), float(fit.x[1]+1.96*standard_error)]
    expected, extrapolation = None, False
    magnitude_range = [float(np.exp(x[:, 1].min())), float(np.exp(x[:, 1].max()))]
    if current:
        # This is an expected count under the fitted model, not a probability.
        current_rate = np.exp(np.clip(fit.x[0]+fit.x[1]*math.log(current["magnitude_sigma"]), -30, 30))
        expected = float(horizon*_hazard_probability(current_rate))
        extrapolation = not magnitude_range[0] <= current["magnitude_sigma"] <= magnitude_range[1]
    crosses_zero = interval is None or interval[0] <= 0 <= interval[1]
    params = {"alpha": float(fit.x[1]), "intercept": float(fit.x[0]), "alpha_ci95": interval,
              "alpha_cluster_year_se": standard_error, "alpha_interval_includes_zero": None if interval is None else crosses_zero,
              "expected_20d_events": expected, "count_unit": "large_move_trading_days_either_direction",
              "likelihood": "binomial(20, p), p = 1-exp(-exp(intercept + alpha*ln(magnitude_sigma)))", "training_magnitude_range": magnitude_range,
              "current_magnitude_extrapolated": extrapolation,
              "current_prediction_status": "no_current_shock" if current is None else "extrapolation" if extrapolation else "descriptive",
              "optimizer_success": True, "optimizer_message": str(fit.message),
              "mean_observed_count": float(y.mean()), "calibrated_probability": False}
    summary = "产出率关系仍不确定" if crosses_zero else "已拟合冲击强度与后续波动次数的关系"
    reason = "仅使用截至日已成熟的事件；正负大波动都计入。"
    reason += "α区间包含0或尚无法估计区间，不能称为稳定预测关系。" if crosses_zero else "区间不含0仍不等于已验证的交易预测能力。"
    if extrapolation:
        reason += "当前冲击强度超出训练范围，条件次数属于外推。"
    return _module("available", summary, reason, parameters=params, **common)


def _archive_path(root):
    root = Path(root)
    return root/"quake" if (root/"quake").is_dir() else root


def _verified_archive(asset_id, frame, asof, root):
    if asset_id not in {"US_IXIC", "US_NDX"}:
        raise ValueError("Archive only covers US_IXIC and US_NDX")
    root = _archive_path(root)
    manifest = json.loads((root/"manifest.json").read_text(encoding="utf-8"))
    if manifest.get("completed") is not True or manifest.get("latest") != asof:
        raise ValueError("Archive cutoff/status does not match requested asof")
    asset = asset_id.removeprefix("US_")
    required = ["results.json", "protocol.json", "analyse.py", "omori_fit_comparison.csv",
                "IXIC_daily_summary.json", "NDX_daily_summary.json", f"inputs/{asset}_daily.csv", f"inputs/{asset}_15m.csv"]
    expected = {k.replace("\\", "/"): v for k, v in manifest["files"].items()}
    hashes = {}
    for name in required:
        actual = hashlib.sha256((root/name).read_bytes()).hexdigest()
        if expected.get(name) != actual:
            raise ValueError(f"Archive hash verification failed: {name}")
        hashes[name] = actual
    with (root/f"inputs/{asset}_daily.csv").open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    archive_dates = [row["date"] for row in rows]
    if archive_dates != sorted(set(archive_dates)) or archive_dates[-1] != asof:
        raise ValueError("Archive input dates invalid")
    archive_close = {row["date"]: float(row["close"]) for row in rows}
    if len(frame) < 252 or frame.date.iloc[-1] != asof:
        raise ValueError("At least 252 exact dated closes are required to verify archive overlap")
    for row in frame.itertuples():
        if row.date not in archive_close or float(row.close) != archive_close[row.date]:
            raise ValueError(f"Archive close input mismatch at {row.date}")
    report = json.loads((root/f"{asset}_daily_summary.json").read_text(encoding="utf-8"))
    result = json.loads((root/"results.json").read_text(encoding="utf-8"))[asset]
    protocol = json.loads((root/"protocol.json").read_text(encoding="utf-8"))
    if report["asset"] != asset or report["latest"] != asof or result["intraday"]["normalization"]["current_cutoff"] != asof:
        raise ValueError("Archive content identity/cutoff mismatch")
    if (result["historical"]["historical_end"] > asof
            or result["historical"]["prediction_examples"]["latest"]["day"] != asof
            or protocol["current_peak"] > asof
            or report["worst_day"] > asof):
        raise ValueError("Archive contains observations beyond requested cutoff")
    return result, report, protocol, {"status": "verified", "archive_version": ARCHIVE_VERSION,
        "manifest_sha256": hashlib.sha256((root/"manifest.json").read_bytes()).hexdigest(),
        "verified_files": hashes, "matching_close_rows": len(frame), "matching_start": frame.date.iloc[0],
        "matching_end": asof, "archive_daily_start": archive_dates[0],
        "reason": "归档文件哈希及当前输入共同收盘序列已核对；更早训练数据保留独立归档来源。"}


def _archive_modules(result, report, protocol):
    daily = result["historical"]
    intraday = result["intraday"]["0.95"]
    normalization = result["intraday"]["normalization"]
    latest = daily["prediction_examples"]["latest"]
    peak = daily["prediction_examples"]["peak"]
    latest_shock = latest["day"] if latest["is_negative_mainshock"] else None
    source_omori = intraday["omori"]
    omori = _module("available" if source_omori.get("optimizer_success") else "failed",
        "峰后大波动尚未显示稳定衰减", "峰后拟合p=0不代表风险消失；最新负向冲击之后尚无完整交易日，不能把峰后曲线当成新冲击的衰减结果。",
        frequency="15m_counts_per_daily_session", mainshock_date=latest_shock,
        anchor_date=protocol["current_peak"], anchor_type="retrospective_price_peak_not_negative_mainshock",
        samples={"observed_after_days": intraday["n_after_days"], "baseline_days": normalization["baseline_sessions"],
                 "baseline_bars": normalization["baseline_bars"], "latest_mainshock_after_days": latest["observed_after_days"],
                 "bars_per_session": normalization["bars_per_session"], "latest5_events": intraday["latest5_events"],
                 "previous5_events": intraday["previous5_events"], "latest_day_events": intraday["latest_day_events"]},
        parameters={key: value for key, value in source_omori.items() if key not in {"status", "n_days"}},
        threshold={"quantile": .95, "value": intraday["threshold"], "normalization": normalization},
        current_mainshock={"date": latest_shock, "observed_after_days": latest["observed_after_days"],
                           "status": "insufficient_data" if latest["observed_after_days"] < 10 else "not_established"},
        direction_counts=intraday.get("direction_counts"),
        alternative_anchor={"date": intraday["alternative_anchor"], "selection": intraday["alternative_anchor_selection"],
                            "parameters": intraday["alternative_omori"]},
        sensitivities={"quantiles": protocol["event_quantiles"], "c": intraday["c_sensitivity"],
                       "exclude_final_bar": result.get("exclude_final_bar_sensitivity", {}).get("0.95")},
        anchor_is_negative_mainshock=peak["is_negative_mainshock"])
    bath = _module("available", "后续冲击已接近此前最大冲击", "起点是已观察区间内最大日线跌幅，属于回顾性比较；当前只有11个后续交易日，幅度差仍可改变，不能换算成底价。",
        mainshock_date=report["worst_day"], anchor_date=report["worst_day"],
        anchor_type="retrospective_largest_daily_decline_since_price_peak",
        samples={"observed_after_days": report["bath_observation_tail"], "horizon_days": 20,
                 "mature": report["bath_observation_tail"] >= 20, "historical_events": daily["n_episodes"]},
        parameters={"gap_log10": report["bath_gap_since_largest_decline_so_far"],
                    "mainshock_abs_log_return": abs(math.log1p(report["worst_return_percent"]/100)),
                    "largest_aftershock_abs_log_return": abs(math.log1p(report["worst_return_percent"]/100))/10**report["bath_gap_since_largest_decline_so_far"],
                    "latest_to_previous_largest_ratio": report["latest_relative_to_previous_largest"],
                    "historical_larger_aftershock_fraction": daily["larger_aftershock_fraction"],
                    "historical_gap_quantiles": daily["bath_gap_quantiles"], "historical_fraction_is_current_probability": False})
    ci = daily["alpha_normal95"]
    productivity = _module("available" if daily["optimizer_success"] else "failed",
        "产出率斜率区间包含0，关系仍不确定", "历史训练使用1990–2025年成熟事件；条件次数均值不是方向、底部概率或精确未来次数。",
        mainshock_date=latest_shock, anchor_date=latest_shock,
        anchor_type="historical_causal_negative_shocks_for_productivity",
        samples={"mature_events": daily["n_episodes"], "training_years": daily["n_years"],
                 "training_start": daily["historical_start"], "training_end": daily["historical_end"],
                 "current_observed_after_days": latest["observed_after_days"], "horizon_days": 20},
        parameters={"alpha": daily["alpha"], "intercept": daily["intercept"], "alpha_ci95": ci,
                    "alpha_cluster_year_se": daily["alpha_cluster_year_se"], "alpha_interval_includes_zero": ci[0] <= 0 <= ci[1],
                    "expected_20d_events": latest["expected_20d_events_from_productivity"],
                    "mean_observed_count": daily["mean_aftershock_count"], "optimizer_success": daily["optimizer_success"],
                    "count_unit": "large_move_trading_days_either_direction", "calibrated_probability": False})
    return {"omori": omori, "bath": bath, "productivity": productivity}


def analyze_aftershock(asset_id, frame, asof, metadata, archive_root=None):
    """Return honest per-module states using only rows dated at/before ``asof``.

    ``metadata`` must identify the requested symbol and should include the
    parent record's data_version/source. A supplied archive is optional: any
    mismatch is explicit and falls back to the independently labelled daily
    experiment, never to another asset or a newer archive.
    """
    data, cutoff = _frame(asset_id, frame, asof, metadata)
    input_hash = _hash({"symbol": str(asset_id), "date": data.date.tolist(), "close": data.close.tolist()})
    base = {"schema_version": SCHEMA, "symbol": str(asset_id), "asof": cutoff,
            "data_asof": str(data.date.iloc[-1]) if len(data) else None,
            "data_version": metadata.get("data_version"), "first_visible_at": None,
            "evidence_state": "historical_reconstruction", "method_version": DAILY_VERSION,
            "frequency": "daily", "source": {"label": metadata.get("source", "provided daily close"),
                "mode": "daily_recalculation", "input_hash": input_hash,
                "first_date": str(data.date.iloc[0]) if len(data) else None, "rows": len(data)},
            "method": dict(RULES), "limits": list(COMMON_LIMITS),
            "archive_reuse": {"status": "not_requested", "reason": "未提供独立研究归档。"}}
    if archive_root is not None:
        try:
            result, report, protocol, audit = _verified_archive(str(asset_id), data, cutoff, archive_root)
            base.update(method_version=ARCHIVE_VERSION, frequency="15m_and_daily", method=protocol,
                        archive_reuse=audit, modules=_archive_modules(result, report, protocol))
            base["source"]["mode"] = "verified_independent_research_archive"
            base["source"]["research_version"] = audit["manifest_sha256"]
            return _clean(base)
        except (ValueError, KeyError, TypeError, OSError, json.JSONDecodeError) as error:
            base["archive_reuse"] = {"status": "rejected", "reason": str(error),
                                     "fallback": DAILY_VERSION}
    if len(data) < 65:
        reason = "至少需要65个收盘观测，才能获得当日收益及此前63个收益的波动率。"
        base["modules"] = {name: _module("insufficient_data", "日线历史不足", reason,
                                         samples={"observed_closes": len(data), "required_closes": 65})
                           for name in ("omori", "bath", "productivity")}
        return _clean(base)
    table = _daily_table(data)
    episodes, current = _episodes(table)
    base["modules"] = {"omori": _daily_omori(current), "bath": _daily_bath(current),
                       "productivity": _daily_productivity(episodes, current)}
    base["episode_ledger"] = [{k: v for k, v in event.items() if k not in {"counts", "dates", "index"}} for event in episodes]
    base["current_episode"] = current
    return _clean(base)
