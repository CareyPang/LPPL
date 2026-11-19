"""Draw the 510210 NAV and closing-position figure from the two replay ledgers."""

import argparse
import csv
from datetime import date
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
from matplotlib import font_manager
from matplotlib import pyplot as plt

REPORT = Path(__file__).resolve().parents[2] / "reports/stage_etf_20261118"
PATHS = ("hold", "release_next", "release_plus5")
COLORS = ("#586771", "#006d83", "#b86926")
STYLES = (":", "-", "--")


def read_rows(path):
    with path.open(encoding="utf-8-sig", newline="") as source:
        return list(csv.DictReader(source))


def plot(report):
    daily = read_rows(report / "daily_positions.csv")
    peaks = [row for row in read_rows(report / "peaks.csv") if row["path"] == "hold"]
    paths = {
        path: sorted((row for row in daily if row["path"] == path), key=lambda row: row["date"])
        for path in PATHS
    }
    dates = [date.fromisoformat(row["date"]) for row in paths["hold"]]
    for rows in paths.values():
        if [date.fromisoformat(row["date"]) for row in rows] != dates:
            raise ValueError("daily ledgers use different sessions")
    if len(set(dates)) != len(dates) or len(dates) != 235 or len(peaks) != 5:
        raise ValueError("expected 235 sessions and five scored peaks")

    families = {f.name for f in font_manager.fontManager.ttflist}
    cjk = next(
        (
            f
            for f in (
                "Microsoft YaHei",
                "Noto Sans CJK SC",
                "PingFang SC",
                "Source Han Sans SC",
                "WenQuanYi Zen Hei",
            )
            if f in families
        ),
        None,
    )
    plt.rcParams.update({"font.family": cjk or "DejaVu Sans", "axes.unicode_minus": False})

    def label(zh, en):
        return zh if cjk else en

    names = (
        label("一直持有", "Buy and hold"),
        label("解除后次日买回", "Buy at next open"),
        label("买回再延后五个交易日", "Delay buyback five sessions"),
    )
    ink, muted, line = "#21353d", "#526976", "#dce4e7"
    fig, (nav, weight) = plt.subplots(
        2, 1, sharex=True, figsize=(11.4, 7.0), gridspec_kw={"height_ratios": [2.1, 1]}
    )
    fig.subplots_adjust(left=0.083, right=0.973, top=0.75, bottom=0.115, hspace=0.35)
    fig.text(
        0.083,
        0.956,
        label("五个阶段顶，当时还持有多少？", "How much was invested at each peak?"),
        fontsize=21,
        fontweight="bold",
        color=ink,
    )
    description = label(
        "富国上证综指 ETF（510210） · 历史持仓回放 · 235 个交易日",
        "Fullgoal SSE Composite ETF (510210)   /   Historical replay   /   235 sessions",
    )
    fig.text(0.083, 0.911, description, fontsize=10.5, color=muted)

    for axis in (nav, weight):
        axis.set_axisbelow(True)
        axis.grid(axis="y", linewidth=0.7, color=line)
        axis.tick_params(axis="both", length=0, pad=6, labelsize=9, colors=muted)
        for spine in axis.spines.values():
            spine.set_visible(False)
        axis.margins(x=0)
    nav.set_ylabel(label("账户净值（万元）", "NAV (CNY 10,000)"), color=muted, fontsize=10)
    weight.set_ylabel(label("收盘仓位（%）", "Closing weight (%)"), color=muted, fontsize=10)
    weight.set_ylim(43, 107)
    weight.set_yticks([50, 75, 100])

    for i, (path, rows) in enumerate(paths.items()):
        nav.plot(
            dates,
            [float(row["nav"]) / 10000 for row in rows],
            color=COLORS[i],
            linestyle=STYLES[i],
            linewidth=1.65,
            label=names[i],
            zorder=3,
        )
        if path != "hold":
            weight.step(
                dates,
                [float(row["position_weight"]) * 100 for row in rows],
                where="post",
                color=COLORS[i],
                linestyle=STYLES[i],
                linewidth=1.7,
            )
    for row in peaks:
        day = date.fromisoformat(row["peak"])
        if day not in dates:
            raise ValueError(f"peak outside the portfolio calendar: {day}")
        hit = bool(row["credited_watch"])
        color = "#54667a" if hit else "#bb4556"
        status = label("命中", "Hit") if hit else label("漏报", "Miss")
        for axis in (nav, weight):
            axis.axvline(day, color=color, linewidth=0.85, linestyle=(0, (3, 4)), alpha=0.68)
        nav.text(
            day,
            1.025,
            f"{day:%m/%d} {status}",
            transform=nav.get_xaxis_transform(),
            ha="center",
            va="bottom",
            fontsize=9,
            color=color,
        )
    handles, texts = nav.get_legend_handles_labels()
    fig.legend(
        handles,
        texts,
        loc="upper left",
        bbox_to_anchor=(0.079, 0.884),
        ncol=3,
        frameon=False,
        fontsize=10,
        handlelength=3.0,
        columnspacing=2.0,
    )
    weight.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    weight.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    footer = label(
        "峰日按上证指数事后标注。仓位为 ETF 市值占账户净值的比例。"
        "净值已扣回放佣金，按开盘价成交、零滑点。",
        "Peaks are retrospective SSE Composite labels. Weights use closing ETF value. "
        "NAV includes simulated commission, with fills at the open and zero slippage.",
    )
    fig.text(0.083, 0.027, footer, fontsize=8.6, color=muted)
    fig.savefig(report / "positions.png", dpi=160, facecolor="white")
    plt.close(fig)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-dir", type=Path, default=REPORT)
    plot(parser.parse_args().report_dir)
