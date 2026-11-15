import json
from types import SimpleNamespace

import pytest

from research.data import daily_alert


@pytest.mark.parametrize(
    ("workflow", "conclusion", "issue", "expected"),
    [
        ("market_daily", "failure", None, "create"),
        ("market_daily", "timed_out", None, "create"),
        ("market_daily", "failure", 12, "comment"),
        ("market_daily", "success", 12, "close"),
        ("market_daily", "success", None, "noop"),
        ("market_daily", "cancelled", 12, "noop"),
        ("market_daily", "skipped", None, "noop"),
        ("market_daily", "neutral", 12, "noop"),
        ("market_daily", "action_required", None, "noop"),
    ],
)
def test_plan_run_alert(workflow, conclusion, issue, expected):
    assert daily_alert.plan_run_alert(workflow, conclusion, issue) == expected


@pytest.mark.parametrize(
    ("stale_count", "issue", "expected"),
    [
        (1, None, "create"),
        (3, 12, "update"),
        (0, 12, "close"),
        (0, None, "noop"),
    ],
)
def test_plan_stale_alert(stale_count, issue, expected):
    assert daily_alert.plan_stale_alert(stale_count, issue) == expected


def test_issue_lookup_requires_exact_title():
    issues = [
        {"number": 10, "title": "日更失败：macro_daily"},
        {"number": 11, "title": "日更失败：market_daily retry"},
        {"number": 12, "title": "日更失败：market_daily"},
    ]

    assert daily_alert.find_open_issue_number(issues, "日更失败：market_daily") == 12
    assert daily_alert.find_open_issue_number(issues, "日更失败：nt_etf_daily") is None


def test_failure_creates_chinese_issue_with_required_run_details(monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "not-a-real-token")
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        if command[1:3] == ["issue", "list"]:
            return SimpleNamespace(stdout="[]")
        return SimpleNamespace(stdout="")

    monkeypatch.setattr(daily_alert.subprocess, "run", fake_run)

    action = daily_alert.handle_run_alert(
        "market_daily",
        "failure",
        "https://github.com/owner/repo/actions/runs/123",
        "2026-11-13T17:30:00Z",
        "abcdef123456",
    )

    assert action == "create"
    assert calls[0][1:4] == ["label", "create", "daily-alert"]
    create = calls[-1]
    assert create[1:3] == ["issue", "create"]
    assert create[create.index("--title") + 1] == "日更失败：market_daily"
    body = create[create.index("--body") + 1]
    assert "结论：failure" in body
    assert "开始时间（北京时间）：2026-11-14 01:30:00" in body
    assert "提交：`abcdef1`" in body
    assert "https://github.com/owner/repo/actions/runs/123" in body
    assert "not-a-real-token" not in " ".join(create)
    assert create[-2:] == ["--repo", "owner/repo"]


def test_repeated_failure_comments_and_success_closes_issue(monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "token")
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        if command[1:3] == ["issue", "list"]:
            return SimpleNamespace(
                stdout=json.dumps([{"number": 42, "title": "日更失败：macro_daily"}])
            )
        return SimpleNamespace(stdout="")

    monkeypatch.setattr(daily_alert.subprocess, "run", fake_run)
    url = "https://github.com/owner/repo/actions/runs/456"

    action = daily_alert.handle_run_alert("macro_daily", "timed_out", url, "2026-11-14T00:00:00Z", "abc1234")
    assert action == "comment"
    assert calls[-1][1:5] == ["issue", "comment", "42", "--body"]
    assert calls[-1][5] == f"又失败一次：{url}"

    action = daily_alert.handle_run_alert("macro_daily", "success", url, "2026-11-14T00:00:00Z", "abc1234")
    assert action == "close"
    assert calls[-1][1:5] == ["issue", "close", "42", "--comment"]
    assert calls[-1][5] == f"已恢复：{url}"


def test_stale_issue_body_contains_freshness_table_and_calendar_note(monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "token")
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        if command[1:3] == ["issue", "list"]:
            return SimpleNamespace(stdout="[]")
        return SimpleNamespace(stdout="")

    monkeypatch.setattr(daily_alert.subprocess, "run", fake_run)

    action = daily_alert.handle_stale_alert(
        {"calendar_source": "trading", "stale": [{"key": "market"}]},
        "| 数据 | 数据日期 | 晚几个交易日 | 状态 |\n| --- | --- | ---: | --- |\n",
    )

    assert action == "create"
    create = calls[-1]
    assert create[create.index("--title") + 1] == "日更数据过期"
    body = create[create.index("--body") + 1]
    assert "| 数据 | 数据日期 | 晚几个交易日 | 状态 |" in body
    assert "只按 A 股交易日计算（trading）；数据日期取 asof 或生成时间" in body


def test_stale_recovery_comment_links_current_workflow_run(monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "token")
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GITHUB_RUN_ID", "789")
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        if command[1:3] == ["issue", "list"]:
            return SimpleNamespace(stdout='[{"number":8,"title":"日更数据过期"}]')
        return SimpleNamespace(stdout="")

    monkeypatch.setattr(daily_alert.subprocess, "run", fake_run)
    action = daily_alert.handle_stale_alert({"stale": []}, "")

    assert action == "close"
    assert calls[-1][1:5] == ["issue", "close", "8", "--comment"]
    assert calls[-1][5] == "已恢复：https://github.com/owner/repo/actions/runs/789"
