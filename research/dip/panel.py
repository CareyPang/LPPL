"""Descriptive stock dip panel backed by a manifest-selected event library."""
from __future__ import annotations

import hashlib
import json
import logging
import math
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

from ..features.wells import well_features_at
from . import events

LOGGER = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[2]
DIP_DATA = ROOT / "data" / "dip"
RANDOM_WALK_N = 20_000
RANDOM_WALK_SEED = 20261103
REGIME_SEEDS = (20261110, 20261111, 20261112, 20261113, 20261114)
REGIME_SEED = REGIME_SEEDS[0]
REGIME_MIN_WEEKS = 104
EXCLUDED_YEARS = ("2015", "2016")
QUANTILES = (0.10, 0.25, 0.50, 0.75, 0.90)
MATURITY_COLUMNS = {
    "r60": "known60",
    "mdd60": "known60",
    "up60": "known60",
    "r120": "known120",
    "mdd120": "known120",
    "up120": "known120",
    "r250": "known250",
    "fh60": "fh60_known",
    "fh120": "fh120_known",
}


def _number(value: object, digits: int = 6) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(number):
        return None
    return round(number, digits)


def _json_safe(value):
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return _number(value)
    if pd.isna(value):
        return None
    return value


def _load_library(data_dir: Path) -> tuple[dict, pd.DataFrame, dict[str, str]]:
    manifest_path = data_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    events_path = data_dir / manifest.get("events_file", "events.parquet")
    payload_hash = hashlib.sha256(events_path.read_bytes()).hexdigest()
    if payload_hash != manifest.get("sha256"):
        raise ValueError("dip event library SHA-256 does not match its manifest")
    event_frame = pd.read_parquet(events_path)
    industry_file = data_dir / manifest.get("industry_file", "sw1_current.csv")
    industries: dict[str, str] = {}
    if industry_file.exists():
        current = pd.read_csv(industry_file, dtype={"sym": str})
        if {"sym", "sw1_name"}.issubset(current.columns):
            industries = {
                str(row.sym): str(row.sw1_name)
                for row in current.itertuples(index=False)
                if pd.notna(row.sw1_name) and str(row.sw1_name).strip()
            }
    return manifest, event_frame, industries


def _load_oos_verdict(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"items": {}, "label": "样本外检验未完成"}


def _first_touch(values: pd.Series) -> dict:
    valid = values.dropna()
    total = len(valid)
    return {
        label: (_number(float((valid == label).mean())) if total else None)
        for label in ("U", "L", "none")
    } | {"n": int(total)}


def _mature(frame: pd.DataFrame, column: str, asof: str | None) -> pd.DataFrame:
    known_column = MATURITY_COLUMNS[column]
    if asof is None:
        return frame.iloc[0:0].copy()
    cutoff = pd.Timestamp(asof).strftime("%Y-%m-%d")
    eligible = frame
    if "sig_date" in eligible:
        signal_dates = pd.to_datetime(eligible["sig_date"], errors="coerce").dt.strftime(
            "%Y-%m-%d"
        )
        eligible = eligible.loc[signal_dates.notna() & (signal_dates <= cutoff)]
    if known_column not in eligible:
        return eligible.iloc[0:0].copy()
    known_dates = pd.to_datetime(
        eligible[known_column], errors="coerce"
    ).dt.strftime("%Y-%m-%d")
    return eligible.loc[known_dates.notna() & (known_dates <= cutoff)].copy()


def _summary(frame: pd.DataFrame, asof: str | None) -> dict:
    outcomes = ("r60", "r120", "r250", "mdd120", "up120")
    quantile_rows = {}
    outcome_counts = {}
    for column in outcomes:
        mature = _mature(frame, column, asof)
        values = (
            pd.to_numeric(mature[column], errors="coerce").dropna()
            if column in mature
            else pd.Series(dtype=float)
        )
        outcome_counts[column] = int(len(values))
        quantile_rows[column] = (
            [_number(value) for value in values.quantile(QUANTILES).to_numpy()]
            if len(values)
            else [None] * len(QUANTILES)
        )
    mature_up120 = _mature(frame, "up120", asof)
    up120 = (
        pd.to_numeric(mature_up120["up120"], errors="coerce").dropna()
        if "up120" in mature_up120
        else pd.Series(dtype=float)
    )
    first_hits = {
        key: _historical_first_hit(frame, key, asof) for key in ("fh60", "fh120")
    }
    return {
        "n": int(len(frame)),
        "n_delisted": int(frame["delisted"].fillna(False).astype(bool).sum())
        if "delisted" in frame
        else 0,
        "n_outcome": outcome_counts,
        "n_excluded_immature": {
            column: int(len(frame) - len(_mature(frame, column, asof)))
            for column in MATURITY_COLUMNS
        },
        "q": quantile_rows,
        "p_up120_ge30": _number(float((up120 >= 0.30).mean())) if len(up120) else None,
        "p_up120_ge50": _number(float((up120 >= 0.50).mean())) if len(up120) else None,
        "fh60": {
            label: first_hits["fh60"][label]
            for label in ("U", "L", "none")
        },
        "fh120": {
            label: first_hits["fh120"][label]
            for label in ("U", "L", "none")
        },
    }


def _sample_counts(frame: pd.DataFrame) -> dict[str, int]:
    return {
        "n": int(len(frame)),
        "n_delisted": int(frame["delisted"].fillna(False).astype(bool).sum())
        if "delisted" in frame
        else 0,
    }


def _historical_first_hit(
    frame: pd.DataFrame, key: str, asof: str | None
) -> dict:
    mature = _mature(frame, key, asof)
    rates = (
        _first_touch(mature[key])
        if key in mature
        else _first_touch(pd.Series(dtype=object))
    )
    return {label: rates[label] for label in ("U", "L", "none")} | {"n": rates["n"]}


def _random_walk(vol_d: float | None) -> dict:
    results: dict[str, dict[str, float | None]] = {}
    if vol_d is None or vol_d <= 0:
        return {key: {"U": None, "L": None, "none": None} for key in events.FH}
    max_horizon = max(value[2] for value in events.FH.values())
    rng = np.random.default_rng(RANDOM_WALK_SEED)
    log_steps = rng.normal(
        loc=-(vol_d**2) / 2,
        scale=vol_d,
        size=(RANDOM_WALK_N, max_horizon),
    )
    paths = np.exp(np.cumsum(log_steps, axis=1))
    for key, (lower, upper, horizon) in events.FH.items():
        values = paths[:, :horizon]
        lower_mask = values <= lower
        upper_mask = values >= upper
        lower_first = np.where(lower_mask.any(axis=1), lower_mask.argmax(axis=1), horizon + 1)
        upper_first = np.where(upper_mask.any(axis=1), upper_mask.argmax(axis=1), horizon + 1)
        counts = {
            "U": int((upper_first < lower_first).sum()),
            "L": int((lower_first < upper_first).sum()),
            "none": int((lower_first == upper_first).sum()),
        }
        results[key] = {
            label: _number(count / RANDOM_WALK_N)
            for label, count in counts.items()
        }
    return results


def _regime(prices: pd.DataFrame) -> dict:
    weeks = 0
    base = {
        "p_hi_filtered": None,
        "hi_vol_ann": None,
        "lo_vol_ann": None,
        "hi_mean_wk": None,
        "lo_mean_wk": None,
        "weeks": weeks,
        "status": "failed",
        "seed": None,
        "attempts": 0,
        "reason": None,
        "note": "波动体制，不是涨跌信号",
    }
    try:
        close = prices.set_index(pd.to_datetime(prices["date"]))["close"].astype(float)
        weekly = close.resample("W-FRI").last().dropna().pct_change().dropna().tail(260)
        weeks = int(len(weekly))
        base["weeks"] = weeks
        if weeks < REGIME_MIN_WEEKS:
            base.update(
                status="short_history",
                reason="short history",
                note="周收益不足 104 周；波动体制，不是涨跌信号",
            )
            return base
        from statsmodels.tools.sm_exceptions import ConvergenceWarning, ValueWarning
        from statsmodels.tsa.regime_switching.markov_regression import MarkovRegression

        model = MarkovRegression(
            weekly,
            k_regimes=2,
            trend="c",
            switching_variance=True,
        )
    except Exception as exc:
        base.update(
            status="failed",
            reason=f"{type(exc).__name__}: {str(exc)[:120]}",
            note="波动体制估计失败，不是涨跌信号",
        )
        LOGGER.warning("dip volatility regime fit failed: %s", base["reason"])
        return base

    saw_nonconverged = False
    last_exception = None
    for seed in REGIME_SEEDS:
        base["attempts"] += 1
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", ConvergenceWarning)
                warnings.simplefilter("ignore", ValueWarning)
                fitted = model.fit(
                    disp=False,
                    search_reps=10,
                    rng=np.random.RandomState(seed),
                )
            if not fitted.mle_retvals.get("converged"):
                saw_nonconverged = True
                continue
            names = list(fitted.model.param_names)
            params = np.asarray(fitted.params, dtype=float)
            filtered = fitted.filtered_marginal_probabilities
            probabilities = np.asarray(filtered, dtype=float)
            if not np.isfinite(params).all() or not np.isfinite(probabilities).all():
                raise ValueError("non-finite parameters or probabilities")
            variance_indices = [
                i for i, name in enumerate(names) if name.startswith("sigma2[")
            ]
            mean_indices = [
                i for i, name in enumerate(names) if name.startswith("const[")
            ]
            if len(variance_indices) != 2 or len(mean_indices) != 2:
                raise ValueError("MarkovRegression returned unexpected parameter names")
            variances = [float(params[index]) for index in variance_indices]
            low_index, high_index = np.argsort(variances)
            last = filtered.iloc[-1] if hasattr(filtered, "iloc") else filtered[-1]
            with np.errstate(invalid="ignore"):
                values = np.asarray(
                    [
                        last[int(high_index)],
                        np.sqrt(variances[int(high_index)] * 52),
                        np.sqrt(variances[int(low_index)] * 52),
                        params[mean_indices[int(high_index)]],
                        params[mean_indices[int(low_index)]],
                    ],
                    dtype=float,
                )
            if not np.isfinite(values).all():
                raise ValueError("non-finite parameters or probabilities")
        except Exception as exc:
            last_exception = exc
            continue

        base.update(
            {
                "p_hi_filtered": _number(values[0]),
                "hi_vol_ann": _number(values[1]),
                "lo_vol_ann": _number(values[2]),
                "hi_mean_wk": _number(values[3]),
                "lo_mean_wk": _number(values[4]),
                "status": "ok",
                "seed": seed,
                "reason": None,
            }
        )
        return base

    base.update(
        status="nonconverged" if saw_nonconverged else "failed",
        reason=(
            f"{type(last_exception).__name__}: {str(last_exception)[:120]}"
            if last_exception is not None
            else "not converged"
        ),
        note=(
            "波动体制估计未收敛，不是涨跌信号"
            if saw_nonconverged
            else "波动体制估计失败，不是涨跌信号"
        ),
    )
    if last_exception is not None:
        LOGGER.warning("dip volatility regime fit failed: %s", base["reason"])
    return base


def _state(prices: pd.DataFrame) -> tuple[dict, float | None, float | None]:
    frame = prices.copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    frame = frame.dropna(subset=["close"]).loc[lambda d: d.close > 0].sort_values("date")
    if frame.empty:
        return (
            {
                key: None
                for key in (
                    "asof",
                    "close",
                    "peak_date",
                    "runup",
                    "dd",
                    "td_since_peak",
                    "low_date",
                    "bounce_from_low",
                    "ret20",
                    "ret60",
                    "rv20",
                    "rv20_pct5y",
                    "vol_d",
                    "well_dist_below",
                )
            },
            None,
            None,
        )
    closes = frame["close"].to_numpy(dtype=float)
    dates = frame["date"].to_numpy()
    n = len(closes)
    peak_index = max(0, n - events.W) + int(np.argmax(closes[-events.W :]))
    peak_close = closes[peak_index]
    trough_start = max(0, peak_index - events.W + 1)
    trough_index = trough_start + int(np.argmin(closes[trough_start : peak_index + 1]))
    low_index = peak_index + int(np.argmin(closes[peak_index:]))
    current = closes[-1]
    drawdown = current / peak_close - 1
    log_returns = np.diff(np.log(closes), prepend=np.nan)
    rv_series = pd.Series(log_returns).rolling(20).std() * np.sqrt(252)
    rv20 = _number(rv_series.iloc[-1])
    rv_window = rv_series.iloc[-1260:].dropna()
    rv20_pct = (
        _number(float((rv_window <= rv20).mean()))
        if rv20 is not None and len(rv_window)
        else None
    )
    ewma = events.ewma_vol(closes)
    vol_d = _number(ewma[-1]) if len(ewma) else None
    well_dist_below = None
    if {"high", "low", "volume"}.issubset(frame.columns):
        high = pd.to_numeric(frame["high"], errors="coerce").to_numpy(dtype=float)
        low = pd.to_numeric(frame["low"], errors="coerce").to_numpy(dtype=float)
        volume = pd.to_numeric(frame["volume"], errors="coerce").to_numpy(dtype=float)
        typical = (high + low + closes) / 3
        if (
            np.isfinite(typical).all()
            and np.isfinite(high).all()
            and np.isfinite(low).all()
            and np.isfinite(volume).all()
            and (typical > 0).all()
            and (high > 0).all()
            and (low > 0).all()
        ):
            x = np.log(typical)[-events.W :]
            r2 = ((np.log(high) - np.log(low)) ** 2 / 12)[-events.W :]
            well = well_features_at(
                x, r2, volume[-events.W :], math.log(current)
            )
            well_dist_below = _number(well[2])
    state = {
        "asof": str(pd.Timestamp(dates[-1]).date()),
        "close": _number(current),
        "peak_date": str(pd.Timestamp(dates[peak_index]).date()),
        "runup": _number(peak_close / closes[trough_index] - 1),
        "dd": _number(drawdown),
        "td_since_peak": int(n - 1 - peak_index),
        "low_date": str(pd.Timestamp(dates[low_index]).date()),
        "bounce_from_low": _number(current / closes[low_index] - 1),
        "ret20": _number(current / closes[-21] - 1) if n > 20 else None,
        "ret60": _number(current / closes[-61] - 1) if n > 60 else None,
        "rv20": rv20,
        "rv20_pct5y": rv20_pct,
        "vol_d": vol_d,
        "well_dist_below": well_dist_below,
    }
    return state, vol_d, rv20


def build_panel(prices: pd.DataFrame, data_dir: Path | str | None = None) -> dict:
    data_path = Path(data_dir) if data_dir is not None else DIP_DATA
    oos_verdict = _load_oos_verdict(data_path / "oos_verdict.json")
    state, vol_d, _ = _state(prices)
    regime = _regime(prices)
    try:
        manifest, library, industries = _load_library(data_path)
    except Exception as exc:
        LOGGER.warning("dip event library unavailable: %s: %s", type(exc).__name__, exc)
        manifest, library, industries = {}, pd.DataFrame(), {}
    sym = str(prices.attrs.get("sym", ""))
    current_sw1 = industries.get(sym)
    dd = state["dd"]
    depth_bucket = next(
        (depth for depth in reversed(events.DEPTHS) if dd is not None and dd <= depth),
        None,
    )
    in_structure = bool(
        state["runup"] is not None
        and state["runup"] >= events.MIN_RUNUP
        and dd is not None
        and dd <= events.DEPTHS[0]
        and state["td_since_peak"] <= events.MAXAGE
    )
    full = pd.DataFrame()
    if depth_bucket is not None and not library.empty and "depth" in library:
        depth_values = pd.to_numeric(library["depth"], errors="coerce")
        full = library.loc[np.isclose(depth_values, depth_bucket, equal_nan=False)].copy()
    if "sig_date" in full:
        if state["asof"] is None:
            full = full.iloc[0:0].copy()
        else:
            signal_dates = pd.to_datetime(
                full["sig_date"], errors="coerce"
            ).dt.strftime("%Y-%m-%d")
            full = full.loc[
                signal_dates.notna() & (signal_dates <= state["asof"])
            ].copy()
    industry = (
        full.loc[full["sw1"].astype(str) == current_sw1]
        if current_sw1 and "sw1" in full
        else pd.DataFrame()
    )
    lib_info = {
        "version": manifest.get("version"),
        "cutoff": manifest.get("cutoff"),
        "smoke": bool(manifest.get("smoke", False)),
        "n_events": manifest.get("n_events"),
        "reference_asof": state["asof"],
    }
    if (
        manifest.get("cutoff") is not None
        and state["asof"] is not None
        and str(manifest["cutoff"]) > str(state["asof"])
    ):
        lib_info["note"] = "参考库截止晚于行情日期，已按结果成熟日期筛选"
    if not in_structure:
        similar = None
        first_hit = {
            key: {"hist": None, "rw": values}
            for key, values in _random_walk(vol_d).items()
        }
    else:
        no_1516 = full.loc[
            ~full["sig_date"].astype(str).str[:4].isin(EXCLUDED_YEARS)
        ]
        similar = {
            "full": _summary(full, state["asof"]),
            "industry": _summary(industry, state["asof"])
            if len(industry) >= 30
            else None,
            "excl1516": _summary(no_1516, state["asof"]),
            "industry_counts": _sample_counts(industry),
        }
        first_hit = {
            key: {
                "hist": _historical_first_hit(full, key, state["asof"]),
                "rw": values,
            }
            for key, values in _random_walk(vol_d).items()
        }
    return _json_safe(
        {
            "evidence": "descriptive",
            "oos": oos_verdict,
            "note": "历史分位，不是预测；样本外检验结果见各卡片标识",
            "lib": lib_info,
            "state": state,
            "in_structure": in_structure,
            "depth_bucket": depth_bucket,
            "similar": similar,
            "first_hit": first_hit,
            "regime": regime,
        }
    )
