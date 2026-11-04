"""PIT dip-event library construction. Definitions are frozen in oos/PROTOCOL.md."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

CUTOFF = pd.Timestamp("2026-11-03")
W, MIN_RUNUP, MAXAGE = 500, 2.0, 250
DEPTHS = (-0.40, -0.50, -0.60)
HS = (60, 120, 250)
FH = {"fh60": (0.85, 1.15, 60), "fh120": (0.80, 1.30, 120)}
UNC_STEP = 20


def load(path: Path | str) -> pd.DataFrame:
    d = pd.read_parquet(path)
    d["date"] = pd.to_datetime(d["date"])
    d = d[(d.close > 0) & (d.date <= CUTOFF)].drop_duplicates("date").sort_values("date")
    return d.reset_index(drop=True)


def ewma_vol(c: np.ndarray | pd.Series) -> np.ndarray:
    lr = np.diff(np.log(c), prepend=np.nan)
    return pd.Series(lr).ewm(alpha=0.06, min_periods=20).std().to_numpy()


def outcomes(
    c: np.ndarray, dates: pd.Series | pd.DatetimeIndex, e: int, delisted: bool
) -> dict:
    """从入场 bar e 起的结果；未来不足且未退市 -> 缺失；退市 -> 截断到最后一根。"""
    n, E, o = len(c), c[e], {}
    for h in HS:
        if e + h < n:
            seg, end = c[e + 1 : e + h + 1], e + h
        elif delisted and e + 1 < n:
            seg, end = c[e + 1 :], n - 1
            o[f"cens{h}"] = True
        else:
            continue
        o[f"r{h}"] = c[end] / E - 1
        o[f"mdd{h}"] = seg.min() / E - 1
        o[f"up{h}"] = seg.max() / E - 1
        o[f"known{h}"] = str(dates[end].date())
    for k, (L, U, H) in FH.items():
        full = e + H < n
        if not full and not (delisted and e + 1 < n):
            continue
        seg = c[e + 1 : e + H + 1] / E
        hL, hU = seg <= L, seg >= U
        iL = int(hL.argmax()) if hL.any() else 10**9
        iU = int(hU.argmax()) if hU.any() else 10**9
        if iL < iU:
            o[k] = "L"
        elif iU < iL:
            o[k] = "U"
        else:
            o[k] = "none" if full else "L"  # 退市前未触及：按协议记为 L
        end = min(e + H, n - 1)
        o[f"{k}_known"] = str(dates[end].date())
    return o


def one(path: Path, delisted: bool) -> tuple[list[dict], list[dict]]:
    sym = path.stem
    try:
        d = load(path)
    except Exception:
        return [], []
    if len(d) < W + 2:
        return [], []
    c, dates = d.close.to_numpy(float), d.date
    vol = ewma_vol(c)
    lr = np.diff(np.log(c), prepend=np.nan)
    rv20 = pd.Series(lr).rolling(20).std().to_numpy() * math.sqrt(252)
    rmax = pd.Series(c).rolling(W).max().to_numpy()
    n, ev, used = len(c), [], set()
    for t in range(W - 1, n - 1):
        if c[t] / rmax[t] - 1 > DEPTHS[0]:
            continue
        p = t - W + 1 + int(c[t - W + 1 : t + 1].argmax())
        if t - p > MAXAGE:
            continue
        tr = c[max(0, p - W + 1) : p + 1].min()
        runup = c[p] / tr - 1
        if runup < MIN_RUNUP:
            continue
        dd = c[t] / c[p] - 1
        for D in DEPTHS:
            if dd > D or (p, D) in used:
                continue
            used.add((p, D))
            e = t + 1
            o = dict(
                sym=sym,
                depth=D,
                sig_date=str(dates[t].date()),
                entry_date=str(dates[e].date()),
                peak_date=str(dates[p].date()),
                runup=runup,
                dd_sig=dd,
                age=t - p,
                vol_d=vol[t],
                rv20=rv20[t],
                delisted=delisted,
                sig_idx=t,
            )
            o.update(outcomes(c, dates, e, delisted))
            ev.append(o)
    unc = []
    for t in range(W - 1, n - 1, UNC_STEP):
        e = t + 1
        o = dict(
            sym=sym,
            sig_date=str(dates[t].date()),
            entry_date=str(dates[e].date()),
            vol_d=vol[t],
            delisted=delisted,
        )
        o.update(outcomes(c, dates, e, delisted))
        unc.append(o)
    return ev, unc


def _delisted_symbols(universe_file: Path | str | None) -> dict[str, bool]:
    if universe_file is None:
        return {}
    path = Path(universe_file)
    if not path.exists():
        return {}
    rows = json.loads(path.read_text(encoding="utf-8"))
    return {row["sym"]: bool(row.get("delisted")) for row in rows}


def _current_industry_map(path: Path | str | None) -> dict[str, str]:
    if path is None or not Path(path).exists():
        return {}
    frame = pd.read_csv(path, dtype={"sym": str})
    if not {"sym", "sw1_name"}.issubset(frame.columns):
        raise ValueError("current industry file must contain sym and sw1_name")
    return {
        str(row.sym): str(row.sw1_name)
        for row in frame.itertuples(index=False)
        if pd.notna(row.sw1_name) and str(row.sw1_name).strip()
    }


def _pit_industry_map(path: Path | str | None) -> dict[str, list[tuple[pd.Timestamp, pd.Timestamp | None, str]]]:
    if path is None or not Path(path).exists():
        return {}
    frame = pd.read_parquet(path)
    required = {"sym", "start_date", "end_date", "sw1_name"}
    if not required.issubset(frame.columns):
        raise ValueError(f"PIT industry file must contain {sorted(required)}")
    frame["start_date"] = pd.to_datetime(frame["start_date"])
    frame["end_date"] = pd.to_datetime(frame["end_date"], errors="coerce")
    result: dict[str, list[tuple[pd.Timestamp, pd.Timestamp | None, str]]] = {}
    for row in frame.itertuples(index=False):
        if pd.isna(row.sw1_name):
            continue
        end = None if pd.isna(row.end_date) else pd.Timestamp(row.end_date)
        result.setdefault(str(row.sym), []).append(
            (pd.Timestamp(row.start_date), end, str(row.sw1_name))
        )
    for rows in result.values():
        rows.sort(key=lambda value: value[0])
    return result


def _attach_industry(
    events: pd.DataFrame,
    current_map: dict[str, str],
    pit_map: dict[str, list[tuple[pd.Timestamp, pd.Timestamp | None, str]]],
) -> pd.DataFrame:
    out = events.copy()
    values = []
    for row in out.itertuples(index=False):
        sym = str(row.sym)
        sig_date = pd.Timestamp(row.sig_date)
        pit_name = None
        for start, end, name in reversed(pit_map.get(sym, [])):
            if start <= sig_date:
                if end is None or sig_date <= end:
                    pit_name = name
                break
        values.append(pit_name or current_map.get(sym))
    out["sw1"] = values
    return out


def _definition() -> dict:
    return {
        "W": W,
        "MIN_RUNUP": MIN_RUNUP,
        "MAXAGE": MAXAGE,
        "DEPTHS": list(DEPTHS),
        "HS": list(HS),
        "FH": {key: list(value) for key, value in FH.items()},
        "UNC_STEP": UNC_STEP,
    }


def build_library(
    cache_dir: Path | str,
    universe_file: Path | str | None,
    out_dir: Path | str,
    events_name: str = "events.parquet",
    unconditional_name: str = "uncond.parquet",
    current_industry: Path | str | None = None,
    industry_history: Path | str | None = None,
    smoke: bool = False,
    version: str | None = None,
) -> dict:
    cache_path, output_path = Path(cache_dir), Path(out_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    delisted = _delisted_symbols(universe_file)
    files = sorted(
        path
        for path in cache_path.glob("*.parquet")
        if path.stem[:2] in ("sh", "sz")
    )
    events, unconditional = [], []
    with ProcessPoolExecutor(8) as executor:
        for event_rows, unconditional_rows in executor.map(
            one,
            files,
            [delisted.get(path.stem, False) for path in files],
            chunksize=16,
        ):
            events += event_rows
            unconditional += unconditional_rows

    current_map = _current_industry_map(current_industry)
    pit_map = _pit_industry_map(industry_history)
    event_frame = pd.DataFrame(events)
    if event_frame.empty:
        event_frame = pd.DataFrame(columns=["sym", "sig_date", "depth", "sw1"])
    else:
        event_frame = _attach_industry(event_frame, current_map, pit_map)
    event_path = output_path / events_name
    unconditional_path = output_path / unconditional_name
    event_frame.to_parquet(event_path, index=False)
    pd.DataFrame(unconditional).to_parquet(unconditional_path, index=False)

    manifest = {
        "version": version or ("20261103-smoke-v1" if smoke else "20261103-v1"),
        "cutoff": str(CUTOFF.date()),
        "n_stocks": len(files),
        "n_events": len(event_frame),
        "n_unconditional": len(unconditional),
        "definition": _definition(),
        "sha256": hashlib.sha256(event_path.read_bytes()).hexdigest(),
        "events_file": events_name,
        "unconditional_file": unconditional_name,
        "smoke": bool(smoke),
        "sw1_pit": bool(pit_map),
    }
    (output_path / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"{len(files)} files {len(event_frame)} events {len(unconditional)} uncond rows"
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a PIT dip-event library")
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--universe", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--events-name", default="events.parquet")
    parser.add_argument("--unconditional-name", default="uncond.parquet")
    parser.add_argument("--current-industry", type=Path)
    parser.add_argument("--industry-history", type=Path)
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--version")
    args = parser.parse_args()
    build_library(
        args.cache,
        args.universe,
        args.out,
        args.events_name,
        args.unconditional_name,
        args.current_industry,
        args.industry_history,
        args.smoke,
        args.version,
    )


if __name__ == "__main__":
    main()
