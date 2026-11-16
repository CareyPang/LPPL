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
    plan = workflow["jobs"]["plan"]
    fit = workflow["jobs"]["fit"]
    publish_job = workflow["jobs"]["publish"]
    plan_step = next(
        step
        for step in plan["steps"]
        if step.get("name") == "Plan latest closed-day index fits"
    )
    run_index = next(
        step
        for step in fit["steps"]
        if step.get("name") == "Run latest closed-day index fit"
    )
    publish = next(
        step
        for step in publish_job["steps"]
        if step.get("name") == "Publish to stock-results"
    )
    upload = next(
        step
        for step in fit["steps"]
        if step.get("name") == "Upload index fit artifact"
    )
    download = next(
        step
        for step in publish_job["steps"]
        if step.get("name") == "Download index fit artifacts"
    )

    assert triggers["schedule"] == [{"cron": "0 10 * * 1-5"}]
    assert triggers["workflow_dispatch"] is None
    assert 'asof="$(python -c \'from research.data.trading_date import latest_closed_trading_day; print(latest_closed_trading_day())\')"' in plan_step["run"]
    assert 'symbols=\'["sh000001","sh000016","sh000300","sh000905","sh000688","sz399001","sz399006"]\'' in plan_step["run"]
    assert 'symbols=\'["sh000001"]\'' in plan_step["run"]
    assert fit["needs"] == "plan"
    assert fit["timeout-minutes"] == 75
    assert fit["strategy"]["fail-fast"] is False
    assert fit["strategy"]["max-parallel"] == 7
    assert 'LPPLS_BOX=v2 python -m research.pipeline.daily "$SYM"' in run_index["run"]
    assert '--asof "$ASOF" --out out/index' in run_index["run"]
    assert upload["with"]["name"] == (
        "index-fit-${{ matrix.sym }}-${{ github.run_id }}-${{ github.run_attempt }}"
    )
    assert upload["with"]["if-no-files-found"] == "warn"
    assert publish_job["needs"] == ["plan", "fit"]
    assert publish_job["if"] == (
        "${{ !cancelled() && github.event_name != 'pull_request' }}"
    )
    assert download["with"]["pattern"] == (
        "index-fit-*-${{ github.run_id }}-*"
    )
    assert "merge-multiple" not in download["with"]
    assert download["with"]["path"] == "out/artifacts"
    assert 'dir="$(ls -d "out/artifacts/index-fit-${sym}-${GITHUB_RUN_ID}-"*' in publish["run"]
    assert 'source="$dir/${sym}_${ASOF}.json"' in publish["run"]
    assert "Missing symbols:" in publish["run"]
    assert 'if (( ${#published[@]} == 0 )); then' in publish["run"]
    publish_lines = [line.strip() for line in publish["run"].splitlines()]
    rebase_line = publish_lines.index("rebase origin/stock-results")
    assert publish_lines[rebase_line - 2 : rebase_line + 1] == [
        'git -c user.name="github-actions[bot]" \\',
        '-c user.email="41898282+github-actions[bot]@users.noreply.github.com" \\',
        "rebase origin/stock-results",
    ]


def test_index_replay_workflow_accepts_dispatch_and_publishes_under_index_replay():
    workflow = _workflow("index_replay.yml")
    triggers = workflow.get("on", workflow.get(True, {}))
    steps = {step.get("name"): step for step in workflow["jobs"]["replay"]["steps"] if step.get("name")}

    assert triggers["repository_dispatch"] == {"types": ["index_replay"]}
    assert workflow["run-name"].startswith("index_replay ${{ github.event.client_payload.sym || inputs.sym")
    assert set(triggers["workflow_dispatch"]["inputs"]) == {"sym", "asof", "job_id"}
    assert workflow["permissions"] == {"contents": "write"}
    assert "index-replay-" in workflow["concurrency"]["group"]
    assert workflow["concurrency"]["cancel-in-progress"] is False

    validate = steps["Validate request"]["run"]
    for sym in ("sh000001", "sh000016", "sh000300", "sh000905", "sh000688", "sz399001", "sz399006"):
        assert sym in validate
    assert "asof must be YYYY-MM-DD" in validate

    run = steps["Run as-of index fit"]
    assert run["if"] == "github.event_name != 'pull_request'"
    assert 'python -m research.pipeline.daily "$SYM" --asof "$ASOF" --out out/index' in run["run"]
    assert '"status": "failed"' in run["run"]
    assert 'permanent = "不是交易日" in msg' in run["run"]

    publish = steps["Publish to stock-results"]
    assert publish["if"] == "github.event_name != 'pull_request'"
    assert 'target="index/replay/${SYM}_${ASOF}.json"' in publish["run"]
    assert "git push origin HEAD:stock-results" in publish["run"]
