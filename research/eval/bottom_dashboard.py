"""模块二：金融物理“说人话”底部与冷却期多维仪表盘（严格 Point-in-Time）。

将单一价格冷却期升级为三层验证（赔率层 / 出清层 / 右侧层）：
1. Omori 余震衰减（自适应波动分位大阴线 + 波动比 + 死猫跳破底检测）
2. 估值赔率（ERP 股债性价比 + 破净率 PBN）
3. 杠杆出清（融资余额 + 维持担保比例，滞后 1 交易日 PIT）
4. 成交地量 / 换手代理（成交量/额相对 20 日均与 252 日分位）
5. 国家队 ETF 代理（4 只头部沪深300ETF 份额申赎流向）
6. 右侧结构确认（站上 20 日线 + 市场宽度回升）
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BOTTOM_SIGNAL_PATH = ROOT / "web/mock/data/market/bottom_signal_latest.json"
DEFAULT_NT_ETF_PATH = ROOT / "web/mock/data/nt_etf/nt_etf_latest.json"
DEFAULT_BREADTH_PATH = ROOT / "web/mock/data/market/breadth_latest.json"
DEFAULT_MARGIN_CACHE = ROOT / "data/cache/margin/sse_margin.parquet"


def _load_json_pit(path: Path, date: pd.Timestamp) -> dict[str, Any] | None:
    """仅当外部快照的 asof 落在 [date-10d, date] 区间内时才使用，防止历史回放发生未来泄漏。"""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    asof_str = data.get("asof") or (data.get("current") or {}).get("date")
    if not asof_str:
        return None
    try:
        snap_dt = pd.Timestamp(str(asof_str)[:10])
    except Exception:  # noqa: BLE001
        return None
    # 严格 PIT：快照日期不得晚于 asof，且距 asof 不超过 15 个自然日（避免拿过时快照充数）
    if snap_dt > date or (date - snap_dt).days > 15:
        return None
    return data


def _eval_omori(close_pit: pd.Series) -> dict[str, Any]:
    """维度 1：Omori 余震衰减（自适应分位大阴线 + 波动率比 + 死猫跳破底检测）。"""
    tail = close_pit.tail(252)
    if len(tail) < 25:
        return {
            "id": "omori",
            "name": "Omori 余震衰减",
            "value_text": "样本不足",
            "pct": None,
            "light": "gray",
            "active": False,
            "drawdown_from_peak": None,
            "elapsed_days_since_peak": None,
            "dead_cat_risk": False,
            "plain_text": "历史交易日不足 25 日，暂无法评估余震衰减。",
            "bottom_rule": "大阴线频次衰减 + 短/长波动比回落 + 近 20 日不再破底",
            "top_rule": "高位剧烈振幅放大往往是相变前兆",
            "is_proxy": False,
        }

    peak_idx = tail.idxmax()
    peak_val = float(tail.loc[peak_idx])
    cur_val = float(tail.iloc[-1])
    drawdown = round(cur_val / peak_val - 1.0, 4) if peak_val > 0 else 0.0
    elapsed = int(len(tail.loc[peak_idx:]) - 1)

    rets = tail.pct_change().dropna()
    # 按标的自身过去 1 年收益率的 5% 分位作为大阴线自适应阈值（兜底 -2.0%，上限 -4.5%）
    q05 = float(rets.quantile(0.05))
    drop_thresh = float(np.clip(q05, -0.045, -0.020))
    recent15 = rets.tail(15)
    big_drops = int((recent15 <= drop_thresh).sum())
    vol10 = float(rets.tail(10).std() * np.sqrt(252)) if len(rets) >= 10 else 0.0
    vol60 = float(rets.tail(60).std() * np.sqrt(252)) if len(rets) >= 20 else vol10
    vol_ratio = round(vol10 / vol60, 2) if vol60 > 0 else 1.0

    # 死猫跳/二次破底检测：近 10 日内创过近 60 日收盘新低，且当前距离高点已跌超 12%
    # 若已处于低波动阴跌横盘阶段（近 10 日跌幅 < 3% 且无大阴线、无波动放大），不误判为剧烈余震
    low60 = float(tail.tail(60).min())
    recent10 = tail.tail(10)
    recent10_low = float(recent10.min())
    recent10_drop = float(recent10.iloc[-1] / recent10.iloc[0] - 1.0) if len(recent10) >= 2 and float(recent10.iloc[0]) > 0 else 0.0
    new_low_recently = (
        recent10_low <= low60 * 1.005
        and drawdown <= -0.12
        and (recent10_drop <= -0.03 or big_drops >= 1 or vol_ratio > 1.15)
    )

    aftershock_active = (big_drops >= 2) or (vol_ratio > 1.35) or new_low_recently
    if drawdown > -0.10 and not aftershock_active:
        light = "gray"
        plain = f"距年内高点回撤 {drawdown * 100:.1f}%，未进入主震下跌相，无余震限制。"
    elif aftershock_active:
        light = "red"
        reasons = []
        if big_drops >= 2:
            reasons.append(f"近 15 日出现 {big_drops} 次大阴线（阈值 {drop_thresh * 100:.1f}%）")
        if vol_ratio > 1.35:
            reasons.append(f"短期波动放大至 60 日均值的 {vol_ratio:.2f} 倍")
        if new_low_recently:
            reasons.append("近 10 日再创 60 日新低（防死猫跳二次杀跌）")
        plain = "余震未消（" + "；".join(reasons) + "），严禁左侧重仓抄底。"
    elif elapsed < 20:
        light = "yellow"
        plain = f"距高点仅 {elapsed} 交易日（未满 20 日最小冷却期），继续观察。"
    else:
        light = "green"
        plain = f"距高点已过 {elapsed} 交易日，大阴线与波动比（{vol_ratio:.2f}×）均已衰减，未再破底。"

    return {
        "id": "omori",
        "name": "Omori 余震衰减",
        "value_text": f"大阴线 {big_drops} 次 · 波动比 {vol_ratio:.2f}×",
        "pct": None,
        "light": light,
        "active": bool(aftershock_active),
        "drawdown_from_peak": drawdown,
        "elapsed_days_since_peak": elapsed,
        "dead_cat_risk": bool(new_low_recently),
        "drop_threshold": round(drop_thresh, 4),
        "plain_text": plain,
        "bottom_rule": "大阴线衰减 + 波动比 ≤1.35× + 近 10 日不再创 60 日新低 + 冷却 ≥20 日",
        "top_rule": "高位剧烈波动放大提示筹码松动",
        "is_proxy": False,
    }


def _eval_erp(date: pd.Timestamp, has_active_top: bool, path: Path = DEFAULT_BOTTOM_SIGNAL_PATH) -> dict[str, Any]:
    """维度 2：估值赔率（ERP 股债性价比 + 破净率 PBN）。"""
    snap = _load_json_pit(path, date)
    cur = (snap or {}).get("current") or {}
    erp = cur.get("erp")
    erp_pct = cur.get("erp_pct")
    pbn_pct = cur.get("pbn_pct")

    if erp_pct is None and pbn_pct is None:
        return {
            "id": "erp",
            "name": "股债性价比 ERP",
            "value_text": "当日快照未同步",
            "pct": None,
            "light": "gray",
            "passed_bottom": False,
            "passed_top": False,
            "plain_text": "当前日期无可用 ERP/破净率快照（严格 PIT，不跨日借用未来数据）。",
            "bottom_rule": "ERP 分位 ≥80% 且破净率分位 ≥80%（双高=估值地板资格证）",
            "top_rule": "ERP 分位 ≤20% 且叠加 6–12 月正向泡沫加速",
            "is_proxy": False,
        }

    erp_p = float(erp_pct) if erp_pct is not None else None
    pbn_p = float(pbn_pct) if pbn_pct is not None else None
    passed_bottom = (erp_p is not None and erp_p >= 0.80) or (pbn_p is not None and pbn_p >= 0.80)
    both_high = (erp_p is not None and erp_p >= 0.80) and (pbn_p is not None and pbn_p >= 0.80)
    passed_top = (erp_p is not None and erp_p <= 0.20) and has_active_top

    val_parts = []
    if erp is not None:
        val_parts.append(f"ERP {erp * 100:.2f}%")
    if erp_p is not None:
        val_parts.append(f"分位 {erp_p * 100:.0f}%")
    if pbn_p is not None:
        val_parts.append(f"破净分位 {pbn_p * 100:.0f}%")
    value_text = " · ".join(val_parts)

    if passed_top:
        light = "red"
        plain = "股票相对国债已偏贵（ERP 低分位）且叠加顶部泡沫加速，属于高危减仓区。"
    elif both_high:
        light = "green"
        plain = "股债性价比与破净率双双进入历史极值（≥80%），长期赔率极佳，拿到左侧分批资格证。"
    elif passed_bottom:
        light = "yellow"
        plain = "估值或破净率已有一项进入便宜区间，具备赔率支撑，但仍需等待出清与右侧确认。"
    elif erp_p is not None and erp_p <= 0.25:
        light = "yellow"
        plain = "股债性价比偏低（股票相对国债偏贵），安全边际不足，不宜激进追涨。"
    else:
        light = "gray"
        plain = "股债性价比处于历史中性区间，既不算便宜地板也未到极端高估。"

    return {
        "id": "erp",
        "name": "股债性价比 ERP",
        "value_text": value_text,
        "pct": round(erp_p, 4) if erp_p is not None else None,
        "pbn_pct": round(pbn_p, 4) if pbn_p is not None else None,
        "light": light,
        "passed_bottom": bool(passed_bottom),
        "passed_top": bool(passed_top),
        "plain_text": plain,
        "bottom_rule": "ERP ≥80% 分位或破净率 ≥80% 分位（只保证赔率不保证时点）",
        "top_rule": "ERP ≤20% 分位 + 顶部泡沫加速 = 高危减仓",
        "is_proxy": False,
    }


def _eval_margin(date: pd.Timestamp, close_pit: pd.Series, path: Path = DEFAULT_MARGIN_CACHE) -> dict[str, Any]:
    """维度 3：杠杆出清（融资余额，严格 T+1 滞后 1 交易日 PIT）。"""
    if not path.exists():
        return {
            "id": "margin",
            "name": "融资余额（杠杆出清）",
            "value_text": "两融缓存待同步",
            "pct": None,
            "light": "gray",
            "passed_bottom": False,
            "passed_top": False,
            "plain_text": "本地尚无两融日频缓存（交易所 T+1 披露），暂不计入出清打分。",
            "bottom_rule": "余额停止下降 + 20 日净偿还减速 + 指数不创新低",
            "top_rule": "余额加速上行且创近 1 年高分位（≥90%）",
            "is_proxy": False,
        }
    try:
        df = pd.read_parquet(path)
        df["date"] = pd.to_datetime(df["date"])
        # 严格 PIT：交易所两融数据 T+1 早间披露，因此截至 asof 当日最多只能看到 date - 1 天
        pit = df[df["date"] < date].sort_values("date").tail(260)
    except Exception:  # noqa: BLE001
        pit = pd.DataFrame()

    if len(pit) < 30 or "fin_balance" not in pit:
        return {
            "id": "margin",
            "name": "融资余额（杠杆出清）",
            "value_text": "样本不足",
            "pct": None,
            "light": "gray",
            "passed_bottom": False,
            "passed_top": False,
            "plain_text": "有效两融历史不足 30 日，暂无法判定去杠杆进度。",
            "bottom_rule": "余额停止下降 + 20 日净偿还减速 + 指数不创新低",
            "top_rule": "余额加速上行且创近 1 年高分位（≥90%）",
            "is_proxy": False,
        }

    bal = pd.to_numeric(pit["fin_balance"], errors="coerce").dropna()
    cur_bal = float(bal.iloc[-1])
    pct = float((bal <= cur_bal).mean())
    chg20 = float(bal.iloc[-1] / bal.iloc[-21] - 1.0) if len(bal) >= 21 else 0.0
    chg5 = float(bal.iloc[-1] / bal.iloc[-6] - 1.0) if len(bal) >= 6 else 0.0
    # 净偿还减速：前 20 日整体在去杠杆（chg20 <= -0.02），但近 5 日降幅收窄或企稳（chg5 > chg20 / 4）
    deleveraging_slowed = chg20 <= -0.02 and chg5 >= -0.008
    price_stable = len(close_pit) >= 20 and float(close_pit.iloc[-1]) > float(close_pit.tail(20).min()) * 1.005

    passed_bottom = (pct <= 0.35 and deleveraging_slowed and price_stable)
    passed_top = (pct >= 0.90 and chg20 >= 0.05)

    val_yi = cur_bal / 1e8 if cur_bal > 1e6 else cur_bal
    value_text = f"{val_yi:.0f} 亿 · 分位 {pct * 100:.0f}% · 20日 {chg20 * 100:+.1f}%"
    if passed_top:
        light = "red"
        plain = "借钱炒股的杠杆盘创近一年新高且仍在加速加仓，一旦下跌极易引发强平踩踏。"
    elif passed_bottom:
        light = "green"
        plain = "杠杆盘处于低位且净偿还明显减速、指数不再创新低，抛压燃料基本出清。"
    elif pct <= 0.25:
        light = "yellow"
        plain = "融资余额虽在低位（下跌燃料有限），但尚未看到企稳回流，单靠低位不能直接抄底。"
    else:
        light = "gray"
        plain = "两融杠杆处于常态区间，既无过热踩踏风险也未到极端出清点。"

    return {
        "id": "margin",
        "name": "融资余额（杠杆出清）",
        "value_text": value_text,
        "pct": round(pct, 4),
        "light": light,
        "passed_bottom": bool(passed_bottom),
        "passed_top": bool(passed_top),
        "plain_text": plain,
        "bottom_rule": "余额低位 + 20 日净偿还减速 + 指数不创新低（低位本身不是买点）",
        "top_rule": "余额创近 1 年 ≥90% 分位且 20 日加速扩张 ≥5%",
        "is_proxy": False,
    }


def _eval_turnover(ohlc: pd.DataFrame, date: pd.Timestamp, close_pit: pd.Series) -> dict[str, Any]:
    """维度 4：成交地量 / 换手代理（基于严格 PIT 的成交量/成交额相对 20 日均与 252 日分位）。"""
    df = ohlc.copy()
    if "date" in df:
        df["date"] = pd.to_datetime(df["date"])
        df = df[df["date"] <= date].sort_values("date")
    col = "amount" if "amount" in df and pd.to_numeric(df["amount"], errors="coerce").notna().sum() >= 30 else (
        "volume" if "volume" in df and pd.to_numeric(df["volume"], errors="coerce").notna().sum() >= 30 else None
    )
    if col is None:
        return {
            "id": "turnover",
            "name": "成交地量（换手代理）",
            "value_text": "无量能数据",
            "pct": None,
            "light": "gray",
            "passed_bottom": False,
            "passed_top": False,
            "plain_text": "当前行情缺少成交量/成交额序列，暂无法评估地量出清。",
            "bottom_rule": "先见一年 20% 分位以下地量，随后放量站上 20 日线",
            "top_rule": "成交创一年 95% 分位以上天量或量价背离",
            "is_proxy": True,
        }

    vol = pd.to_numeric(df[col], errors="coerce").dropna().tail(252)
    if len(vol) < 25:
        return {
            "id": "turnover",
            "name": "成交地量（换手代理）",
            "value_text": "样本不足",
            "pct": None,
            "light": "gray",
            "passed_bottom": False,
            "passed_top": False,
            "plain_text": "历史量能不足 25 日，暂无法计算地量分位。",
            "bottom_rule": "先见一年 20% 分位以下地量，随后放量站上 20 日线",
            "top_rule": "成交创一年 95% 分位以上天量或量价背离",
            "is_proxy": True,
        }

    ma5 = float(vol.tail(5).mean())
    ma20 = float(vol.tail(20).mean())
    ratio20 = round(ma5 / ma20, 2) if ma20 > 0 else 1.0
    pct_cur = float((vol <= float(vol.iloc[-1])).mean())
    had_dry_volume_20d = float(vol.tail(20).min() <= vol.quantile(0.20)) > 0
    above_ma20 = len(close_pit) >= 20 and float(close_pit.iloc[-1]) >= float(close_pit.tail(20).mean())

    passed_bottom = bool(had_dry_volume_20d and ratio20 >= 1.05 and above_ma20)
    passed_top = bool(pct_cur >= 0.95 and ratio20 >= 1.35)

    value_text = f"5/20日量比 {ratio20:.2f}× · 年内分位 {pct_cur * 100:.0f}%"
    if passed_top:
        light = "red"
        plain = "成交放巨量至年内 95% 分位以上，情绪极度亢奋，需防高位天量派发与量价背离。"
    elif passed_bottom:
        light = "green"
        plain = "近 20 日已出现情绪冰点地量，且最新温和放量站上 20 日线，量能右侧确认。"
    elif pct_cur <= 0.20:
        light = "yellow"
        plain = "成交跌至年内 20% 分位以下（地量冰点：该卖的快卖完了），但还没看到放量资金接盘，先别急。"
    else:
        light = "gray"
        plain = "成交量能处于常态区间（以成交额/量比作换手率代理），无极端地量或天量。"

    return {
        "id": "turnover",
        "name": "成交地量（换手代理）",
        "value_text": value_text,
        "pct": round(pct_cur, 4),
        "ratio20": ratio20,
        "light": light,
        "passed_bottom": passed_bottom,
        "passed_top": passed_top,
        "plain_text": plain,
        "bottom_rule": "先缩至年内 20% 分位以下地量，再温和放量站上 20 日线",
        "top_rule": "成交冲上年内 95% 分位天量且量比 ≥1.35×",
        "is_proxy": True,
    }


def _eval_nt_etf(date: pd.Timestamp, drawdown: float | None, path: Path = DEFAULT_NT_ETF_PATH) -> dict[str, Any]:
    """维度 5：国家队 ETF 代理（4 只头部沪深300ETF 份额申赎流向）。"""
    snap = _load_json_pit(path, date)
    cats = (snap or {}).get("categories") or []
    hs300 = next((c for c in cats if c.get("category") == "沪深300"), None)
    if not hs300:
        return {
            "id": "nt_etf",
            "name": "头部300ETF（国家队代理）",
            "value_text": "快照未同步",
            "pct": None,
            "light": "gray",
            "passed_bottom": False,
            "passed_top": False,
            "plain_text": "当前日期无可用沪深300头部 ETF 份额快照（严格 PIT，不跨日借用）。",
            "bottom_rule": "指数回撤期 4 只头部 300ETF 逆势净申购（近 5 日 ≥50 亿）",
            "top_rule": "指数高位但 4 只头部 300ETF 持续净赎回",
            "is_proxy": True,
        }

    d5 = float(hs300.get("d5") or 0.0)
    d21 = float(hs300.get("d21") or 0.0)
    in_drawdown = drawdown is not None and drawdown <= -0.08
    near_high = drawdown is not None and drawdown >= -0.05

    passed_bottom = bool(in_drawdown and (d5 >= 50.0 or d21 >= 150.0))
    passed_top = bool(near_high and d5 <= -50.0 and d21 <= -100.0)

    value_text = f"5日 {d5:+.1f} 亿 · 21日 {d21:+.1f} 亿"
    if passed_bottom:
        light = "green"
        plain = "指数回撤期间头部 300ETF 出现明显逆势净申购，说明大资金/国家队在低位托底接货。"
    elif passed_top:
        light = "red"
        plain = "指数处于高位但头部 300ETF 连续净赎回，存在大资金高位派发迹象。"
    elif d5 >= 30.0:
        light = "yellow"
        plain = "近 5 日头部 300ETF 呈净申购，但全市场申赎含机构/散户，需结合回撤位置观察。"
    elif d5 <= -30.0:
        light = "yellow"
        plain = "近 5 日头部 300ETF 呈净赎回，暂未看到大资金逆势托底。"
    else:
        light = "gray"
        plain = "头部 300ETF 份额流向平稳，暂无明显托底或派发异动（全市场申赎代理口径）。"

    return {
        "id": "nt_etf",
        "name": "头部300ETF（国家队代理）",
        "value_text": value_text,
        "pct": None,
        "light": light,
        "passed_bottom": passed_bottom,
        "passed_top": passed_top,
        "plain_text": plain,
        "bottom_rule": "回撤期 4 只头部 300ETF 逆势净申购（5 日 ≥50 亿或 21 日 ≥150 亿）",
        "top_rule": "高位期持续净赎回（5 日 ≤-50 亿且 21 日 ≤-100 亿）",
        "is_proxy": True,
    }


def _eval_right_side(close_pit: pd.Series, date: pd.Timestamp, path: Path = DEFAULT_BREADTH_PATH) -> dict[str, Any]:
    """维度 6：右侧结构与市场宽度确认（站上 20 日线 + 市场宽度改善）。"""
    if len(close_pit) < 25:
        return {
            "id": "right_side",
            "name": "右侧结构与宽度",
            "value_text": "样本不足",
            "pct": None,
            "light": "gray",
            "passed_bottom": False,
            "plain_text": "历史交易日不足 25 日，暂无法判断右侧均线结构。",
            "bottom_rule": "指数站上 20 日线 + 20 日线走平拐头（配合市场宽度回升）",
            "top_rule": "指数新高但市场宽度背离下行",
            "is_proxy": False,
        }

    ma20 = close_pit.rolling(20).mean()
    cur_c = float(close_pit.iloc[-1])
    cur_ma20 = float(ma20.iloc[-1])
    prev_ma20 = float(ma20.iloc[-5]) if len(ma20) >= 25 else cur_ma20
    above_ma20 = cur_c >= cur_ma20
    ma20_rising = cur_ma20 >= prev_ma20 * 0.998

    snap = _load_json_pit(path, date)
    breadth_note = ""
    if snap:
        latest = snap.get("latest") or {}
        adv_ratio = latest.get("adv_ratio") or latest.get("above_ma20")
        if adv_ratio is not None:
            breadth_note = f" · 宽度 {float(adv_ratio) * 100:.0f}%"

    passed_bottom = bool(above_ma20 and ma20_rising)
    dist = (cur_c / cur_ma20 - 1.0) * 100.0 if cur_ma20 > 0 else 0.0
    value_text = f"距 20 日线 {dist:+.1f}%{breadth_note}"

    if passed_bottom:
        light = "green"
        plain = "价格站上 20 日线且均线走平/向上，右侧承接结构初步成立。"
    elif above_ma20:
        light = "yellow"
        plain = "价格刚反抽至 20 日线上方，但 20 日线仍在下行，防反抽回落。"
    else:
        light = "red"
        plain = "价格仍在 20 日线下方运行，右侧趋势尚未扭转，不急于抢跑。"

    return {
        "id": "right_side",
        "name": "右侧结构与宽度",
        "value_text": value_text,
        "pct": None,
        "light": light,
        "passed_bottom": passed_bottom,
        "plain_text": plain,
        "bottom_rule": "收盘站上 20 日线且 20 日线走平/拐头向上",
        "top_rule": "跌破 20 日线且反弹无力",
        "is_proxy": False,
    }


def build_bottom_dashboard(
    ohlc: pd.DataFrame,
    close_pit: pd.Series,
    date: pd.Timestamp,
    has_active_top: bool,
    *,
    bottom_signal_path: Path = DEFAULT_BOTTOM_SIGNAL_PATH,
    nt_etf_path: Path = DEFAULT_NT_ETF_PATH,
    breadth_path: Path = DEFAULT_BREADTH_PATH,
    margin_path: Path = DEFAULT_MARGIN_CACHE,
) -> dict[str, Any]:
    """合成三层验证（赔率 / 出清 / 右侧）与“说人话”总结论。"""
    omori = _eval_omori(close_pit)
    erp = _eval_erp(date, has_active_top, path=bottom_signal_path)
    margin = _eval_margin(date, close_pit, path=margin_path)
    turnover = _eval_turnover(ohlc, date, close_pit)
    nt_etf = _eval_nt_etf(date, omori.get("drawdown_from_peak"), path=nt_etf_path)
    right_side = _eval_right_side(close_pit, date, path=breadth_path)

    dimensions = [omori, erp, margin, turnover, nt_etf, right_side]

    # 三层判定
    layer_odds = bool(erp["passed_bottom"])
    clearing_hits = sum([
        1 if omori["light"] == "green" else 0,
        1 if margin["passed_bottom"] else 0,
        1 if turnover["passed_bottom"] else 0,
        1 if nt_etf["passed_bottom"] else 0,
    ])
    layer_clearing = (not omori["active"]) and (clearing_hits >= 2)
    layer_right = bool(right_side["passed_bottom"])
    layers_passed = int(layer_odds) + int(layer_clearing) + int(layer_right)

    top_alert = bool(has_active_top or erp["passed_top"] or (margin["passed_top"] and turnover["passed_top"]))

    if top_alert:
        verdict = "top_warning"
        verdict_light = "red"
        headline = "顶部风险活跃 → 严禁追高，注意逢高减仓"
    elif omori["active"]:
        verdict = "aftershock_block"
        verdict_light = "red"
        headline = "大跌余震未消 / 防死猫跳 → 严禁左侧抄底"
    elif layers_passed == 3:
        verdict = "reentry_green"
        verdict_light = "green"
        headline = "赔率 + 出清 + 右侧三层全过 → 可分批试探（30%→30%→40%）"
    elif layers_passed == 2:
        verdict = "watch_yellow"
        verdict_light = "yellow"
        headline = f"三层已过 {layers_passed} 层 → 进入观察区，等待剩余条件补齐"
    else:
        verdict = "neutral"
        verdict_light = "gray"
        headline = "既无顶部泡沫也未见底部三层共振 → 常态观望，不急于抄底"

    return {
        "verdict": verdict,
        "verdict_light": verdict_light,
        "headline": headline,
        "layers": {
            "odds": layer_odds,
            "clearing": layer_clearing,
            "right_side": layer_right,
            "passed_count": layers_passed,
        },
        "omori": omori,
        "dimensions": dimensions,
        "note": "所有阈值均为经验参数，非监管标准；两融与 ETF 份额严格滞后 1 交易日（PIT）；北向日频净买入已停披露故不纳入。",
        "evidence": "descriptive",
    }


DEFAULT_VALUATION_HISTORY_PATH = Path("data/market/bottom_valuation_series.csv")


def load_valuation_history(path: Path = DEFAULT_VALUATION_HISTORY_PATH) -> pd.DataFrame | None:
    """加载严格 PIT 的全 A 历史股债利差（erp_pct）与破净股占比（pbn_pct）日频序列。"""
    if not path.exists():
        return None
    try:
        df = pd.read_csv(path, parse_dates=["date"])
        if df.empty or "date" not in df.columns:
            return None
        df = df.sort_values("date").drop_duplicates("date", keep="last").set_index("date")
        return df
    except Exception:
        return None


def compute_fco_neg_intensity_series(
    frames: list[dict[str, Any]],
    valuation_df: pd.DataFrame | None = None,
    valuation_path: Path = DEFAULT_VALUATION_HISTORY_PATH,
) -> list[dict[str, Any]]:
    """为历史周度帧逐帧计算严格 PIT 的 A 股四维实证底部绿色强度（0–1）与底部首次共振标记。

    补齐纯负泡沫 LPPLS 在 A 股胜率低的短板，综合经 A 股 2005–2026 历次大底验证的 4 个 PIT 维度：
    1. valuation（估值安全边际，权 0.35）：全 A 股债利差 ERP 3 年滚动分位 + 破净股占比 3 年滚动分位；
    2. clearing（超跌出清深度，权 0.30）：相对过去 52 周高点的回撤深度（<= -12% 起步，-40% 满分）；
    3. stabilize（防死猫跳/大森余震过滤，权 0.20）：近 4 周不再创 12 周新低 + 近 4 周波动收敛；
    4. right_side（右侧企稳触发，权 0.15）：站上 10 周均线或 10 周均线走平拐头。
    红绿互斥：若当前帧存在活跃 6–12m 顶部红柱，绿色强度强制归零。
    """
    val_df = valuation_df if valuation_df is not None else load_valuation_history(valuation_path)
    val_dates = val_df.index.to_numpy() if val_df is not None and len(val_df) else None

    closes: list[float] = []
    last_bottom_idx = -999
    enriched: list[dict[str, Any]] = []

    for idx, frame in enumerate(frames):
        c = frame.get("close")
        w6 = (frame.get("w") or {}).get("6-12m")
        has_top = bool(isinstance(w6, list) and len(w6) == 2 and w6[0])
        asof_str = str(frame.get("asof") or "")

        # 严格 PIT 查表：仅取 <= asof 的最后一条全 A 估值记录
        erp_pct: float | None = None
        pbn_pct: float | None = None
        if val_dates is not None and asof_str:
            ts = np.datetime64(pd.Timestamp(asof_str))
            pos = int(np.searchsorted(val_dates, ts, side="right")) - 1
            if pos >= 0:
                row = val_df.iloc[pos]
                e_val = row.get("erp_pct")
                p_val = row.get("pbn_pct")
                if e_val is not None and np.isfinite(float(e_val)):
                    erp_pct = float(e_val)
                if p_val is not None and np.isfinite(float(p_val)):
                    pbn_pct = float(p_val)

        intensity = 0.0
        factors: dict[str, Any] = {}
        stabilize_ok = False

        if c is not None and np.isfinite(float(c)) and float(c) > 0:
            cur_c = float(c)
            closes.append(cur_c)
            if not has_top and len(closes) >= 20:
                win52 = closes[-52:]
                peak52 = max(win52)
                dd = cur_c / peak52 - 1.0 if peak52 > 0 else 0.0

                # 1) 估值安全边际（ERP 分位 + 破净率分位）
                val_scores = [x for x in (erp_pct, pbn_pct) if x is not None]
                val_raw = float(np.mean(val_scores)) if val_scores else None
                # 仅在进入偏低估区间（>= 0.60）才计分，>= 0.90 满分 1.0
                val_score = float(np.clip((val_raw - 0.60) / 0.30, 0.0, 1.0)) if val_raw is not None else None

                # 2) 超跌出清深度（-12% 起步，-40% 满分 1.0）
                clearing_score = float(np.clip((-dd - 0.12) / 0.28, 0.0, 1.0)) if dd <= -0.12 else 0.0

                # 3) 防死猫跳（大森余震过滤：止跌不再创 12 周新低 + 波动收敛）
                recent4 = closes[-4:]
                low12 = min(closes[-12:])
                stopped_falling = (min(recent4) > low12 * 1.005) or (cur_c >= recent4[0] * 0.995)
                rets12 = np.diff(np.log(closes[-13:])) if len(closes) >= 13 else np.array([])
                vol_calm = (
                    len(rets12) >= 8
                    and float(np.std(rets12[-4:])) <= float(np.std(rets12)) * 1.05
                )
                stabilize_score = (0.65 if stopped_falling else 0.0) + (0.35 if vol_calm else 0.0)
                stabilize_ok = bool(stopped_falling)

                # 4) 右侧企稳（站上 10 周均线或 10 周均线走平）
                ma10 = float(np.mean(closes[-10:]))
                prev_ma10 = float(np.mean(closes[-12:-2])) if len(closes) >= 12 else ma10
                above_ma10 = cur_c >= ma10
                ma10_flat = ma10 >= prev_ma10 * 0.995
                right_score = (0.70 if above_ma10 else 0.0) + (0.30 if ma10_flat else 0.0)

                # 必须满足“显著回撤 <= -12%”或“极端便宜（ERP/破净均值 >= 0.85 且回撤 <= -8%）”才启动底部评分
                in_drawdown_zone = (dd <= -0.12) or (val_raw is not None and val_raw >= 0.85 and dd <= -0.08)
                if in_drawdown_zone:
                    if val_score is not None:
                        raw_int = (
                            0.35 * val_score
                            + 0.30 * clearing_score
                            + 0.20 * stabilize_score
                            + 0.15 * right_score
                        )
                    else:
                        # 2005 年前缺少 ERP/破净数据时，将权重按比例分配给量价维度
                        raw_int = (
                            0.50 * clearing_score
                            + 0.30 * stabilize_score
                            + 0.20 * right_score
                        )
                    intensity = round(float(np.clip(raw_int, 0.0, 1.0)), 3)
                    if intensity < 0.20:
                        intensity = 0.0
                    else:
                        factors = {
                            "dd_52w": round(dd, 3),
                            "erp_pct": round(erp_pct, 3) if erp_pct is not None else None,
                            "pbn_pct": round(pbn_pct, 3) if pbn_pct is not None else None,
                            "valuation": round(val_score, 2) if val_score is not None else None,
                            "clearing": round(clearing_score, 2),
                            "stabilize": round(stabilize_score, 2),
                            "right_side": round(right_score, 2),
                        }
        else:
            closes.append(closes[-1] if closes else 0.0)

        # 独立底部共振事件：综合强度 >= 0.50 + 已止跌（防死猫跳），且距上次独立事件 >= 12 周
        first_bottom_flag = bool(intensity >= 0.50 and stabilize_ok and (idx - last_bottom_idx) >= 12)
        if first_bottom_flag:
            last_bottom_idx = idx

        new_frame = dict(frame)
        new_frame["fco_neg_intensity"] = intensity
        new_frame["bottom_first_alert_flag"] = first_bottom_flag
        if factors:
            new_frame["bottom_factors"] = factors
        elif "bottom_factors" in new_frame:
            new_frame.pop("bottom_factors", None)
        enriched.append(new_frame)

    return enriched


def summarize_bottom_backtest(frames: list[dict[str, Any]]) -> dict[str, Any]:
    """对四维底部共振事件（bottom_first_alert_flag）做严格 PIT 事件级历史回测，并与非信号下跌周基线对照。"""
    closes = [
        float(f["close"]) if f.get("close") is not None and np.isfinite(float(f["close"])) else np.nan
        for f in frames
    ]
    n = len(frames)

    def _eval_indices(indices: list[int]) -> dict[str, Any]:
        r12, r24, r50, mdd50 = [], [], [], []
        for i in indices:
            c0 = closes[i]
            if not np.isfinite(c0) or c0 <= 0:
                continue
            if i + 12 < n and np.isfinite(closes[i + 12]):
                r12.append(closes[i + 12] / c0 - 1.0)
            if i + 24 < n and np.isfinite(closes[i + 24]):
                r24.append(closes[i + 24] / c0 - 1.0)
            if i + 50 < n and np.isfinite(closes[i + 50]):
                r50.append(closes[i + 50] / c0 - 1.0)
                fut = [x for x in closes[i + 1 : i + 51] if np.isfinite(x)]
                if fut:
                    mdd50.append(min(fut) / c0 - 1.0)
        return {
            "n_events": len(indices),
            "n_with_50w": len(r50),
            "win_rate_12w": round(float(np.mean([x > 0 for x in r12])), 3) if r12 else None,
            "win_rate_24w": round(float(np.mean([x > 0 for x in r24])), 3) if r24 else None,
            "win_rate_50w": round(float(np.mean([x > 0 for x in r50])), 3) if r50 else None,
            "median_ret_12w": round(float(np.median(r12)), 4) if r12 else None,
            "median_ret_24w": round(float(np.median(r24)), 4) if r24 else None,
            "median_ret_50w": round(float(np.median(r50)), 4) if r50 else None,
            "median_post_min_50w": round(float(np.median(mdd50)), 4) if mdd50 else None,
        }

    event_indices = [i for i, f in enumerate(frames) if f.get("bottom_first_alert_flag")]
    # 对照基线：任意回撤 <= -12% 的非信号周（检验四维共振相对普通下跌抄底的真实超额胜率）
    base_indices = []
    for i in range(20, n):
        if frames[i].get("bottom_first_alert_flag"):
            continue
        win52 = [x for x in closes[max(0, i - 51) : i + 1] if np.isfinite(x)]
        if win52 and np.isfinite(closes[i]) and max(win52) > 0:
            if closes[i] / max(win52) - 1.0 <= -0.12:
                base_indices.append(i)

    ev_stats = _eval_indices(event_indices)
    base_stats = _eval_indices(base_indices)
    lift_50w = (
        round(ev_stats["win_rate_50w"] - base_stats["win_rate_50w"], 3)
        if ev_stats["win_rate_50w"] is not None and base_stats["win_rate_50w"] is not None
        else None
    )
    return {
        "rule": "A股四维底部共振（ERP/破净滚动3年分位 + 52周超跌出清 + 防死猫跳止跌 + 10周均线右侧企稳），综合强度≥50%且间隔≥12周计独立事件",
        "events": [
            {
                "asof": str(frames[i].get("asof")),
                "split": str(frames[i].get("split") or ""),
                "intensity": frames[i].get("fco_neg_intensity"),
                "ret_24w": round(closes[i + 24] / closes[i] - 1.0, 4) if i + 24 < n and np.isfinite(closes[i + 24]) and closes[i] > 0 else None,
                "ret_50w": round(closes[i + 50] / closes[i] - 1.0, 4) if i + 50 < n and np.isfinite(closes[i + 50]) and closes[i] > 0 else None,
            }
            for i in event_indices[-12:]
        ],
        **ev_stats,
        "baseline_win_rate_50w": base_stats["win_rate_50w"],
        "baseline_median_ret_50w": base_stats["median_ret_50w"],
        "win_rate_lift_50w": lift_50w,
    }
