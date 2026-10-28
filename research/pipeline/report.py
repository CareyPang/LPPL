"""由契约 JSON 自动生成研究报告（原站 F12 "Reports" 的个人版）：只读 web/mock/data/*_latest.json 与 universe_latest.json，不做计算。

每份报告写明：数据版本与来源、模型版本与窗口、每个字段的证据等级（来自契约 evidence_levels / docs/evidence_table.md）、
三段验证结论原文。输出 reports/auto/<asof>.md。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

DATA = Path("web/mock/data")
OUT = Path("reports/auto")
SYMS = ["sh000001", "sh000016", "sh000300", "sh000905", "sz399001", "sz399006"]


def pct(x) -> str:
    return "—" if x is None else f"{x * 100:.0f}%"


def section(d: dict) -> list[str]:
    T, B, IND = d["top"], d["top"].get("bubble", {}), d["top"].get("indicators", {})
    ev = d.get("evidence_levels", {})
    lv = lambda k: "描述性" if k == "descriptive" else ev.get(k, k)  # noqa: E731
    md = [f"## {d['name']}（{d['symbol']}）· as-of {d['asof']}",
          f"- 数据：`{d['data_version']}` · 模型：`{d['model_version']}` · 信号状态：**{T.get('signal_status')}**",
          f"- 泡沫状态（{lv(B.get('evidence', 'descriptive'))}）：{B.get('signal_status')}；起点 {B.get('start')}，持续 {B.get('duration_days')} 日，"
          f"模型泡沫大小 {pct(B.get('size_model'))}，实际涨幅 {pct(B.get('size_realized'))}，最长合格尺度 {B.get('longest_qualified_scale') or '—'}",
          "", "| 尺度 | STANDARD | END | PURE | EARLY | box | 合格窗口 | 证据 |", "|---|---|---|---|---|---|---|---|"]
    se = T.get("lppls_confidence", {}).get("scale_evidence", {})
    for k, v in IND.items():
        if k == "rule_note" or not isinstance(v, dict):
            continue
        c = v.get("confidence") or {}
        md.append(f"| {k} | {pct(c.get('standard'))} | {pct(c.get('end'))} | {pct(c.get('pure'))} | {pct(c.get('early'))} | {pct(c.get('box'))} | {v.get('n_qualified_standard', '—')}/{v.get('n_windows', '—')} | {lv(se.get(k, 'none'))} |")
    tr = T.get("trust")
    if tr and tr.get("trust") is not None:
        md.append(f"\n- DS Trust（描述性）：{pct(tr['trust'])}（{tr['n_windows']} 窗 × {tr['n_boot']} 次 bootstrap）")
    cb = T.get("combo", {})
    md.append(f"- Combo（STANDARD，p=0.1/1/10，{lv(cb.get('evidence', 'none'))}）：{pct(cb.get('p0.1'))} / {pct(cb.get('p1'))} / {pct(cb.get('p10'))}")
    sc = T.get("scenarios", [])
    if sc:
        md.append("- t_c 情景（簇占比=Gerlach 2018 口径，非崩盘概率）：" + "；".join(
            f"情景{'ABCDEFGHI'[i]} 占比 {pct(s['share'])}，20–80 分位 {s['q20_date']}–{s['q80_date']}，代表 t_c {s['representative']['tc']}" for i, s in enumerate(sc)))
    else:
        md.append("- t_c 情景：无合格拟合，无情景")
    w = T.get("window", {})
    md.append(f"- 顶部区间（{lv(w.get('evidence', 'dev'))}）：{w.get('start') or '—'} – {w.get('end') or '—'}（{w.get('rule')}）")
    rb = d.get("regime_band", {})
    md.append(f"- 上月体制带（描述性）：{rb.get('month')} {rb.get('state') or '—'}")
    md.append(f"- p20 概率：不显示（{lv(T.get('p20', {}).get('evidence'))}）；底部概率：不显示（{lv(d.get('bottom', {}).get('state_p', {}).get('evidence'))}）")
    return md


def main(asof: str | None = None) -> Path:
    recs = [json.loads((DATA / f"{s}_latest.json").read_text()) for s in SYMS if (DATA / f"{s}_latest.json").exists()]
    asof = asof or max(r["asof"] for r in recs)
    md = [f"# 临界点 2.0 自动研究报告 · {asof}", "",
          "本报告由日更契约 JSON 自动生成，所有数字为描述性或规则输出；证据等级见各行。三段验证（开发 2000–2018 / 校准 2019–2021 / 最终测试 2022–2025.08）结论：",
          "LPPLS 置信度 = 开发段有信号、校准段脆弱、测试段未通过（`dev_only`）；p20 与底部概率链未通过、不显示（`docs/evidence_table.md`、`reports/final_test_2022_2025.md`）。",
          "2026 起的新证据只来自前瞻日志（`forward_log/`，季度复盘）。", ""]
    for r in recs:
        md += section(r) + [""]
    up = DATA / "universe_latest.json"
    if up.exists():
        u = json.loads(up.read_text())
        md += ["## 多资产扫描（描述性，非 PIT 成分，个股横截面排名无预测信息）", f"- as-of {u['asof']} · {u['n_assets']} 个标的 · 窗口 {u['windows'][0]}–{u['windows'][-1]} 日",
               "| 类型 | 已分析 | 失败 | 正泡沫信号 | 占比 |", "|---|---|---|---|---|"]
        tn = {"index": "宽基指数", "industry": "行业指数", "stock": "沪深300 成分股"}
        for k, v in u["summary"].items():
            md.append(f"| {tn[k]} | {v['analysed']} | {v['failed']} | {v['positive_signal']} | {pct(v['positive_share'])} |")
        sig = sorted([r for r in u["rows"] if r.get("signal_status") == "signal"], key=lambda r: -(r.get("combo_p01") or 0))[:20]
        if sig:
            md += ["", "有合格拟合的标的（按 Combo p=0.1，前 20）：", "| 标的 | 类型 | Combo 0.1 | 6–12 月 STD | 12–24 月 STD | 尺度 | 代表 t_c |", "|---|---|---|---|---|---|---|"]
            md += [f"| {r['name']} {r['symbol']} | {tn[r['type']]} | {pct(r.get('combo_p01'))} | {pct((r.get('conf') or {}).get('6-12m', {}).get('standard'))} | "
                   f"{pct((r.get('conf') or {}).get('12-24m', {}).get('standard'))} | {r.get('longest_qualified_scale') or '—'} | {r.get('tc_representative') or '—'} |" for r in sig]
        else:
            md.append("\n当前没有任何标的有合格拟合。")
    md += ["", "---", "来源：契约字段定义 `docs/product_contract.md`、公式核对 `docs/fco_indicator_audit.md`、用户指南 `docs/user_guide.md`。本报告不构成投资建议。"]
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / f"{asof}.md"
    p.write_text("\n".join(md))
    return p


if __name__ == "__main__":
    print(main(sys.argv[1] if len(sys.argv) > 1 else None))
