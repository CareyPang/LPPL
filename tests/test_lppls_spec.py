import re
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from research.features import lppls_rules, lppls_scan
from research.lppls import core
from research.lppls.spec import (
    GLOBAL_ALLOW_INSIDE,
    GLOBAL_BOX_CYCLES_1_5,
    GLOBAL_SEARCH_BOUNDS,
    GLOBAL_WINDOWS,
    LEGACY_VARIANT_NOTE,
    LONG_CONDITION_MAX,
    LONG_FAMILY_SPAN_MAX_SESSIONS,
    LONG_M_BOUNDS,
    LONG_OMEGA_BOUNDS,
    LONG_SEED_GAP_MAX_SESSIONS,
    LONG_SEEDS,
    LONG_TC_AHEAD,
    LONG_WINDOWS,
    NORMAL_BOX_AHEAD_BOUNDS,
    NORMAL_BOX_B_MAX_EXCLUSIVE,
    NORMAL_BOX_M_BOUNDS,
    NORMAL_BOX_NAME,
    NORMAL_BOX_OMEGA_BOUNDS,
    SCAN_BOXES,
    SPEC_VERSION,
    long_fit_bounds,
)
from research.pipeline import daily, global_terminal, long_horizon, long_rolling

ROOT = Path(__file__).resolve().parents[1]


def _rule_row(m=0.5, omega=9.0, ahead=30.0, B=-0.5):
    tc = 251.0 + ahead
    return {
        "date": "2020-01-02",
        "n": 252,
        "tc": tc,
        "m": m,
        "w": omega,
        "A": 5.0,
        "B": B,
        "C1": 0.01,
        "C2": 0.0,
        "sse": 0.01,
        "r2": 0.95,
        "pow_tc": tc,
        "pow_m": 0.5,
        "pow_B": -1.0,
        "pow_sse": 0.02,
        "y_std": 0.3,
    }


def _box_passes(**values):
    raw = pd.DataFrame([_rule_row(**values)])
    return bool(lppls_rules.rules(lppls_rules._derived(raw)).box.iloc[0])


def test_scan_v2_search_and_legacy_variants_are_the_spec_boxes():
    assert lppls_scan.BOXES is SCAN_BOXES
    assert lppls_scan.BOXES["v2"] == {
        "m": (0.01, 2.0),
        "w": (1.0, 50.0),
        "tc": (-0.2, 0.2),
        "inside": True,
        "n_random": 10,
        "short": True,
    }
    assert lppls_scan.BOXES["v1"] == SCAN_BOXES["v1"]
    assert lppls_scan.BOXES["proto"] == SCAN_BOXES["proto"]
    assert LEGACY_VARIANT_NOTE == (
        "Legacy research variants (v1 = early registration, proto = old browser prototype domain, "
        "never backtested); all production workflows set LPPLS_BOX=v2."
    )


def test_normal_box_boundaries_are_inclusive():
    assert _box_passes(m=NORMAL_BOX_M_BOUNDS[0], omega=NORMAL_BOX_OMEGA_BOUNDS[0],
                       ahead=NORMAL_BOX_AHEAD_BOUNDS[0])
    assert _box_passes(m=NORMAL_BOX_M_BOUNDS[1], omega=NORMAL_BOX_OMEGA_BOUNDS[1],
                       ahead=NORMAL_BOX_AHEAD_BOUNDS[1])
    assert not _box_passes(m=np.nextafter(NORMAL_BOX_M_BOUNDS[0], -np.inf))
    assert not _box_passes(m=np.nextafter(NORMAL_BOX_M_BOUNDS[1], np.inf))
    assert not _box_passes(omega=np.nextafter(NORMAL_BOX_OMEGA_BOUNDS[0], -np.inf))
    assert not _box_passes(omega=np.nextafter(NORMAL_BOX_OMEGA_BOUNDS[1], np.inf))
    assert not _box_passes(ahead=-1e-8)
    assert not _box_passes(ahead=NORMAL_BOX_AHEAD_BOUNDS[1] + 1e-8)
    assert not _box_passes(B=NORMAL_BOX_B_MAX_EXCLUSIVE)


def _global_row(ahead, omega, n=252):
    t2 = n - 1
    tc = t2 + ahead
    return {
        "date": "2020-01-02",
        "n": n,
        "tc": tc,
        "m": 0.5,
        "w": omega,
        "A": 5.0,
        "B": -0.5,
        "C1": 0.01,
        "C2": 0.0,
        "sse": 0.01,
        "r2": 0.95,
        "pow_tc": tc,
        "pow_m": 0.5,
        "pow_B": -1.0,
        "pow_sse": 0.02,
        "y_std": 0.3,
    }


def test_global_variant_uses_spec_thresholds_and_boundaries():
    target_omega = (
        GLOBAL_BOX_CYCLES_1_5["full_cycles_min_inclusive"]
        * 2
        * np.pi
        / np.log((251 + 90) / 90)
    )
    _, above = global_terminal.derived_and_rules(
        [_global_row(90, target_omega + 1e-9)]
    )
    _, below = global_terminal.derived_and_rules(
        [_global_row(90, target_omega - 1e-9)]
    )
    _, at_asof = global_terminal.derived_and_rules([_global_row(0, 9.0)])
    assert bool(above["box_cycles_1_5"].iloc[0])
    assert not bool(below["box_cycles_1_5"].iloc[0])
    assert not bool(at_asof["box_cycles_1_5"].iloc[0])


def _long_record(
    n=925,
    seed=11,
    ahead=1.0,
    m=0.5,
    omega=9.0,
    B=-0.1,
    damping=1.0,
    r2=0.9,
    rank=4,
    condition=LONG_CONDITION_MAX,
    cycles=1.5,
    boundary="INTERIOR",
):
    return {
        "n": n,
        "seed": seed,
        "asof": long_horizon.ASOF,
        "symbol": "US_IXIC",
        "status": "complete",
        "fit": {
            "x": [n - 1 + ahead, m, omega],
            "beta": [10.0, B, 0.01, 0.02],
            "sse": 0.1,
            "r2": r2,
            "damping": damping,
            "nosc": cycles,
            "rank": rank,
            "condition": condition,
            "strict_pass": cycles >= 2.5,
            "optimizer_success": True,
            "boundary_status": boundary,
        },
    }


def test_long_bounds_and_gate_use_spec_at_inclusive_quality_edges():
    assert long_horizon.WINDOWS == LONG_WINDOWS
    assert long_horizon.SEEDS == LONG_SEEDS
    assert long_rolling.WINDOWS == LONG_WINDOWS
    assert long_rolling.SEEDS == LONG_SEEDS
    assert long_fit_bounds(925) == [
        (925.0, 1014.0),
        tuple(map(float, LONG_M_BOUNDS)),
        tuple(map(float, LONG_OMEGA_BOUNDS)),
    ]
    assert LONG_TC_AHEAD == (1, 90)

    summary = long_horizon.seed_summary(_long_record())
    assert summary["passes"] == {"cycles_2_5": False, "cycles_1_5": True}
    assert summary["failed_gates"] == []


@pytest.mark.parametrize(
    "changes",
    [
        {"m": LONG_M_BOUNDS[0]},
        {"m": LONG_M_BOUNDS[1]},
        {"omega": LONG_OMEGA_BOUNDS[0]},
        {"omega": LONG_OMEGA_BOUNDS[1]},
        {"B": 0.0},
        {"damping": np.nextafter(1.0, -np.inf)},
        {"r2": np.nextafter(0.9, -np.inf)},
        {"rank": 3},
        {"condition": np.nextafter(LONG_CONDITION_MAX, np.inf)},
    ],
)
def test_long_gate_rejects_each_noninterior_or_quality_boundary(changes):
    summary = long_horizon.seed_summary(_long_record(**changes))
    assert not any(summary["passes"].values())


def test_long_gate_requires_all_parameters_interior():
    records = {
        (long_horizon.ASOF, 925, seed): _long_record(
            seed=seed, boundary="tc_LOW" if seed == LONG_SEEDS[0] else "INTERIOR"
        )
        for seed in LONG_SEEDS
    }
    window = next(
        item for item in long_horizon.summarize_windows(records, long_horizon.ASOF)
        if item["n"] == 925
    )
    assert not window["eligible"]["cycles_1_5"]


def test_long_seed_agreement_accepts_exact_two_session_boundary():
    records = {
        (long_horizon.ASOF, 925, seed): _long_record(seed=seed, ahead=ahead)
        for seed, ahead in zip(LONG_SEEDS, (30.0, 32.0), strict=True)
    }
    result = next(
        item for item in long_horizon.summarize_windows(records, long_horizon.ASOF)
        if item["n"] == 925
    )
    assert result["seed_gap_days"] == LONG_SEED_GAP_MAX_SESSIONS
    assert result["eligible"]["cycles_1_5"]

    unstable = {
        (long_horizon.ASOF, 925, seed): _long_record(seed=seed, ahead=ahead)
        for seed, ahead in zip(LONG_SEEDS, (30.0, 32.01), strict=True)
    }
    result = next(
        item for item in long_horizon.summarize_windows(unstable, long_horizon.ASOF)
        if item["n"] == 925
    )
    assert not result["eligible"]["cycles_1_5"]


def test_global_metadata_and_long_rolling_method_match_spec():
    method = global_terminal.method_identity()
    assert global_terminal.WINDOWS == GLOBAL_WINDOWS
    assert len(method["windows"]) == 27
    assert method["search_bounds"] == GLOBAL_SEARCH_BOUNDS
    assert method["box"] == NORMAL_BOX_NAME
    assert method["allow_inside"] is GLOBAL_ALLOW_INSIDE
    assert method["lppls_spec"] == SPEC_VERSION

    rolling_method = long_rolling.experiment_method()
    assert rolling_method["lppls_spec"] == SPEC_VERSION
    assert rolling_method["windows"] == list(LONG_WINDOWS)
    assert rolling_method["seeds"] == list(LONG_SEEDS)
    assert rolling_method["future_tc_sessions"] == list(LONG_TC_AHEAD)
    assert rolling_method["m_bounds"] == list(LONG_M_BOUNDS)
    assert rolling_method["omega_bounds"] == list(LONG_OMEGA_BOUNDS)
    assert rolling_method["family_width_max_sessions"] == LONG_FAMILY_SPAN_MAX_SESSIONS
    assert rolling_method["seed_gap_max_sessions"] == LONG_SEED_GAP_MAX_SESSIONS
    assert daily.SPEC_VERSION == SPEC_VERSION
    assert long_horizon.SPEC_VERSION == SPEC_VERSION


def test_v2_synthetic_fit_matches_pre_refactor_parameters(monkeypatch):
    monkeypatch.setattr(lppls_scan, "BOX", "v2")
    monkeypatch.setattr(lppls_scan, "WINDOWS_MODE", "full")
    monkeypatch.setattr(lppls_scan, "SIGN", "pos")
    monkeypatch.setattr(lppls_scan, "ANCHOR", "end")
    monkeypatch.setattr(lppls_scan, "G3", False)
    monkeypatch.setattr(lppls_scan, "Q3_K", 0)
    monkeypatch.setattr(core, "ALLOW_INSIDE", True)

    rng = np.random.default_rng(1)
    n = 130
    t = np.arange(n, dtype=float)
    dt = n - 1
    tc0 = dt + 0.05 * dt
    design = core.design(t, tc0, 0.5, 9.0, allow_inside=True)
    B = -0.6 / abs(tc0) ** 0.5
    synthetic = design @ np.array([8.0, B, 0.1 * abs(B), 0.1 * abs(B)])
    synthetic += rng.normal(0, 0.01, n)

    row = lppls_scan.fit_one(synthetic, opt="tcgrid")
    assert row[1:4] == pytest.approx(
        [135.23304720438415, 0.5086536523219787, 8.978324404905349],
        rel=1e-12,
        abs=1e-12,
    )


def test_production_workflows_set_v2_for_every_pipeline_invocation():
    targets = (
        "research.pipeline.daily",
        "research.features.lppls_scan",
        "research.pipeline.history_extend",
    )
    invocation = re.compile(
        r"\bpython(?:\d+(?:\.\d+)*)?\s+-m\s+("
        + "|".join(re.escape(target) for target in targets)
        + r")\b"
    )
    seen = set()

    for path in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
        workflow_env = workflow.get("env") or {}
        for job in workflow.get("jobs", {}).values():
            job_env = job.get("env") or {}
            for step in job.get("steps", []):
                run = step.get("run") or ""
                effective_env = {
                    **workflow_env,
                    **job_env,
                    **(step.get("env") or {}),
                }
                exported_v2 = False
                for line in run.splitlines():
                    if re.search(r"^\s*(?:export\s+)?LPPLS_BOX=v2\b", line):
                        exported_v2 = True
                    for match in invocation.finditer(line):
                        target = match.group(1)
                        seen.add(target)
                        inline_v2 = bool(re.search(r"\bLPPLS_BOX=v2\s+python", line[:match.start()]))
                        assert (
                            inline_v2
                            or exported_v2
                            or effective_env.get("LPPLS_BOX") == "v2"
                        ), f"{path.name} invokes {target} without LPPLS_BOX=v2"

    assert seen == set(targets)
