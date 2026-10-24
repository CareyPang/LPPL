"""t_c 区间覆盖率实验：python -m research.lppls.interval_coverage → reports/tc_interval_coverage.{json,md}"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..lppls.core import default_bounds
from ..synth.hard import sample_hard
from .intervals import bootstrap_interval, profile_interval

OUT = Path(__file__).resolve().parents[2] / "reports"


def main(n_cases=12, scenarios=("base", "weak_osc", "short"), noises=("iid", "garch"), sigma=0.02):
    rows = []
    for sc in scenarios:
        for noise in noises:
            for c in range(n_cases):
                t, y, tr = sample_hard(sc, sigma=sigma, noise=noise, seed=5000 + 100 * c)
                lo, hi = default_bounds(tr.n, horizon=(1, 90))
                for name, fn in (("profile", profile_interval), ("bootstrap", bootstrap_interval)):
                    a, b, hat = fn(t, y, lo, hi)
                    rows.append(dict(scenario=sc, noise=noise, case=c, method=name, lo=a, hi=b, hat=hat, tc=tr.tc,
                                     covered=bool(a <= tr.tc <= b), width=b - a))
            print(sc, noise, "done", flush=True)
    df = pd.DataFrame(rows)
    df.to_json(OUT / "tc_interval_coverage.json", orient="records")
    tab = df.groupby(["method"]).agg(coverage=("covered", "mean"), med_width=("width", "median"))
    per = df.groupby(["scenario", "noise", "method"]).agg(coverage=("covered", "mean"), med_width=("width", "median"))
    (OUT / "tc_interval_coverage.md").write_text(
        "# t_c 90% 区间覆盖率（阶段 3b）\n\n名义水平 90%。profile = 剖面似然（未含 modified 校正）；bootstrap = 残差循环块 bootstrap（B=50，块长 10）。\n\n"
        + tab.round(3).to_markdown() + "\n\n## 分场景\n" + per.round(3).to_markdown() + "\n")
    print(tab)


if __name__ == "__main__":
    main()
