"""Render explicitly nominated review cases, never fit or score a forecast.

This is an artifact generator, not the proposed evaluation engine. It checks
only named points from the hand-authored casebook. No project modules, network,
automatic peak search, parameter tuning, predictions or strategy are loaded.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "D:/CodexData/cache/matplotlib-lppl-label-review")
import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
FONT = FontProperties(fname="C:/Windows/Fonts/msyh.ttc")
plt.rcParams.update({"font.family": FONT.get_name(), "axes.unicode_minus": False,
                     "font.size": 11, "savefig.facecolor": "#ffffff"})
DATA = json.loads((HERE / "synthetic_cases.json").read_text(encoding="utf-8"))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def style(ax, title, xlabel):
    ax.set_title(title, loc="left", fontsize=15, pad=13, fontweight="normal")
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_color("#ccd4dc")
    ax.grid(axis="y", color="#e9edf1", linewidth=0.7)
    ax.set_xlabel(xlabel)
    ax.set_ylabel("示意价格" if xlabel.startswith("交易日") else "快照收盘值")
    ax.margins(x=0.02, y=0.15)


def synthetic_series(case):
    anchors = np.array(case["anchors"])
    x = np.arange(181)
    y = np.round(np.interp(x, anchors[:, 0], anchors[:, 1]), 2)
    return x, y


checks = []
csv_rows = []
for case in DATA["cases"]:
    x, y = synthetic_series(case)
    csv_rows.extend({"case_id": case["id"], "session": int(i), "close": float(p)}
                    for i, p in zip(x, y))
    for peak, expected_short, expected_stage in zip(
            case["peaks"], case["expected_short"], case["expected_stage"]):
        short = bool(y[peak] == max(y[peak-10:peak+11]))
        stage = bool(y[peak] == max(y[peak-63:peak+22]))
        assert (short, stage) == (expected_short, expected_stage), case["id"]
        checks.append({"case": case["id"], "peak_session": peak,
                       "short_point": short, "stage_structure_point": stage,
                       "status": "VERIFIED_NOMINATED_SYNTHETIC_POINT_ONLY"})
pd.DataFrame(csv_rows).to_csv(HERE / "synthetic_prices.csv", index=False, encoding="utf-8", lineterminator="\n")


def draw_synthetic(case, ax):
    x, y = synthetic_series(case)
    ax.plot(x, y, color="#26485c", linewidth=2)
    for peak, stage in zip(case["peaks"], case["expected_stage"]):
        color = "#2865a5" if stage else "#995b22"
        ax.scatter([peak], [y[peak]], color=color, s=48, zorder=4)
        text = f"T{peak}  阶段＋短期" if stage else f"T{peak}  仅短期"
        # Keep the final event on the chart; text offset is purely presentation.
        ax.annotate(text, (peak, y[peak]), xytext=(9, 10),
                    textcoords="offset points", color=color, fontsize=11)
    a = case.get("rise_start")
    if a is not None:
        ax.scatter([a], [y[a]], s=26, color="#6a7682", zorder=4)
        ax.annotate(f"起点 T{a}", (a, y[a]), xytext=(8, -18),
                    textcoords="offset points", color="#56616b", fontsize=10)
    if case.get("plateau_end"):
        ax.axvspan(case["peaks"][0], case["plateau_end"], color="#2865a5", alpha=.10)
    style(ax, f"{case['id']}  {case['title']}", "交易日序号（合成示意）")
    ax.text(0, -0.28, case["note"], transform=ax.transAxes, fontsize=10, color="#52616c")


for filename, cases in [("core_examples.png", DATA["cases"][:3]),
                        ("boundary_examples.png", DATA["cases"][3:])]:
    fig, axes = plt.subplots(3, 1, figsize=(12.6, 11.8))
    for case, ax in zip(cases, axes):
        draw_synthetic(case, ax)
    fig.subplots_adjust(top=.91, bottom=.075, left=.08, right=.97, hspace=.62)
    fig.suptitle("顶部标签语义审阅 · 合成曲线，不是模型预测", fontsize=19, x=.08, ha="left")
    fig.savefig(HERE / filename, dpi=170)
    plt.close(fig)

real_path = HERE / "real_case_spec.json"
inputs = []
if real_path.exists():
    spec = json.loads(real_path.read_text(encoding="utf-8"))
    records, subsets = [], []
    fig, axes = plt.subplots(len(spec["cases"]), 1,
                             figsize=(12.6, 3.5 * len(spec["cases"]) + 1), squeeze=False)
    for case, ax in zip(spec["cases"], axes[:, 0]):
        path = ROOT / case["source"]
        data = pd.read_parquet(path).sort_values("date").reset_index(drop=True)
        assert data["date"].is_unique
        source_hash = sha(path)
        if case.get("source_sha256"):
            assert source_hash == case["source_sha256"]
        inputs.append({"path": case["source"], "sha256": source_hash})
        peak = int(data.index[data["date"] == pd.Timestamp(case["peak_date"])][0])
        p = data["close"].astype(float)
        short = bool(p.iloc[peak] == p.iloc[peak-10:peak+11].max())
        stage = bool(p.iloc[peak] == p.iloc[peak-63:peak+22].max())
        assert (short, stage) == (case["short"], case["stage"]), case["id"]
        rise = None
        if case.get("rise_start"):
            a = int(data.index[data["date"] == pd.Timestamp(case["rise_start"])][0])
            assert p.iloc[a] == p.iloc[a-21:a+22].min()
            assert 21 <= peak-a <= 126
            assert p.iloc[peak] > p.iloc[a]
            assert p.iloc[a+1:peak+1].min() >= p.iloc[a]
            rise = peak-a
        subset = data.loc[data["date"].between(case["display_start"], case["display_end"]),
                          ["date", "close"]].copy()
        subset["case_id"] = case["id"]
        subsets.append(subset)
        ax.plot(subset["date"], subset["close"], color="#26485c", linewidth=1.6)
        date, price = data.loc[peak, ["date", "close"]]
        ax.scatter([date], [price], color="#2865a5" if stage else "#995b22", s=42, zorder=4)
        ax.annotate(f"{date:%Y-%m-%d}\n{price:,.2f}", (date, price),
                    xytext=(10, 9), textcoords="offset points", fontsize=10)
        if rise is not None:
            ax.scatter([data.loc[a,"date"]], [p.iloc[a]], color="#6a7682", s=25)
            ax.annotate(f"起点 {data.loc[a,'date']:%m-%d} · {rise}个观测间隔",
                        (data.loc[a,"date"], p.iloc[a]), xytext=(10,-18),
                        textcoords="offset points", fontsize=10)
        style(ax, f"{case['id']}  {case['title']}", "日期（既有仓库快照；不是当时预测）")
        ax.xaxis.set_major_locator(mdates.MonthLocator(interval=1))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
        records.append({"id":case["id"], "peak_date":case["peak_date"],
                        "close":float(price), "short":short, "stage_structure":stage,
                        "rise_observation_intervals":rise,
                        "short_support_start":str(data.loc[peak-10,"date"].date()),
                        "short_support_end":str(data.loc[peak+10,"date"].date()),
                        "stage_support_start":str(data.loc[peak-63,"date"].date()),
                        "stage_support_end":str(data.loc[peak+21,"date"].date()),
                        "short_closure_date_if_singleton":str(data.loc[peak+15,"date"].date()),
                        "stage_closure_date_if_singleton":str(data.loc[peak+26,"date"].date()),
                        "status":"SNAPSHOT_ONLY_NOT_PIT_OR_FORECAST_EVIDENCE"})
    fig.subplots_adjust(top=.91, bottom=.075, left=.08, right=.97, hspace=.52)
    fig.suptitle("已有行情的具体例子 · 只核对顶部定义", fontsize=19, x=.08, ha="left")
    fig.savefig(HERE / "real_examples.png", dpi=170)
    plt.close(fig)
    pd.concat(subsets).to_csv(HERE / "real_example_prices.csv", index=False, encoding="utf-8", date_format="%Y-%m-%d", lineterminator="\n")
    (HERE / "real_example_checks.json").write_text(json.dumps(records,ensure_ascii=False,indent=2)+"\n",encoding="utf-8",newline="\n")

    # Verify the explicitly nominated right-context comparison, not a sweep.
    review = json.loads((HERE / "selected_real_cases.json").read_text(encoding="utf-8"))
    for case in review["right_context_semantic_comparison"]["cases"]:
        data = pd.read_parquet(ROOT / "data/frozen/v20261104" /
                               (case["symbol"] + "_qfq.parquet")).sort_values("date").reset_index(drop=True)
        u = int(data.index[data.date == pd.Timestamp(case["peak_date"])][0])
        for right in (21, 42):
            actual = bool(data.close.iloc[u] == data.close.iloc[u-63:u+right+1].max())
            assert actual == case[f"stage_L63_R{right}"]
            assert str(data.loc[u+right,"date"].date()) == case[f"right_end_R{right}"]

    data = pd.read_parquet(ROOT / "data/frozen/v20261104/sh000001_qfq.parquet")
    subset = data.loc[data.date.between("2024-01-01", "2024-07-31")]
    fig, ax = plt.subplots(figsize=(12.6, 6.1))
    ax.plot(subset.date, subset.close, color="#26485c", linewidth=1.8)
    ax.axvspan(pd.Timestamp("2024-03-18"),pd.Timestamp("2024-04-18"),
               color="#b5cddd",alpha=.22)
    ax.axvline(pd.Timestamp("2024-04-18"),color="#8597a5",linewidth=1,linestyle="--")
    ax.axvline(pd.Timestamp("2024-05-22"),color="#2865a5",linewidth=1,linestyle="--")
    annotations = [("2024-02-05", "上涨起点 2/5", (8,-24)),
                   ("2024-03-18", "3/18：右21日规则纳入\n右42日规则排除", (-110,26)),
                   ("2024-05-20", "5/20：两种阶段规则均纳入", (12,20))]
    for date,text,offset in annotations:
        row = data.loc[data.date == date].iloc[0]
        ax.scatter([row.date],[row.close],s=40,color="#2865a5",zorder=4)
        ax.annotate(text,(row.date,row.close),xytext=offset,textcoords="offset points",
                    fontsize=11,arrowprops={"arrowstyle":"-","color":"#8597a5","lw":.8})
    style(ax,"同一轮上涨：3月的中间高点，还是5月的阶段高点？", "日期（既有快照）")
    ax.xaxis.set_major_locator(mdates.MonthLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax.text(pd.Timestamp("2024-04-18"),.02,"右21日结束",rotation=90,va="bottom",ha="right",
             transform=ax.get_xaxis_transform(),fontsize=9,color="#687985")
    ax.text(pd.Timestamp("2024-05-22"),.02,"右42日结束",rotation=90,va="bottom",ha="right",
             transform=ax.get_xaxis_transform(),fontsize=9,color="#2865a5")
    fig.subplots_adjust(top=.83,bottom=.18,left=.08,right=.97)
    fig.suptitle("待确认的标签语义 · 阴影与虚线是事后确认范围，不是预测区间",
                 fontsize=16,x=.08,ha="left")
    fig.text(.08,.045,"右窗越长，标签确认越晚；这不是更准的预测，也不是永远不会再创新高的证明。",fontsize=11,color="#52616c")
    fig.savefig(HERE / "stage_semantics_comparison.png",dpi=170)
    plt.close(fig)

manifest = {"status":"CASEBOOK_ONLY_NOT_EVALUATOR_NOT_BACKTEST",
            "synthetic_cases":len(DATA["cases"]), "nominated_point_checks":checks,
            "inputs":inputs, "no_forecast_or_fit_files_read":True,
            "price_and_calendar": "Real qfq snapshots: corporate actions, PIT availability and exchange-calendar completeness NOT_ESTABLISHED; row gaps are observation intervals.",
            "files": {p.name:sha(p) for p in sorted(HERE.iterdir())
                       if p.is_file() and p.name != "manifest.json"}}
(HERE / "manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8",newline="\n")
print(json.dumps({"synthetic_cases":len(DATA["cases"]),"point_checks":len(checks),
                  "real_cases":len(inputs),"outputs":list(manifest["files"])},ensure_ascii=False))
