import pytest

from research.data.sources import parse_code
from research.pipeline.universe import _sym


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("600519", "sh600519"),
        ("000001", "sz000001"),
        ("300750", "sz300750"),
        ("430047", "bj430047"),
        ("830799", "bj830799"),
        ("870204", "bj870204"),
        ("920002", "bj920002"),
    ],
)
def test_sym_routes_stock_codes(code, expected):
    assert _sym(code) == expected


@pytest.mark.parametrize("code", ["430047", "830799", "870204", "920002", "bj920002"])
def test_parse_code_accepts_beijing_stock_symbols(code):
    expected_code = code[-6:]
    assert parse_code(code) == ("bj", expected_code, False)
