"""Canonical search and qualification rules for the LPPLS pipelines."""
from __future__ import annotations

import math
import sys

SPEC_VERSION = "lppls-spec-v1"
NORMAL_BOX_NAME = "v2"
LEGACY_VARIANT_NOTE = (
    "Legacy research variants (v1 = early registration, proto = old browser prototype domain, "
    "never backtested); all production workflows set LPPLS_BOX=v2."
)

LEGACY_VARIANTS = {
    "v1": "Early registration.",
    "proto": "Old browser prototype domain.",
}

SCAN_BOXES = {
    "v1": {
        "m": (0.01, 2.0),
        "w": (1.0, 50.0),
        "tc": (0.5, 0.2),
        "inside": False,
        "n_random": 0,
        "short": False,
    },
    "proto": {
        "m": (0.01, 0.99),
        "w": (2.0, 25.0),
        "tc": (0.5, 0.2),
        "inside": False,
        "n_random": 0,
        "short": False,
        "tc_cap": 115.0,
    },
    "v2": {
        "m": (0.01, 2.0),
        "w": (1.0, 50.0),
        "tc": (-0.2, 0.2),
        "inside": True,
        "n_random": 10,
        "short": True,
    },
}

NORMAL_BOX_M_BOUNDS = (0.1, 0.9)
NORMAL_BOX_OMEGA_BOUNDS = (6, 13)
NORMAL_BOX_AHEAD_BOUNDS = (0, 90)
NORMAL_BOX_B_MAX_EXCLUSIVE = 0.0

GLOBAL_WINDOWS = (
    10, 14, 18, 21, 30, 42, 52, 63, 64, 84, 105, 126, 127, 168,
    210, 252, 253, 315, 378, 441, 504, 525, 630, 756, 1008, 1260, 1500,
)
GLOBAL_SEARCH_BOUNDS = {
    "m": [0.01, 2.0],
    "omega": [1, 50],
    "ahead_fraction": [-0.2, 0.2],
}
GLOBAL_ALLOW_INSIDE = SCAN_BOXES["v2"]["inside"]
GLOBAL_BOX_CYCLES_1_5 = {
    "ahead_min_exclusive": 0,
    "full_cycles_min_inclusive": 1.5,
}
GLOBAL_BOX_CYCLES_1_5_DESCRIPTION = (
    "production box AND ahead>0 AND full_cycles>=1.5; "
    "same fit pool, not future-only refit"
)

LONG_WINDOWS = (900, 925, 950, 6500, 6600, 6700)
LONG_FIT_ORDER = (925, 6600, 900, 950, 6500, 6700)
LONG_SEEDS = (11, 29)
LONG_TC_AHEAD = (1, 90)
LONG_M_BOUNDS = (0.1, 0.9)
LONG_OMEGA_BOUNDS = (6, 13)
LONG_DAMPING_MIN = 1
LONG_R2_MIN = 0.9
LONG_RANK_MIN = 4
LONG_CONDITION_MAX = 1 / math.sqrt(sys.float_info.epsilon)
LONG_INTERIOR_STATUS = "INTERIOR"
LONG_SEED_GAP_MAX_SESSIONS = 2
LONG_FAMILY_SPAN_MAX_SESSIONS = 5
LONG_CYCLE_RULES = (("cycles_2_5", 2.5), ("cycles_1_5", 1.5))
LONG_PRIMARY_RULE = "cycles_1_5"
LONG_COMPARISON_RULE = "cycles_2_5"
LONG_PROFILE_WINDOW = 6600
LONG_PROFILE_GRID = tuple(range(1, 89, 3)) + (90,)
LONG_LEAD_5_DAYS = "report separately; never a filter"
LONG_FAMILY_SPLIT = 1000
LONG_FAMILIES = ("long_900", "ultra_6600")
LONG_B_MAX_EXCLUSIVE = 0.0


def long_fit_bounds(n: int) -> list[tuple[float, float]]:
    """Return frozen-kernel bounds with tc ahead measured from t2 = n - 1."""
    t2 = n - 1
    return [
        (float(t2 + LONG_TC_AHEAD[0]), float(t2 + LONG_TC_AHEAD[1])),
        tuple(map(float, LONG_M_BOUNDS)),
        tuple(map(float, LONG_OMEGA_BOUNDS)),
    ]


def long_profile_bounds() -> list[tuple[float, float]]:
    return [
        tuple(map(float, LONG_M_BOUNDS)),
        tuple(map(float, LONG_OMEGA_BOUNDS)),
    ]


def long_seed_base_pass(optimizer_success, m, omega, B, damping, r2, rank, condition) -> bool:
    return bool(
        optimizer_success
        and LONG_M_BOUNDS[0] < m < LONG_M_BOUNDS[1]
        and LONG_OMEGA_BOUNDS[0] < omega < LONG_OMEGA_BOUNDS[1]
        and B < LONG_B_MAX_EXCLUSIVE
        and damping >= LONG_DAMPING_MIN
        and r2 >= LONG_R2_MIN
        and rank >= LONG_RANK_MIN
        and condition <= LONG_CONDITION_MAX
    )


def long_cycle_threshold(rule: str) -> float:
    return dict(LONG_CYCLE_RULES)[rule]


def long_rule_definition(rule: str) -> str:
    return (
        "Both seeds converge; B<0, .1<m<.9, 6<omega<13, damping>=1, R2>=.9, "
        "rank=4, conditioned; all parameters interior; seed tc gap<=2 sessions; "
        f"full cycles>={long_cycle_threshold(rule)}"
    )
