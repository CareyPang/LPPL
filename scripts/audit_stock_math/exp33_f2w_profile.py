# ruff: noqa: E402
"""F2'（预登记 §26.1）：白化剖面似然比范围。OLS 残差 ρ̂ → Prais–Winsten 白化剖面 S_ρ̂(t_c) → 阈值 c(α,N)=F_{1,N−7;1−α}/(N−7)。
S-A 标定 α（合并覆盖率 ≥ 0.80 的最大 α）；门：S-B 合并覆盖率 ∈ [0.80, 0.95] 且四类各 ≥ 0.70；N'（种子 20–39）宽度中位 ≥ 搜索域 50%。
用法：OMP_NUM_THREADS=1 PYTHONPATH=. python scripts/audit_stock_math/exp33_f2w_profile.py [procs]"""
import sys
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fitacc_common as F

OUT = Path("reports/f2w_profile")
ALPHAS = (0.10, 0.05, 0.02, 0.01)
NULL_SEEDS = tuple(range(20, 40))
FILTER_BARS = 60


def one(c):
    if "null" in c:
        t, y = F.null_series(c)
        tc_true = np.nan
    else:
        t, y, tr = F.synth(c["n"], c["sigma"], c["kind"], c["phi"], c["seed"])
        tc_true = float(tr.theta()[0])
    lo, hi = F.bounds(len(y))
    _, rho = F.ols_rho(t, y, lo, hi)
    tcs, P = F.profile_tc_rho(t, y, lo, hi, rho)
    return dict(c, N=len(y), rho=rho, tc_true=tc_true, tcs=tcs, P=P, span=float(hi[0] - lo[0]))


def ranges(row, alpha):
    tcs, P = np.asarray(row.tcs), np.asarray(row.P)
    h = (tcs[1] - tcs[0]) / 2
    ok = tcs[P <= P.min() * (1 + F.f_thresh(alpha, int(row.N)))]
    lo_, hi_ = ok.min() - h, ok.max() + h
    return hi_ - lo_, (lo_ <= row.tc_true <= hi_) if np.isfinite(row.tc_true) else np.nan


def add_cols(D, alpha):
    w, cov = zip(*[ranges(r, alpha) for r in D.itertuples()], strict=True)
    D = D.copy()
    D["width"] = w
    D["rel_width"] = D.width / D.span
    D["cover"] = [float(c) if c == c else np.nan for c in cov]
    D["filt_pass"] = D.width < FILTER_BARS
    return D


def main():
    procs = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    cells = [dict(c, part="A") for c in F.synth_cells(F.SEEDS_A)] + [dict(c, part="B") for c in F.synth_cells(F.SEEDS_B)]
    cells += [dict(c, part="N") for c in F.null_cells(seeds=NULL_SEEDS)]
    with Pool(procs, initializer=F.init) as p:
        D = pd.DataFrame(p.map(one, cells, chunksize=1))
    OUT.mkdir(parents=True, exist_ok=True)
    D.to_parquet(OUT / "profiles.parquet")
    A, B, N = (D[D.part == k] for k in "ABN")
    lines = ["== S-A 标定（合并覆盖率）"]
    alpha = None
    for a in ALPHAS:
        cov = add_cols(A, a).cover.mean()
        lines.append(f"α={a:.2f}  coverage_A={cov:.4f}")
        if alpha is None and cov >= 0.80:
            alpha = a
    if alpha is None:
        lines.append("α=0.01 仍 < 0.80 → 标定失败，按 α=0.01 继续算 S-B/N' 仅作记录；F2' 未通过")
        alpha = 0.01
        calib_ok = False
    else:
        calib_ok = True
        lines.append(f"冻结 α={alpha}")
    Bc, Nc = add_cols(B, alpha), add_cols(N, alpha)
    Bc.drop(columns=["tcs", "P"]).to_csv(OUT / "s_b.csv", index=False)
    Nc.drop(columns=["tcs", "P"]).to_csv(OUT / "null.csv", index=False)
    cov_all = Bc.cover.mean()
    cov_noise = Bc.groupby("noise").cover.mean()
    lines.append(f"== S-B 合并覆盖率 {cov_all:.4f}（门 [0.80, 0.95]）\n" + cov_noise.round(4).to_string())
    lines.append("S-B 按 n：\n" + Bc.groupby(["noise", "n"]).cover.mean().round(4).to_string())
    g1 = calib_ok and 0.80 <= cov_all <= 0.95 and (cov_noise >= 0.70).all()
    medw = Nc.rel_width.median()
    lines.append(f"== N' 相对宽度中位 {medw:.4f}（门 ≥ 0.5）\n" + Nc.groupby("null").rel_width.median().round(4).to_string())
    g2 = medw >= 0.5
    lines.append("== 描述（不进裁决）：ρ̂ 中位  S-B " + ", ".join(f"{k}: {v:.3f}" for k, v in Bc.groupby("noise").rho.median().items())
                 + "；N' " + ", ".join(f"{k}: {v:.3f}" for k, v in Nc.groupby("null").rho.median().items()))
    lines.append(f"描述：宽度 < {FILTER_BARS} bar 的比例  S-B {Bc.filt_pass.mean():.3f}（"
                 + ", ".join(f"{k}: {v:.2f}" for k, v in Bc.groupby('noise').filt_pass.mean().items())
                 + f"）；N' {Nc.filt_pass.mean():.3f}（" + ", ".join(f"{k}: {v:.2f}" for k, v in Nc.groupby('null').filt_pass.mean().items()) + "）")
    lines.append(f"\nF2' 合成门：{'通过' if g1 and g2 else '未通过'}（覆盖门 {g1}，N' 宽度门 {g2}）")
    txt = "\n".join(lines)
    print(txt)
    (OUT / "run.log").write_text(txt + "\n")


if __name__ == "__main__":
    main()
