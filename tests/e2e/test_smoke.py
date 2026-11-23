from __future__ import annotations

import base64
import json
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlsplit

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
VALUATION_FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "tests"
    / "fixtures"
    / "market"
    / "valuation_percentiles.json"
)
TOP_RISK_FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "frontend"
    / "tests"
    / "fixtures"
    / "top_risk_latest.json"
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


def drawing_pixel_diff(
    page: Page, first: bytes, second: bytes, *, chart_only: bool = False
) -> dict[str, int]:
    images = [base64.b64encode(first).decode("ascii"), base64.b64encode(second).decode("ascii")]
    return page.evaluate(
        """async ([leftPng, rightPng, chartOnly]) => {
          async function pixels(value) {
            const image = await createImageBitmap(await fetch('data:image/png;base64,' + value).then(r => r.blob()));
            const canvas = document.createElement('canvas');
            canvas.width = image.width; canvas.height = image.height;
            const context = canvas.getContext('2d');
            context.drawImage(image, 0, 0);
            return { width:image.width, height:image.height, data:context.getImageData(0, 0, image.width, image.height).data };
          }
          const left = await pixels(leftPng), right = await pixels(rightPng);
          if (left.width !== right.width || left.height !== right.height) return { changed:-1, width:left.width, height:left.height };
          let changed = 0;
          const x0 = Math.floor(left.width * 0.04), x1 = Math.floor(left.width * 0.96);
          const y0 = Math.floor(left.height * (chartOnly ? 0.44 : 0.12)), y1 = Math.floor(left.height * 0.94);
          for (let y = y0; y < y1; y++) for (let x = x0; x < x1; x++) {
            const i = (y * left.width + x) * 4;
            if (Math.abs(left.data[i] - right.data[i]) +
                Math.abs(left.data[i + 1] - right.data[i + 1]) +
                Math.abs(left.data[i + 2] - right.data[i + 2]) > 45) changed++;
          }
          return { changed, width:left.width, height:left.height };
        }""",
        images + [chart_only],
    )


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
    for tile_index, label, reason in (
        (0, "未形成区间", "有合格拟合，但没有形成聚类区间"),
        (1, "无合格拟合", "已计算，没有合格拟合（不代表风险较低）"),
    ):
        tile = empty_tiles.nth(tile_index)
        expect(tile.locator("b")).to_have_text(label)
        expect(tile.locator(".sub")).to_have_text(reason)
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
def test_chart_30m_obv_renders_worker_fixture(page: Page) -> None:
    page.goto(f"{BASE_URL}/chart.html?code=600519&kind=stock")
    page.wait_for_function(
        "() => document.querySelector('#chart-page')?.dataset.loaded === 'true'"
    )
    expect(page.locator("#period-selector")).to_be_visible()
    expect(page.locator("#period-selector [data-period]")).to_have_count(3)
    expect(page.locator('#period-selector [data-period="d"]')).to_have_attribute(
        "aria-pressed", "true"
    )
    page.locator('#period-selector [data-period="30"]').click()
    page.wait_for_function(
        "() => document.querySelector('#chart-page')?.dataset.period === '30'"
    )
    expect(page.locator("#intraday-notice")).to_contain_text(
        "分钟线不显示 LPPLS 区间"
    )
    expect(page.locator("#obv-caption")).to_be_visible()
    expect(page.locator("#obv-caption")).to_contain_text(
        "OBV 背离为历史形态描述"
    )
    expect(page.locator("#obv-caption")).to_contain_text(
        "分钟线仅含最近约 20 根"
    )
    expect(page.locator("#scale-selector")).to_be_hidden()
    expect(page.locator("#chart-host canvas").first).to_be_visible()
    expect(page.locator("#data-source")).to_have_text(
        "fixture · 30 分钟 · 不复权"
    )
    expect(page.locator("#market-date")).to_have_text(
        "行情时间 2026-11-18 15:00:00"
    )
    notice = page.locator("#intraday-notice").bounding_box()
    chart = page.locator("#chart-host").bounding_box()
    assert notice and chart and chart["y"] >= notice["y"] + notice["height"] + 12
    page.locator('#period-selector [data-period="d"]').click()
    expect(page.locator("#data-source")).to_have_text(
        "tencent_fqkline · 未复权"
    )
    expect(page.locator("#market-date")).to_have_text(
        "行情日期 2026-11-17"
    )
    page.locator('#period-selector [data-period="30"]').click()
    expect(page.locator("#data-source")).to_have_text(
        "fixture · 30 分钟 · 不复权"
    )
    for width, height in ((1280, 900), (390, 844)):
        page.set_viewport_size({"width": width, "height": height})
        assert page.evaluate(
            "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
        ), f"chart page overflows at {width}px"
    assert any(
        method == "GET"
        and (urlsplit(url).hostname or "").endswith(".workers.dev")
        and urlsplit(url).path == "/kline"
        and parse_qs(urlsplit(url).query).get("code") == ["600519"]
        and parse_qs(urlsplit(url).query).get("period") == ["30"]
        for method, url, _ in page._e2e_requests
    ), page._e2e_requests


@pytest.mark.e2e
def test_flow_4_index_chip_updates_header(page: Page) -> None:
    page.goto(f"{BASE_URL}/index.html?code=sh000001")
    expect(page.locator("#sym-n")).to_contain_text("上证指数")
    with page.expect_response(
        lambda response: urlsplit(response.url).path == "/quote"
        and parse_qs(urlsplit(response.url).query).get("codes") == ["sh000300"]
    ):
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
        "2026-11 对三段历史重新计算；测试段结论仍以预登记的一次性结果为准（未通过）。"
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
    page.route(
        "**/lab/mock/data/market/top_risk_latest.json",
        lambda route: route.fulfill(path=str(TOP_RISK_FIXTURE)),
    )
    page.set_viewport_size({"width": 1280, "height": 900})
    page.goto(f"{BASE_URL}/market.html")
    expect(page.locator("#s-lhb-seats")).to_be_hidden()
    page.locator('.odn-sub a.odn-t[href="#s-breadth"]').click()
    expect(page.locator("#s-lhb-seats")).to_be_visible()
    expect(page.locator("#lhb-seats-body .lhb-card.buy strong")).to_contain_text("12.30亿")
    expect(page.locator("#lhb-subtitle")).to_contain_text("已识别游资 2 家")
    expect(page.locator("#lhb-date-badge")).to_have_text("2026.11.18 / 周三 · 盘后榜单")
    expect(page.locator("#lhb-seats-body .lhb-top-buy")).to_contain_text(
        "游资已披露买入：前6只"
    )
    expect(page.locator("#lhb-seats-body .lhb-top-buy")).to_contain_text("全部 5 只")
    expect(page.locator("#lhb-seats-body .lhb-meta")).to_have_text(
        "样本 34 只（其中单日榜 28、多日榜 6） · 历史分位"
    )
    seat_rows = page.locator("#lhb-seats-body .lhb-youzi-row")
    expect(seat_rows).to_have_count(2)
    expect(seat_rows.first.locator(".lhb-youzi-name")).to_have_text("游资甲")
    expect(seat_rows.first.locator(".lhb-youzi-subline")).to_contain_text("游资常用 · 4只")
    expect(seat_rows.first.locator(".lhb-youzi-subline")).to_have_attribute(
        "title",
        "某证券股份有限公司上海分公司；某证券股份有限公司北京分公司",
    )
    source_link = seat_rows.first.get_by_role("link", name="来源")
    expect(source_link).to_have_attribute("href", "https://example.test/lhb-alias")
    expect(source_link).to_have_attribute("title", "公开报道来源")
    expect(seat_rows.first).to_contain_text("入 甲股份 4.20亿")
    expect(seat_rows.first).to_contain_text("出 乙科技 2.10亿")
    expect(seat_rows.first.locator(".lhb-more")).to_have_text("+2笔")
    expect(page.locator("#lhb-seats-body .lhb-other-heading")).to_have_text(
        "其他主要席位 · 已披露样本"
    )
    expect(page.locator("#lhb-seats-body .lhb-other")).to_contain_text("机构专用")
    expect(page.locator("#lhb-seats-body .lhb-other")).to_contain_text("沪股通专用")
    expect(page.locator("#lhb-seats-body .lhb-other")).to_contain_text("未识别营业部")
    expect(page.locator("#lhb-seats-body .lhb-note")).to_contain_text(
        "游资别名按公开报道整理，可能有误或过时。"
    )
    assistant_button = page.locator(".ai-btn")
    if assistant_button.get_attribute("aria-expanded") != "true":
        assistant_button.click()
    expect(assistant_button).to_have_attribute("aria-expanded", "true")
    expect(page.locator(".ai-panel.ai-dock")).to_be_visible()
    assert page.locator("#s-lhb-seats").evaluate(
        "(section) => section.scrollWidth <= section.clientWidth + 1"
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
    top_risk = page.locator("#s-top-risk")
    expect(top_risk).to_have_attribute("data-ai-context", "顶部风险区")
    expect(top_risk.locator(".top-risk-card")).to_have_count(4)
    expect(top_risk.locator(".top-risk-common-item")).to_have_count(3)
    expect(top_risk.locator(".top-risk-common-item .top-risk-bar span")).to_have_count(3)
    expect(top_risk.locator(".top-risk-stat")).to_have_count(4)
    expect(top_risk.locator(".top-risk-stats")).to_contain_text(
        "上证指数 · n=7 段 · 42.9% · 基准 12.9%"
    )
    expect(top_risk.locator(".top-risk-card").first).to_contain_text("满足 3/3 项")
    for card in top_risk.locator(".top-risk-card").all():
        expect(card).not_to_contain_text("集中度")
        expect(card).not_to_contain_text("融资余额")
        expect(card).not_to_contain_text("宽度回落")
    expect(top_risk.locator(".top-risk-card").first).to_contain_text(
        "离250日低点 22.0%"
    )
    expect(top_risk.locator(".top-risk-table tbody tr").first).to_contain_text(
        "待定（未满120日）"
    )
    verdicts = top_risk.locator(".top-risk-table tbody .top-risk-verdict")
    expect(verdicts).to_have_count(2)
    expect(verdicts.filter(has_text="顶部区间")).to_have_count(1)
    expect(verdicts.filter(has_text="待定（未满120日）")).to_have_count(1)

    def assert_verdicts_fit() -> None:
        for cell in verdicts.all():
            cell.scroll_into_view_if_needed()
            assert cell.evaluate(
                """cell => {
                  const scroller = cell.closest('.table-scroll').getBoundingClientRect();
                  const rect = cell.getBoundingClientRect();
                  return cell.scrollWidth <= cell.clientWidth + 1 &&
                    rect.left >= scroller.left - 1 && rect.right <= scroller.right + 1;
                }"""
            )

    page.locator('.odn-sub a.odn-t[href="#s-top-risk"]').click()
    expect(top_risk).to_be_visible()
    assert_verdicts_fit()
    page.set_viewport_size({"width": 390, "height": 844})
    assert_verdicts_fit()
    visible_episodes = top_risk.locator(
        ".top-risk-table tbody tr:not([hidden])"
    )
    expect(visible_episodes).to_have_count(2)
    filters = top_risk.get_by_role("group", name="按指数筛选历史时段")
    filters.get_by_role("button", name="沪深300", exact=True).click()
    expect(visible_episodes).to_have_count(1)
    expect(visible_episodes.first).to_contain_text("沪深300")
    expect(top_risk.locator('.top-risk-stat[data-index="沪深300"]')).to_have_class(
        "top-risk-stat is-highlighted"
    )
    filters.get_by_role("button", name="科创50", exact=True).click()
    expect(visible_episodes).to_have_count(0)
    expect(top_risk.locator(".top-risk-filter-empty")).to_be_visible()
    expect(top_risk.locator('.top-risk-stat[data-index="科创50"]')).to_have_class(
        "top-risk-stat is-highlighted"
    )
    filters.get_by_role("button", name="全部", exact=True).click()
    expect(visible_episodes).to_have_count(2)
    assert "is-highlighted" not in top_risk.locator(
        '.top-risk-stat[data-index="沪深300"]'
    ).get_attribute("class")
    assert top_risk.evaluate("(section) => section.scrollWidth <= section.clientWidth + 1")
    dimensions = page.evaluate(
        "() => ({scrollWidth: document.documentElement.scrollWidth, innerWidth})"
    )
    assert dimensions["scrollWidth"] <= dimensions["innerWidth"] + 1, dimensions
    page.locator('.odn-sub a.odn-t[href="#s-breadth"]').click()
    assert page.locator("#s-lhb-seats").evaluate(
        "(section) => section.scrollWidth <= section.clientWidth + 1"
    )
    mobile_row = page.locator("#lhb-seats-body .lhb-youzi-row").first
    assert mobile_row.locator(".lhb-youzi-total").evaluate(
        """(amounts) => {
          const row = amounts.closest('.lhb-youzi-row').getBoundingClientRect();
          return amounts.getBoundingClientRect().right <= row.right + 1;
        }"""
    )
    chip_tops = mobile_row.locator(".lhb-trade-chip").evaluate_all(
        "(chips) => [...new Set(chips.map(chip => Math.round(chip.getBoundingClientRect().top)))]"
    )
    assert len(chip_tops) > 1, chip_tops
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
def test_chart_drawings_persist_history_exports_and_mobile_toolbar(
    page: Page, tmp_path: Path
) -> None:
    screenshot_dir = (
        Path(os.environ["LPPL_DRAWING_SHOT_DIR"])
        if os.environ.get("LPPL_DRAWING_SHOT_DIR")
        else tmp_path
    )
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(f"{BASE_URL}/chart.html?code=sh000001")
    page.wait_for_function(
        "() => document.querySelector('#chart-page')?.dataset.loaded === 'true'"
    )
    expect(page.locator("#drawing-toolbar")).to_contain_text(
        "画线仅保存在此浏览器，是你自己的标注，不是模型结果"
    )
    expect(page.locator("[data-drawing-tool]")).to_have_count(5)
    host = page.locator("#chart-host")
    page.locator('[data-drawing-tool="horizontal-line"]').click()
    host.click(position={"x": 330, "y": 180})
    page.wait_for_function(
        "() => JSON.parse(localStorage.getItem('lppl.drawings.v1:sh000001') || '{\"items\":[]}').items.length === 1"
    )
    saved = page.evaluate(
        "() => JSON.parse(localStorage.getItem('lppl.drawings.v1:sh000001'))"
    )
    assert saved["v"] == 1
    assert saved["items"][0]["drawing"]["kind"] == "horizontal-line"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", saved["items"][0]["createdAt"])

    page.reload()
    page.wait_for_function(
        "() => document.querySelector('#chart-page')?.dataset.loaded === 'true' && "
        "document.querySelector('#drawing-toolbar')?.dataset.drawingCount === '1'"
    )
    expect(page.locator("[data-drawing-visibility]")).to_have_text("全部隐藏")
    expect(page.locator("[data-drawing-history]")).to_be_hidden()
    expect(page.locator("[data-drawing-history]")).not_to_contain_text("晚于当前截止日")
    page.locator('[data-drawing-tool="rectangle"]').click()
    host.click(position={"x": 450, "y": 160})
    host.click(position={"x": 610, "y": 260})
    page.wait_for_function(
        "() => JSON.parse(localStorage.getItem('lppl.drawings.v1:sh000001')).items.length === 2"
    )
    page.locator('[data-drawing-tool="text"]').click()
    host.click(position={"x": 400, "y": 320})
    editor = page.locator(".chart-drawing-text-editor")
    expect(editor).to_be_visible()
    editor.fill("TEST-PRIVATE-NOTE")
    editor.evaluate(
        """input => {
          input.dispatchEvent(new KeyboardEvent("keydown", {
            key: "Enter", bubbles: true, cancelable: true, isComposing: true
          }));
          const escape = new KeyboardEvent("keydown", {
            key: "Escape", bubbles: true, cancelable: true
          });
          Object.defineProperty(escape, "keyCode", { get: () => 229 });
          input.dispatchEvent(escape);
        }"""
    )
    expect(editor).to_be_visible()
    editor.press("Enter")
    page.wait_for_function(
        "() => JSON.parse(localStorage.getItem('lppl.drawings.v1:sh000001')).items.length === 3 && "
        "JSON.parse(localStorage.getItem('lppl.drawings.v1:sh000001')).items.some(x => x.drawing.text === 'TEST-PRIVATE-NOTE')"
    )
    assert "TEST-PRIVATE-NOTE" not in page.locator("#chart-page").inner_text()
    page.screenshot(path=str(screenshot_dir / "chart_1440.png"))

    without_path = screenshot_dir / "export_without_notes.png"
    with_path = screenshot_dir / "export_with_notes.png"
    include = page.locator("#include-drawings")
    expect(include).not_to_be_checked()
    with page.expect_download() as download:
        page.locator("#share-screenshot").click()
    download.value.save_as(str(without_path))
    assert without_path.stat().st_size > 10_000
    expect(page.locator("#action-feedback")).to_have_text(
        "当前图表与证据截图已下载；不含私人研究资料。"
    )
    include.check()
    with page.expect_download() as download:
        page.locator("#share-screenshot").click()
    download.value.save_as(str(with_path))
    assert with_path.stat().st_size > 10_000
    expect(page.locator("#action-feedback")).to_have_text(
        "当前图表与证据截图已下载，包含你选择的个人标注。"
    )
    export_diff = drawing_pixel_diff(
        page, without_path.read_bytes(), with_path.read_bytes(), chart_only=True
    )
    assert export_diff["changed"] > 100, export_diff

    replay_url = f"{BASE_URL}/chart.html?code=sh000001&asof=2015-06-12"
    page.goto(replay_url)
    page.wait_for_function(
        "() => document.querySelector('#chart-page')?.dataset.loaded === 'true'"
    )
    visibility = page.locator("[data-drawing-visibility]")
    expect(visibility).to_have_text("显示我的画线")
    page.screenshot(path=str(screenshot_dir / "chart_asof_hidden_1440.png"))
    visibility.click()
    expect(page.locator("[data-drawing-history]")).to_be_visible()
    assert f"这些画线创建于 {saved['items'][0]['createdAt']}" in page.locator(
        "[data-drawing-history]"
    ).inner_text()
    assert f"创建于 {saved['items'][0]['createdAt']}" in page.locator(
        "[data-drawing-dates]"
    ).inner_text()
    expect(page.locator("[data-drawing-history]")).to_contain_text(
        "晚于当前截止日 2015-06-12"
    )
    page.screenshot(path=str(screenshot_dir / "chart_asof_shown_1440.png"))
    page.locator('[data-drawing-tool="horizontal-line"]').click()
    host = page.locator("#chart-host")
    host.click(position={"x": 540, "y": 240})
    page.wait_for_function(
        "() => JSON.parse(localStorage.getItem('lppl.drawings.v1:sh000001')).items.length === 4"
    )
    visible_image = host.screenshot()
    visibility.click()
    expect(visibility).to_have_text("显示我的画线")
    hidden_image = host.screenshot()
    view_diff = drawing_pixel_diff(page, hidden_image, visible_image)
    assert view_diff["changed"] > 50, view_diff
    page.screenshot(path=str(screenshot_dir / "chart_asof_hidden_1440.png"))
    visibility.click()
    expect(page.locator("[data-drawing-history]")).to_be_visible()
    page.screenshot(path=str(screenshot_dir / "chart_asof_shown_1440.png"))

    page.set_viewport_size({"width": 390, "height": 844})
    dimensions = page.evaluate(
        "() => ({scrollWidth:document.documentElement.scrollWidth, innerWidth})"
    )
    assert dimensions["scrollWidth"] <= dimensions["innerWidth"] + 1, dimensions
    tool = page.locator('[data-drawing-tool="trend-line"]')
    tool.click()
    expect(tool).to_have_attribute("aria-pressed", "true")
    tool.click()
    expect(tool).to_have_attribute("aria-pressed", "false")
    page.screenshot(path=str(screenshot_dir / "chart_390.png"))


@pytest.mark.e2e
def test_chart_drawings_merge_between_tabs(page: Page) -> None:
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(f"{BASE_URL}/chart.html?code=sh000001")
    page.wait_for_function(
        "() => document.querySelector('#chart-page')?.dataset.loaded === 'true'"
    )
    page.locator('[data-drawing-tool="horizontal-line"]').click()
    page.locator("#chart-host").click(position={"x": 330, "y": 180})
    page.wait_for_function(
        "() => JSON.parse(localStorage.getItem('lppl.drawings.v1:sh000001') || '{\"items\":[]}').items.length === 1"
    )

    second = page.context.new_page()
    try:
        second.set_viewport_size({"width": 1440, "height": 900})
        second.goto(f"{BASE_URL}/chart.html?code=sh000001")
        second.wait_for_function(
            "() => document.querySelector('#chart-page')?.dataset.loaded === 'true' && "
            "document.querySelector('#drawing-toolbar')?.dataset.drawingCount === '1'"
        )
        second.locator('[data-drawing-tool="horizontal-line"]').click()
        second.locator("#chart-host").click(position={"x": 420, "y": 230})
        second.wait_for_function(
            "() => JSON.parse(localStorage.getItem('lppl.drawings.v1:sh000001')).items.length === 2"
        )
        page.wait_for_function(
            "() => document.querySelector('#drawing-toolbar')?.dataset.drawingCount === '2'"
        )

        page.locator('[data-drawing-tool="horizontal-line"]').click()
        page.locator("#chart-host").click(position={"x": 520, "y": 280})
        page.wait_for_function(
            "() => JSON.parse(localStorage.getItem('lppl.drawings.v1:sh000001')).items.length === 3"
        )
        second.wait_for_function(
            "() => document.querySelector('#drawing-toolbar')?.dataset.drawingCount === '3'"
        )
    finally:
        second.close()


@pytest.mark.e2e
def test_chart_clear_all_cancels_draft_and_removes_other_tab_records(page: Page) -> None:
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(f"{BASE_URL}/chart.html?code=sh000001")
    page.wait_for_function(
        "() => document.querySelector('#chart-page')?.dataset.loaded === 'true'"
    )
    storage_count = (
        "() => JSON.parse(localStorage.getItem('lppl.drawings.v1:sh000001') || "
        "'{\"items\":[]}').items.length"
    )
    page.locator('[data-drawing-tool="text"]').click()
    page.locator("#chart-host").click(position={"x": 375, "y": 300})
    editor = page.locator(".chart-drawing-text-editor")
    expect(editor).to_be_visible()
    editor.fill("UNSAVED")

    second = page.context.new_page()
    try:
        second.set_viewport_size({"width": 1440, "height": 900})
        second.goto(f"{BASE_URL}/chart.html?code=sh000001")
        second.wait_for_function(
            "() => document.querySelector('#chart-page')?.dataset.loaded === 'true'"
        )
        second.locator('[data-drawing-tool="horizontal-line"]').click()
        second.locator("#chart-host").click(position={"x": 420, "y": 230})
        second.wait_for_function(storage_count + " === 1")
        expect(editor).to_be_visible()

        page.on("dialog", lambda dialog: dialog.accept())
        page.locator("[data-drawing-clear]").click()
        expect(editor).to_be_hidden()
        page.wait_for_function(storage_count + " === 0")
    finally:
        second.close()

    page.reload()
    page.wait_for_function(
        "() => document.querySelector('#chart-page')?.dataset.loaded === 'true'"
    )
    page.wait_for_function(storage_count + " === 0")


@pytest.mark.e2e
def test_chart_drawings_survive_back_navigation(page: Page) -> None:
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(f"{BASE_URL}/chart.html?code=sh000001")
    page.wait_for_function(
        "() => document.querySelector('#chart-page')?.dataset.loaded === 'true'"
    )
    page.locator('[data-drawing-tool="horizontal-line"]').click()
    page.locator("#chart-host").click(position={"x": 350, "y": 190})
    page.wait_for_function(
        "() => JSON.parse(localStorage.getItem('lppl.drawings.v1:sh000001') || '{\"items\":[]}').items.length === 1"
    )

    page.goto(f"{BASE_URL}/index.html")
    page.go_back(wait_until="domcontentloaded")
    page.wait_for_function(
        "() => document.querySelector('#chart-page')?.dataset.loaded === 'true' && "
        "document.querySelector('#drawing-toolbar')?.dataset.drawingCount === '1'"
    )
    expect(page.locator("[data-drawing-visibility]")).to_have_text("全部隐藏")
    expect(page.locator("#drawing-toolbar")).to_be_visible()
    page.locator('[data-drawing-tool="horizontal-line"]').click()
    page.locator("#chart-host").click(position={"x": 500, "y": 280})
    page.wait_for_function(
        "() => JSON.parse(localStorage.getItem('lppl.drawings.v1:sh000001')).items.length === 2"
    )


@pytest.mark.e2e
def test_chart_text_drawings_persist_only_after_submission(page: Page) -> None:
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(f"{BASE_URL}/chart.html?code=sh000001")
    page.wait_for_function(
        "() => document.querySelector('#chart-page')?.dataset.loaded === 'true'"
    )
    storage_count = (
        "() => JSON.parse(localStorage.getItem('lppl.drawings.v1:sh000001') || "
        "'{\"items\":[]}').items.length"
    )
    text_tool = page.locator('[data-drawing-tool="text"]')
    host = page.locator("#chart-host")
    editor = page.locator(".chart-drawing-text-editor")
    undo = page.locator("[data-drawing-undo]")

    page.locator('[data-drawing-tool="horizontal-line"]').click()
    host.click(position={"x": 350, "y": 190})
    page.wait_for_function(storage_count + " === 1")
    text_tool.click()
    host.click(position={"x": 375, "y": 300})
    expect(editor).to_be_visible()
    editor.press_sequentially("ab")
    expect(editor).to_have_value("ab")
    editor.press("Control+z")
    expect(editor).to_be_visible()
    assert editor.input_value() != "ab"
    page.wait_for_function(storage_count + " === 1")
    expect(undo).to_be_enabled()
    undo.click()
    page.wait_for_function(storage_count + " === 0")
    expect(editor).to_be_hidden()
    expect(page.locator("#drawing-toolbar")).to_have_attribute("data-drawing-count", "0")
    expect(undo).to_be_disabled()

    text_tool.click()
    host.click(position={"x": 400, "y": 320})
    expect(editor).to_be_visible()
    editor.fill("")
    editor.press("Enter")
    page.wait_for_function(storage_count + " === 0")
    expect(page.locator("#drawing-toolbar")).to_have_attribute("data-drawing-count", "0")
    expect(undo).to_be_disabled()

    text_tool.click()
    host.click(position={"x": 450, "y": 340})
    expect(editor).to_be_visible()
    editor.fill("CANCEL-ME")
    editor.press("Escape")
    page.wait_for_function(storage_count + " === 0")
    expect(page.locator("#drawing-toolbar")).to_have_attribute("data-drawing-count", "0")
    expect(undo).to_be_disabled()

    text_tool.click()
    host.click(position={"x": 500, "y": 360})
    expect(editor).to_be_visible()
    editor.fill("SAVE-ME")
    editor.press("Enter")
    page.wait_for_function(
        storage_count + " === 1 && "
        "JSON.parse(localStorage.getItem('lppl.drawings.v1:sh000001')).items[0].drawing.text === 'SAVE-ME'"
    )
    expect(undo).to_be_enabled()
    undo.click()
    page.wait_for_function(storage_count + " === 0")
    expect(page.locator("#drawing-toolbar")).to_have_attribute("data-drawing-count", "0")
    expect(undo).to_be_disabled()


@pytest.mark.e2e
def test_deleting_text_drawing_closes_editor_without_saving_it(page: Page) -> None:
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(f"{BASE_URL}/chart.html?code=sh000001")
    page.wait_for_function(
        "() => document.querySelector('#chart-page')?.dataset.loaded === 'true'"
    )
    storage_count = (
        "() => JSON.parse(localStorage.getItem('lppl.drawings.v1:sh000001') || "
        "'{\"items\":[]}').items.length"
    )
    editor = page.locator(".chart-drawing-text-editor")
    page.locator('[data-drawing-tool="text"]').click()
    page.locator("#chart-host").click(position={"x": 450, "y": 340})
    expect(editor).to_be_visible()
    editor.fill("DELETE-ME")
    delete = page.locator("[data-drawing-delete]")
    expect(delete).to_be_enabled()
    delete.click()
    expect(editor).to_be_hidden()
    page.wait_for_function(storage_count + " === 0")
    page.locator(".chart-drawing-text-editor").evaluate(
        """input => input.dispatchEvent(new KeyboardEvent("keydown", {
          key: "Enter", bubbles: true, cancelable: true
        }))"""
    )
    page.wait_for_function(
        storage_count + " === 0 && "
        "document.querySelector('#drawing-toolbar')?.dataset.drawingCount === '0'"
    )


@pytest.mark.e2e
def test_chart_undo_with_empty_history_preserves_open_note_draft(page: Page) -> None:
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(f"{BASE_URL}/chart.html?code=sh000001")
    page.wait_for_function(
        "() => document.querySelector('#chart-page')?.dataset.loaded === 'true'"
    )
    storage_count = (
        "() => JSON.parse(localStorage.getItem('lppl.drawings.v1:sh000001') || "
        "'{\"items\":[]}').items.length"
    )
    page.wait_for_function(storage_count + " === 0")
    undo = page.locator("[data-drawing-undo]")
    page.locator('[data-drawing-tool="text"]').click()
    host = page.locator("#chart-host")
    host.click(position={"x": 375, "y": 300})
    editor = page.locator(".chart-drawing-text-editor")
    expect(editor).to_be_visible()
    editor.fill("DRAFT")
    expect(undo).to_be_disabled()

    host.focus()
    page.keyboard.press("Control+z")
    expect(editor).to_be_visible()
    expect(editor).to_have_value("DRAFT")
    page.wait_for_function(storage_count + " === 0")


@pytest.mark.e2e
def test_chart_note_escape_does_not_exit_fullscreen(page: Page) -> None:
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(f"{BASE_URL}/chart.html?code=sh000001")
    page.wait_for_function(
        "() => document.querySelector('#chart-page')?.dataset.loaded === 'true'"
    )
    fullscreen = page.locator("#chart-fullscreen")
    fullscreen.click()
    expect(fullscreen).to_have_attribute("aria-pressed", "true")
    page.evaluate(
        """() => {
          const textarea = document.createElement("textarea");
          document.body.appendChild(textarea);
          textarea.focus();
          textarea.dispatchEvent(new KeyboardEvent("keydown", {
            key: "Escape", bubbles: true, cancelable: true
          }));
          textarea.remove();
        }"""
    )
    expect(fullscreen).to_have_attribute("aria-pressed", "true")

    page.locator('[data-drawing-tool="text"]').click()
    page.locator("#chart-host").click(position={"x": 400, "y": 320})
    editor = page.locator(".chart-drawing-text-editor")
    expect(editor).to_be_visible()
    page.evaluate(
        """() => {
          window.__noteEscapeBubbled = false;
          document.addEventListener("keydown", event => {
            if (event.target.matches(".chart-drawing-text-editor") && event.key === "Escape") {
              window.__noteEscapeBubbled = true;
            }
          });
        }"""
    )
    editor.evaluate(
        """input => input.dispatchEvent(new KeyboardEvent("keydown", {
          key: "Escape", bubbles: true, cancelable: true, isComposing: true
        }))"""
    )
    expect(editor).to_be_visible()
    assert page.evaluate("() => window.__noteEscapeBubbled") is False

    editor.evaluate(
        """input => input.dispatchEvent(new KeyboardEvent("keydown", {
          key: "Escape", bubbles: true, cancelable: true
        }))"""
    )
    expect(editor).to_be_hidden()
    expect(fullscreen).to_have_attribute("aria-pressed", "true")
    assert page.evaluate("() => window.__noteEscapeBubbled") is False
    fullscreen.evaluate("(button) => button.click()")
    expect(fullscreen).to_have_attribute("aria-pressed", "false")


@pytest.mark.e2e
def test_chart_undo_keeps_history_drawings_hidden(page: Page) -> None:
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(f"{BASE_URL}/chart.html?code=sh000001")
    page.wait_for_function(
        "() => document.querySelector('#chart-page')?.dataset.loaded === 'true'"
    )
    page.locator('[data-drawing-tool="horizontal-line"]').click()
    page.locator("#chart-host").click(position={"x": 350, "y": 190})
    page.wait_for_function(
        "() => JSON.parse(localStorage.getItem('lppl.drawings.v1:sh000001') || '{\"items\":[]}').items.length === 1"
    )

    page.goto(f"{BASE_URL}/chart.html?code=sh000001&asof=2015-06-12")
    page.wait_for_function(
        "() => document.querySelector('#chart-page')?.dataset.loaded === 'true' && "
        "document.querySelector('#drawing-toolbar')?.dataset.drawingCount === '1'"
    )
    visibility = page.locator("[data-drawing-visibility]")
    expect(visibility).to_have_text("显示我的画线")
    host = page.locator("#chart-host")
    page.mouse.move(1, 1)
    hidden_before = host.screenshot()

    page.locator('[data-drawing-tool="horizontal-line"]').click()
    host.click(position={"x": 500, "y": 280})
    page.wait_for_function(
        "() => JSON.parse(localStorage.getItem('lppl.drawings.v1:sh000001')).items.length === 2"
    )
    expect(visibility).to_have_text("显示我的画线")
    page.locator("[data-drawing-undo]").click()
    page.wait_for_function(
        "() => JSON.parse(localStorage.getItem('lppl.drawings.v1:sh000001')).items.length === 1"
    )
    expect(visibility).to_have_text("显示我的画线")
    page.mouse.move(1, 1)
    hidden_after = host.screenshot()
    assert drawing_pixel_diff(page, hidden_before, hidden_after)["changed"] < 50


@pytest.mark.e2e
def test_chart_stock_archive_20250523_keeps_cutoff_and_drawings(page: Page) -> None:
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(f"{BASE_URL}/chart.html?code=sh600519&asof=2025-05-23")
    page.wait_for_function(
        "() => document.querySelector('#chart-page')?.dataset.loaded === 'true'"
    )
    expect(page.locator("#asof-tag")).to_have_text("历史截止日 2025-05-23 · 封存回放")
    assert (page.locator("#chart-page").get_attribute("data-last-bar-date") or "") <= "2025-05-23"
    assert page.locator("#evidence-state").inner_text().strip()
    visibility = page.locator("[data-drawing-visibility]")
    expect(visibility).to_have_text("显示我的画线")
    page.locator('[data-drawing-tool="horizontal-line"]').click()
    page.locator("#chart-host").click(position={"x": 460, "y": 240})
    page.wait_for_function(
        "() => JSON.parse(localStorage.getItem('lppl.drawings.v1:sh600519') || '{\"items\":[]}').items.length === 1"
    )
    expect(page.locator("[data-drawing-visibility]")).to_have_text("显示我的画线")
    expect(page.locator("[data-drawing-history]")).to_be_hidden()
    visibility.click()
    expect(page.locator("[data-drawing-visibility]")).to_have_text("全部隐藏")
    expect(page.locator("[data-drawing-history]")).to_contain_text(
        "晚于当前截止日 2025-05-23"
    )


@pytest.mark.e2e
def test_chart_drawing_rebinds_after_close_only_series_switch(page: Page) -> None:
    close_only = False

    def serve_price_data(route) -> None:
        response = route.fetch()
        payload = response.json()
        if close_only:
            for field in ("open", "high", "low"):
                payload["price_history"].pop(field, None)
        route.fulfill(response=response, body=json.dumps(payload))

    def instrument_chart(route) -> None:
        response = route.fetch()
        body = response.text() + (
            '\n;const originalMount=LPPLChart.mount;LPPLChart.mount=function(...args){'
            'window.__qaChart=originalMount(...args);'
            'window.__qaInitialPriceSeries=window.__qaChart.drawingTarget().series;'
            'window.__qaPriceSeriesEvents=[];'
            'window.__qaChart.on("priceSeries",series=>window.__qaPriceSeriesEvents.push(series));'
            'return window.__qaChart;};'
        )
        route.fulfill(response=response, body=body)

    page.route("**/lab/mock/data/sh000001_latest.json", serve_price_data)
    page.route("**/app/lppl-chart.js", instrument_chart)
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(f"{BASE_URL}/chart.html?code=sh000001")
    page.wait_for_function(
        "() => document.querySelector('#chart-page')?.dataset.loaded === 'true'"
    )
    page.locator('[data-drawing-tool="horizontal-line"]').click()
    page.locator("#chart-host").click(position={"x": 400, "y": 200})
    page.wait_for_function(
        "() => JSON.parse(localStorage.getItem('lppl.drawings.v1:sh000001') || '{\"items\":[]}').items.length === 1"
    )

    close_only = True
    page.reload()
    page.wait_for_function(
        "() => document.querySelector('#chart-page')?.dataset.loaded === 'true' && "
        "document.querySelector('#chart-page')?.dataset.priceMode === 'close'"
    )
    expect(page.locator("#price-mode-note")).to_contain_text(
        "真实收盘线，不补造 K 线"
    )
    assert page.evaluate(
        """() => ({
          switched: window.__qaInitialPriceSeries !== window.__qaChart.drawingTarget().series,
          emitted: window.__qaPriceSeriesEvents.length > 0,
          eventUsesVisibleSeries: window.__qaPriceSeriesEvents.at(-1) === window.__qaChart.drawingTarget().series,
          importedDrawing: document.querySelector('#drawing-toolbar').dataset.drawingCount === '1',
        })"""
    ) == {
        "switched": True,
        "emitted": True,
        "eventUsesVisibleSeries": True,
        "importedDrawing": True,
    }


@pytest.mark.e2e
def test_workspace_chart_replay_round_trip_preserves_research_context(page: Page) -> None:
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(f"{BASE_URL}/research-workspace.html")
    page.wait_for_function(
        "() => !document.querySelector('#empty-watch')?.hidden || "
        "document.querySelector('#watch-list')?.children.length > 0"
    )
    watch_rows = page.locator("#watch-list [data-row]")
    maotai = watch_rows.filter(has_text="贵州茅台")
    if maotai.count() == 0:
        page.locator('[data-add-sample="stock:600519"]').click()
        maotai = page.locator('#watch-list [data-row="stock:600519"]')
    expect(maotai).to_be_visible()
    maotai.locator("[data-select]").click()
    expect(page.locator("#detail-heading")).to_have_text("贵州茅台")

    current_href = page.locator("#open-full-chart").get_attribute("href")
    assert current_href and "code=600519" in current_href
    assert "asof=" not in urlsplit(current_href).query

    page.goto(
        f"{BASE_URL}/research-workspace.html"
        "?kind=stock&code=600519&asof=2025-05-23"
    )
    page.wait_for_function(
        """() => {
          const link = document.querySelector('#open-full-chart');
          return document.querySelector('#detail-heading')?.textContent === '贵州茅台' &&
            document.querySelector('#detail-summary')?.innerText.includes('2025-05-23') &&
            link?.href.includes('asof=2025-05-23');
        }"""
    )
    detail_before = page.locator("#detail-summary").inner_text()
    list_before = page.locator("#watch-list").inner_text()
    page.evaluate("window.scrollTo(0, 280)")
    list_position = page.evaluate("window.scrollY")
    full_chart = page.locator("#open-full-chart")
    href = full_chart.get_attribute("href")
    assert href and "code=600519" in href and "from=research-workspace.html" in href
    asof_match = re.search(r"(?:\?|&)asof=(\d{4}-\d{2}-\d{2})", href)
    assert asof_match and asof_match.group(1) == "2025-05-23", href
    assert asof_match.group(1) in detail_before
    expect(full_chart).to_contain_text(asof_match.group(1))
    full_chart.scroll_into_view_if_needed()
    list_position = page.evaluate("window.scrollY")
    full_chart.click()
    page.wait_for_function(
        "() => document.querySelector('#chart-page')?.dataset.loaded === 'true' || "
        "document.querySelector('#error-panel')?.hidden === false"
    )
    expect(page.locator("#chart-page")).to_have_attribute("data-loaded", "true")
    assert page.locator("#chart-page").get_attribute("data-code") == "sh600519"
    archive_date = page.locator("#asof-tag").inner_text()
    evidence = page.locator("#evidence-state").inner_text()
    assert archive_date == f"历史截止日 {asof_match.group(1)} · 封存回放"
    assert (page.locator("#chart-page").get_attribute("data-last-bar-date") or "") <= asof_match.group(1)
    assert evidence
    page.locator('[data-drawing-tool="horizontal-line"]').click()
    page.locator("#chart-host").click(position={"x": 460, "y": 220})
    page.wait_for_function(
        "() => JSON.parse(localStorage.getItem('lppl.drawings.v1:sh600519') || '{\"items\":[]}').items.length === 1"
    )
    page.go_back()
    expect(page.locator("#detail-heading")).to_have_text("贵州茅台")
    assert page.locator("#detail-summary").inner_text() == detail_before
    assert page.locator("#watch-list").inner_text() == list_before
    assert page.evaluate("window.scrollY") == list_position
    expect(page.locator("#open-full-chart")).to_have_attribute("href", href)


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
    expect(page.locator('.odn-sidebar .odn-side-link[href="market.html#s-summary"]')).to_have_attribute(
        "aria-current", "location"
    )
    expect(page.locator('.odn-l2 .odn-sub a[href="#s-summary"]')).to_have_attribute(
        "aria-current", "location"
    )


@pytest.mark.e2e
def test_market_group_tabs_follow_anchor_ids(page: Page) -> None:
    page.goto(f"{BASE_URL}/market.html")
    tabs = page.locator(".odn-sub a.odn-t")
    expect(tabs).to_have_count(5)
    emotion_tab = tabs.filter(has_text="情绪")
    emotion_tab.click()
    expect(page.locator("#s-limit")).to_be_visible()
    expect(emotion_tab).to_have_attribute("aria-current", "location")
    expect(
        page.locator(".odn-sidebar .odn-side-link").filter(has_text="情绪")
    ).to_have_attribute("aria-current", "location")


@pytest.mark.e2e
def test_market_tabs_show_only_their_sections_and_freshness_hash(page: Page) -> None:
    groups = [
        ("今日", ["s-summary", "s-news", "s-events"]),
        ("资金", ["s-breadth", "s-board", "s-nb", "s-mg", "s-lhb", "s-lhb-seats"]),
        ("情绪", ["s-limit", "s-sentiment", "s-ladder", "s-strength", "s-themes", "s-hot"]),
        ("风险", ["s-top-risk", "s-bottom", "s-abnormal", "s-range"]),
        ("宏观", ["s-val", "s-macro", "s-growth"]),
    ]
    page.goto(f"{BASE_URL}/market.html")
    tabs = page.locator(".odn-sub a.odn-t")
    expect(tabs).to_have_count(5)
    seen: set[str] = set()

    for title, expected_ids in groups:
        tab = tabs.filter(has_text=title)
        tab.click()
        expect(tab).to_have_attribute("aria-current", "location")
        assert tab.get_attribute("href") == f"#{expected_ids[0]}"
        visible_ids = page.locator("main > section.sec[id]").evaluate_all(
            "(sections) => sections.filter((section) => section.getClientRects().length).map((section) => section.id)"
        )
        assert set(visible_ids) == set(expected_ids)
        assert len(visible_ids) == len(expected_ids)
        assert seen.isdisjoint(visible_ids)
        seen.update(visible_ids)
        assert page.locator("#s-fresh").evaluate(
            "(section) => section.getClientRects().length"
        ) == 0

    expected_group_ids = {section_id for _, ids in groups for section_id in ids}
    assert seen == expected_group_ids

    page.goto(f"{BASE_URL}/market.html#s-fresh")
    assert page.locator("#s-fresh").evaluate(
        "(section) => section.getClientRects().length"
    ) > 0
    expect(page.locator('.odn-sub a.odn-t[href="#s-summary"]')).to_have_attribute(
        "aria-current", "location"
    )

    page.goto(f"{BASE_URL}/market.html")
    tabs.filter(has_text="情绪").click()
    page.evaluate("window.scrollTo(0, 1500)")
    page.wait_for_function("window.scrollY >= 1490")
    page.locator('.odn-sidebar .odn-side-sub a[href$="#s-breadth"]').click()
    page.wait_for_function("location.hash === '#s-breadth' && window.scrollY === 0")
    breadth_top = page.locator("#s-breadth").evaluate(
        "(section) => section.getBoundingClientRect().top"
    )
    header_bottom = page.locator("header.odn").evaluate(
        "(header) => header.getBoundingClientRect().bottom"
    )
    assert page.evaluate("window.scrollY") == 0
    assert breadth_top >= header_bottom

    page.goto(f"{BASE_URL}/market.html")
    tabs.filter(has_text="宏观").click()
    page.evaluate("document.body.style.minHeight = '2400px'; window.scrollTo(0, 1500)")
    page.wait_for_function("window.scrollY === 1500")
    page.locator('.odn-sidebar .odn-side-sub a[href$="#s-summary"]').click()
    page.wait_for_function("location.hash === '#s-summary' && window.scrollY === 0")
    summary_top = page.locator("#s-summary").evaluate(
        "(section) => section.getBoundingClientRect().top"
    )
    header_bottom = page.locator("header.odn").evaluate(
        "(header) => header.getBoundingClientRect().bottom"
    )
    assert page.evaluate("window.scrollY") == 0
    assert summary_top >= header_bottom
    page.route(
        re.compile(r"^https://lppl-stock-query\.careypang\.workers\.dev/quote\?"),
        lambda route: route.fulfill(status=200, json={"quotes": {}}),
    )
    page.route(
        re.compile(r"^https://lppl-stock-query\.careypang\.workers\.dev/news(?:\?|$)"),
        lambda route: route.fulfill(status=200, json={"cls": [], "eastmoney": []}),
    )
    page.goto(f"{BASE_URL}/market.html")
    tabs.filter(has_text="资金").click()
    page.evaluate(
        "window.scrollTo(0, 800); "
        "sessionStorage.setItem('market-tab-scroll-restore', String(window.scrollY)); "
        "sessionStorage.removeItem('market-tab-top-reset')"
    )
    page.wait_for_function("window.scrollY >= 790")
    page.add_init_script(
        """
        (() => {
          const navigation = performance.getEntriesByType('navigation')[0];
          if (navigation && navigation.type === 'reload') {
            const y = Number(sessionStorage.getItem('market-tab-scroll-restore') || 0);
            const scrollTo = window.scrollTo.bind(window);
            window.scrollTo = function (x, y) {
              if (Number(x) === 0 && Number(y) === 0) {
                sessionStorage.setItem('market-tab-top-reset', '1');
              }
              return scrollTo(x, y);
            };
            addEventListener('pageshow', () => {
              setTimeout(() => window.scrollTo(0, y), 50);
            }, { once: true });
          }
        })();
        """
    )
    page.reload()
    page.wait_for_function(
        "() => window.scrollY > 0 && "
        "document.querySelector('#s-lhb-seats')?.getClientRects().length"
    )
    assert page.evaluate("window.scrollY") > 0
    assert page.evaluate(
        "sessionStorage.getItem('market-tab-top-reset')"
    ) is None
    expect(tabs.filter(has_text="资金")).to_have_attribute(
        "aria-current", "location"
    )
    visible_ids = page.locator("main > section.sec[id]").evaluate_all(
        "(sections) => sections.filter((section) => section.getClientRects().length).map((section) => section.id)"
    )
    assert set(visible_ids) == {
        "s-breadth",
        "s-board",
        "s-nb",
        "s-mg",
        "s-lhb",
        "s-lhb-seats",
    }

@pytest.mark.e2e
def test_market_valuation_macro_tab_shows_legu_monthly_pe_percentiles(page: Page) -> None:
    percentiles = json.loads(VALUATION_FIXTURE.read_text(encoding="utf-8"))

    def add_percentile_fixture(route) -> None:
        response = route.fetch()
        payload = response.json()
        for code, values in percentiles.items():
            payload["valuation"]["indices"][code].update(values)
        payload["valuation"]["note"] = (
            "PE1/PE2 与股息率取中证官方；PE 10 年分位使用乐咕月度静态 PE1 历史计算。"
        )
        route.fulfill(status=response.status, json=payload)

    page.route(
        "**/lab/mock/data/market/market_latest.json",
        add_percentile_fixture,
    )
    page.goto(f"{BASE_URL}/market.html")
    macro_tab = page.locator(".odn-sub a.odn-t").filter(has_text="宏观")
    macro_tab.click()
    expect(page.locator("#s-val")).to_be_visible()
    expect(macro_tab).to_have_attribute("aria-current", "location")

    rows = page.locator("#val-body tbody tr")
    expect(rows).to_have_count(4)
    expect(rows.nth(0).locator("td").last).to_contain_text("42%")
    expect(rows.nth(0).locator("td").last).to_contain_text(
        "乐咕月度，自 2016 年起，n=120"
    )
    expect(page.locator("#val-body")).not_to_contain_text("源文件只有近")
    expect(page.locator("#val-body .note")).to_contain_text("乐咕月度静态 PE1 历史")


@pytest.mark.e2e
def test_research_workspace_shared_navigation_and_mobile_layout(page: Page) -> None:
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(f"{BASE_URL}/research-workspace.html")
    expect(page.locator("header.odn")).to_be_visible()
    research_link = page.locator(
        '.odn-sidebar .odn-side-link[href="research-workspace.html"]'
    )
    expect(research_link).to_have_attribute("aria-current", "location")
    desktop_layout = page.evaluate(
        """() => ({
          paddingLeft: parseFloat(getComputedStyle(document.body).paddingLeft),
          mainLeft: document.querySelector("main").getBoundingClientRect().left,
          sidebarRight: document.querySelector(".odn-sidebar").getBoundingClientRect().right
        })"""
    )
    assert abs(desktop_layout["paddingLeft"] - desktop_layout["sidebarRight"]) <= 1
    assert abs(desktop_layout["mainLeft"] - desktop_layout["sidebarRight"]) <= 1

    page.set_viewport_size({"width": 390, "height": 844})
    expect(page.locator(".odn-mobile-toggle")).to_be_hidden()
    entries = page.locator(".odn-main a")
    expect(entries).to_have_count(5)
    for entry in entries.all():
        expect(entry).to_be_visible()
    bounds = entries.evaluate_all(
        "(items) => items.map((item) => { const r = item.getBoundingClientRect(); return [r.left, r.right]; })"
    )
    assert all(left >= -1 and right <= 391 for left, right in bounds), bounds
    dimensions = page.evaluate(
        "() => ({scrollWidth: document.documentElement.scrollWidth, innerWidth})"
    )
    assert dimensions["scrollWidth"] <= dimensions["innerWidth"] + 1, dimensions
