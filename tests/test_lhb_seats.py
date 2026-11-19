import json

import pytest

from research.data import lhb_seats


def _summary_row(code, name, trade_id, explanation, buy, sell):
    return {
        "TRADE_ID": trade_id,
        "SECURITY_CODE": code,
        "SECURITY_NAME_ABBR": name,
        "EXPLANATION": explanation,
        "BILLBOARD_BUY_AMT": buy,
        "BILLBOARD_SELL_AMT": sell,
    }


def _detail_row(trade_id, code, name, dept_code, seat, buy, sell, explanation):
    return {
        "TRADE_ID": trade_id,
        "SECURITY_CODE": code,
        "SECURITY_NAME_ABBR": name,
        "OPERATEDEPT_CODE": dept_code,
        "OPERATEDEPT_NAME": seat,
        "BUY": buy,
        "SELL": sell,
        "EXPLANATION": explanation,
    }


@pytest.mark.parametrize("explanation", ["连续3个交易日", "连续三个交易日"])
def test_list_type_recognizes_arabic_and_chinese_multi_day_labels(explanation):
    assert lhb_seats._list_type(explanation) == "multi"


def test_aggregate_matches_full_seat_name_to_normalized_alias_and_source():
    seat = "国泰海通证券股份有限公司上海长宁区江苏路证券营业部"
    aliases = lhb_seats._load_aliases()
    normalized_seat = lhb_seats._normalize_seat_name(seat)
    explanation = "日涨幅偏离值达到7%"
    summary = [_summary_row("600001", "甲股份", "trade-1", explanation, 100, 20)]
    detail = _detail_row(
        "trade-1", "600001", "甲股份", "dept-a", seat, 100, 20, explanation
    )

    result = lhb_seats.aggregate_lhb_seats(
        "2026-11-18", summary, [detail], [detail.copy()], aliases
    )

    matched = next(row for row in result["seats"] if row["seat"] == seat)
    assert normalized_seat == "国泰海通证券上海长宁区江苏路证券营业部"
    assert matched["alias"] == "章盟主"
    assert matched["alias_source"] == aliases[normalized_seat]["source"]
    assert matched["alias_source_url"] == aliases[normalized_seat]["source_url"]


def test_aggregate_keeps_legacy_full_name_alias_keys():
    seat = "某证券股份有限公司上海分公司"
    explanation = "日涨幅偏离值达到7%"
    summary = [_summary_row("600001", "甲股份", "trade-1", explanation, 100, 20)]
    detail = _detail_row(
        "trade-1", "600001", "甲股份", "dept-a", seat, 100, 20, explanation
    )

    result = lhb_seats.aggregate_lhb_seats(
        "2026-11-18",
        summary,
        [detail],
        [detail.copy()],
        {
            seat: {
                "alias": "兼容别名",
                "source": "legacy source",
                "source_url": "https://example.test/legacy",
            }
        },
    )

    matched = next(row for row in result["seats"] if row["seat"] == seat)
    assert matched["alias"] == "兼容别名"
    assert matched["alias_source"] == "legacy source"
    assert matched["alias_source_url"] == "https://example.test/legacy"


def test_aggregate_groups_depts_by_alias_and_merges_trades_by_stock():
    explanation = "日涨幅偏离值达到7%"
    summary = [
        _summary_row("600001", "甲股份", "trade-a", explanation, 250, 40),
        _summary_row("000002", "乙科技", "trade-b", explanation, 60, 10),
        _summary_row("300003", "丙新材", "trade-c", explanation, 20, 10),
        _summary_row("000004", "丁设备", "trade-d", explanation, 10, 0),
    ]
    details = [
        _detail_row("trade-a", "600001", "甲股份", "dept-a", "营业部甲", 100, 20, explanation),
        _detail_row("trade-a", "600001", "甲股份", "dept-b", "营业部乙", 50, 10, explanation),
        _detail_row("trade-b", "000002", "乙科技", "dept-a", "营业部甲", 40, 0, explanation),
        _detail_row("trade-c", "300003", "丙新材", "dept-b", "营业部乙", 10, 5, explanation),
        _detail_row("trade-d", "000004", "丁设备", "dept-b", "营业部乙", 6, 0, explanation),
    ]
    aliases = {
        "营业部甲": {
            "alias": "游资甲",
            "source": "来源甲",
            "source_url": "https://example.test/a",
        },
        "营业部乙": {
            "alias": "游资甲",
            "source": "来源乙",
            "source_url": "https://example.test/b",
        },
    }

    result = lhb_seats.aggregate_lhb_seats(
        "2026-11-18", summary, details, [row.copy() for row in details], aliases
    )

    assert result["date_badge"] == "2026.11.18 / 周三 · 盘后榜单"
    assert result["youzi_summary"] == {
        "n_aliases": 1,
        "n_stocks": 4,
        "top_buy": [
            {"code": "600001", "name": "甲股份", "buy": 150},
            {"code": "000002", "name": "乙科技", "buy": 40},
            {"code": "300003", "name": "丙新材", "buy": 10},
            {"code": "000004", "name": "丁设备", "buy": 6},
        ],
    }
    assert result["youzi"][0] == {
        "alias": "游资甲",
        "depts": ["营业部乙", "营业部甲"],
        "buy": 206,
        "sell": 35,
        "net": 171,
        "n_stocks": 4,
        "trades": [
            {"code": "600001", "name": "甲股份", "buy": 150, "sell": 30, "list": "single"},
            {"code": "000002", "name": "乙科技", "buy": 40, "sell": 0, "list": "single"},
            {"code": "300003", "name": "丙新材", "buy": 10, "sell": 5, "list": "single"},
            {"code": "000004", "name": "丁设备", "buy": 6, "sell": 0, "list": "single"},
        ],
        "chips": [
            {"code": "600001", "name": "甲股份", "side": "in", "amount": 150, "list": "single"},
            {"code": "000002", "name": "乙科技", "side": "in", "amount": 40, "list": "single"},
            {"code": "600001", "name": "甲股份", "side": "out", "amount": 30, "list": "single"},
        ],
        "more_trades": 3,
        "sources": [
            {"source": "来源乙", "source_url": "https://example.test/b"},
            {"source": "来源甲", "source_url": "https://example.test/a"},
        ],
    }


def test_aggregate_classifies_bare_institution_seat_as_institution():
    explanation = "日涨幅偏离值达到7%"
    summary = [_summary_row("688613", "奥精医疗", "trade-1", explanation, 100, 40)]
    institution = _detail_row(
        "trade-1", "688613", "奥精医疗", "dept-1", "机构", 100, 40, explanation
    )

    result = lhb_seats.aggregate_lhb_seats(
        "2026-11-18", summary, [institution], [institution.copy()]
    )

    assert result["seats"][0]["kind"] == "institution"
    assert result["totals"]["institution_net"] == 60
    assert result["other_seats"][0] == {
        "seat": "机构",
        "kind": "institution",
        "buy": 100,
        "sell": 40,
        "net": 60,
    }


def test_aggregate_merges_side_tables_deduplicates_and_classifies_seats():
    multi = "连续三个交易日内，涨幅偏离值累计达到20%"
    single = "日涨幅偏离值达到7%"
    summary = [
        _summary_row("600001", "甲股份", "multi-1", multi, 100_000, 30_000),
        _summary_row("000002", "乙科技", "single-1", single, 80_000, 15_000),
    ]
    dept = _detail_row("multi-1", "600001", "甲股份", "dept-a", "某营业部", 100_000, 30_000, multi)
    institution = _detail_row("single-1", "000002", "乙科技", "0", "机构专用", 80_000, 10_000, single)
    northbound = _detail_row("single-1", "000002", "乙科技", "sct", "深股通专用", 0, 5_000, single)
    buy = [dept, dept.copy(), institution, northbound]
    sell = [dept.copy(), institution.copy(), northbound.copy()]

    result = lhb_seats.aggregate_lhb_seats(
        "2026-11-18",
        summary,
        buy,
        sell,
        {"某营业部": {"alias": "游资甲", "source": "公开报道"}},
    )

    assert result["totals"] == {
        "buy": 180_000,
        "sell": 45_000,
        "institution_net": 70_000,
        "n_stocks": 2,
        "n_stocks_single": 1,
        "n_stocks_multi": 1,
    }
    assert [seat["seat"] for seat in result["seats"]] == ["某营业部", "机构专用", "深股通专用"]
    assert result["seats"][0]["alias"] == "游资甲"
    assert result["seats"][0]["kind"] == "dept"
    assert result["seats"][0]["net"] == 70_000
    assert result["seats"][0]["trades"] == [
        {
            "code": "600001",
            "name": "甲股份",
            "side": "in",
            "amount": 100_000,
            "list": "multi",
        },
        {
            "code": "600001",
            "name": "甲股份",
            "side": "out",
            "amount": 30_000,
            "list": "multi",
        },
    ]
    assert result["seats"][1]["kind"] == "institution"
    assert result["seats"][2]["kind"] == "northbound"


def test_aggregate_keeps_institution_rows_and_deduplicates_duplicate_causes():
    explanation = "日涨幅偏离值达到7%"
    amounts = (73_179_025.20, 71_717_621.34, 52_400_372)
    summary = [
        _summary_row("000530", "冰山冷热", "cause-a", explanation, sum(amounts), 0),
        _summary_row("000530", "冰山冷热", "cause-b", explanation, sum(amounts), 0),
    ]
    rows = [
        _detail_row(trade_id, "000530", "冰山冷热", "0", "机构专用", amount, "", explanation)
        for trade_id in ("cause-a", "cause-b")
        for amount in amounts
    ]
    sell_rows = [
        _detail_row("cause-a", "000530", "冰山冷热", "0", "机构专用", amount, float("nan"), explanation)
        for amount in amounts
    ]

    result = lhb_seats.aggregate_lhb_seats("2026-11-18", summary, rows, sell_rows)

    institution = next(seat for seat in result["seats"] if seat["kind"] == "institution")
    assert result["totals"]["buy"] == 197_297_018.54
    assert result["totals"]["sell"] == 0
    assert result["totals"]["institution_net"] == 197_297_018.54
    assert institution["buy"] == 197_297_018.54
    assert institution["sell"] == 0
    assert len(institution["trades"]) == 3
    assert result["totals"]["n_stocks"] == 1


@pytest.mark.parametrize("reversed_order", [False, True])
def test_aggregate_deduplicates_identical_single_multi_rows_before_totals_and_alias_groups(reversed_order):
    single = "日涨幅偏离值达到7%"
    multi = "连续三个交易日内，涨幅偏离值累计达到20%"
    summary = [
        _summary_row("600001", "甲股份", "same-trade", single, 140, 60),
        _summary_row("600001", "甲股份", "same-trade", multi, 140, 60),
    ]
    single_alias = _detail_row(
        "same-trade", "600001", "甲股份", "dept-a", "某营业部", 100, 50, single
    )
    single_institution = _detail_row(
        "same-trade", "600001", "甲股份", "0", "机构专用", 40, 10, single
    )
    multi_alias = {
        **single_alias,
        "EXPLANATION": multi,
    }
    multi_institution = {
        **single_institution,
        "EXPLANATION": multi,
    }
    details = [
        single_alias,
        single_institution,
        multi_alias,
        multi_institution,
    ]
    if reversed_order:
        details.reverse()

    result = lhb_seats.aggregate_lhb_seats(
        "2026-11-18",
        summary,
        details,
        [row.copy() for row in details],
        {"某营业部": {"alias": "游资甲", "source": "公开报道"}},
    )

    assert result["totals"]["buy"] == 140
    assert result["totals"]["sell"] == 60
    assert result["totals"]["institution_net"] == 30
    assert result["totals"]["n_stocks_single"] == 1
    assert result["totals"]["n_stocks_multi"] == 1
    group = result["youzi"][0]
    assert (group["buy"], group["sell"], group["net"], group["n_stocks"]) == (
        100,
        50,
        50,
        1,
    )
    assert group["trades"] == [
        {"code": "600001", "name": "甲股份", "buy": 100, "sell": 50, "list": "single"}
    ]
    assert result["youzi_summary"]["top_buy"] == [
        {"code": "600001", "name": "甲股份", "buy": 100}
    ]


def test_aggregate_deduplicates_same_seat_amounts_across_lists_with_distinct_trade_ids():
    single = "日涨幅偏离值达到7%"
    multi = "连续三个交易日内，涨幅偏离值累计达到20%"
    summary = [
        _summary_row("600001", "甲股份", "single-trade", single, 140, 60),
        _summary_row("600001", "甲股份", "multi-trade", multi, 140, 60),
    ]
    multi_alias = _detail_row(
        "multi-trade", "600001", "甲股份", "dept-a", "某营业部", 100, 50, multi
    )
    multi_institution = _detail_row(
        "multi-trade", "600001", "甲股份", "0", "机构专用", 40, 10, multi
    )
    single_alias = _detail_row(
        "single-trade", "600001", "甲股份", "dept-a", "某营业部", 100, 50, single
    )
    single_institution = _detail_row(
        "single-trade", "600001", "甲股份", "0", "机构专用", 40, 10, single
    )
    details = [multi_alias, multi_institution, single_alias, single_institution]

    result = lhb_seats.aggregate_lhb_seats(
        "2026-11-18",
        summary,
        details,
        [row.copy() for row in details],
        {"某营业部": {"alias": "游资甲"}},
    )

    assert result["totals"]["buy"] == 140
    assert result["totals"]["sell"] == 60
    assert result["totals"]["institution_net"] == 30
    assert result["totals"]["n_stocks_single"] == 1
    assert result["totals"]["n_stocks_multi"] == 1
    group = result["youzi"][0]
    assert (group["buy"], group["sell"], group["net"]) == (100, 50, 50)
    seat = next(seat for seat in result["seats"] if seat["seat"] == "某营业部")
    assert {trade["list"] for trade in seat["trades"]} == {"single"}


def test_youzi_buying_summary_excludes_sell_only_stocks():
    explanation = "日涨幅偏离值达到7%"
    summary = [
        _summary_row("600001", "甲股份", "buy-trade", explanation, 100, 0),
        _summary_row("000002", "乙科技", "sell-trade", explanation, 0, 50),
    ]
    buy_row = _detail_row(
        "buy-trade", "600001", "甲股份", "dept-a", "买入营业部", 100, 0, explanation
    )
    sell_only_row = _detail_row(
        "sell-trade", "000002", "乙科技", "dept-b", "卖出营业部", 0, 50, explanation
    )

    result = lhb_seats.aggregate_lhb_seats(
        "2026-11-18",
        summary,
        [buy_row, sell_only_row],
        [buy_row.copy(), sell_only_row.copy()],
        {
            "买入营业部": {"alias": "游资甲"},
            "卖出营业部": {"alias": "游资乙"},
        },
    )

    assert result["youzi_summary"]["n_stocks"] == 1
    assert result["youzi_summary"]["top_buy"] == [
        {"code": "600001", "name": "甲股份", "buy": 100}
    ]


def test_unverified_department_names_and_commentary_are_not_aliases():
    aliases = lhb_seats._load_aliases()
    invalid = {"东方财富证券上海东方路证券营业部", "光大证券昆明人民中路证券营业部",
               "国信证券深圳泰然九路证券营业部", "华泰证券无锡梁清路证券营业部"}
    assert not invalid.intersection(aliases)


@pytest.mark.parametrize("explanation", [None, "", "某种未说明期限的公开披露"])
def test_ambiguous_detail_does_not_default_to_single(explanation):
    summary = [_summary_row("600001", "甲", "X", why, 100, 20)
               for why in ("日涨幅偏离值达到7%", "连续三个交易日内，涨幅偏离值累计达到20%")]
    row = _detail_row("X", "600001", "甲", "A", "席位甲", 100, 20, explanation)
    with pytest.raises(RuntimeError, match="榜单类型不明确"):
        lhb_seats.aggregate_lhb_seats("2026-11-18", summary, [row], [row.copy()])


def test_same_alias_stock_overlapping_periods_use_single_ranking_and_separate_chips():
    summary, details = [], []
    for period, why, amount in [("single", "日涨幅偏离值达到7%", 100),
                                ("multi", "连续三个交易日内，涨幅偏离值累计达到20%", 200)]:
        summary.append(_summary_row("600001", "甲", period, why, amount, 0))
        details.append(_detail_row(period, "600001", "甲", "A", "席位甲", amount, 0, why))
    result = lhb_seats.aggregate_lhb_seats("2026-11-18", summary, details, details,
                                           {"席位甲": {"alias": "游资甲"}})
    assert result["totals"]["buy"] == result["youzi"][0]["buy"] == 100
    assert result["youzi_summary"]["top_buy"] == [{"code": "600001", "name": "甲", "buy": 100}]
    assert result["ranking_basis"] == "single_only"
    assert {(t["list"], t["amount"]) for t in result["youzi"][0]["chips"]} == {("single", 100), ("multi", 200)}
    assert result["youzi"][0]["n_stocks"] == 1


def test_aggregate_uses_largest_same_type_disclosure():
    explanation = "日涨幅偏离值达到7%"
    summary = [
        _summary_row("600003", "丙科技", "smaller", explanation, 100, 0),
        _summary_row("600003", "丙科技", "larger", explanation, 200, 0),
    ]
    smaller = _detail_row("smaller", "600003", "丙科技", "dept-a", "某营业部", 100, 0, explanation)
    larger = _detail_row("larger", "600003", "丙科技", "dept-b", "另一营业部", 200, 0, explanation)

    result = lhb_seats.aggregate_lhb_seats("2026-11-18", summary, [smaller, larger], [larger.copy()])

    assert result["totals"]["buy"] == 200
    assert [seat["seat"] for seat in result["seats"]] == ["另一营业部"]


def test_aggregate_keeps_both_amounts_for_buy_only_and_sell_only_ranked_rows():
    explanation = "日涨幅偏离值达到7%"
    summary = [
        _summary_row("300857", "协创数据", "buy-only", explanation, 116_077_036, 6_138_254),
        _summary_row("600004", "丁股份", "rankings", explanation, 9_500, 13_000),
    ]
    buy_only = _detail_row(
        "buy-only",
        "300857",
        "协创数据",
        "ht",
        "华泰证券股份有限公司上海武定路证券营业部",
        116_077_036,
        6_138_254,
        explanation,
    )
    buy_ranked = _detail_row("rankings", "600004", "丁股份", "dept-a", "买入榜席位", 7_000, 4_000, explanation)
    sell_ranked = _detail_row("rankings", "600004", "丁股份", "dept-b", "卖出榜席位", 2_500, 9_000, explanation)

    result = lhb_seats.aggregate_lhb_seats(
        "2026-11-18", summary, [buy_only, buy_ranked], [sell_ranked]
    )

    huatai = next(seat for seat in result["seats"] if seat["seat"] == buy_only["OPERATEDEPT_NAME"])
    assert huatai["buy"] == 116_077_036
    assert huatai["sell"] == 6_138_254
    assert huatai["net"] == 109_938_782
    assert result["totals"]["sell"] == 6_151_254


@pytest.mark.parametrize("missing_report", ["buy", "sell"])
def test_aggregate_rejects_empty_detail_report_for_nonempty_summary(missing_report):
    explanation = "日涨幅偏离值达到7%"
    summary = [_summary_row("000530", "冰山冷热", "trade-1", explanation, 100, 50)]
    row = _detail_row("trade-1", "000530", "冰山冷热", "0", "机构专用", 100, 50, explanation)
    buy_rows = [] if missing_report == "buy" else [row]
    sell_rows = [] if missing_report == "sell" else [row]

    with pytest.raises(RuntimeError, match="买入或卖出席位明细为空"):
        lhb_seats.aggregate_lhb_seats("2026-11-18", summary, buy_rows, sell_rows)


def test_aggregate_rejects_summary_stock_without_detail_rows():
    explanation = "日涨幅偏离值达到7%"
    summary = [
        _summary_row("000530", "冰山冷热", "trade-a", explanation, 100, 50),
        _summary_row("600001", "甲股份", "trade-b", explanation, 100, 50),
    ]
    row = _detail_row("trade-a", "000530", "冰山冷热", "0", "机构专用", 100, 50, explanation)

    with pytest.raises(RuntimeError, match="汇总股票缺少买卖席位明细"):
        lhb_seats.aggregate_lhb_seats("2026-11-18", summary, [row], [row.copy()])


def test_aggregate_counts_unique_stock_across_single_and_multi_lists():
    single = "日涨幅偏离值达到7%"
    multi = "连续三个交易日内，涨幅偏离值累计达到20%"
    summary = [
        _summary_row("600001", "甲股份", "single-1", single, 100, 20),
        _summary_row("600001", "甲股份", "multi-1", multi, 200, 30),
    ]
    single_row = _detail_row("single-1", "600001", "甲股份", "dept-a", "某营业部", 100, 20, single)
    multi_row = _detail_row("multi-1", "600001", "甲股份", "dept-b", "另一营业部", 200, 30, multi)

    result = lhb_seats.aggregate_lhb_seats(
        "2026-11-18",
        summary,
        [single_row, multi_row],
        [single_row.copy(), multi_row.copy()],
    )

    assert result["totals"]["n_stocks"] == 1
    assert result["totals"]["n_stocks_single"] == 1
    assert result["totals"]["n_stocks_multi"] == 1
    assert result["sample_note"] == (
        "样本 1 只（其中单日榜 1、多日榜 1） · 历史分位，不是预测"
    )


def test_aggregate_keeps_single_and_multi_disclosures_for_920157():
    single = "日涨幅偏离值达到7%"
    multi = "连续3个交易日内，涨幅偏离值累计达到20%"
    summary = [
        _summary_row("920157", "新锦动力", "single-1", single, 100, 20),
        _summary_row("920157", "新锦动力", "multi-1", multi, 200, 30),
    ]
    single_row = _detail_row("single-1", "920157", "新锦动力", "dept-a", "单日榜席位", 100, 20, single)
    multi_row = _detail_row("multi-1", "920157", "新锦动力", "dept-b", "多日榜席位", 200, 30, multi)

    result = lhb_seats.aggregate_lhb_seats(
        "2026-11-13",
        summary,
        [single_row, multi_row],
        [single_row.copy(), multi_row.copy()],
    )

    trades = {
        (trade["list"], trade["amount"])
        for seat in result["seats"]
        for trade in seat["trades"]
    }
    assert result["totals"]["n_stocks"] == 1
    assert result["totals"]["n_stocks_single"] == 1
    assert result["totals"]["n_stocks_multi"] == 1
    assert ("single", 100) in trades
    assert ("multi", 200) in trades


def test_empty_summary_is_a_confirmed_no_board_result():
    result = lhb_seats.aggregate_lhb_seats("2026-11-18", [], [], [])

    assert result["totals"] == {
        "buy": 0,
        "sell": 0,
        "institution_net": 0,
        "n_stocks": 0,
        "n_stocks_single": 0,
        "n_stocks_multi": 0,
    }
    assert result["seats"] == []


def test_fetch_rejects_9201_buy_report_when_summary_has_stocks(tmp_path):
    explanation = "日涨幅偏离值达到7%"
    summary = _summary_row("000530", "冰山冷热", "trade-1", explanation, 100, 50)
    sell = _detail_row("trade-1", "000530", "冰山冷热", "0", "机构专用", 100, 50, explanation)
    aliases = tmp_path / "aliases.json"
    aliases.write_text("{}", encoding="utf-8")

    class Client:
        def get_json(self, _url, params):
            report = params["reportName"]
            if report == lhb_seats.REPORTS["summary"]:
                rows = [summary]
            elif report == lhb_seats.REPORTS["buy"]:
                return {"code": 9201}
            else:
                rows = [sell]
            return {"code": 0, "result": {"pages": 1, "count": 1, "data": rows}}

    with pytest.raises(RuntimeError, match="买入或卖出席位明细为空"):
        lhb_seats.fetch_lhb_seats("2026-11-18", Client(), aliases)


def test_fetch_report_paginates_and_checks_count():
    class Client:
        def __init__(self):
            self.pages = []

        def get_json(self, _url, params):
            page = int(params["pageNumber"])
            assert params["columns"] == "ALL"
            assert params["filter"] == "(TRADE_DATE='2026-11-18')"
            assert params["pageSize"] == "500"
            self.pages.append(page)
            if page == 1:
                return {
                    "code": 0,
                    "result": {
                        "pages": 2,
                        "count": 501,
                        "data": [{}] * 500,
                    },
                }
            return {
                "code": 0,
                "result": {"pages": 2, "count": 501, "data": [{}]},
            }

    client = Client()
    rows = lhb_seats._fetch_report(client, "report", "2026-11-18")
    assert len(rows) == 501
    assert client.pages == [1, 2]


def test_failed_fetch_reuses_previous_json(monkeypatch, tmp_path):
    previous = tmp_path / "previous.json"
    previous.write_text('{"asof":"2026-11-17"}', encoding="utf-8")
    output = tmp_path / "out" / "lhb_seats_latest.json"
    monkeypatch.setattr(
        lhb_seats,
        "fetch_lhb_seats",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("offline")),
    )

    with pytest.raises(RuntimeError, match="offline"):
        lhb_seats.main(
            [
                "--date",
                "2026-11-18",
                "--out",
                str(output),
                "--previous",
                str(previous),
            ]
        )

    assert json.loads(output.read_text(encoding="utf-8")) == {"asof": "2026-11-17"}
