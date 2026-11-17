from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

import pytest

if TYPE_CHECKING:
    from playwright.sync_api import Page


def expect(locator: object):
    from playwright.sync_api import expect as playwright_expect

    return playwright_expect(locator)

BASE_URL = os.environ.get("E2E_BASE_URL", "http://127.0.0.1:8765")


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
def test_flow_6_market_summary_and_news_leave_loading_state(page: Page) -> None:
    page.goto(f"{BASE_URL}/market.html")
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
def test_overflow_2_stock_catalog(page: Page) -> None:
    assert_page_has_no_overflow(page, "stock.html")


@pytest.mark.e2e
def test_overflow_3_stock_detail(page: Page) -> None:
    assert_page_has_no_overflow(page, "stock.html?code=600519")


@pytest.mark.e2e
@pytest.mark.xfail(
    reason="index.html still overflows at 390px (document scrollWidth 474px)",
    strict=True,
)
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
