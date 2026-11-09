import json
from argparse import Namespace

import pytest

from scripts import update_market_context as runner


def _payload(asof):
    return {
        "asof": asof,
        "generated_at": f"{asof}T23:00:00+00:00",
        "sources": {"market": {"url_host": "example.test", "fetched_at": f"{asof}T23:00:00+00:00", "ok": True, "raw_sha256": "b" * 64}},
        "board_flow": {},
        "limit_pools": {"zt": 1, "zb": 0, "dt": 0, "pool_rows": {"zt": [{"code": "000001", "name": "示例", "streak": 2, "limit_time": "09:25:00"}], "zb": [], "dt": []}},
        "northbound": {},
        "valuation": {},
        "margin": {},
    }


def test_runner_seals_dated_context_and_manifest_without_frontend_write(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "fetch_market", lambda asof: _payload(asof))
    monkeypatch.setattr(
        runner,
        "fetch_ths_reasons_topics",
        lambda asof: (
            {"status": "fresh", "rows": [{"code": "000001", "name": "示例", "reason": "算力"}], "stale_reason": None},
            {"status": "fresh", "rows": [{"code": "000001", "name": "示例", "topic_label": "算力"}], "stale_reason": None},
            {"source_id": "ths_limit_up_pool", "source_url": "https://data.10jqka.com.cn/dataapi/limit_up/limit_up_pool", "status": "fresh", "ok": True, "raw_sha256": "c" * 64, "fetched_at": f"{asof}T23:00:00+00:00"},
        ),
    )
    monkeypatch.setattr(
        runner,
        "fetch_yesterday_pool",
        lambda asof: {"status": "fresh", "asof": asof, "rows": [], "source": {"source_id": "eastmoney_yesterday_zt_pool", "source_url": "https://push2ex.eastmoney.com/getYesterdayZTPool", "status": "fresh", "ok": True, "raw_sha256": "d" * 64}},
    )
    result = runner.run(Namespace(asof="2026-11-03", prior_asof=None, trading_calendar=None, out=str(tmp_path), source_url=None, requested_at=None, run_mode="live"))
    assert result["real_snapshot_count"] == 1
    context = json.loads((tmp_path / "market_context_2026-11-03.json").read_text(encoding="utf-8"))
    assert context["run_mode"] == "live"
    assert context["limit_pools"]["topics"]["rows"][0]["topic_label"] == "算力"
    assert (tmp_path / "market_2026-11-03.json").exists()
    manifest = json.loads((tmp_path / "market_context_manifest.json").read_text(encoding="utf-8"))
    assert manifest["real_snapshot_count"] == 1


def test_runner_resolves_prior_session_and_keeps_append_only_dates(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "fetch_market", lambda asof: _payload(asof))
    monkeypatch.setattr(
        runner,
        "fetch_ths_reasons_topics",
        lambda asof: (
            {"status": "fresh", "rows": [], "stale_reason": None},
            {"status": "fresh", "rows": [], "stale_reason": None},
            {"source_id": "ths", "source_url": "https://example.test/ths", "status": "fresh", "ok": True, "raw_sha256": "c" * 64, "fetched_at": f"{asof}T23:00:00+00:00"},
        ),
    )
    monkeypatch.setattr(
        runner,
        "fetch_yesterday_pool",
        lambda asof: {"status": "fresh", "asof": asof, "rows": [], "source": {"source_id": "eastmoney", "source_url": "https://example.test/em", "status": "fresh", "ok": True, "raw_sha256": "d" * 64}},
    )
    calendar = tmp_path / "calendar.json"
    calendar.write_text(json.dumps({"version": "test-v1", "dates": ["2026-11-05", "2026-11-06"]}), encoding="utf-8")
    common = dict(prior_asof=None, trading_calendar=str(calendar), today="2026-11-06", out=str(tmp_path), source_url=None, requested_at=None, run_mode="live")
    first = runner.run(Namespace(asof="2026-11-05", **common))
    second = runner.run(Namespace(asof=None, **common))
    assert first["prior_asof"] is None
    assert second["asof"] == "2026-11-06"
    assert second["prior_asof"] == "2026-11-05"
    assert second["calendar_status"] == "provided"
    manifest = json.loads((tmp_path / "market_context_manifest.json").read_text(encoding="utf-8"))
    assert [entry["asof"] for entry in manifest["snapshots"]] == ["2026-11-05", "2026-11-06"]
    assert manifest["snapshots"][1]["prior_asof"] == "2026-11-05"
    assert json.loads((tmp_path / "market_context_2026-11-05.json").read_text(encoding="utf-8"))["asof"] == "2026-11-05"


def test_runner_rejects_conflicting_rewrite_of_dated_snapshot(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "fetch_market", lambda asof: _payload(asof))
    monkeypatch.setattr(runner, "fetch_ths_reasons_topics", lambda asof: ({"status": "fresh", "rows": [], "stale_reason": None}, {"status": "fresh", "rows": [], "stale_reason": None}, {"source_id": "ths", "status": "fresh", "ok": True, "raw_sha256": "c" * 64}))
    monkeypatch.setattr(runner, "fetch_yesterday_pool", lambda asof: {"status": "fresh", "asof": asof, "rows": [], "source": {"source_id": "em", "status": "fresh", "ok": True, "raw_sha256": "d" * 64}})
    args = Namespace(asof="2026-11-05", prior_asof=None, trading_calendar=None, today=None, out=str(tmp_path), source_url=None, requested_at=None, run_mode="live")
    runner.run(args)
    original = json.loads((tmp_path / "market_2026-11-05.json").read_text(encoding="utf-8"))
    original["limit_pools"]["zt"] = 999
    (tmp_path / "market_2026-11-05.json").write_text(json.dumps(original), encoding="utf-8")
    with pytest.raises(ValueError, match="immutable"):
        runner.run(args)
