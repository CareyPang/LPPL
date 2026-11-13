"""forward_log_seal.yml 结构检查：工作日定时、只提交 forward_log/、不改已跟踪的其他文件、失败不补封。"""
from pathlib import Path

import yaml

WF = Path(__file__).resolve().parents[1] / ".github/workflows/forward_log_seal.yml"


def _steps():
    doc = yaml.safe_load(WF.read_text(encoding="utf-8"))
    assert doc["permissions"] == {"contents": "write"}
    cron = doc[True]["schedule"][0]["cron"] if True in doc else doc["on"]["schedule"][0]["cron"]
    assert cron.split()[-1] == "1-5", "只在工作日运行"
    job = doc["jobs"]["seal"]
    assert job["timeout-minutes"] <= 60
    return job["steps"]


def test_runs_daily_update_then_seals_only_forward_log():
    steps = _steps()
    run = "\n".join(s.get("run", "") for s in steps)
    assert "scripts/daily_update.sh" in run
    assert "git add forward_log/" in run
    adds = [ln for ln in run.splitlines() if ln.strip().startswith("git add ")]
    assert adds == ["          git add forward_log/"] or all("forward_log/" in a for a in adds)
    assert "git checkout -- ." in run, "其余已跟踪文件改动不得进入 main"
    assert "git push origin HEAD:main" in run
    assert "forward_log check" in run


def test_no_backfill_flags():
    run = "\n".join(s.get("run", "") for s in _steps())
    assert "--asof" not in run, "封存只取当日 as-of，不得回填历史日期"
    assert "--frozen" not in run
