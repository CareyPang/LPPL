from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

DAILY_ALERT_LABEL = "daily-alert"
STALE_ISSUE_TITLE = "日更数据过期"


def plan_run_alert(
    workflow: str, conclusion: str, open_issue_number: int | None
) -> str:
    if conclusion in {"failure", "timed_out"}:
        return "comment" if open_issue_number is not None else "create"
    if conclusion == "success":
        return "close" if open_issue_number is not None else "noop"
    return "noop"


def plan_stale_alert(stale_count: int, open_issue_number: int | None) -> str:
    if stale_count > 0:
        return "update" if open_issue_number is not None else "create"
    return "close" if open_issue_number is not None else "noop"


def find_open_issue_number(issues: list[dict], title: str) -> int | None:
    for issue in issues:
        if issue.get("title") == title:
            number = issue.get("number")
            return int(number) if number is not None else None
    return None


def _gh(args: list[str]) -> subprocess.CompletedProcess:
    if not os.environ.get("GH_TOKEN"):
        raise RuntimeError("GH_TOKEN is required")
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not repo:
        raise RuntimeError("GITHUB_REPOSITORY is required")
    return subprocess.run(
        ["gh", *args, "--repo", repo],
        check=True,
        capture_output=True,
        text=True,
    )


def _ensure_label() -> None:
    _gh(["label", "create", DAILY_ALERT_LABEL, "--color", "d93f0b", "--force"])


def _open_issue_number(title: str) -> int | None:
    result = _gh(
        [
            "issue",
            "list",
            "--label",
            DAILY_ALERT_LABEL,
            "--state",
            "open",
            "--json",
            "number,title",
        ]
    )
    issues = json.loads(result.stdout or "[]")
    return find_open_issue_number(issues, title)


def _beijing_started(started: str) -> str:
    value = started.strip().replace("Z", "+00:00")
    timestamp = datetime.fromisoformat(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    return timestamp.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S")


def _run_body(
    workflow: str, conclusion: str, url: str, started: str, sha: str
) -> str:
    return (
        f"日更工作流失败：{workflow}\n\n"
        f"- 结论：{conclusion}\n"
        f"- 开始时间（北京时间）：{_beijing_started(started)}\n"
        f"- 提交：`{sha[:7]}`\n"
        f"- 运行链接：{url}"
    )


def _current_run_url() -> str:
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com").rstrip("/")
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    if repository and run_id:
        return f"{server}/{repository}/actions/runs/{run_id}"
    return "数据检查结果正常"


def _stale_body(report: dict, markdown: str) -> str:
    calendar_source = report.get("calendar_source", "weekday")
    return (
        f"{markdown.rstrip()}\n\n"
        f"只按 A 股交易日计算（{calendar_source}）；数据日期取 asof 或生成时间"
    )


def handle_run_alert(
    workflow: str, conclusion: str, url: str, started: str, sha: str
) -> str:
    if conclusion not in {"failure", "timed_out", "success"}:
        return "noop"

    title = f"日更失败：{workflow}"
    _ensure_label()
    open_issue_number = _open_issue_number(title)
    action = plan_run_alert(workflow, conclusion, open_issue_number)
    if action == "create":
        _gh(
            [
                "issue",
                "create",
                "--title",
                title,
                "--body",
                _run_body(workflow, conclusion, url, started, sha),
                "--label",
                DAILY_ALERT_LABEL,
            ]
        )
    elif action == "comment":
        _gh(
            [
                "issue",
                "comment",
                str(open_issue_number),
                "--body",
                f"又失败一次：{url}",
            ]
        )
    elif action == "close":
        _gh(
            [
                "issue",
                "close",
                str(open_issue_number),
                "--comment",
                f"已恢复：{url}",
            ]
        )
    return action


def handle_stale_alert(report: dict, markdown: str) -> str:
    stale = report.get("stale")
    if isinstance(stale, list):
        stale_count = len(stale)
    else:
        stale_count = sum(item.get("status") != "ok" for item in report.get("items", []))

    _ensure_label()
    open_issue_number = _open_issue_number(STALE_ISSUE_TITLE)
    action = plan_stale_alert(stale_count, open_issue_number)
    if action == "create":
        _gh(
            [
                "issue",
                "create",
                "--title",
                STALE_ISSUE_TITLE,
                "--body",
                _stale_body(report, markdown),
                "--label",
                DAILY_ALERT_LABEL,
            ]
        )
    elif action == "update":
        _gh(
            [
                "issue",
                "edit",
                str(open_issue_number),
                "--body",
                _stale_body(report, markdown),
            ]
        )
    elif action == "close":
        _gh(
            [
                "issue",
                "close",
                str(open_issue_number),
                "--comment",
                f"已恢复：{_current_run_url()}",
            ]
        )
    return action


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create or update daily alert issues.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--workflow", required=True)
    run_parser.add_argument("--conclusion", required=True)
    run_parser.add_argument("--url", required=True)
    run_parser.add_argument("--started", required=True)
    run_parser.add_argument("--sha", required=True)

    stale_parser = subparsers.add_parser("stale")
    stale_parser.add_argument("--report", required=True)
    stale_parser.add_argument("--markdown", required=True)

    args = parser.parse_args(argv)
    if args.command == "run":
        action = handle_run_alert(
            args.workflow, args.conclusion, args.url, args.started, args.sha
        )
    else:
        report = json.loads(open(args.report, encoding="utf-8").read())
        markdown = open(args.markdown, encoding="utf-8").read()
        action = handle_stale_alert(report, markdown)
    print(action)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
