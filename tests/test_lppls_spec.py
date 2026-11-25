import ast
import re
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from research.features import lppls_rules, lppls_scan
from research.lppls import frozen_v2588
from research.lppls.spec import (
    GLOBAL_ALLOW_INSIDE,
    GLOBAL_BOX_CYCLES_1_5,
    GLOBAL_SEARCH_BOUNDS,
    GLOBAL_WINDOWS,
    LEGACY_VARIANT_NOTE,
    LONG_B_MAX_EXCLUSIVE,
    LONG_COMPARISON_RULE,
    LONG_CONDITION_MAX,
    LONG_CYCLE_RULES,
    LONG_DAMPING_MIN,
    LONG_FAMILY_SPAN_MAX_SESSIONS,
    LONG_LEAD_5_DAYS,
    LONG_M_BOUNDS,
    LONG_OMEGA_BOUNDS,
    LONG_PRIMARY_RULE,
    LONG_PROFILE_GRID,
    LONG_PROFILE_WINDOW,
    LONG_R2_MIN,
    LONG_RANK_MIN,
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
    long_profile_bounds,
)
from research.pipeline import global_terminal, long_horizon, long_rolling

ROOT = Path(__file__).resolve().parents[1]
FROZEN_KERNEL_HASH = "ac00580978ed58cc57a5a1a5c07b69846d5516ec7499722ea46f6d49fc715c01"


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


def test_scan_box_definitions_match_spec_data():
    assert SPEC_VERSION == "lppls-spec-v1"
    assert lppls_scan.BOXES == SCAN_BOXES
    assert "lppls.spec" not in Path(lppls_scan.__file__).read_text(encoding="utf-8")


def test_normal_box_boundaries_match_spec_and_are_inclusive():
    for field, (lower, upper) in (
        ("m", NORMAL_BOX_M_BOUNDS),
        ("omega", NORMAL_BOX_OMEGA_BOUNDS),
        ("ahead", NORMAL_BOX_AHEAD_BOUNDS),
    ):
        lower_out = -1e-8 if field == "ahead" else np.nextafter(lower, -np.inf)
        upper_out = upper + 1e-8 if field == "ahead" else np.nextafter(upper, np.inf)
        assert _box_passes(**{field: lower})
        assert _box_passes(**{field: upper})
        assert not _box_passes(**{field: lower_out})
        assert not _box_passes(**{field: upper_out})
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


def test_global_method_identity_matches_search_spec():
    method = global_terminal.method_identity()
    assert global_terminal.WINDOWS == GLOBAL_WINDOWS
    assert method["windows"] == list(GLOBAL_WINDOWS)
    assert method["search_bounds"] == GLOBAL_SEARCH_BOUNDS
    assert method["allow_inside"] == GLOBAL_ALLOW_INSIDE
    assert method["box"] == NORMAL_BOX_NAME
    assert "lppls_spec" not in method


def test_global_box_cycles_1_5_boundaries_match_spec():
    cycles = GLOBAL_BOX_CYCLES_1_5["full_cycles_min_inclusive"]
    ahead = 90.0
    log_ratio = np.log((251.0 + ahead) / ahead)
    target_omega = cycles * 2 * np.pi / log_ratio

    derived, at_boundary = global_terminal.derived_and_rules(
        [_global_row(ahead, target_omega)]
    )
    _, below_boundary = global_terminal.derived_and_rules(
        [_global_row(ahead, target_omega - 1e-9)]
    )
    _, at_asof = global_terminal.derived_and_rules([_global_row(0.0, 9.0)])

    assert derived.n_osc.iloc[0] == pytest.approx(cycles)
    assert bool(at_boundary["box_cycles_1_5"].iloc[0])
    assert not bool(below_boundary["box_cycles_1_5"].iloc[0])
    assert not bool(at_asof["box_cycles_1_5"].iloc[0])
    assert GLOBAL_BOX_CYCLES_1_5["ahead_min_exclusive"] == 0


def _long_record(
    n=925,
    seed=11,
    ahead=30.0,
    m=0.5,
    omega=9.0,
    B=-0.1,
    damping=LONG_DAMPING_MIN,
    r2=LONG_R2_MIN,
    rank=LONG_RANK_MIN,
    condition=LONG_CONDITION_MAX,
    cycles=1.5,
    boundary="INTERIOR",
    optimizer_success=True,
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
            "optimizer_success": optimizer_success,
            "boundary_status": boundary,
        },
    }


def _long_records(aheads=(30.0, 30.0), boundaries=("INTERIOR", "INTERIOR"), **values):
    return {
        (long_horizon.ASOF, 925, seed): _long_record(
            seed=seed,
            ahead=ahead,
            boundary=boundary,
            **values,
        )
        for seed, ahead, boundary in zip(LONG_SEEDS, aheads, boundaries, strict=True)
    }


def _long_window(records):
    return next(
        item
        for item in long_horizon.summarize_windows(records, long_horizon.ASOF)
        if item["n"] == 925
    )


def test_long_windows_seeds_and_seed_summary_match_spec_boundaries():
    assert long_horizon.WINDOWS == LONG_WINDOWS
    assert long_horizon.SEEDS == LONG_SEEDS

    low = long_horizon.seed_summary(
        _long_record(ahead=LONG_TC_AHEAD[0], boundary="tc_LOW")
    )
    high = long_horizon.seed_summary(
        _long_record(ahead=LONG_TC_AHEAD[1], boundary="tc_HIGH")
    )
    assert low["tc_ahead"] == LONG_TC_AHEAD[0]
    assert high["tc_ahead"] == LONG_TC_AHEAD[1]
    assert low["passes"]["cycles_1_5"]
    assert high["passes"]["cycles_1_5"]
    assert low["failed_gates"] == ["parameter_boundary"]
    assert high["failed_gates"] == ["parameter_boundary"]


@pytest.mark.parametrize(("rule", "threshold"), LONG_CYCLE_RULES)
def test_long_cycle_thresholds_are_inclusive(rule, threshold):
    summary = long_horizon.seed_summary(_long_record(cycles=threshold))
    assert summary["passes"][rule]


@pytest.mark.parametrize(
    "changes",
    [
        {"m": LONG_M_BOUNDS[0]},
        {"m": LONG_M_BOUNDS[1]},
        {"omega": LONG_OMEGA_BOUNDS[0]},
        {"omega": LONG_OMEGA_BOUNDS[1]},
        {"B": LONG_B_MAX_EXCLUSIVE},
        {"damping": np.nextafter(LONG_DAMPING_MIN, -np.inf)},
        {"r2": np.nextafter(LONG_R2_MIN, -np.inf)},
        {"rank": LONG_RANK_MIN - 1},
        {"condition": np.nextafter(LONG_CONDITION_MAX, np.inf)},
        {"optimizer_success": False},
    ],
)
def test_long_seed_summary_rejects_each_failed_gate(changes):
    summary = long_horizon.seed_summary(_long_record(**changes))
    assert not any(summary["passes"].values())


def test_long_seed_pair_boundary_and_frozen_tc_boundaries():
    assert LONG_TC_AHEAD == (1, 90)
    assert LONG_SEED_GAP_MAX_SESSIONS == 2

    at_gap = _long_window(_long_records(aheads=(30.0, 32.0)))
    assert at_gap["seed_gap_days"] == LONG_SEED_GAP_MAX_SESSIONS
    assert at_gap["eligible"]["cycles_1_5"]

    over_gap = _long_window(_long_records(aheads=(30.0, 32.01)))
    assert not over_gap["eligible"]["cycles_1_5"]

    for ahead, boundary in (
        (LONG_TC_AHEAD[0], "tc_LOW"),
        (LONG_TC_AHEAD[1], "tc_HIGH"),
    ):
        records = _long_records(
            aheads=(ahead, 30.0),
            boundaries=(boundary, "INTERIOR"),
        )
        assert not _long_window(records)["eligible"]["cycles_1_5"]


def _bound_value(node, n):
    if isinstance(node, ast.List):
        return [_bound_value(value, n) for value in node.elts]
    if isinstance(node, ast.Tuple):
        return tuple(_bound_value(value, n) for value in node.elts)
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name) and node.id == "n":
        return n
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "float":
        return float(_bound_value(node.args[0], n))
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _bound_value(node.left, n) + _bound_value(node.right, n)
    raise AssertionError(f"Unsupported frozen bounds expression: {ast.dump(node)}")


def _frozen_bounds(function_name, n):
    source = Path(frozen_v2588.__file__).read_text(encoding="utf-8")
    module = ast.parse(source)
    function = next(
        node
        for node in module.body
        if isinstance(node, ast.FunctionDef) and node.name == function_name
    )
    assignment = next(
        node
        for node in function.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "bounds" for target in node.targets)
    )
    return _bound_value(assignment.value, n)


def test_frozen_kernel_bounds_match_spec_data():
    assert _frozen_bounds("fit_one", 925) == long_fit_bounds(925)
    assert _frozen_bounds("profile_fit", 925) == long_profile_bounds()


def test_long_rolling_method_fields_match_spec_data():
    method = long_rolling.experiment_method()
    assert method["windows"] == list(LONG_WINDOWS)
    assert method["seeds"] == list(LONG_SEEDS)
    assert method["future_tc_sessions"] == list(LONG_TC_AHEAD)
    assert method["m_bounds"] == list(LONG_M_BOUNDS)
    assert method["omega_bounds"] == list(LONG_OMEGA_BOUNDS)
    assert method["primary_rule"] == LONG_PRIMARY_RULE
    assert method["comparison_rule"] == LONG_COMPARISON_RULE
    assert method["family_width_max_sessions"] == LONG_FAMILY_SPAN_MAX_SESSIONS
    assert method["seed_gap_max_sessions"] == LONG_SEED_GAP_MAX_SESSIONS
    assert method["lead_5_days"] == LONG_LEAD_5_DAYS
    assert method["profile_grid"] == list(LONG_PROFILE_GRID)
    assert method["profile_n"] == LONG_PROFILE_WINDOW
    assert "lppls_spec" not in method


def test_frozen_kernel_math_ast_hash_is_unchanged():
    assert long_horizon.math_ast_hash(frozen_v2588.__file__) == FROZEN_KERNEL_HASH


def test_legacy_variants_are_documented_as_unbacktested():
    assert "v1 = early registration" in LEGACY_VARIANT_NOTE
    assert "proto = old browser prototype domain" in LEGACY_VARIANT_NOTE
    assert "never backtested" in LEGACY_VARIANT_NOTE
    assert "all production workflows set LPPLS_BOX=v2" in LEGACY_VARIANT_NOTE


def test_production_workflows_set_v2_for_every_pipeline_invocation():
    targets = (
        "research.pipeline.index_daily",
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
                        inline_v2 = bool(
                            re.search(r"\bLPPLS_BOX=v2\s+python", line[: match.start()])
                        )
                        assert (
                            inline_v2
                            or exported_v2
                            or effective_env.get("LPPLS_BOX") == "v2"
                        ), f"{path.name} invokes {target} without LPPLS_BOX=v2"

    assert seen == set(targets)
