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


def test_market_daily_uses_off_hour_schedules():
    workflow = _workflow("market_daily.yml")
    triggers = workflow.get("on", workflow.get(True, {}))

    assert triggers["schedule"] == [
        {"cron": "45 7 * * 1-5"},
        {"cron": "30 8 * * 1-5"},
        {"cron": "0 11 * * 1-5"},
    ]


def test_daily_workflows_accept_worker_repository_dispatch():
    names = (
        "market_daily",
        "index_daily",
        "dip_env",
        "forward_log_seal",
        "nt_etf_daily",
        "macro_daily",
        "growth_daily",
        "us_nightly",
    )
    for name in names:
        workflow = _workflow(f"{name}.yml")
        triggers = workflow.get("on", workflow.get(True, {}))
        assert triggers["repository_dispatch"] == {"types": [name]}


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


def test_lhb_seat_workflow_keeps_previous_json_and_publishes_latest():
    workflow = _workflow("market_daily.yml")
    steps = workflow["jobs"]["collect"]["steps"]
    lhb = next(step for step in steps if step.get("id") == "lhb_seats")
    publish = next(step for step in steps if step.get("name") == "Publish to stock-results")

    assert lhb["continue-on-error"] is True
    assert 'steps.fetch.outputs.asof' in lhb["run"]
    assert "--previous \"$previous\"" in lhb["run"]
    assert "out/previous-market/lhb_seats_latest.json" in lhb["run"]
    assert "steps.lhb_seats.outcome == 'success'" in publish["if"]
    assert "cp out/market/lhb_seats_latest.json market/lhb_seats_latest.json" in publish["run"]


def test_nt_etf_workflow_bootstraps_and_uses_trading_date():
    workflow = _workflow("nt_etf_daily.yml")
    assert workflow["concurrency"] == {
        "group": "nt-etf-daily",
        "cancel-in-progress": False,
    }
    steps = workflow["jobs"]["collect"]["steps"]
    previous = next(step for step in steps if step.get("id") == "previous")
    collect = next(step for step in steps if step.get("name") == "Collect snapshot (PR smoke does not publish)")
    gate = next(step for step in steps if step.get("name") == "Gate publish on a successful share source")

    assert "web/mock/data/nt_etf/nt_etf_latest.json" in previous["run"]
    assert 'snapshot_date="$(python -m research.data.trading_date)"' in collect["run"]
    assert '--previous "$PREVIOUS_PATH"' in collect["run"]
    assert '("sse_shares","szse_shares")' in gate["run"]


def test_growth_monitor_workflow_uses_macro_schedule_and_previous_snapshot():
    workflow = _workflow("growth_daily.yml")
    triggers = workflow.get("on", workflow.get(True, {}))
    assert triggers["schedule"] == [{"cron": "30 22 * * 1-5"}]

    steps = workflow["jobs"]["collect"]["steps"]
    previous = next(step for step in steps if step.get("id") == "previous")
    collect = next(step for step in steps if step.get("id") == "fetch")
    assert "growth/growth_latest.json" in previous["run"]
    assert 'research.data.trading_date' in collect["run"]
    assert "research.data.growth_monitor" in collect["run"]
    assert "--previous" in collect["run"]
    artifact = next(
        step for step in steps if step.get("name") == "Upload growth monitor artifact"
    )
    assert artifact["if"] == "always()"
    assert artifact["uses"] == "actions/upload-artifact@v4"

    publish = next(
        step for step in steps if step.get("name") == "Publish to stock-results"
    )
    assert publish["if"] == (
        "github.event_name != 'pull_request' && steps.fetch.outputs.publishable == 'true'"
    )
    assert "--kind growth" in publish["run"]
    assert "out/growth/growth_latest.json" in publish["run"]
    assert "git add --" in publish["run"]
    assert "git push origin HEAD:stock-results" in publish["run"]
    assert "gh workflow run pages.yml --ref main" in publish["run"]
    build = (ROOT / "scripts/build_site.sh").read_text(encoding="utf-8")
    assert 'git -C "$ROOT" archive stock-results growth' in build

    alerts = _workflow("daily_alert.yml")
    alert_triggers = alerts.get("on", alerts.get(True, {}))
    assert "growth_daily" in alert_triggers["workflow_run"]["workflows"]


def test_versioned_workflows_use_the_publisher_and_keep_stock_list_unversioned():
    market = _workflow("market_daily.yml")
    steps = {
        step.get("name"): step
        for step in market["jobs"]["collect"]["steps"]
        if step.get("name")
    }
    event_publish = steps["Fetch and publish event calendar"]["run"]
    market_publish = steps["Publish to stock-results"]["run"]

    assert "--kind events" in event_publish
    for kind in ("market", "abnormal", "bottom_signal", "range"):
        assert f"publish_versioned {kind} " in market_publish
    assert "cp out/market/stock_list.json market/stock_list.json" in market_publish
    assert "git add market/stock_list.json" in market_publish
    assert "cp out/market/market_latest.json" not in market_publish

    for workflow_name, kind in (
        ("macro_daily.yml", "macro"),
        ("nt_etf_daily.yml", "nt_etf"),
        ("growth_daily.yml", "growth"),
    ):
        workflow = _workflow(workflow_name)
        publish = next(
            step
            for step in workflow["jobs"]["collect"]["steps"]
            if step.get("name") == "Publish to stock-results"
        )
        assert f"--kind {kind}" in publish["run"]
        assert "git add --" in publish["run"]


def test_market_breadth_uses_cache_fallback_and_publishes_latest_json():
    workflow = _workflow("market_daily.yml")
    steps = workflow["jobs"]["collect"]["steps"]
    breadth_cache = next(step for step in steps if step.get("id") == "breadth_cache")
    breadth = next(step for step in steps if step.get("id") == "breadth")
    cache_save = next(
        step for step in steps if step.get("name") == "Save market breadth cache"
    )
    publish = next(
        step for step in steps if step.get("name") == "Publish to stock-results"
    )

    assert breadth_cache["uses"] == "actions/cache/restore@v4"
    assert breadth_cache["with"]["path"] == "data/cache/breadth"
    assert breadth["continue-on-error"] is True
    assert "research.data.breadth" in breadth["run"]
    assert '--date "${{ steps.fetch.outputs.asof }}"' in breadth["run"]
    assert "--backfill 300" in breadth["run"]
    assert "--previous out/previous-market/breadth_latest.json" in breadth["run"]
    assert cache_save["uses"] == "actions/cache/save@v4"
    assert cache_save["with"]["path"] == "data/cache/breadth"
    assert "steps.breadth.outcome == 'success'" in publish["if"]
    assert (
        "cp out/market/breadth_latest.json market/breadth_latest.json"
        in publish["run"]
    )
    assert "git add market/breadth_latest.json" in publish["run"]

    build = (ROOT / "scripts/build_site.sh").read_text(encoding="utf-8")
    assert 'git -C "$ROOT" archive stock-results market' in build


def test_top_risk_runs_after_breadth_and_publishes_the_snapshot():
    workflow = _workflow("market_daily.yml")
    steps = workflow["jobs"]["collect"]["steps"]
    breadth = next(step for step in steps if step.get("id") == "breadth")
    top_risk = next(step for step in steps if step.get("id") == "top_risk")
    publish = next(
        step for step in steps if step.get("name") == "Publish to stock-results"
    )
    run = top_risk["run"]

    assert steps.index(top_risk) > steps.index(breadth)
    assert top_risk["continue-on-error"] is True
    assert "research.data.top_risk" in run
    assert '--date "${{ steps.fetch.outputs.asof }}"' in run
    assert "--breadth out/market/breadth_latest.json" in run
    assert 'previous="out/previous-market/top_risk_latest.json"' in run
    assert '--previous "$previous"' in run
    assert "steps.top_risk.outcome == 'success'" in publish["if"]
    assert (
        "cp out/market/top_risk_latest.json market/top_risk_latest.json"
        in publish["run"]
    )
    assert "git add market/top_risk_latest.json" in publish["run"]


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

    assert triggers["schedule"] == [
        {"cron": "45 7 * * 1-5"},
        {"cron": "0 11 * * 1-5"},
    ]
    assert triggers["workflow_dispatch"] is None
    assert 'asof="$(python -c \'from research.data.trading_date import latest_closed_trading_day; print(latest_closed_trading_day())\')"' in plan_step["run"]
    assert 'symbols=\'["sh000001","sh000016","sh000300","sh000905","sh000688","sz399001","sz399006"]\'' in plan_step["run"]
    assert 'symbols=\'["sh000001"]\'' in plan_step["run"]
    assert plan["outputs"]["skip"] == "${{ steps.plan.outputs.skip }}"
    assert 'skip=false' in plan_step["run"]
    assert 'if [[ "$GITHUB_EVENT_NAME" == "schedule" || "$GITHUB_EVENT_NAME" == "repository_dispatch" ]]; then' in plan_step["run"]
    assert "git fetch --no-tags --depth=1 origin stock-results" in plan_step["run"]
    assert 'json.loads(result.stdout)' in plan_step["run"]
    assert 'origin/stock-results:index/{symbol}_latest.json' in plan_step["run"]
    assert 'payload.get("asof") != asof' in plan_step["run"]
    assert 'printf \'skip=%s\\n\' "$skip"' in plan_step["run"]
    assert "$GITHUB_STEP_SUMMARY" in plan_step["run"]
    assert fit["needs"] == "plan"
    assert fit["if"] == "needs.plan.outputs.skip != 'true'"
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
        "${{ !cancelled() && github.event_name != 'pull_request' && needs.plan.outputs.skip != 'true' }}"
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
