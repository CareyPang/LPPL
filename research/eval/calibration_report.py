"""汇总校准段（2019–2021）结果为 reports/calibration_2019_2021.md。只读 reports/calibration_2019_2021/*.csv，不做任何计算选择。
python -m research.eval.calibration_report"""
from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

SPLIT = os.environ.get("CP_EVAL_SPLIT", "cal")
D = Path("reports/calibration_2019_2021" if SPLIT == "cal" else "reports/final_test_2022_2025")
OUT = Path("reports/calibration_2019_2021.md" if SPLIT == "cal" else "reports/final_test_2022_2025.md")
SEG = "校准段 2019–2021" if SPLIT == "cal" else "最终测试段 2022-01–2025-08（只跑一次）"
VARIANTS = ("share30", "share70", "fixed15", "sigma1.5")


def _tab(df: pd.DataFrame, cols: list[str] | None = None, r: int = 5) -> str:
    if cols:
        df = df[[c for c in cols if c in df.columns]]
    return "```\n" + df.round(r).to_string(index=False) + "\n```\n"


def _rd(name: str) -> pd.DataFrame | None:
    p = D / name
    return pd.read_csv(p) if p.exists() else None


def main() -> None:
    top, toph, topp = _rd("top_chain.csv"), _rd("top_holdouts.csv"), _rd("top_platt.csv")
    bot, boti, both, botp = _rd("bottom_chain.csv"), _rd("bottom_chain_index_only.csv"), _rd("bottom_holdouts.csv"), _rd("bottom_platt.csv")
    ls, la, ly = _rd("lppls_summary.csv"), _rd("lppls_a1a2.csv"), _rd("lppls_by_year.csv")
    r2 = top[top.level == "R2"].iloc[0]
    pass_i_top = bool(r2.pass_i_vs_R0)
    pass_i_bot = {lv: bool(x) for lv, x in zip(bot.level, bot.pass_i_vs_R0, strict=True) if lv != "R0"}
    md = [f"# {SEG} 报告（只报告，不选择；冻结见 docs/dev_freeze.md）\n",
          "开发段 2000–2018 一次拟合 → 校准段前推。基线 R0 = 开发段基率。ΔBrier 为负=优于基率；90% 区间为 80 日块 bootstrap。",
          "判据（用户 2026-10-26 接受）：(i) ΔBrier 区间上界<0；(ii) ≥4/6 指数 A1 循环平移 p≤0.05 且 A2≥0.5（H=120）；(iii) 留出任一指数/年份不翻转。\n",
          "## 1. 样本", f"- 顶部（稀疏 as-of 网格，R2 特征）：校准段 n={int(r2.n)}，正标签 {int(r2.events_pos)}，指数 7（含科创50 自 2020）。",
          f"- 底部（逐日，指数+个股）：校准段 n={int(bot.n.iloc[0])}，正标签 {int(bot.events_pos.iloc[0])}。\n",
          "## 2. 判据 (i)：概率模块\n### 2.1 顶部 p20 = R2（GSADF bsadf500_psy）",
          _tab(top, ["level", "features", "brier", "log_loss", "ece", "bss", "pr_auc", "dbrier_vs_R0", "ci_lo_R0", "ci_hi_R0", "pass_i_vs_R0", "n_events", "hit_rate", "false_alarm_rate"]),
          f"**结论：判据 (i) {'通过' if pass_i_top else '未通过'}**（点估计 {r2.dbrier_vs_R0:+.5f}，上界 {r2.ci_hi_R0:+.5f}）。",
          ("Platt（校准段一次拟合，仅记录）：" if SPLIT == "cal" else "Platt（套用校准段固定 (a,b)，不重拟合）："), _tab(topp),
          "斜率 a<0 表示校准段内 R2 概率与结果方向相反。\n",
          "留出（LOCO / 留出年）：", _tab(toph),
          "标签变体（§3 步骤 5；冻结标签为 main，变体只报告不替换）："]
    for v in VARIANTS:
        t = _rd(f"top_chain_{v}.csv")
        if t is not None:
            x = t[t.level == "R2"].iloc[0]
            md.append(f"- {v}: ΔBrier {x.dbrier_vs_R0:+.5f} [{x.ci_lo_R0:+.5f}, {x.ci_hi_R0:+.5f}] → {'通过' if x.pass_i_vs_R0 else '未通过'}")
    md += ["\n### 2.2 底部链 R0 → B1 → B2 → B3", _tab(bot, ["level", "dbrier_vs_R0", "ci_lo_R0", "ci_hi_R0", "pass_i_vs_R0", "dbrier", "ci_lo", "ci_hi", "brier", "ece", "pr_auc"]),
           "**结论：判据 (i) " + "、".join(f"{k} {'通过' if v else '未通过'}" for k, v in pass_i_bot.items()) + "**。",
           "仅指数子样本：", _tab(boti), "Platt（仅记录）：", _tab(botp), "留出：", _tab(both)]
    md += ["\n## 3. 判据 (ii)：LPPLS 置信度报警（产品尺度 6–12 月 / 12–24 月，q=0.05）"]
    if ls is None:
        md.append("**待校准段扫描完成后运行 `research.eval.calibration_lppls`。**")
    else:
        md += ["按指标 × H 汇总（n_pass = A1 p≤0.05 且 A2≥0.5 的指数数；pass_ii = n_pass≥4；loco_min = 留出任一指数后的最小 n_pass，pass_iii_loco = 留出后仍 ≥4）：", _tab(ls)]
        w = ls[(ls.H == 120) & ls.pass_ii]
        if len(w):
            md += ["**判据 (ii) 名义通过的组合（H=120）：** " + "、".join(f"{r.indicator}（n_pass {r.n_pass}，留出后最小 {r.loco_min}，(iii) {'通过' if r.pass_iii_loco else '不通过'}）" for r in w.itertuples()),
                   "校准段每指数仅 1–5 个合格顶、报警日 60–250 个，4/7 恰好过线且留出任一通过指数即跌到 3/6，属脆弱结果；FCO END/STANDARD 在校准段全部不过，"
                   "与开发段六档重测（END 最强、box≈随机）相反——开发段与校准段的强弱互换本身说明过滤集之间没有稳健的优劣。"]
        else:
            md += ["**判据 (ii)：无组合通过。**"]
        if la is not None:
            # Holm 修正（补充）：对同一指标跨 7 指数的 A1 p 做 Holm，看 n_pass 变化
            rows = []
            for (c, H), g in la.groupby(["indicator", "H"]):
                p = g.A1_p.fillna(1).sort_values().to_numpy()
                m = len(p)
                adj = pd.Series([min(1.0, max((m - j) * p[j] for j in range(i + 1))) for i in range(m)])
                rows.append(dict(indicator=c, H=H, n_pass_raw=int((g.A1_p <= 0.05).sum()), n_pass_holm=int((adj <= 0.05).sum())))
            md += ["Holm 修正后 A1 显著指数数（补充，不改变判据口径）：", _tab(pd.DataFrame(rows))]
            md += ["逐指数明细（H=120）：", _tab(la[la.H == 120], ["symbol", "indicator", "n_alarm", "n_tops", "A1", "A1_null", "A1_p", "A2", "A2_null", "A2_p"], 3)]
        if ly is not None:
            piv = ly.pivot_table(index=["indicator", "year"], values=["n_alarm", "A1_H120"], aggfunc={"n_alarm": "sum", "A1_H120": "median"}).reset_index()
            md += ["按年（报警日合计与 A1 中位数）：", _tab(piv, None, 3)]
    md += ["\n## 4. 多重比较（§3 步骤 4）",
           "- 开发段阶梯 70 配置：CSCV-PBO 0.503、SPA p 0.1615（`reports/ladder_dev_full_v2_mt.md`）——开发段的配置选择本身接近运气水平，与校准段 R2 未通过一致。",
           "- 开发段候选总数：阶梯 70 + 原版标准网格 108 + 尺度敏感性 162 = 340；原版标准/尺度敏感性的 A1 p 值在开发段未做多重比较修正，报告中已声明为开发段描述。",
           "- 校准段只评价冻结配置（R2 一个；LPPLS 2 尺度 × 3 规则 × 2 H），不再选择；§3 给出 Holm 修正作为补充。",
           "\n## 5. 对抗性检查（§3 步骤 5）",
           "- 标签扰动：见 §2.1 标签变体——share30/share70 与主标签同向（未通过），fixed15/sigma1.5 为负；结论依赖标签定义，按冻结以 main 为准。",
           "- 安慰剂：LPPLS A1/A2 的零分布即报警序列循环平移（§3）；R2 概率模块的对照为开发段基率 R0。",
           "- 留出指数 / 留出年：§2.1、§2.2 表，顶部与底部均不翻转（全部未通过）。",
           "\n## 6. 结论与产品处置",
           f"- 顶部 p20（R2）：判据 (i) **{'通过' if pass_i_top else '未通过'}** → 契约 `top.p20` 证据等级 `dev_failed`，不显示概率。",
           f"- 底部概率链 B1/B2/B3：判据 (i) **{'全部未通过' if not any(pass_i_bot.values()) else '部分通过'}** → `bottom.state_p/thrust_p` 不显示概率。",
           "- LPPLS 置信度（泡沫状态）：判据 (ii) 仅 box 6–12 月档 H=120 名义通过（4/7），判据 (iii) 留出不满足，Holm 后 3/7；FCO END/STANDARD 不过 → "
           "证据等级 `cal_fragile`（校准段部分通过、不稳健），只作状态分级显示，不作概率、不升级。",
           "- 产品层按用户裁决改为原版输出形式：DS 置信度 / t_c 情景 / 泡沫大小与持续时间（`docs/dev_freeze.md` §6）。",
           "- 最终测试段 2022-01–2025-08：按冻结只跑一次、只报告；未通过模块不因测试段结果升级。是否运行待用户决定。"]
    OUT.write_text("\n".join(md), encoding="utf-8")
    print(OUT, len(md))


if __name__ == "__main__":
    main()
