"""§20.1 `_g3` 敏感性（计划 docs/plan_continuation_2026_11.md 步 C）：
`lppls_v2_g3q3`（tcgrid_lm∧de_lbfgsb 取最小 SSE）对 `lppls_v2_g2`（生产 tcgrid_lm，Actions 产物）的逐窗与逐报警日对照。
输出：窗级 SSE/t_c 变动分位、box 通过数、报警日 Jaccard（scale×q，全样本与剔除 2007/08/2014/15）。
用法：PYTHONPATH=. python scripts/audit_stock_math/exp19_g3_sensitivity.py [out_dir]
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("LPPLS_BOX", "v2")
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from research.eval.original_standard import THRESHOLDS  # noqa: E402
from research.features.lppls_rules import SCALES, multiscale_scores  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))
from exp18_dev_eval import EX, INDEXES, load_scan  # noqa: E402


def main(out_dir: str = "reports/q3_dev") -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    syms = os.environ.get("EXP18_SYMBOLS", ",".join(INDEXES)).split(",")
    win_rows, jac_rows = [], []
    for sym in syms:
        a = load_scan("lppls_v2_g3q3", sym)
        b = load_scan("lppls_v2_g2", sym)
        m = a.merge(b, on=["date", "n"], suffixes=("", "_g2"))
        rel = (m.sse - m.sse_g2) / m.sse_g2
        de = m[m.g3_src == "de_lbfgsb"]
        dtc = (de.tc - de.tc_g2).abs()
        ma, mb = multiscale_scores(a), multiscale_scores(b)
        win_rows.append(dict(
            symbol=sym, n_win=len(m), de_share=float((m.g3_src == "de_lbfgsb").mean()),
            sse_lower_1e6=float((rel < -1e-6).mean()), sse_higher_1e6=float((rel > 1e-6).mean()),
            sse_rel_p50_tcgrid=float(rel[m.g3_src == "tcgrid_lm"].abs().median()),
            sse_rel_p99_tcgrid=float(rel[m.g3_src == "tcgrid_lm"].abs().quantile(0.99)),
            dtc_de_p50=float(dtc.median()), dtc_de_p90=float(dtc.quantile(0.9)), dtc_de_p99=float(dtc.quantile(0.99)),
            box_g2=int(mb.filter(like="box__").notna().any(axis=1).sum()),
            box_pass_g2=int(sum(rules_pass(b))), box_pass_g3=int(sum(rules_pass(a))),
            q3_computed=int(a.q3_p.notna().sum()), q3_pass=int((a.q3_p <= 0.10).sum()),
        ))
        for sample in ("full", "ex"):
            ia = ma.index if sample == "full" else ma.index[~ma.index.year.isin(EX)]
            for sc in SCALES:
                col = f"box__{sc}"
                for q in THRESHOLDS:
                    sa = set(ia[(ma[col].reindex(ia).fillna(0) >= q).to_numpy()])
                    sb = set(ia[(mb[col].reindex(ia).fillna(0) >= q).to_numpy()])
                    u = len(sa | sb)
                    jac_rows.append(dict(symbol=sym, sample=sample, scale=sc, q=q, n_g2=len(sb), n_g3=len(sa),
                                         jaccard=(len(sa & sb) / u) if u else np.nan))
        print("done", sym, flush=True)
    w = pd.DataFrame(win_rows)
    j = pd.DataFrame(jac_rows)
    w.to_csv(out / "g3_windows.csv", index=False)
    j.to_csv(out / "g3_jaccard.csv", index=False)
    pd.set_option("display.width", 220)
    print(w.to_string(index=False))
    print(j.groupby(["sample", "scale"]).jaccard.describe()[["count", "min", "50%"]].to_string())
    print("Jaccard 中位（全部配置）", round(float(j.jaccard.median()), 3), "最小", round(float(j.jaccard.min()), 3))


def rules_pass(scan: pd.DataFrame):
    from research.features.lppls_rules import _derived, rules
    return rules(_derived(scan)).box.to_numpy()


if __name__ == "__main__":
    main(*sys.argv[1:])
