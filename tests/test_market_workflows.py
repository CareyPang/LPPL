from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def _workflow(name):
    return yaml.safe_load(
        (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
    )


def test_market_snapshot_dates_use_trading_date_helper():
    workflow = _workflow("market_daily.yml")
    runs = [
        step.get("run", "")
        for job in workflow["jobs"].values()
        for step in job.get("steps", [])
        if "snapshot_date=" in step.get("run", "")
    ]
    helper_runs = [
        run
        for run in runs
        if 'snapshot_date="$(python -m research.data.trading_date)"' in run
    ]

    assert len(helper_runs) == 3
    assert not any("TZ=Asia/Shanghai date +%F" in run for run in runs)
    assert any('snapshot_date="${{ steps.fetch.outputs.asof }}"' in run for run in runs)


def test_market_event_smoke_uses_trading_date_helper():
    workflow = _workflow("market_daily.yml")
    steps = [
        step
        for job in workflow["jobs"].values()
        for step in job.get("steps", [])
    ]

    assert any(
        step.get("name") == "Smoke event calendar"
        and 'research.data.events --date "$(python -m research.data.trading_date)"'
        in step.get("run", "")
        for step in steps
    )


def test_nt_etf_workflow_bootstraps_and_uses_trading_date():
    workflow = _workflow("nt_etf_daily.yml")
    steps = workflow["jobs"]["collect"]["steps"]
    previous = next(step for step in steps if step.get("id") == "previous")
    collect = next(step for step in steps if step.get("name") == "Collect snapshot (PR smoke does not publish)")
    gate = next(step for step in steps if step.get("name") == "Gate publish on a successful share source")

    assert "web/mock/data/nt_etf/nt_etf_latest.json" in previous["run"]
    assert 'snapshot_date="$(python -m research.data.trading_date)"' in collect["run"]
    assert '--previous "$PREVIOUS_PATH"' in collect["run"]
    assert '("sse_shares","szse_shares")' in gate["run"]
