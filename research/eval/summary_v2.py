"""§17 合并报告：把原版标准评分（A1/A2、FBE、稳定性、价值分层）、次要 CPCV（20/60 日）、PBO/SPA 汇成一份。
用法：python -m research.eval.summary_v2 [box=v2]  → reports/lppls_v2_summary.md
只读已生成的 csv/md，不重新计算。"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd


def _read(p: Path) -> pd.DataFrame | None:
    return pd.read_csv(p) if p.exists() else None


def main(box: str = "v2") -> None:
    out = [f"# LPPLS {box} 合并报告（开发段 2000–2018；指数；预登记 §17）\n"]
    osd = Path(f"reports/original_standard_dev_{box}")
    agg = _read(osd / "alarm_grid_agg.csv")
    if agg is not None:
        agg["scale"] = agg.indicator.str.split("__").str[-1]
        rob = agg[agg.robust] if "robust" in agg else agg.iloc[0:0]
        out.append(f"## 1. 原版标准（报警→H 日内体制改变）\n\n组合 {len(agg)}，稳健区域 {len(rob)}。\n")
        best = (agg.assign(lift=agg.A1 - agg.A1_null).sort_values("lift", ascending=False)
                .groupby(["scale", "H"]).head(1)[["indicator", "q", "H", "n_sym", "n_alarm", "A1", "A1_null", "A1_p_med", "A2", "A2_null", "A2_p_med", "robust"]])
        out.append("每个尺度×H 的最佳提升（仅供定位，保留仍按稳健区域）：\n\n" + best.round(3).to_markdown(index=False) + "\n")
        sc = agg.groupby(["scale", "H"]).agg(A1=("A1", "median"), A1_null=("A1_null", "median"), A2=("A2", "median"),
                                            A2_null=("A2_null", "median"), robust=("robust", "sum")).round(3)
        out.append("按尺度中位数：\n\n" + sc.to_markdown() + "\n")
    win = _read(osd / "quantile_windows.csv")
    if win is not None:
        cols = [c for c in win.columns if c.startswith("cover") or c.startswith("random")]
        w = win.groupby(["rule", "kind"]).agg(n=("cover", "size"), width_med=("width", "median"), **{c: (c, "mean") for c in cols}).round(3)
        out.append("## 2. FBE 式分位窗（含 bootstrap 窗 lagrange_boot）\n\n" + w.to_markdown() + "\n")
        if "stab3" in win:
            s = win.dropna(subset=["stab3"]).assign(stab_hi=lambda x: x.stab3 >= 0.5).groupby(["rule", "kind", "stab_hi"]).agg(
                n=("cover", "size"), cover=("cover", "mean"), cover_updays=("cover_updays", "mean"), cover_sg=("cover_sg", "mean")).round(3)
            out.append("t_c 分布稳定性分层：\n\n" + s.to_markdown() + "\n")
    summ = osd / "summary.md"
    if summ.exists():
        txt = summ.read_text()
        if "价值分数分层" in txt:
            out.append("## 3. 价值分层\n\n" + txt.split("## 价值分数分层")[1].split("## ")[0].strip() + "\n")
    out.append("## 4. 次要检验：CPCV Brier\n")
    for tag, label in ((f"ladder_dev_lppls_{box}", "20 日视窗"), (f"ladder_dev_lppls_{box}_h60", "60 日视窗"), (f"ladder_dev_full_{box}", "完整阶梯 20 日")):
        t = _read(Path(f"reports/{tag}.csv"))
        if t is None:
            out.append(f"- {label}：未生成\n")
            continue
        ch = t[t.config.astype(str).str.contains("chosen")] if "config" in t else t
        cols = [c for c in ("level", "config", "C", "kept", "dbrier", "ci_lo", "ci_hi") if c in ch.columns]
        out.append(f"### {label}（{tag}）\n\n" + ch[cols].round(5).to_markdown(index=False) + "\n")
    mt = Path(f"reports/{f'ladder_dev_full_{box}'}_mt.md")
    if mt.exists():
        out.append("## 5. 多重比较（PBO/SPA）\n\n" + mt.read_text().strip()[:3000] + "\n")
    out.append("\n说明：全部为开发段结果，不是样本外结论；校准段、最终测试段未运行。v1 结果保留在 reports/ladder_dev_lppls.md 等文件作为失败记录。\n")
    Path(f"reports/lppls_{box}_summary.md").write_text("\n".join(out))
    print("\n".join(out)[:4000])


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "v2")
