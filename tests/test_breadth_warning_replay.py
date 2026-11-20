import datetime as dt

from research.eval import breadth_warning_replay as replay


def test_panel_score_counts_first_watch_and_keeps_later_updates_in_the_audit(monkeypatch):
    rows = []
    ledger = []
    for i in range(95):
        day = (dt.date(2025, 1, 1) + dt.timedelta(days=i)).isoformat()
        rows.append({"date": day, "label_close": 100 + i, "P60": 0.5})
        ledger.append({"asof": day, "state": "quiet", "alerts": [],
                       "phase": {"id": "sustained_decline", "maturity": "middle_late"}})
    first = rows[65]["date"]
    watch = {"id": "rebound:episode", "trigger_date": first, "kind": "rebound",
             "title": "短线可能反弹", "message": "观察上涨家数", "reasons": ["上涨家数回升"],
             "next_check": "留意后续收盘", "level": "watch", "update_date": first}
    ledger[65]["alerts"] = [watch]
    ledger[66]["alerts"] = [watch]  # unchanged card
    ledger[67]["alerts"] = [{**watch, "level": "strengthening", "update_date": rows[67]["date"]}]
    ledger[68]["alerts"] = [{**watch, "level": "invalidated", "update_date": rows[68]["date"]}]
    monkeypatch.setattr(replay, "build_trend_ledger", lambda _, *, evidence: ledger)
    summary, changes, outcomes = replay.replay(rows)
    assert summary["tasks"]["rebound"]["first_watches"] == 1
    assert [item["level"] for item in changes] == ["watch", "strengthening", "invalidated"]
    assert len([item for item in outcomes if item["task"] == "rebound"]) == 1
    assert summary["first_publication_at"] is None
