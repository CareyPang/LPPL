import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from research.pipeline import forward_log as fl

SHANGHAI = ZoneInfo("Asia/Shanghai")


@pytest.mark.parametrize(
    ("asof", "expected"),
    [
        ("2026-11-23", datetime(2026, 11, 24, 9, 15, tzinfo=SHANGHAI)),
        ("2026-11-20", datetime(2026, 11, 23, 9, 15, tzinfo=SHANGHAI)),
        ("2026-12-31", datetime(2027, 1, 4, 9, 15, tzinfo=SHANGHAI)),
    ],
)
def test_seal_deadline_uses_next_cn_trading_day(asof, expected):
    assert fl.seal_deadline(asof) == expected


def _run_guard(monkeypatch, capsys, *args):
    monkeypatch.setattr(sys, "argv", ["forward_log", "guard", *args])
    try:
        fl.main()
    except SystemExit as exc:
        code = exc.code
    else:
        code = 0
    return code, capsys.readouterr().out


def test_guard_accepts_seal_before_next_day_deadline(monkeypatch, capsys):
    code, output = _run_guard(
        monkeypatch,
        capsys,
        "--asof",
        "2026-11-23",
        "--now",
        "2026-11-24T06:53:00+08:00",
    )
    assert code == 0
    assert "within seal deadline 2026-11-24T09:15+08:00" in output


def test_guard_rejects_at_deadline(monkeypatch, capsys):
    code, output = _run_guard(
        monkeypatch,
        capsys,
        "--asof",
        "2026-11-23",
        "--now",
        "2026-11-24T09:15:00+08:00",
    )
    assert code == 3
    assert "sealed after deadline 2026-11-24T09:15+08:00" in output


def test_guard_rejects_future_asof(monkeypatch, capsys):
    code, output = _run_guard(
        monkeypatch,
        capsys,
        "--asof",
        "2026-11-25",
        "--now",
        "2026-11-24T06:53:00+08:00",
    )
    assert code == 3
    assert "is after today 2026-11-24 Asia/Shanghai" in output


def test_guard_requires_one_distinct_asof(monkeypatch, capsys):
    code, output = _run_guard(
        monkeypatch,
        capsys,
        "--asof",
        "2026-11-23",
        "--asof",
        "2026-11-24",
        "--now",
        "2026-11-24T06:53:00+08:00",
    )
    assert code == 3
    assert "exactly one distinct new as-of" in output
