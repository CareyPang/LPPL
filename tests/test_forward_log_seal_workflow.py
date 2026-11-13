"""forward_log_seal.yml 结构检查（纯文本，不依赖 PyYAML）：工作日定时、只提交 forward_log/、不改已跟踪的其他文件、失败不补封。"""
import re
from pathlib import Path

WF = Path(__file__).resolve().parents[1] / ".github/workflows/forward_log_seal.yml"
TXT = WF.read_text(encoding="utf-8")


def test_schedule_and_permissions():
    cron = re.search(r'cron:\s*"([^"]+)"', TXT).group(1)
    assert cron.split()[-1] == "1-5", "只在工作日运行"
    assert "workflow_dispatch" in TXT
    assert re.search(r"permissions:\s*\n\s+contents: write", TXT)
    assert int(re.search(r"timeout-minutes:\s*(\d+)", TXT).group(1)) <= 60
    assert re.search(r"ref:\s*main", TXT), "必须在 main 上封存"


def test_runs_daily_update_then_seals_only_forward_log():
    assert "bash scripts/daily_update.sh" in TXT
    adds = [ln.strip() for ln in TXT.splitlines() if ln.strip().startswith("git add ")]
    assert adds == ["git add forward_log/"], adds
    assert "git checkout -- ." in TXT, "其余已跟踪文件改动不得进入 main"
    assert "git push origin HEAD:main" in TXT
    assert "forward_log check" in TXT


def test_no_backfill_flags():
    assert "--asof" not in TXT, "封存只取当日 as-of，不得回填历史日期"
    assert "--frozen" not in TXT
