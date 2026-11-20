"""Read sealed replay outputs and explain first-window failures without rescoring.

No optimizer, price download, relabeling, event rematching, or changed scores.
Later contract hits are oracle diagnostics against the SAME saved target_event_id.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import html
import json
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

VERSION = "top_time_first_window_attribution_v1"
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "docs/research/evidence/top-time-replay-20261106/v1"
PRIMARY_ORDER = (
    "NO_FIRST_CLAIM", "INTERVAL_BEFORE_PEAK", "INTERVAL_AFTER_PEAK",
    "INVALID_OR_NONFUTURE", "BEYOND_HORIZON", "WIDTH_EXCEEDED",
    "EVENT_LEAD_INSUFFICIENT", "WINDOW_LEAD_INSUFFICIENT", "OTHER_FAILURE",
)
LABELS = {
    "SUCCESS": "首窗联合合格", "NO_FIRST_CLAIM": "没有关联首条提醒",
    "INTERVAL_BEFORE_PEAK": "窗口完全偏早", "INTERVAL_AFTER_PEAK": "窗口完全偏晚",
    "INVALID_OR_NONFUTURE": "无效或非未来", "BEYOND_HORIZON": "超出期限",
    "WIDTH_EXCEEDED": "区间过宽", "EVENT_LEAD_INSUFFICIENT": "事件提前不足",
    "WINDOW_LEAD_INSUFFICIENT": "整窗提前不足", "OTHER_FAILURE": "其他失败",
}
INPUTS = ("manifest.json", "event_scores.csv", "hypothetical_forecasts.csv.gz",
          "evaluations.jsonl.gz", "daily_replay_ledger.csv.gz", "label_books.jsonl.gz",
          "input_map.json", "actual_published_forecasts.csv", "summary_pooled.csv")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_csv(path: Path):
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8", newline="") as stream:
        yield from csv.DictReader(stream)


def read_jsonl(path: Path):
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        for line in stream:
            yield json.loads(line)


def flag(value):
    if value is True or value == "True":
        return True
    if value is False or value == "False":
        return False
    raise ValueError(f"not an explicit boolean: {value!r}")


def classify(first, peak, *, maximum_width=10, minimum_lead=5, horizon=63):
    """Independent arithmetic flags; they overlap and do not alter saved scores."""
    if first is None:
        return {"interval_relation": "NO_FIRST_CLAIM", "flags": ["NO_FIRST_CLAIM"]}
    left, right = int(first["interval_start"]), int(first["interval_end"])
    action, cutoff = int(first["hypothetical_action_session"]), int(first["session"])
    width, lead = right-left+1, peak-action
    relation = "BEFORE" if right < peak else "AFTER" if left > peak else "CONTAINS"
    reasons = []
    if relation != "CONTAINS":
        reasons.append("INTERVAL_BEFORE_PEAK" if relation == "BEFORE" else "INTERVAL_AFTER_PEAK")
    if width < 1 or left < 0 or left <= action or left <= cutoff or action <= cutoff:
        reasons.append("INVALID_OR_NONFUTURE")
    if right > action+horizon:
        reasons.append("BEYOND_HORIZON")
    if width > maximum_width:
        reasons.append("WIDTH_EXCEEDED")
    if lead < minimum_lead:
        reasons.append("EVENT_LEAD_INSUFFICIENT")
    # Unlike the score reason list, expose this even when another failure exists.
    if left-action < minimum_lead:
        reasons.append("WINDOW_LEAD_INSUFFICIENT")
    return {"interval_relation": relation, "width": width, "event_lead": lead,
            "window_lead": left-action, "interval_end_offset_from_peak": right-peak,
            "interval_start_offset_from_peak": left-peak, "flags": reasons}


def primary_reason(strict_hit, reasons):
    if strict_hit:
        if reasons:
            raise AssertionError("saved successful first claim has independent failures")
        return "SUCCESS"
    return next((name for name in PRIMARY_ORDER if name in reasons), "OTHER_FAILURE")


def later_qualified(claims, *, event_id, first):
    """Independent contract diagnostic, original target and time, never a new TP."""
    rows = [c for c in claims if c.get("target_event_id") == event_id
            and c.get("scope") == "stage" and c.get("diagnostic_contract_hit")
            and (first is None or (c["published_session"], c["prediction_id"])
                 > (first["published_session"], first["prediction_id"]))]
    return sorted(rows, key=lambda c: (c["published_session"], c["prediction_id"]))


def contract_qualified(claim, forecast):
    """Reconstruct geometry, not deleted raw_strict_hit or official event score.

    The evaluator removes its internal raw score before saving. Ignore ONLY
    duplicate_event_claim; keep the saved event assignment and all other gates.
    """
    return bool(claim.get("scope") == "stage" and claim.get("status") == "event"
                and not claim.get("pending") and not claim.get("boundary_excluded")
                and claim.get("target_session") is not None and claim.get("target_event_id")
                and claim.get("action_session") == int(forecast["hypothetical_action_session"])
                and claim.get("published_session") == int(forecast["session"])
                and "late_publication" not in claim.get("strict_evidence_failures", [])
                and not (set(claim["failure_reasons"]) - {"duplicate_event_claim"})
                and not classify(forecast, claim["target_session"])["flags"])


def dump_csv(path, rows):
    if not rows:
        raise ValueError(f"refuse empty schema-less CSV: {path}")
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: json.dumps(value, ensure_ascii=False, separators=(",", ":"))
                             if isinstance(value, (list, dict)) else value for key, value in row.items()})


def make_html(rows, arms):
    def esc(value):
        return html.escape(str(value), quote=True)

    def option(values):
        return "".join(f'<option value="{esc(v)}">{esc(v)}</option>' for v in values)
    markup = []
    for r in rows:
        symbols = "；".join(LABELS[f] for f in r["all_failure_flags"]) or "无"
        first = (f'{esc(r["first_published_date"])}<br>{esc(r["interval_start_date"])} → {esc(r["interval_end_date"])}'
                 if r["first_prediction_id"] else "—")
        detail = esc(r["first_prediction_id"] or "无关联首条")
        detail += "<br>来源："+esc(r["source_id"])+"<br>后续合格ID："+esc("；".join(r["later_qualified_ids"]) or "无")
        markup.append(f'<tr data-symbol="{esc(r["symbol"])}" data-arm="{esc(r["arm"])}" '
                      f'data-reason="{esc(r["primary_reason"])}" data-event="{esc(r["event_id"])}">'
                      f'<td>{esc(r["symbol"])}<br><b>{esc(r["peak_date"])}</b></td>'
                      f'<td>{esc(r["arm"])}</td><td>{"合格" if r["strict_hit"] else "漏报"}</td>'
                      f'<td>{esc(LABELS[r["primary_reason"]])}</td><td>{first}</td>'
                      f'<td>{esc(r["event_lead"])} / {esc(r["window_lead"])} / {esc(r["width"])}</td>'
                      f'<td>{esc(symbols)}</td><td>{r["later_qualified_count"]}<br>{esc(r["first_claim_cost_status"])}</td>'
                      f'<td>扫描 {r["opportunity_scheduled"]}<br>输出 {r["opportunity_forecasts"]}<br>'
                      f'无信号 {r["opportunity_no_signal"]}<br>输入不可用 {r["opportunity_unavailable"]}</td>'
                      f'<td><details><summary>来源与诊断</summary>{detail}<br>{esc(r["no_first_claim_detail"])}</details></td></tr>')
    return '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>91阶段顶 · 首窗逐项诊断</title><style>
body{font:14px/1.7 system-ui,"Microsoft YaHei",sans-serif;margin:24px;color:#17283a;background:#f4f6f8}h1{font-size:27px}
.notice{max-width:1100px;padding:16px;background:#fff3d6;border-left:4px solid #a77821}label{display:inline-block;margin:12px 18px 12px 0}
select,input{font:inherit;padding:8px;max-width:100%}.table-wrap{overflow:auto;background:white;max-height:75vh}table{border-collapse:collapse;min-width:1480px;width:100%}
th{position:sticky;top:0;background:#18334c;color:white;z-index:1;text-align:left}th,td{padding:9px 12px;border-bottom:1px solid #d9e0e6;vertical-align:top}
details{max-width:270px;overflow-wrap:anywhere}summary{cursor:pointer}tr[hidden]{display:none}a{color:#1c567f}small{color:#526578}
</style><h1>91 个已知阶段顶：首窗逐项诊断</h1>
<p class="notice"><b>历史重放 · 条件性诊断 · 不是提前发布成绩。</b>91事件×10策略=910行；另有3个未知阶段锚点不冒充已知事件。保留原评分，后续合格窗口只作事后oracle诊断，不修复首条成绩。数字均为观测日索引，未证明完整交易所日历或严格PIT。主原因按预定展示顺序选择，重叠原因另列，不表示因果优先级。</p>
<p><a href="first_window_attribution.csv">完整910行CSV</a> · <a href="event_index.csv">91事件索引</a> · <a href="summary_by_arm.csv">策略汇总</a> · <a href="manifest.json">输入/输出指纹</a></p>
<label>标的 <select id="symbol"><option value="">全部</option>''' + option(sorted({r["symbol"] for r in rows})) + '''</select></label>
<label>策略 <select id="arm"><option value="">全部</option>''' + option(arms) + '''</select></label>
<label>主原因 <select id="reason"><option value="">全部</option>''' + "".join(f'<option value="{esc(k)}">{esc(v)}</option>' for k,v in LABELS.items()) + '''</select></label>
<label>峰日/事件 <input id="search" type="search" placeholder="例如 2015-06"></label><p id="count" aria-live="polite"></p>
<small>提前/整窗/宽度 = 峰日−行动日 / 区间最早日−行动日 / 含端点宽度。无首条时留空。机会统计采用峰前可行动H=63范围，包含提前不足的候选；5日提前资格另在CSV列出。</small>
<div class="table-wrap"><table><thead><tr><th>标的 / 峰日</th><th>策略</th><th>原成绩</th><th>主原因</th><th>首条日期 / 区间</th><th>提前/整窗/宽度</th><th>全部重叠原因</th><th>后续合格（oracle）</th><th>峰前机会</th><th>追溯</th></tr></thead><tbody>''' + "".join(markup) + '''</tbody></table></div>
<script>
const rows=[...document.querySelectorAll('tbody tr')],controls=['symbol','arm','reason','search'].map(id=>document.getElementById(id));
function filter(){const [symbol,arm,reason,query]=controls.map(el=>el.value);let n=0;const events=new Set();
 for(const row of rows){const ok=(!symbol||row.dataset.symbol===symbol)&&(!arm||row.dataset.arm===arm)&&(!reason||row.dataset.reason===reason)&&(!query||row.dataset.event.includes(query));row.hidden=!ok;if(ok){n++;events.add(row.dataset.event);}}
 document.getElementById('count').textContent=`当前 ${n} 行，${events.size} 个事件。`;}
controls.forEach(el=>el.addEventListener('input',filter));filter();
</script></html>'''


def run(source: Path, output: Path):
    started = perf_counter()
    if output.exists():
        raise FileExistsError("use a new directory; existing evidence is immutable")
    before = {name: sha(source/name) for name in INPUTS}
    original = json.loads((source/"manifest.json").read_text(encoding="utf-8"))
    for name, data in original["outputs"].items():
        if sha(source/name) != data["sha256"]:
            raise ValueError(f"sealed replay output changed: {name}")
    config = original["source_parameters"]
    assert (config["horizon"], config["minimum_lead"], config["maximum_width"]) == (63, 5, 10)
    arms = original["arms"]
    saved_events = [r for r in read_csv(source/"event_scores.csv") if r["scope_probe"] == "stage"]
    forecasts = {r["new_forecast_id"]: r for r in read_csv(source/"hypothetical_forecasts.csv.gz") if r["scope_probe"] == "stage"}
    evaluations = {(e["symbol"], e["arm"]): e for e in read_jsonl(source/"evaluations.jsonl.gz") if e["scope_probe"] == "stage"}
    daily = defaultdict(dict)
    for r in read_csv(source/"daily_replay_ledger.csv.gz"):
        if r["scope_probe"] == "stage":
            daily[(r["symbol"], r["arm"])][int(r["session"])] = r
    source_ids = {r["symbol"]:r["source_id"] for r in json.loads((source/"input_map.json").read_text(encoding="utf-8"))["sources"]}
    rows, unknown, transitions = [], [], []
    for book in read_jsonl(source/"label_books.jsonl.gz"):
        meta = evaluations[(book["symbol"], arms[0])]["metadata"]
        for pos in range(meta["start_session"], meta["end_session"]+1):
            if not book["known"]["stage"][pos]:
                unknown.append({"symbol":book["symbol"],"session":pos,"date":book["sessions"][pos],"status":"UNKNOWN_STAGE_ANCHOR_NOT_IN_91"})
    event_sets = []
    for arm in arms:
        event_sets.append({r["event_id"] for r in saved_events if r["arm"] == arm})
    assert len(event_sets[0]) == 91 and all(s == event_sets[0] for s in event_sets)
    assert len(saved_events) == 910 and len(unknown) == 3
    for saved in saved_events:
        key = saved["symbol"], saved["arm"]
        evaluation = evaluations[key]
        event_id, peak = saved["event_id"], int(saved["peak_session"])
        original_event = next(e for e in evaluation["events"] if e["event_id"] == event_id)
        first_id = saved["first_prediction_id"]
        assert (original_event["first_prediction_id"] or "") == first_id
        assert original_event["strict_hit"] == flag(saved["strict_hit"])
        assert original_event["failure_reasons"] == json.loads(saved["failure_reasons"])
        claims = [{**c,"diagnostic_contract_hit":contract_qualified(c,forecasts[c["prediction_id"]])}
                  for c in evaluation["claims"]]
        episode_first = {c["episode_id"]:c for c in claims if c["is_first"]}
        for c in claims:
            if c["is_first"] and not c["duplicate_event"]:
                assert c["strict_hit"] == c["diagnostic_contract_hit"]
            if c["is_revision"] and c["target_event_id"] == episode_first[c["episode_id"]]["target_event_id"]:
                assert c["revision_hit"] == c["diagnostic_contract_hit"]
        first = next((c for c in claims if c["prediction_id"] == first_id), None)
        first_forecast = forecasts.get(first_id)
        flags = classify(first_forecast, peak)
        if first:
            assert first["target_event_id"] == event_id and first["is_first"]
            assert first["strict_hit"] == flag(saved["strict_hit"])
            assert first["lead"] == flags["event_lead"] and first["width"] == flags["width"]
        hit = flag(saved["strict_hit"])
        primary = primary_reason(hit, flags["flags"])
        targeted = [c for c in claims if c.get("target_event_id") == event_id and c["scope"] == "stage"]
        qualified = [c for c in targeted if c["diagnostic_contract_hit"]]
        later = later_qualified(claims, event_id=event_id, first=first)
        prior = [c for c in qualified if first is not None and
                 (c["published_session"],c["prediction_id"]) < (first["published_session"],first["prediction_id"])]
        for c in prior if first is not None else targeted:
            initial = episode_first[c["episode_id"]]
            cf, initial_forecast = forecasts[c["prediction_id"]], forecasts[initial["prediction_id"]]
            transitions.append({"symbol":key[0],"arm":key[1],"event_id":event_id,"peak_date":saved["peak_date"],
                                "kind":"QUALIFIED_REVISION_BEFORE_EVENT_FIRST" if first else "REVISION_WITHOUT_EVENT_FIRST",
                                "official_first_prediction_id":first_id,"official_first_date":first_forecast["date"] if first_forecast else "",
                                "episode_id":c["episode_id"],"episode_first_prediction_id":initial["prediction_id"],
                                "episode_first_date":initial_forecast["date"],"episode_first_target":initial["target_event_id"] or "",
                                "episode_first_status":initial["status"],"revision_prediction_id":c["prediction_id"],
                                "revision_date":cf["date"],"revision_target":c["target_event_id"],
                                "revision_is_revision":c["is_revision"],"revision_contract_qualified":c["diagnostic_contract_hit"],
                                "revision_interval_start":cf["interval_start_date"],"revision_interval_end":cf["interval_end_date"],
                                "revision_action_lead":c["lead"],"target_changed_from_episode_first":initial["target_event_id"] != c["target_event_id"]})
        # Next-session action: cutoff in [peak-H-1, peak-2]. Do not use the
        # earlier replay's fixed common-subset lookback as exact opportunities.
        opportunity_start, opportunity_end = peak-64, peak-2
        opportunities = [daily[key].get(i) for i in range(opportunity_start, opportunity_end+1)]
        present = [r for r in opportunities if r is not None]
        counts = Counter(r["status"] for r in present)
        issued = [r for r in present if r["status"] == "HYPOTHETICAL_INTERVAL"]
        absent = len(opportunities)-len(present)
        eligible = [r for r in present if int(r["session"]) <= peak-6]
        if first:
            no_first_detail = "HAS_ORIGINAL_EVENT_FIRST"
        elif not issued:
            no_first_detail = "NO_OUTPUT_IN_ACTIONABLE_HORIZON" if not absent else "NO_OUTPUT_WITH_LEDGER_GAPS"
        elif targeted:
            no_first_detail = "ONLY_REVISIONS_TARGET_EVENT_NO_EPISODE_FIRST"
        else:
            no_first_detail = "OUTPUTS_EXIST_BUT_TARGET_OTHER_EVENT_OR_UNKNOWN"
        cost = ("FIRST_SUCCEEDED" if hit else "NO_EVENT_FIRST_BUT_DIAGNOSTIC_QUALIFIED_EXISTS" if first is None and qualified
                else "LATER_QUALIFIED_FIRST_FAILED" if first and later
                else "DIAGNOSTIC_QUALIFIED_BEFORE_EVENT_FIRST" if prior else "NO_DIAGNOSTIC_QUALIFIED_SAME_TARGET")
        ff = first_forecast or {}
        row = {"symbol":key[0],"arm":key[1],"event_id":event_id,"peak_date":saved["peak_date"],"peak_session":peak,
               "evidence_status":"CONDITIONAL_REPLAY_DIAGNOSTIC_NOT_PROSPECTIVE","source_manifest_sha256":before["manifest.json"],
               "source_id":source_ids[key[0]],"protocol_sha256":original["protocol_sha256"],
               "strict_hit":hit,"first_prediction_id":first_id,"first_episode_id":ff.get("episode_id", ""),
               "first_published_date":ff.get("date", ""),"first_action_date":ff.get("hypothetical_action_date", ""),
               "first_cutoff_session":ff.get("session", ""),"first_action_session":ff.get("hypothetical_action_session", ""),
               "interval_start_date":ff.get("interval_start_date", ""),"interval_end_date":ff.get("interval_end_date", ""),
               "interval_start_session":ff.get("interval_start", ""),"interval_end_session":ff.get("interval_end", ""),
               "interval_relation":flags["interval_relation"],"width":flags.get("width", ""),
               "event_lead":flags.get("event_lead", ""),"window_lead":flags.get("window_lead", ""),
               "interval_start_offset_from_peak":flags.get("interval_start_offset_from_peak", ""),
               "interval_end_offset_from_peak":flags.get("interval_end_offset_from_peak", ""),
               "primary_reason":primary,"all_failure_flags":flags["flags"],"saved_failure_reasons":json.loads(saved["failure_reasons"]),
               "common_eligible":flag(saved["common_eligible"]),"targeted_claim_count":len(targeted),
               "diagnostic_qualified_same_target_count":len(qualified),"later_qualified_count":len(later),
               "prior_qualified_count":len(prior),"prior_qualified_ids":[c["prediction_id"] for c in prior],
               "later_qualified_ids":[c["prediction_id"] for c in later],
               "later_same_episode_count":sum(first is not None and c["episode_id"] == first["episode_id"] for c in later),
               "later_other_episode_count":sum(first is not None and c["episode_id"] != first["episode_id"] for c in later),
               "first_later_qualified_date":forecasts[later[0]["prediction_id"]]["date"] if later else "",
               "first_later_qualified_lead":later[0]["lead"] if later else "",
               "first_claim_cost_status":cost,"no_first_claim_detail":no_first_detail,
               "opportunity_cutoff_start":opportunity_start,"opportunity_cutoff_end":opportunity_end,
               "opportunity_ledger_days":len(present),"opportunity_ledger_absent":absent,
               "opportunity_scheduled":sum(flag(r["scheduled"]) for r in present),
               "opportunity_forecasts":len(issued),"opportunity_no_signal":counts["NO_SIGNAL"],
               "opportunity_unavailable":counts["INPUT_UNAVAILABLE"]+counts["NO_CACHED_FIT"],
               "opportunity_not_scheduled":counts["NOT_SCHEDULED"],
               "minimum_lead_opportunity_forecasts":sum(r["status"] == "HYPOTHETICAL_INTERVAL" for r in eligible),
               "first_window_before_peak_with_later_qualified":bool(first and later and flags["interval_relation"] == "BEFORE"),
               "original_published_at":"","hypothetical_published_at":ff.get("hypothetical_published_at", "")}
        assert sum((row["opportunity_forecasts"],row["opportunity_no_signal"],row["opportunity_unavailable"],row["opportunity_not_scheduled"])) == len(present)
        rows.append(row)
    rows.sort(key=lambda r:(r["symbol"],r["peak_date"],arms.index(r["arm"])))
    summary = []
    for arm in arms:
        group = [r for r in rows if r["arm"] == arm]
        pc = Counter(r["primary_reason"] for r in group)
        overlap = Counter(f for r in group for f in r["all_failure_flags"])
        summary.append({"arm":arm,"events":len(group),"TP":sum(r["strict_hit"] for r in group),
                        "FN":sum(not r["strict_hit"] for r in group),"primary_counts":dict(pc),"overlap_counts":dict(overlap),
                        "no_first":pc["NO_FIRST_CLAIM"],"before_peak":overlap["INTERVAL_BEFORE_PEAK"],"after_peak":overlap["INTERVAL_AFTER_PEAK"],
                        "later_qualified_after_failed_first":sum(r["first_claim_cost_status"] == "LATER_QUALIFIED_FIRST_FAILED" for r in group),
                        "no_first_but_diagnostic_qualified":sum(r["first_claim_cost_status"] == "NO_EVENT_FIRST_BUT_DIAGNOSTIC_QUALIFIED_EXISTS" for r in group),
                        "diagnostic_qualified_before_event_first":sum(r["prior_qualified_count"] > 0 for r in group),
                        "any_diagnostic_qualified_same_target":sum(r["diagnostic_qualified_same_target_count"] > 0 for r in group),
                        "no_diagnostic_qualified_same_target":sum(r["diagnostic_qualified_same_target_count"] == 0 for r in group),
                        "no_outputs_in_opportunity":sum(r["opportunity_forecasts"] == 0 for r in group),
                        "no_first_with_outputs":sum(not r["first_prediction_id"] and r["opportunity_forecasts"] > 0 for r in group),
                        "early_first_with_later_qualified":sum(r["first_window_before_peak_with_later_qualified"] for r in group)})
    old_summary = {r["arm"]:r for r in read_csv(source/"summary_pooled.csv") if r["scope_probe"] == "stage"}
    for r in summary:
        assert r["TP"] == int(old_summary[r["arm"]]["TP"]) and r["FN"] == int(old_summary[r["arm"]]["FN"])
    index = []
    for event_id in sorted(event_sets[0]):
        group = [r for r in rows if r["event_id"] == event_id]
        item = {"symbol":group[0]["symbol"],"peak_date":group[0]["peak_date"],"event_id":event_id}
        item.update({r["arm"]:r["primary_reason"] for r in group})
        index.append(item)
    output.mkdir(parents=True)
    dump_csv(output/"first_window_attribution.csv", rows)
    dump_csv(output/"event_index.csv", index)
    dump_csv(output/"summary_by_arm.csv", summary)
    dump_csv(output/"unknown_stage_anchors.csv", unknown)
    dump_csv(output/"episode_transition_diagnostics.csv", transitions)
    (output/"cases.html").write_text(make_html(rows,arms),encoding="utf-8",newline="\n")
    (output/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8",newline="\n")
    after = {name:sha(source/name) for name in INPUTS}
    assert before == after
    manifest = {"version":VERSION,"generated_at":datetime.now(UTC).isoformat(),"source_directory":str(source.relative_to(ROOT)),
                "source_before_sha256":before,"source_after_sha256":after,"source_unchanged":True,
                "generator_sha256":sha(Path(__file__)),"evidence_status":"CONDITIONAL_DIAGNOSTIC_NOT_PROSPECTIVE",
                "first_score_recomputed":False,"model_fit_calls":0,"network_fetches":0,"event_rows":len(rows),"unique_events":len(index),
                "unknown_stage_anchors":len(unknown),"primary_reason_priority":PRIMARY_ORDER,
                "primary_reason_meaning":"DISPLAY_PRIORITY_NOT_CAUSAL_PRIORITY; all independent flags preserved",
                "later_oracle":"Reconstructed single-claim geometry and saved failures excluding ONLY duplicate_event_claim, SAME original target_event_id/status, late publication excluded; actionability remains theoretical. raw_strict_hit is removed by evaluator and NOT present in sealed outputs; never replace saved score",
                "opportunity_cutoffs":"[peak-64, peak-2] for next-session action within 1..63; >=5 lead narrows end to peak-6",
                "input_scope":"saved six-index development replay, observed sessions, current frozen qfq, not PIT or real publication",
                "elapsed_seconds":perf_counter()-started,
                "outputs":{p.name:{"sha256":sha(p),"bytes":p.stat().st_size} for p in sorted(output.iterdir()) if p.is_file()}}
    (output/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8",newline="\n")
    print(json.dumps({"events":len(index),"rows":len(rows),"unknown":len(unknown),"output":str(output),"elapsed_seconds":manifest["elapsed_seconds"]}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source",type=Path,default=DEFAULT_SOURCE)
    parser.add_argument("--out",type=Path,required=True)
    args = parser.parse_args()
    run(args.source.resolve(),args.out.resolve())
