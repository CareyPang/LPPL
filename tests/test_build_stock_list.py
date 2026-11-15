import json
from types import SimpleNamespace

import pandas as pd
import pytest

from scripts import build_stock_list


def make_codes(count, start=0):
    return [f"0{number:05d}" for number in range(start, start + count)]


def test_pinyin_initials_preserve_ascii_and_use_chinese_initials():
    assert build_stock_list.pinyin_initials("万科A") == "wka"
    assert build_stock_list.pinyin_initials("东方财富") == "dfcf"
    assert build_stock_list.pinyin_initials("Arm 2") == "arm2"


def test_build_document_includes_supported_a_us_and_index_rows():
    frame = pd.DataFrame(
        {
            "code": make_codes(4000) + ["920002", "830799", "430047"],
            "name": ["东方财富"] * 4003,
        }
    )

    document = build_stock_list.build_document(frame, "test-source", "2026-11-15")

    assert document["asof"] == "2026-11-15"
    assert document["source"] == "test-source"
    assert document["fields"] == ["code", "name", "py", "kind"]
    counts = {kind: sum(row[3] == kind for row in document["rows"]) for kind in ("a", "us", "index")}
    assert counts == {"a": 4000, "us": 24, "index": 6}
    assert document["rows"][0] == ["000000", "东方财富", "dfcf", "a"]
    assert ["US_NVDA", "英伟达", "ywd", "us"] in document["rows"]
    assert ["sh000300", "沪深300", "hs300", "index"] in document["rows"]


def test_primary_source_retries_with_backoff_before_exchange_fallback(monkeypatch):
    sleeps = []
    calls = []

    def primary():
        calls.append("primary")
        raise ConnectionError("reset")

    def sh(symbol):
        calls.append(symbol)
        start = 0 if symbol == "主板A股" else 2000
        return pd.DataFrame(
            {"证券代码": make_codes(2000, start), "证券简称": ["贵州茅台"] * 2000}
        )

    def sz(symbol):
        calls.append(symbol)
        return pd.DataFrame(
            {"A股代码": make_codes(2000, 4000), "A股简称": ["平安银行"] * 2000}
        )

    monkeypatch.setattr(build_stock_list.time, "sleep", sleeps.append)
    ak = SimpleNamespace(
        stock_info_a_code_name=primary,
        stock_info_sh_name_code=sh,
        stock_info_sz_name_code=sz,
    )

    frame, source = build_stock_list.fetch_stock_frame(ak)

    assert calls == ["primary"] * 4 + ["主板A股", "科创板", "A股列表"]
    assert sleeps == [5, 15, 30]
    assert list(frame.columns) == ["code", "name"]
    assert len(frame) == 6000
    assert frame.iloc[0].to_dict() == {"code": "000000", "name": "贵州茅台"}
    assert frame.iloc[-1].to_dict() == {"code": "005999", "name": "平安银行"}
    assert "ak.stock_info_sh_name_code" in source
    assert "ak.stock_info_sz_name_code" in source


def test_eastmoney_full_market_fallback_uses_live_column_names(monkeypatch):
    monkeypatch.setattr(build_stock_list.time, "sleep", lambda _seconds: None)
    calls = []

    def fail():
        raise ConnectionError("unavailable")

    def spot():
        calls.append("spot")
        return pd.DataFrame({"代码": make_codes(4000), "名称": ["万科A"] * 4000})

    ak = SimpleNamespace(
        stock_info_a_code_name=fail,
        stock_info_sh_name_code=lambda **_kwargs: fail(),
        stock_info_sz_name_code=lambda **_kwargs: fail(),
        stock_zh_a_spot_em=spot,
    )

    frame, source = build_stock_list.fetch_stock_frame(ak)

    assert source == "ak.stock_zh_a_spot_em"
    assert calls == ["spot"]
    assert list(frame.columns) == ["code", "name"]
    assert len(frame) == 4000


def test_baostock_source_filters_current_a_shares_and_logs_out():
    class Result:
        fields = ["code", "code_name", "type", "status"]
        error_code = "0"
        error_msg = ""

        def __init__(self):
            self.rows = iter(
                [
                    ["sh.600519", "贵州茅台", "1", "1"],
                    ["sz.000001", "平安银行", "1", "1"],
                    ["sh.000001", "上证指数", "2", "1"],
                    ["sz.000002", "停牌股票", "1", "0"],
                ]
            )

        def next(self):
            self.current = next(self.rows, None)
            return self.current is not None

        def get_row_data(self):
            return self.current

    class Baostock:
        logged_out = False

        @staticmethod
        def login():
            return SimpleNamespace(error_code="0", error_msg="")

        @staticmethod
        def query_stock_basic():
            return Result()

        @classmethod
        def logout(cls):
            cls.logged_out = True

    frame = build_stock_list._fetch_baostock_frame(Baostock)

    assert frame.to_dict("records") == [
        {"code": "600519", "name": "贵州茅台"},
        {"code": "000001", "name": "平安银行"},
    ]
    assert Baostock.logged_out


def test_small_or_failed_source_does_not_overwrite_existing_file(tmp_path, monkeypatch):
    output = tmp_path / "stock_list.json"
    output.write_text('{"old":true}', encoding="utf-8")
    small_frame = pd.DataFrame({"code": make_codes(3999), "name": ["贵州茅台"] * 3999})
    monkeypatch.setattr(
        build_stock_list,
        "fetch_stock_frame",
        lambda _ak_module=None: (small_frame, "test-source"),
    )

    with pytest.raises(ValueError, match="至少需要 4000"):
        build_stock_list.generate(output)

    assert output.read_text(encoding="utf-8") == '{"old":true}'


def test_failed_sources_do_not_overwrite_existing_file(tmp_path, monkeypatch):
    output = tmp_path / "stock_list.json"
    output.write_text('{"old":true}', encoding="utf-8")
    monkeypatch.setattr(
        build_stock_list,
        "fetch_stock_frame",
        lambda _ak_module=None: (_ for _ in ()).throw(RuntimeError("source failed")),
    )

    with pytest.raises(RuntimeError, match="source failed"):
        build_stock_list.generate(output)

    assert output.read_text(encoding="utf-8") == '{"old":true}'


def test_write_document_is_compact(tmp_path):
    output = tmp_path / "stock_list.json"
    build_stock_list.write_document(
        output,
        {"asof": "2026-11-15", "fields": ["code"], "rows": [["600519"]]},
    )

    content = output.read_text(encoding="utf-8")
    assert "\n" not in content
    assert json.loads(content)["rows"] == [["600519"]]
