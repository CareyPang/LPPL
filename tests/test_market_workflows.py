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


def test_market_build_loads_previous_stock_results_snapshots():
    workflow = _workflow("market_daily.yml")
    fetch = next(
        step for step in workflow["jobs"]["collect"]["steps"] if step.get("id") == "fetch"
    )

    assert "git archive origin/stock-results market" in fetch["run"]
    assert "--prev-dir out/previous-market" in fetch["run"]


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


def test_dip_env_workflow_publishes_when_options_archive_is_skipped():
    workflow = _workflow("dip_env.yml")
    publish = next(
        step
        for step in workflow["jobs"]["collect"]["steps"]
        if step.get("name") == "Publish to stock-results"
    )
    run = publish["run"]
    archive = 'out/stock/dip_env/options/${snapshot_date}.json'

    assert f'if [[ -f "{archive}" ]]; then' in run
    assert f'cp "{archive}"' in run
    assert 'git add "stock/dip_env/options/${snapshot_date}.json"' in run
    assert 'echo "options archive skipped (intraday)"' in run
    assert "git add stock/_dip_env.json" in run


def test_index_daily_workflow_parses_and_guards_publish_from_pull_requests():
    workflow = _workflow("index_daily.yml")
    triggers = workflow.get("on", workflow.get(True, {}))
    run_index = next(
        step
        for step in workflow["jobs"]["update"]["steps"]
        if step.get("name") == "Run latest closed-day index fits"
    )
    publish = next(
        step
        for step in workflow["jobs"]["update"]["steps"]
        if step.get("name") == "Publish to stock-results"
    )

    assert triggers["schedule"] == [{"cron": "0 10 * * 1-5"}]
    assert triggers["workflow_dispatch"] is None
    assert 'symbols=(sh000001 sh000016 sh000300 sh000905 sh000688 sz399001 sz399006)' in run_index["run"]
    assert 'symbols=(sh000001)' in run_index["run"]
    assert publish["if"] == (
        "github.event_name != 'pull_request' && steps.run.outputs.success_count != '0'"
    )
    publish_lines = [line.strip() for line in publish["run"].splitlines()]
    rebase_line = publish_lines.index("rebase origin/stock-results")
    assert publish_lines[rebase_line - 2 : rebase_line + 1] == [
        'git -c user.name="github-actions[bot]" \\',
        '-c user.email="41898282+github-actions[bot]@users.noreply.github.com" \\',
        "rebase origin/stock-results",
    ]
