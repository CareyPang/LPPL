#!/usr/bin/env python3
"""Generate the frozen T01 fit contract and its source maps in a new run directory."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.lppls.future_contract import (  # noqa: E402
    CONTRACT_VERSION,
    DEFAULT_FILTER_BOUNDS,
    DEFAULT_SEARCH_BOUNDS,
    EVAL_H,
)


def source_ref(path: str, marker: str) -> dict[str, Any]:
    lines = (ROOT / path).read_text(encoding="utf-8").splitlines()
    matches = [(index, line.strip()) for index, line in enumerate(lines, start=1) if marker in line]
    if not matches:
        raise ValueError(f"source marker not found: {path}: {marker}")
    line, excerpt = matches[0]
    return {"file": path, "line": line, "excerpt": excerpt}


def build_artifacts() -> dict[str, str | dict[str, Any]]:
    sources = {
        "legacy_v2_box": source_ref("research/features/lppls_scan.py", '"v2": dict('),
        "legacy_fit_bounds": source_ref("research/features/lppls_scan.py", 'tc_lo, tc_hi = bx["tc"]'),
        "legacy_tc_upper": source_ref("research/features/lppls_scan.py", "hi = np.array([dt + ahead_hi"),
        "legacy_random_seed": source_ref("research/features/lppls_scan.py", "r = tcgrid_lm(t, y, lo, hi, seed=0"),
        "legacy_global_design": source_ref("research/lppls/core.py", "if ALLOW_INSIDE if allow_inside is None else allow_inside"),
        "min_dt": source_ref("research/lppls/core.py", "MIN_DT = 1e-3"),
        "solver_budget": source_ref("research/optim/optimizers.py", "budget = budget or dict(n_tc=40"),
        "solver_entry": source_ref("research/optim/optimizers.py", "def tcgrid_lm("),
        "solver_least_squares": source_ref(
            "research/optim/optimizers.py",
            "args=(t, y, k, allow_inside), bounds=(lo, hi), method=\"trf\"",
        ),
        "legacy_derived_damping": source_ref("research/features/lppls_rules.py", 'd["D"] = np.where'),
        "legacy_derived_oscillation": source_ref("research/features/lppls_rules.py", 'd["osc"] = d.w / 2'),
        "headline_direction_and_m_lower": source_ref("research/features/lppls_rules.py", "fco = (d.B < 0) & (d.m > 0)"),
        "headline_standard_rule": source_ref("research/features/lppls_rules.py", 'r["g_fco_standard"] ='),
        "headline_no_other_bounds": source_ref(
            "research/features/lppls_rules.py",
            "# FCO 平台公开的四套合格过滤集",
        ),
        "headline_scale_windows": source_ref("research/features/lppls_rules.py", "SCALES_FCO ="),
        "headline_standard_count": source_ref("research/eval/export_contract.py", 'nq = int(gg["g_fco_standard"][m].sum())'),
        "headline_scale_signal": source_ref("research/eval/export_contract.py", '"signal_status": "display_only" if display_only'),
        "headline_aggregate": source_ref("research/eval/export_contract.py", '"signal_status": "signal" if any(v.get'),
        "separate_lppls_confidence": source_ref(
            "research/eval/export_contract.py",
            '"lppls_confidence": {**_conf(d, r, date)',
        ),
        "daily_global_box": source_ref("research/pipeline/daily.py", "_core.ALLOW_INSIDE ="),
        "daily_default_windows": source_ref("research/pipeline/daily.py", "ws = full_windows(len(logp))"),
        "workflow_daily": source_ref(".github/workflows/index_daily.yml", "LPPLS_BOX=v2"),
        "workflow_replay": source_ref(".github/workflows/index_replay.yml", "LPPLS_BOX=v2"),
        "legacy_scan_fit_one": source_ref("research/features/lppls_scan.py", "def fit_one("),
        "future_logprice": source_ref("research/lppls/future_contract.py", "def log_price_from_price("),
        "future_search_bounds": source_ref("research/lppls/future_contract.py", "class SearchBounds:"),
        "future_search_m": source_ref(
            "research/lppls/future_contract.py",
            "m: tuple[float, float] = (0.01, 2.0)",
        ),
        "future_search_omega": source_ref(
            "research/lppls/future_contract.py",
            "omega: tuple[float, float] = (1.0, 50.0)",
        ),
        "future_search_solver": source_ref(
            "research/lppls/future_contract.py",
            'solver: str = "tcgrid_lm"',
        ),
        "future_search_n_random": source_ref(
            "research/lppls/future_contract.py",
            "n_random: int = 10",
        ),
        "future_search_seed": source_ref(
            "research/lppls/future_contract.py",
            "seed: int = 0",
        ),
        "future_tc_relation": source_ref(
            "research/lppls/future_contract.py",
            'tc_relation: str = "tc > t2"',
        ),
        "future_tc_upper_fraction": source_ref(
            "research/lppls/future_contract.py",
            "FIT_HORIZON_FRACTION = 0.2",
        ),
        "future_tc_numeric_bounds": source_ref(
            "research/lppls/future_contract.py",
            "tc_lo = t2 + self.tc_min_offset",
        ),
        "future_tc_upper_numeric_bounds": source_ref(
            "research/lppls/future_contract.py",
            "tc_hi = t2 + self.tc_max_offset_fraction * dt",
        ),
        "future_allow_inside": source_ref(
            "research/lppls/future_contract.py",
            "allow_inside: bool = False",
        ),
        "future_explicit_false": source_ref(
            "research/lppls/future_contract.py",
            "allow_inside=False,",
        ),
        "future_filter_bounds": source_ref("research/lppls/future_contract.py", "class FilterBounds:"),
        "future_cycle_threshold": source_ref(
            "research/lppls/future_contract.py",
            "cycles_full_min: float = 1.5",
        ),
        "future_cycles": source_ref("research/lppls/future_contract.py", "def cycles_full("),
        "future_cache_key": source_ref("research/lppls/future_contract.py", "def cache_key("),
        "future_fit_window": source_ref("research/lppls/future_contract.py", "def fit_window("),
        "future_attempt_schema": source_ref("research/lppls/future_contract.py", "class Attempt:"),
        "future_window_schema": source_ref("research/lppls/future_contract.py", "class WindowResult:"),
        "future_session_map": source_ref("research/lppls/future_contract.py", "def session_indices_for_bars("),
        "future_width_helper": source_ref("research/lppls/future_contract.py", "def inclusive_width_sessions("),
    }
    search_bounds = DEFAULT_SEARCH_BOUNDS.to_dict()
    search_bounds["source_evidence"] = {
        "m": [sources["legacy_v2_box"], sources["future_search_m"]],
        "omega": [sources["legacy_v2_box"], sources["future_search_omega"]],
        "legacy_tc_domain": [sources["legacy_v2_box"], sources["legacy_fit_bounds"], sources["legacy_tc_upper"]],
        "tc_lower": [sources["min_dt"], sources["future_tc_numeric_bounds"]],
        "tc_upper_fraction": [
            sources["legacy_tc_upper"],
            sources["future_tc_upper_fraction"],
            sources["future_tc_upper_numeric_bounds"],
        ],
        "tc_relation": sources["future_tc_relation"],
        "allow_inside": [sources["future_allow_inside"], sources["future_explicit_false"]],
        "solver": [sources["solver_entry"], sources["future_search_solver"]],
        "budget": sources["solver_budget"],
        "least_squares_defaults": sources["solver_least_squares"],
        "n_random": [sources["legacy_v2_box"], sources["future_search_n_random"]],
        "seed": [sources["legacy_random_seed"], sources["future_search_seed"]],
    }
    filter_bounds = DEFAULT_FILTER_BOUNDS.to_dict()
    filter_bounds["source_evidence"] = {
        "direction": sources["headline_direction_and_m_lower"],
        "m": [sources["headline_direction_and_m_lower"], sources["headline_standard_rule"]],
        "omega": sources["headline_standard_rule"],
        "damping_min": [sources["headline_standard_rule"], sources["legacy_derived_damping"]],
        "tc_relation": sources["future_tc_relation"],
        "cycles_full_min": [sources["future_cycle_threshold"], sources["legacy_derived_oscillation"]],
        "r2_rel_err_horizon_absent": sources["headline_no_other_bounds"],
        "headline_standard_count_by_scale": sources["headline_standard_count"],
        "per_scale_signal_and_headline_aggregation": [
            sources["headline_scale_signal"],
            sources["headline_aggregate"],
        ],
        "scale_ranges": sources["headline_scale_windows"],
    }
    fit_contract = {
        "contract_version": CONTRACT_VERSION,
        "model_status": "specification frozen; no B0 scan or evaluation run",
        "domain": "future_only",
        "units": "full_cycles",
        "unit_definitions": {
            "cycles_full": "omega / (2*pi) * ln((tc - t1) / (tc - t2)); NaN when tc <= t2",
            "legacy_osc": "(omega / 2) * ln(abs(tc) / max(abs(tc - t2), 1e-3))",
            "legacy_osc_to_full_cycles": "osc / pi",
            "legacy_standard_threshold_equivalent": "2.5 / pi = 0.7957747154594768 full cycles",
            "future_filter_threshold": "cycles_full >= 1.5",
            "t1_zero_equivalence": "for t1=0 and tc>t2, the legacy log ratio equals the future formula's log ratio",
        },
        "input": {
            "required_type": "LogPrice",
            "constructors": ["LogPrice.from_price", "LogPrice.from_log_price"],
            "recorded_provenance": ["constructed_from", "source_field", "adjustment_type"],
            "price_validation": "from_price rejects non-positive and non-finite values before log",
            "double_log_note": "Whether arbitrary numeric values were already logged cannot be inferred; callers must select and record the correct constructor.",
        },
        "search_bounds": search_bounds,
        "filter_bounds": filter_bounds,
        "headline_rule_finding": {
            "field": "top.signal_status",
            "primary_column": "g_fco_standard",
            "primary_scales": ["1-3m", "6-12m", "12-24m"],
            "aggregation": "signal if any evaluated SCALES_FCO scale has at least one standard-qualified window",
            "not_primary": ["g_fco_early", "g_fco_end", "g_fco_pure"],
            "separate_field": {
                "field": "top.lppls_confidence",
                "meaning": "distinct _conf(d, rules(d), asof) summary; not the top.signal_status rule",
                "evidence": sources["separate_lppls_confidence"],
            },
            "evidence": [
                sources["headline_standard_rule"],
                sources["headline_standard_count"],
                sources["headline_scale_signal"],
                sources["headline_aggregate"],
            ],
            "legacy_standard_filter": {
                "direction": "B < 0",
                "m": "0 < m <= 1",
                "omega": "2 <= omega <= 25",
                "damping": "D >= 0.5",
                "oscillation": "legacy osc >= 2.5",
                "r2": None,
                "rel_err": None,
                "horizon": None,
            },
            "registered_corrections": [
                "intersect the time domain with tc > t2",
                "replace the legacy osc threshold with cycles_full >= 1.5",
            ],
        },
        "window_and_attempt_schema": {
            "one_window_summary_status": ["fit_ok", "all_attempts_failed", "pending"],
            "attempt_status": ["success", "invalid", "numerical_failure", "pending"],
            "attempt_id": "SHA256(cache_key + seed + retry_idx)",
            "one_tcgrid_lm_invocation_per_seed_retry": True,
            "attempt_fields": [
                "theta",
                "beta",
                "sse",
                "finite",
                "boundary_hits",
                "design_rank",
                "condition_number",
                "error",
            ],
            "filter_outcome": ["pass", "reject with reasons", "not_evaluated"],
            "non_finite_behavior": "reject with non_finite reason; never pass through NaN comparisons",
        },
        "time_fields": {
            "t1": "0 effective bars in the planned window",
            "t2": "L - 1 effective bars in the planned window",
            "lookback_L": "number of effective bars fitted",
            "fit_horizon": "maximum future tc offset, 0.2 * (t2 - t1) bars",
            "eval_H": EVAL_H,
            "label_confirmation_E": None,
            "fit_clock": "effective_bars",
            "bar_to_session_index": "ordered calendar-session index for each fitted bar; gaps retain calendar positions",
            "tc_offset_bars": "fitted tc - t2",
            "inclusive_width_sessions": "b - a + 1",
        },
        "cache_key": {
            "algorithm": "SHA256(canonical JSON; sorted keys, compact separators, UTF-8)",
            "members": [
                "data_hash",
                "asof",
                "window start/end/L",
                "clock-map SHA256",
                "domain=future_only",
                "units=full_cycles",
                "search_bounds",
                "filter_bounds",
                "solver name and budget",
                "n_random",
                "CONTRACT_VERSION",
                "seed",
            ],
        },
        "source_evidence": sources,
    }
    call_chain = f"""# T01 调用链映射

## 旧 daily / scan 路径

`index_daily.yml` 与 `index_replay.yml` 通过 `LPPLS_BOX=v2 python -m research.pipeline.daily ...` 进入日更流水线（{sources['workflow_daily']['file']}:{sources['workflow_daily']['line']}；{sources['workflow_replay']['file']}:{sources['workflow_replay']['line']}）；`daily.run()` 按 BOX 设置全局 `_core.ALLOW_INSIDE=True`（{sources['daily_global_box']['file']}:{sources['daily_global_box']['line']}），未指定 `--windows` 时取 `full_windows(len(logp))`（{sources['daily_default_windows']['file']}:{sources['daily_default_windows']['line']}），再运行 `_derived()`、`rules()` 和 `build_record()`。执行数据加载默认先 `cache.refresh()`，除非显式 `--frozen`；workflow 未传该参数。

扫描器 `lppls_scan.fit_one()`（{sources['legacy_scan_fit_one']['file']}:{sources['legacy_scan_fit_one']['line']}）按 v2 BOX 使用 m=[0.01,2]、ω=[1,50]、tc∈[t₂−0.2dt,t₂+0.2dt]，seed=0、n_random=10，并调用 `tcgrid_lm()`、`lin_fit()`。`allow_inside=None` 保持由 `core.ALLOW_INSIDE` 决定；v2 的内部点经 `abs(tc−t)` 设计矩阵计算。

## 新 future-only 路径

`LogPrice.from_price()` / `LogPrice.from_log_price()` 显式记录输入构造来源（{sources['future_logprice']['file']}:{sources['future_logprice']['line']}）；`fit_window()`（{sources['future_fit_window']['file']}:{sources['future_fit_window']['line']}）使用窗口内有效 bar 坐标 t1=0、t2=L−1，并调用 `SearchBounds.numeric_bounds()` 得到 tc∈[t₂+MIN_DT,t₂+0.2dt]。对每个 seed/retry 调用 `tcgrid_lm(..., allow_inside=False)`；`core.design`、`lin_fit` 和优化器均收到显式 False，不受进程级 `ALLOW_INSIDE` 污染。

每个 `WindowResult` 只汇总一个计划窗口，attempt 按 seed/retry 独立记录。拟合后按 `FilterBounds` 单独给出过滤结果；交易日映射把每个有效 bar 映到 session 索引，停牌缺口不压缩日历 session。eval_H 固定 63，label_confirmation_E 当前为 null。T01 只冻结契约并执行合成单元测试，不进行扫描或 B0 评价。

## 产品 headline 过滤证据

`grid_rules()` 的 `g_fco_standard` 规则是 B<0、0<m≤1、2≤ω≤25、D≥0.5、legacy osc≥2.5（{sources['headline_direction_and_m_lower']['file']}:{sources['headline_direction_and_m_lower']['line']}；{sources['headline_standard_rule']['file']}:{sources['headline_standard_rule']['line']}）。`_indicators()` 以该列的合格窗口数决定每尺度 signal（{sources['headline_standard_count']['file']}:{sources['headline_standard_count']['line']}；{sources['headline_scale_signal']['file']}:{sources['headline_scale_signal']['line']}）；`build_record()` 的 `top.signal_status` 再对 `SCALES_FCO` 尺度作 any 聚合（{sources['headline_scale_windows']['file']}:{sources['headline_scale_windows']['line']}；{sources['headline_aggregate']['file']}:{sources['headline_aggregate']['line']}）。B0 因而沿用这一列作为 primary filter，在三个评价尺度应用同一规则。future 单位为 `cycles_full = omega/(2*pi)*ln((tc-t1)/(tc-t2))`；legacy `osc=(omega/2)*ln(|tc|/max(|tc-t2|,1e-3))`，换算为完整周期需除以 π，故旧 `osc>=2.5` 约等于 0.795775 周期。B0 下界 `tc=t2+MIN_DT` 且 `MIN_DT=1e-3`，因此该 legacy 分母保护不会改变 future 域的等价对数项。`g_fco_early`、`g_fco_end`、`g_fco_pure` 只进入每尺度置信度，不参与该 headline status。另一个字段 `top.lppls_confidence` 是 `_conf(d, rules(d), asof)` 的研究置信度摘要，并非此 headline status 的判定规则（{sources['separate_lppls_confidence']['file']}:{sources['separate_lppls_confidence']['line']}）。原 g_fco_standard 没有 R²、rel_err 或 horizon 限制；这些条件在 B0 中明确记录为 null，而不是补造阈值。
"""
    diff = """# legacy v2 到 future-only B0 契约差异

| 项目 | 分类 | legacy_main_v2 | candidate future-only B0 |
|---|---|---|---|
| inside 状态 | bug-fix（实现隔离） | v2 设置进程全局 `ALLOW_INSIDE=True`，同进程任务可能受其影响 | legacy 默认仍由全局控制；future-only 每次显式传 False |
| 搜索域与参数 | model-domain change | m=[0.01,2]、ω=[1,50]、tc∈[t₂−0.2dt,t₂+0.2dt]，设计可用 `abs(tc−t)`；tcgrid_lm 默认预算、seed=0、10 随机起点 | m、ω、solver、budget、seed、n_random 全部保留；仅将 tc 域修正为 [t₂+MIN_DT,t₂+0.2dt]，严格 future-only，不取 abs、不 clamp |
| headline 过滤 | 评分变化 | 产品 `top.signal_status` 使用各 SCALES_FCO 的 `g_fco_standard`；m/ω/D/方向如 frozen JSON，osc≥2.5 | 保留该过滤列的 m、ω、D 和缺省条件，交集 tc>t₂；振荡门槛改为完整周期≥1.5 |
| 单位解释 | 评分变化 | legacy `osc≥2.5` 按仓库公式约等于 0.795775 个完整周期 | 明确以 `cycles_full≥1.5` 计分 |
| 窗口 / attempts / 缓存 | bug-fix（可复现性与记录完整性） | 旧扫描输出不能表达每 seed attempt 的独立状态和时钟映射 | 一窗口一汇总，多 attempt 分列；缓存键绑定数据哈希、时钟映射、域、单位、边界、solver、版本与 seed |
| 日历映射 | bug-fix（evaluation clock 记录） | 扫描以有效 bars 拟合，原输出未携带逐 bar session 映射 | 仍以有效 bars 拟合，但保留真实 session 索引；evaluation H=63，确认期 E 暂为 null |

以上逐项归入 bug-fix、model-domain change 或 scoring change。新契约下未来重拟合的结果不是纯算法收益，不能与 legacy 结果作“只换算法”的归因。T01 不运行扫描、不生成 B0 成绩。
"""
    return {
        "fit_contract_frozen.json": fit_contract,
        "call_chain_map.md": call_chain,
        "legacy_to_new_contract_diff.md": diff,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", required=True, type=Path)
    args = parser.parse_args()
    out_dir = args.out_dir.expanduser().resolve()
    if out_dir.exists():
        print(f"refusing to overwrite existing run directory: {out_dir}", file=sys.stderr)
        return 2
    artifacts = build_artifacts()
    out_dir.parent.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir()
    for name, value in artifacts.items():
        path = out_dir / name
        if isinstance(value, dict):
            path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        else:
            path.write_text(value, encoding="utf-8")
    print(json.dumps({"output_dir": str(out_dir), "files": sorted(artifacts)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
