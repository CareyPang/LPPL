"""forward_log_seal.yml 结构检查：矩阵拟合、工作日定时、只提交 forward_log/、失败不补封。"""
import re
from pathlib import Path

import yaml

WF = Path(__file__).resolve().parents[1] / ".github/workflows/forward_log_seal.yml"
TXT = WF.read_text(encoding="utf-8")


def test_schedule_and_permissions():
    cron = re.search(r'cron:\s*"([^"]+)"', TXT).group(1)
    assert cron.split()[-1] == "1-5", "只在工作日运行"
    assert "workflow_dispatch" in TXT
    assert re.search(r"permissions:\s*\n\s+contents: write", TXT)
    jobs = yaml.safe_load(TXT)["jobs"]
    assert jobs["fit"]["timeout-minutes"] == 90
    assert jobs["seal"]["timeout-minutes"] == 30
    assert re.search(r"ref:\s*main", TXT), "必须在 main 上封存"


def test_fit_matrix_and_seal_dependency():
    workflow = yaml.safe_load(TXT)
    symbols = ["sh000001", "sh000016", "sh000300", "sh000905", "sz399001", "sz399006"]
    fit = workflow["jobs"]["fit"]
    assert fit["strategy"]["fail-fast"] is False
    assert fit["strategy"]["matrix"]["sym"] == symbols
    assert workflow["jobs"]["seal"]["needs"] == "fit"

    upload = next(step for step in fit["steps"] if step.get("uses") == "actions/upload-artifact@v4")
    assert upload["with"]["path"] == "web/mock/data/${{ matrix.sym }}_latest.json"
    download = next(
        step
        for step in workflow["jobs"]["seal"]["steps"]
        if step.get("uses") == "actions/download-artifact@v4"
    )
    assert download["with"]["pattern"] == "forward-log-fit-*"
    assert download["with"]["path"] == "fit-out/"

    steps = workflow["jobs"]["seal"]["steps"]
    stage = next(step for step in steps if step.get("name") == "Validate and stage fitted index JSONs")
    assert stage["shell"] == "bash"
    assert "for sym in " + " ".join(symbols) + "; do" in stage["run"]
    assert 'echo "::error::missing fit for $sym"' in stage["run"]
    assert 'cp "$src" web/mock/data/' in stage["run"]
    assert steps.index(stage) < next(
        i for i, step in enumerate(steps) if step.get("name") == "Seal and verify"
    )


def test_runs_daily_update_then_seals_only_forward_log():
    assert "SYMS=${{ matrix.sym }} SKIP_SEAL=1 bash scripts/daily_update.sh" in TXT
    adds = [ln.strip() for ln in TXT.splitlines() if ln.strip().startswith("git add ")]
    assert adds == ["git add forward_log/"], adds
    assert "git checkout -- ." in TXT, "其余已跟踪文件改动不得进入 main"
    assert "git push origin HEAD:main" in TXT
    assert "forward_log check" in TXT
    assert 'git config user.name' in TXT and 'git config user.email' in TXT, "rebase 需要提交者身份"


def test_guard_checks_deadline_and_discards_multiple_asofs():
    i = TXT.index("Guard")
    j = TXT.index("Commit forward_log to main")
    guard = TXT[i:j]
    assert "Asia/Shanghai" in guard
    assert 'guard --asof "$new_asofs"' in guard
    assert '--now "$sealed_last"' in guard, "按封存记录的 sealed_at 判定时限，不按校验时刻"
    assert "if [[ ${#asof_values[@]} -gt 1 ]]" in guard
    assert 'echo "::warning::$guard_output; discarding' in guard
    assert 'git checkout -- forward_log/' in guard and "git clean -fdq forward_log/" in guard
    assert i < j, "守卫必须在提交之前"


def test_no_backfill_flags():
    assert 'guard --asof "$new_asofs"' in TXT
    assert "forward_log seal --asof" not in TXT, "seal 仍从最新契约读取 as-of"
    assert "--frozen" not in TXT
