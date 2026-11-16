# ruff: noqa: E402
"""F3'（预登记 §26.2）确认性运行：S-A 种子 0–11 的 AR(1) 格上比较 OLS / 真 φ GLS / AR(1) 精确似然联合估计的参数误差。
不是门；检验 §26.0 D1 的预测：ML/OLS 与 真φGLS/OLS 之比相差 ≤ 0.10，且 φ=0.5 下 t_c、m 不会都 ≤ 0.80。
用法：OMP_NUM_THREADS=1 PYTHONPATH=. python scripts/audit_stock_math/exp32_f3_ml_confirm.py [procs]"""
import sys
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fitacc_common as F

OUT = Path("reports/f3_ml_confirm")
KEYS = ("tc", "m", "w")


def one(c):
    t, y, tr = F.synth(c["n"], c["sigma"], c["kind"], c["phi"], c["seed"])
    lo, hi = F.bounds(c["n"])
    th0 = np.array(tr.theta(), float)
    out = dict(c)
    th_ols, _ = F.fit(t, y, lo, hi, 0.0)
    th_orc, _ = F.fit(t, y, lo, hi, c["phi"])
    th_ml, rho_ml, n_eval = F.fit_ml_ar1(t, y, lo, hi)
    out.update(rho_ml=rho_ml, n_eval=n_eval)
    for lab, th in (("ols", th_ols), ("orc", th_orc), ("ml", th_ml)):
        for i, k in enumerate(KEYS):
            out[f"{lab}_e{k}"] = abs(float(th[i]) - th0[i])
    return out


def main():
    procs = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    cells = [c for c in F.synth_cells(F.SEEDS_A) if c["kind"] == "ar1"]
    with Pool(procs, initializer=F.init) as p:
        D = pd.DataFrame(p.map(one, cells, chunksize=1))
    OUT.mkdir(parents=True, exist_ok=True)
    D.to_csv(OUT / "raw.csv", index=False)
    lines = [f"S-A AR(1) 格 {len(D)} 条；ML ρ̂ 中位 " + ", ".join(f"{no}: {g.rho_ml.median():.3f}" for no, g in D.groupby("noise"))]
    g = D.groupby("noise")[[f"{lab}_e{k}" for lab in ("ols", "orc", "ml") for k in KEYS]].median()
    for k in KEYS:
        g[f"orc/ols_{k}"] = g[f"orc_e{k}"] / g[f"ols_e{k}"]
        g[f"ml/ols_{k}"] = g[f"ml_e{k}"] / g[f"ols_e{k}"]
    lines.append("== 中位绝对误差与比值\n" + g.round(4).to_string())
    gap = max(abs(g[f"ml/ols_{k}"] - g[f"orc/ols_{k}"]).max() for k in KEYS)
    p1 = gap <= 0.10
    r5 = g.loc["ar1_0.5"]
    reopen = (r5["ml/ols_tc"] <= 0.80) and (r5["ml/ols_m"] <= 0.80)
    lines.append(f"预测 1（|ML/OLS − 真φGLS/OLS| ≤ 0.10）：最大差 {gap:.4f} → {'成立' if p1 else '不成立'}")
    lines.append(f"预测 2（φ=0.5 下 t_c、m 不会都 ≤ 0.80）：ML/OLS t_c {r5['ml/ols_tc']:.3f}、m {r5['ml/ols_m']:.3f} → "
                 + ("**重开 F3**" if reopen else "成立，F3 以理论上限不达门归档"))
    txt = "\n".join(lines)
    print(txt)
    (OUT / "run.log").write_text(txt + "\n")


if __name__ == "__main__":
    main()
