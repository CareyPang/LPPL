from __future__ import annotations

import os
import re
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

import pytest

if TYPE_CHECKING:
    from playwright.sync_api import Page


def expect(locator: object):
    from playwright.sync_api import expect as playwright_expect

    return playwright_expect(locator)

BASE_URL = os.environ.get("E2E_BASE_URL", "http://127.0.0.1:8765")
BREADTH_FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "frontend"
    / "tests"
    / "fixtures"
    / "breadth_latest.json"
)
NAV_PAGES = (
    "home.html",
    "index.html?code=sh000001",
    "stock.html",
    "market.html",
    "backtest.html",
    "tools.html",
    "chart.html?code=sh601838&scale=6-12m",
)


def assert_page_has_no_overflow(page: Page, path: str) -> None:
    page.goto(f"{BASE_URL}/{path}")
    for width, height in ((1440, 900), (390, 844)):
        page.set_viewport_size({"width": width, "height": height})
        page.wait_for_timeout(250)
        dimensions = page.evaluate(
            "() => ({scrollWidth: document.documentElement.scrollWidth, innerWidth})"
        )
        assert dimensions["scrollWidth"] <= dimensions["innerWidth"] + 1, dimensions


@pytest.mark.e2e
def test_flow_1_home_search_finds_maotai(page: Page) -> None:
    page.goto(f"{BASE_URL}/home.html")
    page.locator("#hs-i").click()
    expect(page.get_by_role("dialog", name="搜索标的")).to_be_visible()
    page.locator("#odm-i").fill("600519")
    candidate = page.locator("#odm-l li[role=option]").filter(has_text="贵州茅台")
    expect(candidate).to_be_visible()


@pytest.mark.e2e
def test_flow_2_stock_catalog_restores_filter_and_scroll(page: Page) -> None:
    page.goto(f"{BASE_URL}/stock.html")
    catalog = page.locator("#catalog")
    expect(catalog).to_be_visible()
    page.wait_for_function(
        "() => document.querySelector('#catalog .cat-q') && "
        "document.querySelectorAll('#catalog a[data-i]').length > 0"
    )
    page.locator(
        '#catalog .cat-f[aria-label="类型"] button[data-v="stock"]'
    ).click()
    page.locator(
        '#catalog .cat-f[aria-label="结果"] button[data-v="yes"]'
    ).click()
    expect(page.locator("#catalog a[data-i]").first).to_be_visible()
    page.evaluate("window.scrollTo(0, 300)")
    page.wait_for_function("Math.abs(window.scrollY - 300) <= 2")
    page.wait_for_timeout(160)
    saved_state = page.evaluate(
        "() => JSON.parse(sessionStorage.getItem('lppl.catalog.v1') || '{}')"
    )
    assert saved_state.get("type") == "stock"
    assert saved_state.get("published") == "yes"
    assert abs(saved_state.get("scrollY", 0) - 300) <= 2

    page.locator("#catalog a[data-i]").first.click()
    page.wait_for_url(
        re.compile(r"/stock\.html\?code=\d{6}(?:&|$)"),
        wait_until="domcontentloaded",
        timeout=20_000,
    )
    page.wait_for_function(
        "() => { const results = document.querySelector('#results'); "
        "return results !== null && !results.hidden; }",
        timeout=20_000,
    )
    page.go_back(wait_until="domcontentloaded")
    expect(page.locator("#catalog .cat-q")).to_be_visible(timeout=3_000)
    expect(
        page.locator('#catalog .cat-f[aria-label="类型"] button[data-v="stock"]')
    ).to_have_attribute("aria-pressed", "true")
    expect(
        page.locator('#catalog .cat-f[aria-label="结果"] button[data-v="yes"]')
    ).to_have_attribute("aria-pressed", "true")
    page.wait_for_function("Math.abs(window.scrollY - 300) <= 2")


@pytest.mark.e2e
def test_flow_3_stock_market_chart_and_scale_controls(page: Page) -> None:
    page.goto(f"{BASE_URL}/stock.html?code=600519")
    expect(page.locator("#stock-name")).to_contain_text("贵州茅台")
    market_canvas = page.locator("#market-plot")
    expect(market_canvas).to_be_visible()
    page.wait_for_function(
        """() => {
          const canvas = document.querySelector('#market-plot');
          if (!canvas || !canvas.width || !canvas.height) return false;
          const context = canvas.getContext('2d');
          if (!context) return false;
          const pixels = context.getImageData(0, 0, canvas.width, canvas.height).data;
          for (let i = 3; i < pixels.length; i += 4) if (pixels[i] !== 0) return true;
          return false;
        }"""
    )
    scales = page.locator("#stock-scales [role=radio]")
    expect(scales).to_have_count(6)
    expect(page.locator("#stock-rule-caption")).to_be_visible()
    expect(page.locator("#stock-rule-caption")).to_contain_text("FCO 标准过滤")
    expect(page.locator("#summary")).to_contain_text(
        "当前只算了 6–12 月、12–24 月两个尺度"
    )
    expect(page.locator("#risk")).to_contain_text("这个尺度尚未计算")
    empty_tiles = page.locator("#summary .sum-card.top .tiles .tile")
    expect(empty_tiles).to_have_count(3)
    for tile_index in (0, 1):
        tile = empty_tiles.nth(tile_index)
        expect(tile.locator("b")).to_have_text("无合格拟合")
        expect(tile.locator(".sub")).to_have_text(
            "已计算，没有合格拟合（不代表风险较低）"
        )
    for width, height in ((1440, 900), (390, 844)):
        page.set_viewport_size({"width": width, "height": height})
        line_counts = empty_tiles.locator("b").evaluate_all(
            """nodes => nodes.map(element => {
              const range = document.createRange();
              range.selectNodeContents(element);
              return range.getClientRects().length;
            })"""
        )
        assert len(line_counts) == 3 and max(line_counts) <= 2, line_counts
    page.locator('#stock-scales [data-scale="12-24m"]').click()
    expect(
        page.locator('#stock-scales [data-scale="12-24m"]')
    ).to_have_attribute("aria-checked", "true")


@pytest.mark.e2e
def test_flow_4_index_chip_updates_header(page: Page) -> None:
    page.goto(f"{BASE_URL}/index.html?code=sh000001")
    expect(page.locator("#sym-n")).to_contain_text("上证指数")
    page.locator('#ticker button[data-c="沪深300"]').click()
    expect(page.locator("#sym-n")).to_contain_text("沪深300")


@pytest.mark.e2e
def test_flow_5_backtest_alert_ledger_has_evidence_and_rows(page: Page) -> None:
    page.goto(f"{BASE_URL}/backtest.html")
    rows = page.locator("#alert-rows [role=row]")
    page.wait_for_function(
        "() => document.querySelectorAll('#alert-rows [role=row]').length > 0"
    )
    expect(rows.first).to_be_visible()
    evidence = page.locator("#alert-caveat").inner_text()
    assert "不代表通过检验" in evidence or "不是" in evidence


@pytest.mark.e2e
def test_backtest_recompute_notice_uses_history_metadata_in_scenario_and_strategy(page: Page) -> None:
    note = (
        "v2.2（指数 tcgrid_lm 与 de_lbfgsb 取小 SSE）于 2026-11 对三段历史重新计算，"
        "代码改动发生在看过这些历史之后；测试段结论仍以预登记的一次性结果为准（未通过）。"
        "旧版 v2.1 历史存档在 archive/。"
    )

    def add_recompute_metadata(route) -> None:
        response = route.fetch()
        payload = response.json()
        assert payload["model_version"] == "prereg_v1.7_v2.2"
        payload["recompute"] = {
            "label": "事后重算，不是样本外",
            "note": note,
            "replaces": "prereg_v1.7_v2.1",
        }
        route.fulfill(status=response.status, json=payload)

    page.route("**/lab/mock/data/sh000001_history.json", add_recompute_metadata)
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(f"{BASE_URL}/backtest.html?sym=sh000001#view=scenario")
    expect(page.locator("main.app")).to_be_visible()
    expect(page.locator("#recompute-notice")).to_be_visible()
    expect(page.locator("#recompute-label")).to_have_text("事后重算，不是样本外")
    page.locator("#recompute-notice summary").click()
    expect(page.locator("#recompute-text")).to_have_text(note)

    page.locator('.bt-views a[data-view="strategy"]').click()
    expect(page.locator("#strategy-view")).to_be_visible()
    expect(page.locator("#recompute-notice")).to_be_visible()
    expect(page.locator("#recompute-label")).to_have_text("事后重算，不是样本外")


@pytest.mark.e2e
def test_flow_6_market_summary_and_news_leave_loading_state(page: Page) -> None:
    lhb_fixture = Path(__file__).resolve().parents[2] / "frontend" / "tests" / "fixtures" / "lhb_seats_latest.json"
    page.route(
        "**/lab/mock/data/market/lhb_seats_latest.json",
        lambda route: route.fulfill(path=str(lhb_fixture)),
    )
    page.route(
        "**/lab/mock/data/market/breadth_latest.json",
        lambda route: route.fulfill(path=str(BREADTH_FIXTURE)),
    )
    page.set_viewport_size({"width": 1280, "height": 900})
    page.goto(f"{BASE_URL}/market.html")
    expect(page.locator("#s-lhb-seats")).to_be_visible()
    expect(page.locator("#lhb-seats-body .lhb-card.buy strong")).to_contain_text("12.30亿")
    seat_rows = page.locator("#lhb-seats-body .lhb-table tbody tr")
    expect(seat_rows).to_have_count(4)
    expect(seat_rows.first).to_contain_text("游资甲")
    expect(seat_rows.first.locator("td").first).to_have_text("1")
    expect(page.locator("#lhb-seats-body .lhb-meta")).to_contain_text("样本 34 只（单日榜 28 / 多日榜 6）")
    expect(page.locator("#lhb-seats-body .lhb-more")).to_contain_text("+1笔")
    assistant_button = page.locator(".ai-btn")
    if assistant_button.get_attribute("aria-expanded") != "true":
        assistant_button.click()
    expect(assistant_button).to_have_attribute("aria-expanded", "true")
    expect(page.locator(".ai-panel.ai-dock")).to_be_visible()
    assert page.locator("#s-lhb-seats").evaluate(
        "(section) => section.scrollWidth <= section.clientWidth + 1"
    )
    assert seat_rows.first.locator("td").last.evaluate(
        """(cell) => {
          const viewport = cell.closest('.table-scroll').getBoundingClientRect();
          return cell.getBoundingClientRect().right <= viewport.right + 1;
        }"""
    )
    page.wait_for_function(
        """() => {
          const summary = document.querySelector('#today-summary');
          if (!summary) return false;
          const rows = summary.querySelectorAll('.summary-row').length;
          return rows >= 4 || /缺数据|数据不全|不可用|未发布/.test(summary.innerText);
        }""",
        timeout=12_000,
    )
    summary = page.locator("#today-summary")
    rows = summary.locator(".summary-row").count()
    summary_text = summary.inner_text()
    assert rows >= 4 or re.search(
        r"缺数据|数据不全|不可用|未发布", summary_text
    )

    page.wait_for_function(
        """() => {
          const news = document.querySelector('#news-body');
          if (!news) return false;
          const text = news.innerText.trim();
          return !text.includes('加载中') &&
            (news.querySelector('.news-card') || news.querySelector('.news-status') ||
             /暂无|不可用|未发布|数据/.test(text));
        }""",
        timeout=12_000,
    )
    news = page.locator("#news-body")
    assert "加载中" not in news.inner_text()
    assert (
        news.locator(".news-card").count() > 0
        or news.locator(".news-status").count() > 0
        or re.search(r"暂无|不可用|未发布|数据", news.inner_text())
    )
    breadth = page.locator("#s-breadth")
    page.wait_for_function(
        "() => document.querySelector('#breadth-body')?.innerText.includes('0.34')"
    )
    expect(breadth).to_have_attribute("data-ai-context", "宽度与资金")
    expect(breadth.locator("#breadth-body")).to_contain_text("52.5%")
    expect(breadth.locator("#breadth-body")).to_contain_text("14.7%")
    expect(breadth.locator("#breadth-body")).to_contain_text("8.1%")
    expect(breadth.locator("#breadth-body")).to_contain_text("预警规则回测中，暂不显示")
    expect(breadth.locator(".breadth-basis-table tbody tr")).to_have_count(4)
    expect(
        breadth.locator(".breadth-basis-table tbody tr").first.locator("td").nth(4)
    ).to_have_text("20.00")
    expect(breadth.locator(".breadth-history-table tbody tr")).to_have_count(1)
    page.set_viewport_size({"width": 390, "height": 844})
    dimensions = page.evaluate(
        "() => ({scrollWidth: document.documentElement.scrollWidth, innerWidth})"
    )
    assert dimensions["scrollWidth"] <= dimensions["innerWidth"] + 1, dimensions
    assert page.locator("#s-breadth .table-scroll").count() == 2


@pytest.mark.e2e
def test_flow_7_mortgage_calculator_shows_monthly_payment(page: Page) -> None:
    page.goto(f"{BASE_URL}/tools.html")
    page.locator('[data-tool="loan"]').click()
    expect(page.locator("#dlg")).to_be_visible()
    page.locator("#l-p").fill("1000000")
    page.locator("#l-y").fill("30")
    page.locator("#l-r").fill("3.1")
    output = page.locator("#l-out")
    expect(output).to_contain_text("月供")
    assert re.search(r"首月\s+[\d,]+\.\d{2}\s+元", output.inner_text())


@pytest.mark.e2e
def test_overflow_1_home_page(page: Page) -> None:
    assert_page_has_no_overflow(page, "home.html")


@pytest.mark.e2e
def test_home_sparklines_share_domain_and_persist_selected_period(page: Page) -> None:
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(f"{BASE_URL}/home.html")
    page.wait_for_function(
        "() => document.querySelectorAll('#rows a.row svg.sparkline[data-y-domain]').length === 7"
    )
    range_button = page.locator('#spark-range button[data-spark-range="60"]')
    expect(range_button).to_have_attribute("aria-pressed", "true")
    expect(page.locator("#pfn")).to_contain_text(
        "迷你走势：同一纵轴、起点归零的涨跌幅，最近 60 个交易日收盘"
    )

    def assert_shared_domain() -> None:
        domains = page.locator("#rows svg.sparkline").evaluate_all(
            "(items) => items.map(item => item.dataset.yDomain)"
        )
        assert len(domains) == 7 and len(set(domains)) == 1, domains
        minimum, maximum = (float(value) for value in domains[0].split(","))
        assert minimum < 0 < maximum

    assert_shared_domain()
    page.evaluate("localStorage.setItem('lppl.home.sparkRange', 'invalid')")
    page.reload()
    page.wait_for_function(
        "() => document.querySelectorAll('#rows a.row svg.sparkline').length === 7"
    )
    expect(page.locator('#spark-range button[data-spark-range="60"]')).to_have_attribute(
        "aria-pressed", "true"
    )
    assert_shared_domain()

    old_paths = page.locator("#rows svg.sparkline path.spark-line").evaluate_all(
        "(items) => items.map(item => item.getAttribute('d'))"
    )
    index_symbols = (
        "sh000001",
        "sh000016",
        "sh000300",
        "sh000905",
        "sh000688",
        "sz399001",
        "sz399006",
    )

    def index_loads() -> int:
        return sum(
            1
            for _, url, source in page._e2e_requests
            if source == "/home.html"
            and any(f"/{symbol}_latest.json" in url for symbol in index_symbols)
        )

    loads_before = index_loads()
    page.locator('#spark-range button[data-spark-range="250"]').click()
    expect(page.locator('#spark-range button[data-spark-range="250"]')).to_have_attribute(
        "aria-pressed", "true"
    )
    expect(page.locator("#pfn")).to_contain_text(
        "迷你走势：同一纵轴、起点归零的涨跌幅，最近 250 个交易日收盘"
    )
    new_paths = page.locator("#rows svg.sparkline path.spark-line").evaluate_all(
        "(items) => items.map(item => item.getAttribute('d'))"
    )
    assert len(old_paths) == len(new_paths) == 7
    assert all(
        old != new for old, new in zip(old_paths, new_paths, strict=True)
    ), (old_paths, new_paths)
    assert index_loads() == loads_before, "Changing the period should reuse loaded bars"
    assert_shared_domain()
    assert page.evaluate("localStorage.getItem('lppl.home.sparkRange')") == "250"

    page.reload()
    page.wait_for_function(
        "() => document.querySelectorAll('#rows a.row svg.sparkline').length === 7"
    )
    expect(page.locator('#spark-range button[data-spark-range="250"]')).to_have_attribute(
        "aria-pressed", "true"
    )
    expect(page.locator("#pfn")).to_contain_text("最近 250 个交易日收盘")
    assert_shared_domain()

    for width, height in ((1440, 900), (1024, 768), (390, 844)):
        page.set_viewport_size({"width": width, "height": height})
        dimensions = page.evaluate(
            "() => ({scrollWidth: document.documentElement.scrollWidth, innerWidth})"
        )
        assert dimensions["scrollWidth"] <= dimensions["innerWidth"] + 1, (width, dimensions)


@pytest.mark.e2e
def test_home_spark_range_change_preserves_live_quote(page: Page) -> None:
    page.add_init_script(
        """(() => {
          const originalFetch = window.fetch.bind(window);
          window.fetch = (input, init) => {
            const url = typeof input === "string" ? input : input.url;
            if (url.includes("/quote?codes=")) {
              return Promise.resolve(new Response(JSON.stringify({
                source: "e2e",
                quotes: {
                  sh000001: {
                    price: 4321.23,
                    pct: 1.25,
                    time: "20261113103000",
                    tz: "Asia/Shanghai"
                  }
                },
                missing: []
              }), {
                status: 200,
                headers: { "Content-Type": "application/json" }
              }));
            }
            return originalFetch(input, init);
          };
        })();"""
    )
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(f"{BASE_URL}/home.html")
    page.wait_for_function(
        "() => document.querySelector('#rows a.row[data-sym=\"sh000001\"] .p')"
        "?.textContent.includes('4321.23')"
    )

    row = page.locator('#rows a.row[data-sym="sh000001"]')
    expect(page.locator('#spark-range button[data-spark-range="60"]')).to_have_attribute(
        "aria-pressed", "true"
    )
    expect(row.locator(".p")).to_contain_text("4321.23")
    expect(row.locator(".quote-time")).to_have_text("报价 11-13 10:30")
    assert "近3月" in (row.get_attribute("aria-label") or "")

    page.locator('#spark-range button[data-spark-range="250"]').click()

    expect(row.locator(".p")).to_contain_text("4321.23")
    expect(row.locator(".quote-time")).to_have_text("报价 11-13 10:30")
    label = row.get_attribute("aria-label") or ""
    assert "近1年" in label
    assert "报价 11-13 10:30" in label


@pytest.mark.e2e
def test_overflow_2_stock_catalog(page: Page) -> None:
    assert_page_has_no_overflow(page, "stock.html")


@pytest.mark.e2e
def test_overflow_3_stock_detail(page: Page) -> None:
    assert_page_has_no_overflow(page, "stock.html?code=600519")


@pytest.mark.e2e
def test_overflow_4_index_page(page: Page) -> None:
    assert_page_has_no_overflow(page, "index.html?code=sh000001")


@pytest.mark.e2e
def test_overflow_5_backtest_page(page: Page) -> None:
    assert_page_has_no_overflow(page, "backtest.html")


@pytest.mark.e2e
def test_overflow_6_market_page(page: Page) -> None:
    assert_page_has_no_overflow(page, "market.html")


@pytest.mark.e2e
def test_overflow_7_tools_page(page: Page) -> None:
    assert_page_has_no_overflow(page, "tools.html")


@pytest.mark.e2e
def test_overflow_8_chart_page(page: Page) -> None:
    assert_page_has_no_overflow(page, "chart.html?code=sh601838&scale=6-12m")


@pytest.mark.e2e
def test_flow_8_chart_band_and_same_origin_back_link(page: Page) -> None:
    page.goto(f"{BASE_URL}/chart.html?code=sh601838&scale=6-12m")
    row = page.locator("#interval-list .interval-row").first
    expect(row).to_be_visible()
    row.click()
    expect(row).to_have_attribute("aria-pressed", "true")
    href = page.locator("#return-link").get_attribute("href")
    assert href
    return_origin = page.evaluate(
        "(href) => new URL(href, location.href).origin", href
    )
    assert return_origin == urlsplit(page.url).scheme + "://" + urlsplit(page.url).netloc


@pytest.mark.e2e
def test_desktop_sidebar_and_docked_assistant(page: Page) -> None:
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(f"{BASE_URL}/index.html?code=sh000001")
    sidebar = page.locator(".odn-sidebar")
    expect(sidebar).to_be_visible()
    expect(page.locator(".odn-side-main")).to_have_count(5)
    assistant = page.locator(".ai-panel.ai-dock")
    expect(assistant).to_be_visible()
    sidebar_box = sidebar.bounding_box()
    assistant_box = assistant.bounding_box()
    content_box = page.locator("header.odn").bounding_box()
    assert sidebar_box and assistant_box and content_box
    assert abs(sidebar_box["x"]) <= 1 and abs(sidebar_box["width"] - 208) <= 1
    assert abs(assistant_box["x"] - 208) <= 1 and abs(assistant_box["width"] - 340) <= 1
    assert assistant_box["x"] + assistant_box["width"] <= content_box["x"] + 1
    assert content_box["x"] >= 572


@pytest.mark.e2e
def test_home_assistant_switch_persists_without_changing_other_page_defaults(page: Page) -> None:
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(f"{BASE_URL}/home.html")
    page.evaluate("localStorage.removeItem('lppl.assistant.home')")
    page.reload()
    panel = page.locator(".ai-panel.ai-dock")
    switch = page.locator(".ai-switch")
    expect(switch).to_have_attribute("role", "switch")
    expect(panel).to_be_hidden()
    expect(switch).to_have_attribute("aria-checked", "false")
    main_left = page.locator("main").evaluate("(el) => el.getBoundingClientRect().left")
    assert main_left < 300, main_left

    page.evaluate("localStorage.setItem('lppl.assistant.home', 'invalid')")
    page.reload()
    expect(panel).to_be_hidden()
    expect(switch).to_have_attribute("aria-checked", "false")

    switch.click()
    expect(panel).to_be_visible()
    expect(switch).to_have_attribute("aria-checked", "true")
    panel_box = panel.bounding_box()
    assert panel_box and abs(panel_box["x"] - 208) <= 1 and abs(panel_box["width"] - 340) <= 1
    main_left = page.locator("main").evaluate("(el) => el.getBoundingClientRect().left")
    assert main_left >= 572, main_left

    page.reload()
    expect(panel).to_be_visible()
    expect(switch).to_have_attribute("aria-checked", "true")
    switch.click()
    expect(panel).to_be_hidden()
    expect(switch).to_have_attribute("aria-checked", "false")
    assert page.evaluate("localStorage.getItem('lppl.assistant.home')") == "0"

    for width, height in ((390, 844), (1024, 768), (1440, 900)):
        page.set_viewport_size({"width": width, "height": height})
        page.goto(f"{BASE_URL}/home.html")
        if width < 1200:
            expect(page.locator(".ai-panel")).to_be_hidden()
            expect(switch).to_be_hidden()
        dimensions = page.evaluate(
            "() => ({scrollWidth: document.documentElement.scrollWidth, innerWidth})"
        )
        assert dimensions["scrollWidth"] <= dimensions["innerWidth"] + 1, (width, dimensions)

    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(f"{BASE_URL}/index.html?code=sh000001")
    expect(page.locator(".ai-panel.ai-dock")).to_be_visible()
    page.evaluate("localStorage.setItem('lppl.assistant.home', '1')")
    page.reload()
    expect(page.locator(".ai-panel.ai-dock")).to_be_visible()


@pytest.mark.e2e
def test_chart_assistant_switch_defaults_closed_and_persists(page: Page) -> None:
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(f"{BASE_URL}/chart.html?code=sh000001")
    panel = page.locator(".ai-panel.ai-dock")
    switch = page.locator(".ai-switch")
    expect(panel).to_be_hidden()
    expect(switch).to_be_visible()
    expect(switch).to_have_attribute("role", "switch")
    expect(switch).to_have_attribute("aria-checked", "false")
    assert page.evaluate("getComputedStyle(document.body).paddingLeft") == "208px"
    assert page.locator("main").evaluate("(el) => el.getBoundingClientRect().left") < 300

    switch.click()
    expect(panel).to_be_visible()
    expect(switch).to_have_attribute("aria-checked", "true")
    assert page.evaluate("getComputedStyle(document.body).paddingLeft") == "572px"
    assert page.locator("main").evaluate("(el) => el.getBoundingClientRect().left") >= 572
    assert page.evaluate(
        "localStorage.getItem('lppl.assistant.wide:chart.html')"
    ) == "1"

    page.reload()
    expect(panel).to_be_visible()
    expect(switch).to_have_attribute("aria-checked", "true")


@pytest.mark.e2e
def test_index_assistant_close_button_persists_wide_preference(page: Page) -> None:
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(f"{BASE_URL}/index.html?code=sh000001")
    panel = page.locator(".ai-panel.ai-dock")
    switch = page.locator(".ai-switch")
    close = page.get_by_role("button", name="关闭研究助手")
    expect(panel).to_be_visible()
    expect(switch).to_have_attribute("aria-checked", "true")
    expect(close).to_be_visible()

    close.click()
    expect(panel).to_be_hidden()
    expect(switch).to_have_attribute("aria-checked", "false")
    assert page.evaluate(
        "localStorage.getItem('lppl.assistant.wide:index.html')"
    ) == "0"

    page.reload()
    expect(panel).to_be_hidden()
    expect(switch).to_have_attribute("aria-checked", "false")


@pytest.mark.e2e
def test_chart_replay_asof_is_visible_and_links_keep_the_cutoff(page: Page) -> None:
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(f"{BASE_URL}/chart.html?code=sh000001&asof=2015-06-12")
    page.wait_for_function(
        "() => document.querySelector('#chart-page')?.dataset.loaded === 'true'"
    )
    expect(page.locator("#asof-tag")).to_have_text(
        "历史截止日 2015-06-12 · 封存回放"
    )
    expect(page.locator("#model-date")).to_have_text("模型日期 2015-06-12")
    assert page.locator("#index-replay").get_attribute("href") == (
        "index.html?code=sh000001&asof=2015-06-12"
    )

    page.goto(f"{BASE_URL}/index.html?code=sh000001&asof=2015-06-12")
    chart_href = page.locator(".odn-chart-link").get_attribute("href")
    assert chart_href and "asof=2015-06-12" in chart_href


@pytest.mark.e2e
def test_chart_renders_market_bars_when_latest_model_is_missing(page: Page) -> None:
    page.set_viewport_size({"width": 1440, "height": 900})
    page.route(
        "**/lab/mock/data/stock/600519.json",
        lambda route: route.fulfill(status=404, content_type="application/json", body="{}"),
    )
    page.goto(
        f"{BASE_URL}/chart.html?code=sh600519"
    )
    page.wait_for_function(
        "() => document.querySelector('#chart-page')?.dataset.loaded === 'true'"
    )

    chart_page = page.locator("#chart-page")
    assert int(chart_page.get_attribute("data-bar-count") or "0") > 0
    expect(chart_page).to_have_attribute("data-model-status", "missing")
    expect(page.locator("#evidence-state")).to_have_text(
        "没有读到已发布的模型结果（可能尚未发布，或读取失败）"
    )
    expect(page.locator("#interval-list .interval-row")).to_have_count(0)
    expect(page.locator("#model-date")).to_have_text("模型日期 未读到")
    retry = page.locator("#evidence-note .evidence-retry-button")
    expect(retry).to_have_text("重试读取")
    expect(retry).to_be_visible()
    expect(page.locator("#evidence-note a")).to_have_text("回标的页发起计算")
    expect(page.locator("#evidence-note a")).to_have_attribute(
        "href", "stock.html?code=600519"
    )
    expect(page.locator("#asof-notice")).to_be_hidden()
    with page.expect_response("**/lab/mock/data/stock/600519.json") as retry_response:
        retry.click()
    assert retry_response.value.status == 404


@pytest.mark.e2e
def test_stock_historical_cutoff_never_falls_back_to_latest(page: Page) -> None:
    page.route(
        "**/lab/mock/data/stock/600519_history.json",
        lambda route: route.fulfill(
            status=200, content_type="application/json",
            body='{"symbol":"sh600519","frames":[]}',
        ),
    )
    page.goto(f"{BASE_URL}/chart.html?code=sh600519&asof=2015-06-12")
    expect(page.locator("#error-panel")).to_be_visible()
    expect(page.locator("#chart-page")).not_to_have_attribute("data-loaded", "true")
    expect(page.locator("#interval-list .interval-row")).to_have_count(0)
    assert not any(method == "POST" for method, _, _ in page._e2e_requests)


@pytest.mark.e2e
def test_assistant_top_and_content_clearance_across_pages(page: Page) -> None:
    for path in NAV_PAGES:
        page.set_viewport_size({"width": 1440, "height": 900})
        page.goto(f"{BASE_URL}/{path}")
        panel = page.locator(".ai-panel")
        content_left = page.evaluate(
            """() => {
              const el = document.body.classList.contains('vs-home')
                ? document.querySelector('.hero-copy')
                : document.querySelector('main') || document.querySelector('h1');
              return el && el.getBoundingClientRect().left;
            }"""
        )
        assert content_left is not None, path
        if path == "home.html" or path.startswith("chart.html"):
            expect(panel).to_be_hidden()
            assert content_left < 300, (path, content_left)
        else:
            expect(panel).to_be_visible()
            panel_box = panel.bounding_box()
            head_box = page.locator(".ai-head").bounding_box()
            assert panel_box and head_box, path
            assert abs(panel_box["y"]) <= 1 and abs(head_box["y"]) <= 1, (path, panel_box, head_box)
            assert content_left >= panel_box["x"] + panel_box["width"] + 23, (path, content_left)

        page.set_viewport_size({"width": 390, "height": 844})
        page.locator('.odn-mobile-toggle button[data-mode="assistant"]').click()
        panel_box = panel.bounding_box()
        head_box = page.locator(".ai-head").bounding_box()
        assert panel_box and head_box, path
        assert abs(panel_box["y"] - 52) <= 1 and abs(head_box["y"] - 52) <= 1, (
            path,
            panel_box,
            head_box,
        )


@pytest.mark.e2e
def test_desktop_navigation_pages_have_no_horizontal_overflow(page: Page) -> None:
    page.set_viewport_size({"width": 1440, "height": 900})
    for path in NAV_PAGES:
        page.goto(f"{BASE_URL}/{path}")
        page.wait_for_timeout(100)
        dimensions = page.evaluate(
            "() => ({scrollWidth: document.documentElement.scrollWidth, innerWidth})"
        )
        assert dimensions["scrollWidth"] <= dimensions["innerWidth"] + 1, (path, dimensions)


@pytest.mark.e2e
def test_tablet_sidebar_and_assistant_drawer(page: Page) -> None:
    page.set_viewport_size({"width": 1024, "height": 768})
    page.goto(f"{BASE_URL}/home.html")
    expect(page.locator(".odn-sidebar")).to_be_visible()
    expect(page.locator(".odn-side-main")).to_have_count(5)
    expect(page.locator(".ai-panel")).to_be_hidden()
    assistant_button = page.locator(".odn-r .ai-btn")
    expect(assistant_button).to_be_visible()
    assistant_button.click()
    expect(page.locator(".ai-panel")).to_be_visible()
    expect(page.locator(".ai-panel.ai-dock")).to_have_count(0)


@pytest.mark.e2e
def test_backtest_sidebar_links_switch_views(page: Page) -> None:
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(f"{BASE_URL}/backtest.html?sym=sh000001")
    bench = page.locator(
        '.odn-sidebar .odn-side-link[href="backtest.html#view=bench"]'
    )
    strategy = page.locator(
        '.odn-sidebar .odn-side-link[href="backtest.html#view=strategy"]'
    )
    replay = page.locator(
        '.odn-sidebar .odn-side-link[href="backtest.html#view=scenario"]'
    )
    bench.click()
    expect(page.locator("#bench-view")).to_be_visible()
    expect(page).to_have_url(re.compile(r"/backtest\.html\?sym=sh000001#view=bench$"))
    page.wait_for_function(
        "() => document.querySelectorAll('#bench-panel tbody tr').length > 0"
    )
    expect(bench).to_have_attribute("aria-current", "location")
    expect(page.locator('.bt-views a[data-view="bench"]')).to_have_attribute(
        "aria-current", "location"
    )
    strategy.click()
    expect(page.locator("#strategy-view")).to_be_visible()
    expect(page.locator("main.app")).to_be_hidden()
    expect(strategy).to_have_attribute("aria-current", "location")
    expect(page.locator('.bt-views a[data-view="strategy"]')).to_have_attribute(
        "aria-current", "location"
    )
    replay.click()
    expect(page.locator("#strategy-view")).to_be_hidden()
    expect(page.locator("main.app")).to_be_visible()
    expect(replay).to_have_attribute("aria-current", "location")
    expect(page.locator('.bt-views a[data-view="scenario"]')).to_have_attribute(
        "aria-current", "location"
    )


@pytest.mark.e2e
def test_guide_navigation_loads_and_escape_closes_help(page: Page) -> None:
    page.set_viewport_size({"width": 1440, "height": 900})
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(f"{BASE_URL}/guide.html")
    expect(page.locator("header.odn")).to_be_visible()
    assert not errors, errors
    help_menu = page.locator(".odn-help")
    help_menu.locator("summary").click()
    expect(help_menu).to_have_attribute("open", "")
    page.keyboard.press("Escape")
    expect(help_menu).not_to_have_attribute("open", "")


@pytest.mark.e2e
def test_mobile_navigation_fits_and_drives_fullscreen_assistant(page: Page) -> None:
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"{BASE_URL}/home.html")
    entries = page.locator(".odn-main a")
    expect(entries).to_have_count(5)
    bounds = entries.evaluate_all(
        "(items) => items.map((item) => { const r = item.getBoundingClientRect(); return [r.left, r.right]; })"
    )
    assert all(left >= -1 and right <= 391 for left, right in bounds), bounds
    dimensions = page.evaluate(
        "() => ({scrollWidth: document.documentElement.scrollWidth, innerWidth})"
    )
    assert dimensions["scrollWidth"] <= dimensions["innerWidth"] + 1, dimensions
    expect(page.locator(".ai-btn")).to_be_hidden()

    page.locator('.odn-mobile-toggle button[data-mode="assistant"]').click()
    panel = page.locator(".ai-panel")
    expect(panel).to_be_visible()
    expect(page.locator('.odn-mobile-toggle button[data-mode="assistant"]')).to_have_attribute(
        "aria-pressed", "true"
    )
    panel_box = panel.bounding_box()
    assert panel_box and abs(panel_box["x"]) <= 1 and abs(panel_box["width"] - 390) <= 1
    assert abs(panel_box["y"] - 52) <= 1 and abs(panel_box["height"] - 792) <= 1
    page.locator('.odn-mobile-toggle button[data-mode="data"]').click()
    expect(panel).to_be_hidden()
    dimensions = page.evaluate(
        "() => ({scrollWidth: document.documentElement.scrollWidth, innerWidth})"
    )
    assert dimensions["scrollWidth"] <= dimensions["innerWidth"] + 1, dimensions
    page.set_viewport_size({"width": 360, "height": 844})
    bounds = entries.evaluate_all(
        "(items) => items.map((item) => { const r = item.getBoundingClientRect(); return [r.left, r.right]; })"
    )
    assert all(left >= -1 and right <= 361 for left, right in bounds), bounds
    dimensions = page.evaluate(
        "() => ({scrollWidth: document.documentElement.scrollWidth, innerWidth})"
    )
    assert dimensions["scrollWidth"] <= dimensions["innerWidth"] + 1, dimensions


@pytest.mark.e2e
def test_tools_assistant_mounts_without_main_container(page: Page) -> None:
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"{BASE_URL}/tools.html")
    page.locator('.odn-mobile-toggle button[data-mode="assistant"]').click()
    panel = page.locator(".ai-panel")
    expect(panel).to_be_visible()
    box = panel.bounding_box()
    assert box and abs(box["y"] - 52) <= 1 and abs(box["height"] - 792) <= 1
    page.locator('.odn-mobile-toggle button[data-mode="data"]').click()
    expect(panel).to_be_hidden()


@pytest.mark.e2e
def test_stock_page_uses_general_asset_copy(page: Page) -> None:
    page.goto(f"{BASE_URL}/stock.html")
    expect(page.locator(".hero .eyebrow")).to_have_text("标的 · 指数 / 行业 / 个股")
    expect(page.locator(".hero h1")).to_have_text("查标的")
    expect(page.locator(".hero .lead")).to_contain_text(
        "输入指数、股票代码、名称或拼音首字母"
    )
    expect(page).to_have_title("临界点 · 标的")
    description = page.locator('meta[name="description"]').get_attribute("content")
    assert description and "输入指数、股票代码" in description and "个股日线" not in description


@pytest.mark.e2e
def test_rule_labels_index_and_chart_evidence(page: Page) -> None:
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(f"{BASE_URL}/index.html?code=sh000001")
    expect(page.locator("#ph-tip")).to_contain_text("形态框")
    expect(page.locator("#ph-tip")).to_contain_text("FCO 标准过滤")
    expect(page.locator("#ph-tip")).to_contain_text(
        "两者来自同一批拟合窗口、不同过滤规则；不是两套互相印证的结论。占比不是概率。"
    )
    page.locator("#bt-1").click()
    expert = page.locator("#p-expert")
    expect(expert).to_be_visible()
    fit_count = expert.locator("th[title]")
    expect(fit_count).to_have_attribute("title", re.compile("FCO 标准过滤"))
    expect(fit_count).to_have_attribute("aria-label", re.compile("合格拟合数"))
    expect(expert).to_contain_text(
        "两者来自同一批拟合窗口、不同过滤规则；不是两套互相印证的结论。占比不是概率。"
    )

    page.goto(f"{BASE_URL}/chart.html?code=sh000001")
    page.wait_for_function(
        "() => document.querySelector('#chart-page')?.dataset.loaded === 'true'"
    )
    source = page.locator("#evidence-rule-source")
    expect(source).to_be_visible()
    expect(source).to_have_text("区间来源：形态框规则（不含振荡/阻尼条件）")
    expect(page).to_have_title("完整图表 · 临界点")


@pytest.mark.e2e
def test_legacy_three_segment_hash_redirects_to_bench_view(page: Page) -> None:
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(f"{BASE_URL}/index.html?code=sh000001&asof=2007-10-12#p-bench")
    page.wait_for_url(re.compile(r"/backtest\.html\?sym=sh000001#view=bench$"))
    expect(page.locator("#bench-view")).to_be_visible()
    expect(page.locator('.odn-sidebar a[href="backtest.html#view=bench"]')).to_have_attribute(
        "aria-current", "location"
    )
    assert not any(
        re.search(r"/(?:replay|request)(?:/|$)", urlsplit(url).path, re.I)
        for _, url, _ in page._e2e_requests
    )


@pytest.mark.e2e
def test_backtest_bench_loads_latest_fixture_without_replay_or_overflow(page: Page) -> None:
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(f"{BASE_URL}/backtest.html?sym=sh000001#view=bench")
    expect(page.locator("#bench-view")).to_be_visible()
    page.wait_for_function(
        "() => document.querySelectorAll('#bench-panel tbody tr').length > 0"
    )
    assert any(
        method == "GET" and "sh000001_latest.json" in url
        for method, url, _ in page._e2e_requests
    )
    assert not any(
        re.search(r"/(?:replay|request)(?:/|$)", urlsplit(url).path, re.I)
        for _, url, _ in page._e2e_requests
    )
    expect(page.locator('.odn-sidebar a[href="backtest.html#view=bench"]')).to_have_attribute(
        "aria-current", "location"
    )
    for width, height in ((1440, 900), (1024, 768), (390, 844)):
        page.set_viewport_size({"width": width, "height": height})
        dimensions = page.evaluate(
            "() => ({scrollWidth: document.documentElement.scrollWidth, innerWidth})"
        )
        assert dimensions["scrollWidth"] <= dimensions["innerWidth"] + 1, dimensions
        layout = page.evaluate(
            """() => {
              const wrapper = document.querySelector('#bench-panel .scroll-x');
              const table = wrapper.querySelector('table');
              const tableBox = table.getBoundingClientRect();
              const wrapperBox = wrapper.getBoundingClientRect();
              const isContained = (container, group) => {
                const containerBox = container.getBoundingClientRect();
                return [...group.children].every(item => {
                  const itemBox = item.getBoundingClientRect();
                  return itemBox.left >= containerBox.left - 1
                    && itemBox.right <= containerBox.right + 1;
                });
              };
              return {
                tableRight: tableBox.right,
                wrapperRight: wrapperBox.right,
                overflowX: getComputedStyle(wrapper).overflowX,
                scrollWidth: wrapper.scrollWidth,
                clientWidth: wrapper.clientWidth,
                symbolsFit: isContained(document.querySelector('.odn-sub'), document.querySelector('#syms')),
                rangesFit: isContained(document.querySelector('.odn-tools'), document.querySelector('#ranges')),
              };
            }"""
        )
        fits = layout["tableRight"] <= layout["wrapperRight"] + 1
        scrollable = (
            layout["overflowX"] in {"auto", "scroll"}
            and layout["scrollWidth"] > layout["clientWidth"]
        )
        assert fits or scrollable, layout
        assert layout["symbolsFit"] and layout["rangesFit"], layout


@pytest.mark.e2e
def test_bench_ai_context_contains_visible_table_and_respects_limit(page: Page) -> None:
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(f"{BASE_URL}/backtest.html?sym=sh000001")
    expect(page.locator(".ai-panel.ai-dock")).to_be_visible()
    expect(page.locator(".app")).to_be_visible()

    def ask_context() -> str:
        with page.expect_request(
            lambda request: request.method == "POST"
            and urlsplit(request.url).path == "/ai"
        ) as request_info:
            page.locator(".ai-form textarea").fill("请解释三段验证")
            page.locator('.ai-form button[type="submit"]').click()
        context = request_info.value.post_data_json["context"]
        expect(page.locator('.ai-form button[type="submit"]')).to_be_enabled()
        return context

    scenario_context = ask_context()
    assert "开发段：" in scenario_context
    assert "开发段 2000" not in scenario_context
    assert len(scenario_context) <= 8000

    page.locator('.bt-views a[data-view="bench"]').click()
    expect(page.locator("#bench-view")).to_be_visible()
    page.wait_for_function(
        "() => document.querySelectorAll('#bench-panel tbody tr').length > 0"
    )
    bench_context = ask_context()
    assert "开发段 2000" in bench_context
    assert len(bench_context) <= 8000


@pytest.mark.e2e
def test_market_defaults_to_today_highlight_at_scroll_top(page: Page) -> None:
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(f"{BASE_URL}/market.html")
    assert page.evaluate("window.scrollY") == 0
    expect(page.locator('.odn-sidebar .odn-side-link[href="market.html#s-news"]')).to_have_attribute(
        "aria-current", "location"
    )
    expect(page.locator('.odn-l2 .odn-sub a[href="#s-news"]')).to_have_attribute(
        "aria-current", "location"
    )


@pytest.mark.e2e
def test_market_group_tabs_follow_anchor_ids(page: Page) -> None:
    page.goto(f"{BASE_URL}/market.html")
    tabs = page.locator(".odn-sub a.odn-t")
    expect(tabs).to_have_count(4)
    emotion_tab = tabs.filter(has_text="情绪")
    emotion_tab.click()
    expect(page.locator("#s-limit")).to_be_visible()
    expect(emotion_tab).to_have_attribute("aria-current", "location")
    expect(
        page.locator(".odn-sidebar .odn-side-link").filter(has_text="情绪")
    ).to_have_attribute("aria-current", "location")
