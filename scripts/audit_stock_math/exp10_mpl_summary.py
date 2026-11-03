# ruff: noqa: E402, E702
"""exp10 结果汇总：MPL / 普通剖面似然 / 块 bootstrap 的 90%、80% 覆盖率（Clopper–Pearson 95% 下界）与宽度；§21.2 第 2 条门槛判定。"""
import os

import pandas as pd
from scipy.stats import beta

OUT = os.environ.get("AUDIT_OUT", "/home/ubuntu/audit")


def cp_lower(k: int, n: int, conf: float = 0.95) -> float:
    return 0.0 if k == 0 else float(beta.ppf(1 - conf, k, n - k + 1))


if __name__ == "__main__":
    df = pd.read_parquet(f"{OUT}/exp10_mpl.parquet")
    pd.set_option("display.width", 250); pd.set_option("display.max_columns", 40)
    methods = {"lm": "MPL", "lp": "PL", "boot": "block_boot"}
    rows = []
    for key, name in methods.items():
        for lvl in (0.9, 0.8):
            c = df[f"{key}_{lvl}_cover"]
            rows.append(dict(method=name, level=lvl, n=len(c), cover=c.mean(), cp_lower=cp_lower(int(c.sum()), len(c)), width_med=df[f"{key}_{lvl}_width"].median(),
                             target=0.85 if lvl == 0.9 else 0.75))
    tot = pd.DataFrame(rows); tot["pass"] = tot.cover >= tot.target
    print("## overall"); print(tot.round(3).to_string())
    g = df.groupby(["sigma", "tc_rel", "n"]).agg(cnt=("seed", "size"), mpl90=("lm_0.9_cover", "mean"), pl90=("lp_0.9_cover", "mean"), boot90=("boot_0.9_cover", "mean"),
                                                mpl80=("lm_0.8_cover", "mean"), boot80=("boot_0.8_cover", "mean"), w_mpl90=("lm_0.9_width", "median"), w_boot90=("boot_0.9_width", "median"),
                                                bias=("tc_hat", lambda x: (x - df.loc[x.index, "tc0"]).median()))
    print("## by cell"); print(g.round(3).to_string())
    g2 = df.groupby(["sigma"]).agg(mpl90=("lm_0.9_cover", "mean"), pl90=("lp_0.9_cover", "mean"), boot90=("boot_0.9_cover", "mean"), mpl80=("lm_0.8_cover", "mean"), pl80=("lp_0.8_cover", "mean"), boot80=("boot_0.8_cover", "mean"))
    print("## by sigma"); print(g2.round(3).to_string())
    tot.to_csv(f"{OUT}/exp10_summary.csv", index=False); g.to_csv(f"{OUT}/exp10_by_cell.csv")
