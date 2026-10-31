"""教育页 web/guide.html 读取 web/mock/guide.md；它必须与 docs/user_guide.md 完全一致（daily_update.sh 负责同步）。"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_guide_copy_matches_source():
    src = (ROOT / "docs" / "user_guide.md").read_text(encoding="utf-8")
    pub = (ROOT / "web" / "mock" / "guide.md").read_text(encoding="utf-8")
    assert pub == src, "web/mock/guide.md 落后于 docs/user_guide.md，请运行 cp docs/user_guide.md web/mock/guide.md"
