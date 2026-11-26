"""严格因果的价格层势能面（筹码/停留时间势阱）拟合模块。

核心映射：
    rho_t(x) = (1 - alpha_t) * rho_{t-1}(x) + alpha_t * K_{h_t}(x - x_t)
    V_t(x)   = -ln(rho_t(x) + eps)

其中局部极小值 x* 为势阱中心（引力/支撑位），相邻势阱间的局部极大值 x_dagger 为势垒顶（逃逸/加速位）。
兼容纯收盘价（TPO 时间停留势阱）与 OHLCV/换手率（筹码成本势阱）。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.signal import find_peaks, peak_widths

DEFAULT_SCALES: dict[str, int] = {
    "short": 30,    # 对应 xs / 短周期整理
    "medium": 100,  # 对应 6-12m 泡沫主势阱
    "long": 300,    # 对应 12-24m / 跨年度宏观势阱
}


@dataclass(frozen=True)
class Well:
    """单个价格势阱的结构化描述（对数价格与真实价格双口径）。"""

    center_log: float          # 势阱中心 x*
    center_price: float        # exp(x*)
    depth: float               # 势阱深度 Delta V（-V 的拓扑突出度）
    half_width_log: float      # 捕获带半宽 delta（半高宽推导）
    barrier_below_log: float   # 下方最近势垒顶（跌破即判定势阱逃逸）
    barrier_below_price: float
    barrier_above_log: float | None  # 上方最近势垒顶
    barrier_above_price: float | None
    local_density: float       # 势阱底概率密度 rho(x*)


@dataclass(frozen=True)
class WellSnapshot:
    """单日 t 的势能面切片（严格只使用 <= t 的历史数据）。"""

    date: pd.Timestamp
    close: float
    log_close: float
    scale: str
    wells: tuple[Well, ...]
    overhead_mass: float       # 当前价位上方套牢盘/筹码占比 M_above(x_t) in [0, 1]
    grid_x: np.ndarray | None = None
    potential_v: np.ndarray | None = None

    def wells_below(self, ref_log: float | None = None) -> list[Well]:
        """返回参考价位下方的势阱，按从高到低（距当前价由近及远）排序。"""
        ref = self.log_close if ref_log is None else ref_log
        return sorted((w for w in self.wells if w.center_log < ref), key=lambda w: w.center_log, reverse=True)

    def wells_above(self, ref_log: float | None = None) -> list[Well]:
        """返回参考价位上方的势阱，按从低到高排序。"""
        ref = self.log_close if ref_log is None else ref_log
        return sorted((w for w in self.wells if w.center_log > ref), key=lambda w: w.center_log)

    def match_base_well(self, x_base: float, max_dist_log: float = 0.12) -> Well | None:
        """寻找与 LPPLS 泡沫基座 x_base 最契合的主目标势阱（优先近且深）。"""
        cands = [w for w in self.wells_below() if abs(w.center_log - x_base) <= max_dist_log]
        if not cands:
            return None
        return max(cands, key=lambda w: w.depth / (0.02 + abs(w.center_log - x_base)))


def _prepare_price_frame(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "date" in out.columns:
        out["date"] = pd.to_datetime(out["date"])
        out = out.sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)
    elif isinstance(out.index, pd.DatetimeIndex):
        out = out.sort_index().reset_index().rename(columns={out.index.name or "index": "date"})
    else:
        raise ValueError("输入 DataFrame 必须包含 'date' 列或 DatetimeIndex")

    if "close" not in out.columns:
        raise ValueError("输入 DataFrame 缺少必需列 'close'")
    if (out["close"] <= 0).any() or not np.isfinite(out["close"]).all():
        raise ValueError("close 列存在非正或非有限值")
    return out


def _causal_alpha_series(df: pd.DataFrame, half_life: int, vol_ema_span: int = 60) -> np.ndarray:
    """计算严格因果的逐日衰减率 alpha_t。"""
    alpha0 = 1.0 - 2.0 ** (-1.0 / max(1, half_life))
    n = len(df)
    if "turnover" in df.columns and df["turnover"].notna().sum() >= 20:
        turn = df["turnover"].astype(float).ffill().bfill().clip(lower=1e-6)
        base = turn.ewm(span=vol_ema_span, adjust=False).mean().clip(lower=1e-6)
        rel = (turn / base).clip(0.3, 3.0).to_numpy()
    elif "volume" in df.columns and (df["volume"].fillna(0) > 0).sum() >= 20:
        vol = df["volume"].astype(float).replace(0, np.nan).ffill().bfill().clip(lower=1e-6)
        base = vol.ewm(span=vol_ema_span, adjust=False).mean().clip(lower=1e-6)
        rel = (vol / base).clip(0.3, 3.0).to_numpy()
    else:
        rel = np.ones(n, dtype=float)
    return np.clip(alpha0 * rel, 1e-4, 0.35)


def extract_wells(
    grid_x: np.ndarray,
    rho: np.ndarray,
    min_depth: float = 0.18,
    min_sep_log: float = 0.03,
    eps: float = 1e-6,
) -> tuple[tuple[Well, ...], np.ndarray]:
    """从归一化密度 rho(x) 提取有效势能 V(x) 与所有显著势阱。"""
    step = float(grid_x[1] - grid_x[0])
    v = -np.log(np.maximum(rho, 0.0) + eps)
    score = -v  # 势阱底 = score 的峰值

    min_dist_bins = max(2, int(round(min_sep_log / step)))
    peaks, props = find_peaks(score, prominence=min_depth, distance=min_dist_bins)
    if len(peaks) == 0:
        return (), v

    widths_bins, _, left_ips, right_ips = peak_widths(score, peaks, rel_height=0.5)
    proms = props["prominences"]

    wells: list[Well] = []
    for i, idx in enumerate(peaks):
        half_w = float(np.clip(0.5 * widths_bins[i] * step, 0.01, 0.08))

        # 下方势垒：取与相邻低位势阱之间的最高势能点；若已是最低势阱则取左半高外延处
        if i > 0:
            prev_idx = int(peaks[i - 1])
            b_lo_idx = prev_idx + int(np.argmax(v[prev_idx : idx + 1]))
            b_lo_log = float(grid_x[b_lo_idx])
        else:
            b_lo_log = float(grid_x[idx] - max(half_w * 1.5, (idx - left_ips[i]) * step))

        # 上方势垒：取与相邻高位势阱之间的最高势能点
        if i + 1 < len(peaks):
            next_idx = int(peaks[i + 1])
            b_hi_idx = idx + int(np.argmax(v[idx : next_idx + 1]))
            b_hi_log: float | None = float(grid_x[b_hi_idx])
            b_hi_px: float | None = float(np.exp(b_hi_log))
        else:
            b_hi_log = None
            b_hi_px = None

        cx = float(grid_x[idx])
        wells.append(
            Well(
                center_log=cx,
                center_price=float(np.exp(cx)),
                depth=float(proms[i]),
                half_width_log=half_w,
                barrier_below_log=b_lo_log,
                barrier_below_price=float(np.exp(b_lo_log)),
                barrier_above_log=b_hi_log,
                barrier_above_price=b_hi_px,
                local_density=float(rho[idx]),
            )
        )
    return tuple(wells), v


def build_potential_series(
    df: pd.DataFrame,
    half_life: int = 100,
    scale_name: str = "medium",
    step: float = 0.0025,
    bw_vol_mult: float = 1.2,
    min_depth: float = 0.18,
    min_sep_log: float = 0.03,
    warmup: int | None = None,
    keep_curves: bool = False,
) -> tuple[pd.DataFrame, dict[pd.Timestamp, WellSnapshot]]:
    """逐日递推计算严格因果的势能面，输出日频特征表与快照字典。

    Returns:
        features: 按日对齐的 DataFrame，可直接落盘为 Parquet。
        snapshots: {date: WellSnapshot}，用于任意历史时点的无前视结构查询。
    """
    data = _prepare_price_frame(df)
    close = data["close"].to_numpy(dtype=float)
    logp = np.log(close)
    dates = data["date"].tolist()
    n = len(data)

    has_hl = {"high", "low"}.issubset(data.columns) and data["high"].notna().all() and data["low"].notna().all()
    if has_hl:
        high_l = np.log(data["high"].to_numpy(dtype=float))
        low_l = np.log(data["low"].to_numpy(dtype=float))
        typ_l = np.log((data["high"].to_numpy(dtype=float) + data["low"].to_numpy(dtype=float) + 2.0 * close) / 4.0)
        hl_spread = np.maximum(high_l - low_l, 0.0)
    else:
        typ_l = logp
        hl_spread = np.zeros(n, dtype=float)

    # 严格因果的 20 日对数收益波动率（含冷启动兜底）
    ret = np.diff(logp, prepend=logp[0])
    sig20 = pd.Series(ret).rolling(20, min_periods=5).std().bfill().fillna(0.015).clip(lower=0.004).to_numpy()
    down_ret = np.minimum(ret, 0.0)
    down_vol10 = pd.Series(down_ret).rolling(10, min_periods=5).std().to_numpy()
    alphas = _causal_alpha_series(data, half_life=half_life)

    # 相对量能（仅用于阻尼吸收判定，严格因果）
    if "volume" in data.columns and (data["volume"].fillna(0) > 0).sum() >= 20:
        vol_s = data["volume"].astype(float).replace(0, np.nan).ffill().bfill()
        rel_vol = (vol_s / vol_s.ewm(span=20, adjust=False).mean().clip(lower=1e-6)).to_numpy()
    else:
        rel_vol = np.full(n, np.nan)

    # 在 step*Z 固定晶格上分配求值数组；未触及区域密度恒为 0，数学上等价于无穷晶格，无前视泄露
    lo = np.floor(logp.min() / step) * step - 0.15
    hi = np.ceil(logp.max() / step) * step + 0.15
    grid_x = np.arange(lo, hi + 0.5 * step, step, dtype=float)
    rho = np.zeros_like(grid_x)

    min_obs = max(60, half_life) if warmup is None else warmup
    snapshots: dict[pd.Timestamp, WellSnapshot] = {}
    rows: list[dict] = []

    for i in range(n):
        h_i = max(bw_vol_mult * sig20[i], 0.45 * hl_spread[i], 2.0 * step)
        z = (grid_x - typ_l[i]) / h_i
        kern = np.exp(-0.5 * z * z)
        kern /= kern.sum() * step  # 归一化为标准概率密度 (integral = 1)

        if i == 0:
            rho = kern
        else:
            a = alphas[i]
            rho = (1.0 - a) * rho + a * kern
            rho /= rho.sum() * step

        if i + 1 < min_obs:
            rows.append(dict(date=dates[i], close=close[i], scale=scale_name, n_wells_below=0,
                             overhead_mass=np.nan, nearest_well_price=np.nan, nearest_well_depth=np.nan,
                             nearest_barrier_below=np.nan, nearest_well_above=np.nan,
                             in_well_capture=False, potential_rr=np.nan, damping_ok=False, reentry_signal=False))
            continue

        wells, v_curve = extract_wells(grid_x, rho, min_depth=min_depth, min_sep_log=min_sep_log)
        above_mask = grid_x > logp[i]
        overhead_mass = float(np.clip(rho[above_mask].sum() * step, 0.0, 1.0))

        snap = WellSnapshot(
            date=dates[i],
            close=float(close[i]),
            log_close=float(logp[i]),
            scale=scale_name,
            wells=wells,
            overhead_mass=overhead_mass,
            grid_x=grid_x if keep_curves else None,
            potential_v=v_curve if keep_curves else None,
        )
        snapshots[dates[i]] = snap

        below = snap.wells_below()
        above = snap.wells_above()
        w_cur = next((w for w in wells if abs(logp[i] - w.center_log) <= w.half_width_log), None)
        w_ref = w_cur if w_cur is not None else (below[0] if below else None)
        w_up = above[0] if above else None

        # 计算潜在盈亏比 R/R = (上方最近势阱 - 当前价) / (当前价 - 下方势垒止损)
        rr = np.nan
        if w_ref is not None and w_up is not None:
            risk = logp[i] - w_ref.barrier_below_log
            reward = w_up.center_log - logp[i]
            if risk > 0.005 and reward > 0:
                rr = float(reward / risk)

        # 阻尼确认：下行波动率拐头回落，或量价吸收（放量不创新低）
        vol_rollover = bool(
            i >= 5 and np.isfinite(down_vol10[i]) and np.isfinite(down_vol10[i - 3])
            and down_vol10[i] < 0.95 * np.nanmax(down_vol10[i - 4 : i])
            and logp[i] >= np.min(logp[i - 3 : i + 1]) + 0.3 * sig20[i]
        )
        vol_absorb = bool(
            np.isfinite(rel_vol[i]) and rel_vol[i] >= 1.35 and ret[i] >= -0.003
        )
        damping_ok = vol_rollover or vol_absorb
        # 预登记修正：盈亏比缺失（无上方势阱等）记为不通过
        reentry = bool(w_cur is not None and damping_ok and np.isfinite(rr) and rr >= 1.8)

        rows.append(
            dict(
                date=dates[i],
                close=float(close[i]),
                scale=scale_name,
                n_wells_below=len(below),
                overhead_mass=overhead_mass,
                nearest_well_price=w_ref.center_price if w_ref else np.nan,
                nearest_well_depth=w_ref.depth if w_ref else np.nan,
                nearest_barrier_below=w_ref.barrier_below_price if w_ref else np.nan,
                nearest_well_above=w_up.center_price if w_up else np.nan,
                in_well_capture=w_cur is not None,
                potential_rr=rr,
                damping_ok=damping_ok,
                reentry_signal=reentry,
            )
        )

    return pd.DataFrame(rows), snapshots


def build_multiscale_potentials(
    df: pd.DataFrame,
    scales: Mapping[str, int] = DEFAULT_SCALES,
    **kwargs,
) -> tuple[dict[str, pd.DataFrame], dict[str, dict[pd.Timestamp, WellSnapshot]]]:
    """一次构建多尺度（短/中/长）势能面。"""
    feats, snaps = {}, {}
    for name, hl in scales.items():
        feats[name], snaps[name] = build_potential_series(df, half_life=hl, scale_name=name, **kwargs)
    return feats, snaps

