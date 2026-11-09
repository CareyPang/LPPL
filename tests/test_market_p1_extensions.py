from research.data.market_p1_extensions import (
    attach_p1_extensions,
    board_heatmaps,
    funding_percentile,
    limit_pool_stats,
    topic_heat,
)


def test_heatmaps_preserve_source_fields_and_missing_region():
    value = board_heatmaps(
        {"provider": {"industry": "eastmoney"}, "industry": [{"name": "银行", "main_net": 1.2}]},
        "2026-11-03",
    )
    assert value["industry"]["rows"][0]["main_net"] == 1.2
    assert value["industry"]["provider"] == "eastmoney"
    assert value["region"]["status"] == "not_available"


def test_topic_heat_counts_explicit_labels_only():
    value = topic_heat({"topics": {"status": "fresh", "rows": [{"topic_label": "算力"}, {"topic_label": "算力"}, {"name": "无标签"}]}}, "2026-11-03")
    assert value["rows"] == [{"topic_label": "算力", "count": 2}]


def test_limit_pool_stats_does_not_turn_missing_count_into_zero():
    assert limit_pool_stats({"zt": 2, "zb": 1}, "2026-11-03")["status"] == "not_available"
    value = limit_pool_stats({"zt": 2, "zb": 1, "dt": 3}, "2026-11-03")
    assert value["rows"][0]["broken_rate"] == 1 / 3


def test_funding_percentile_requires_real_history_and_excludes_future_rows():
    rows = [{"date": f"2026-10-{day:02d}", "main_net": day} for day in range(1, 22)]
    rows.append({"date": "2026-12-01", "main_net": 999})
    value = funding_percentile(rows, asof="2026-10-21", min_rows=20)
    assert value["status"] == "fresh"
    assert value["rows"][0]["sample_size"] == 21
    assert value["rows"][0]["percentile"] == 1.0


def test_attach_p1_extensions_is_explicit_and_descriptive():
    value = attach_p1_extensions({"asof": "2026-11-03", "limit_pools": {"zt": 1}})
    assert value["p1"]["topic_heat"]["status"] == "not_available"
    assert value["p1"]["disclosures"]["f10"]["status"] == "not_available"
    assert value["p1"]["evidence"] == "descriptive"
