"""Causal claim lifecycle and integer-date cluster experiment, research only.

No function here accepts event labels or future prices. Observation and formal
delivery are separate; assigning an independent evaluation unit never rewrites
the public lifecycle identity.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace

from .contracts import Forecast, Protocol

VERSION = "claim_boundary_v1_dev"
DEFAULT = Protocol()


def classify_interval(cutoff: int, left: int, right: int, config=DEFAULT):
    action = cutoff + 1
    reasons = []
    if right < left or left < 0:
        reasons.append("invalid_interval")
    if left <= action:
        reasons.append("not_future")
    if left - action < config.minimum_lead:
        reasons.append("insufficient_window_lead")
    if right > action + config.horizon:
        reasons.append("beyond_horizon")
    if right - left + 1 > config.maximum_width:
        reasons.append("width_exceeded")
    if not reasons:
        return "FORMAL", []
    early = all(r in {"beyond_horizon", "width_exceeded"} for r in reasons)
    return "EARLY_OBSERVATION" if early else "NONFORMAL_OBSERVATION", reasons


def integer_date_cluster(records, scales, *, cross=False):
    """Generate date-bounded clusters afresh, without trimming a prior cluster."""
    eligible = sorted((r for r in records if r["qualified"]), key=lambda r: (r["ahead"], r["n"]))
    candidates, seen = [], set()
    for left, record in enumerate(eligible):
        lo = record["ahead"]
        if left and lo == eligible[left - 1]["ahead"]:
            continue
        members = []
        for row in eligible[left:]:
            if math.ceil(row["ahead"]) - math.floor(lo) + 1 > 10:
                break
            members.append(row)
        key = tuple(sorted(r["n"] for r in members))
        if len(key) < 3 or key in seen:
            continue
        seen.add(key)
        fractions = {scale: sum(r["scale"] == scale for r in members) / stat["denominator"]
                     for scale, stat in scales.items()}
        supported = [s for s, fraction in fractions.items() if fraction >= .05]
        if len(supported) < (2 if cross else 1):
            continue
        hi = members[-1]["ahead"]
        candidates.append({"lo": lo, "hi": hi, "width": hi - lo,
                           "members": key, "n_members": len(key),
                           "mass": sum(r["weight"] for r in members),
                           "supported_scales": supported})
    candidates.sort(key=lambda c: (-c["mass"], -len(c["supported_scales"]),
                                  -c["n_members"], c["width"], c["lo"], c["members"]))
    return candidates[0] if candidates else None


@dataclass
class ClaimMachine:
    symbol: str
    arm: str
    scope: str = "stage"
    episode: str | None = None
    original_expiry: int = -1
    first_id: str | None = None
    previous_formal_id: str | None = None
    last_cutoff: int = -1

    def step(self, row: dict, *, deliver=True):
        cutoff = int(row["position"])
        if cutoff <= self.last_cutoff:
            raise ValueError("scan cutoffs must be unique and increasing")
        self.last_cutoff = cutoff
        if cutoff > self.original_expiry:
            self.episode = self.first_id = self.previous_formal_id = None
        result = dict(symbol=self.symbol, arm=self.arm, date=row["date"], position=cutoff,
                      lifecycle_version=VERSION, state="INPUT_UNAVAILABLE", gate_reasons=[],
                      signal=False, formal_eligible=False, delivered=False,
                      prediction_id="", episode_id=self.episode or "", first_formal_id=self.first_id or "",
                      parent_id="", original_expiry=self.original_expiry if self.episode else None,
                      interval_start=None, interval_end=None, width_inclusive=None,
                      original_published_at="", hypothetical_published_at="",
                      hypothetical_action_session=cutoff + 1)
        if not row["own_evaluable"]:
            return result, None
        if not row["own_alarm"]:
            result["state"] = "NO_SIGNAL"
            return result, None
        low, high = float(row["interval_lo"]), float(row["interval_hi"])
        if not math.isfinite(low) or not math.isfinite(high) or low > high:
            raise ValueError("alarm needs a finite ordered interval")
        left, right = cutoff + math.floor(low), cutoff + math.ceil(high)
        category, reasons = classify_interval(cutoff, left, right)
        ident = f"{VERSION}:{self.symbol}:{self.arm}:{self.scope}:{row['date']}"
        result.update(signal=True, state=category, gate_reasons=reasons,
                      formal_eligible=category == "FORMAL", interval_start=left,
                      interval_end=right, width_inclusive=right-left+1,
                      prediction_id=ident)
        if category != "FORMAL":
            return result, None
        if not deliver:
            result["state"] = "FORMAL_WITHHELD_BY_PAIR"
            return result, None
        parent = self.previous_formal_id
        if self.episode is None:
            self.episode = f"formal_episode:{ident}"
            self.original_expiry = right
            self.first_id = ident
            change = "NEW_FORMAL"
        else:
            change = "FORMAL_REVISION"
        forecast = Forecast(ident, self.episode, self.symbol, self.scope, left, right,
                            cutoff, cutoff, f"{row['date']}T17:00:00+08:00", cutoff+1,
                            "theoretical", True, None, parent)
        self.previous_formal_id = ident
        result.update(state=change, delivered=True, episode_id=self.episode,
                      first_formal_id=self.first_id, parent_id=parent or "",
                      original_expiry=self.original_expiry,
                      hypothetical_published_at=forecast.published_at)
        return result, forecast


def visible_units(forecasts):
    """Evaluation-only identities: every visible record can be event-first.

    Event association/unknown handling still belongs to the unchanged scorer.
    The original online episode and parent remain in the immutable source ledger.
    """
    return [replace(f, episode_id=f"visible_unit:{f.prediction_id}") for f in forecasts]


def formal_dates(rows):
    result = set()
    for row in rows:
        if row["own_evaluable"] and row["own_alarm"]:
            i = int(row["position"])
            category, _ = classify_interval(i, i+math.floor(float(row["interval_lo"])),
                                            i+math.ceil(float(row["interval_hi"])))
            if category == "FORMAL":
                result.add(str(row["date"]))
    return result


def build_claims(symbol, arm, rows, *, allowed_dates=None):
    machine = ClaimMachine(symbol, arm)
    ledger, forecasts = [], []
    for row in rows:
        record, forecast = machine.step(row, deliver=allowed_dates is None or row["date"] in allowed_dates)
        ledger.append(record)
        if forecast is not None:
            forecasts.append(forecast)
    return ledger, forecasts
