"""Walk the reader's route on the built site, including its real date-stamped archives."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from playwright.sync_api import Page

BASE = os.environ.get("E2E_BASE_URL", "http://127.0.0.1:8765")
CASES = (
    ("sh000001", "上证指数", "2025-07-07", "2025-07-09", "2025-07-16"),
    ("sh600519", "贵州茅台", "2025-05-23", "2025-06-20", "2025-07-08"),
)
pytestmark = pytest.mark.e2e


def capture(page: Page, name: str) -> None:
    folder = os.environ.get("GUANSHI_CAPTURE_DIR")
    if folder:
        dest = Path(folder)
        dest.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=dest / f"{name}.png", animations="disabled")


def assert_fits_viewport(page: Page) -> None:
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")


@pytest.mark.parametrize(("width", "height"), [(1440, 900), (390, 844)])
def test_watchlist_to_window_and_back(page: Page, width: int, height: int) -> None:
    from playwright.sync_api import expect

    page.set_viewport_size({"width": width, "height": height})
    page.goto(f"{BASE}/home.html")
    page.get_by_role("link", name="观时 · 自选回看").click()
    expect(page.locator("#watch-count")).to_have_text("0")
    page.locator("#catalog-tab").click()
    for symbol in ("sh000001", "sh600519", "sh600320"):
        page.locator(f'#rows [data-save="{symbol}"]').click()
    page.locator("#my-tab").click()
    expect(page.locator("#watch-count")).to_have_text("3")
    assert_fits_viewport(page)

    for symbol, name, asof, start, end in CASES:
        page.locator("#filter").fill(name)
        row = page.locator(f'#rows a[data-asset="{symbol}"]')
        expect(row).to_have_count(1)
        row.click()
        expect(page.locator("#asset-name")).to_have_text(name)
        select = page.locator("#asof")
        select.select_option(asof)
        interval = page.locator(f'.gs-plot path[data-start="{start}"][data-end="{end}"]')
        expect(interval).to_have_count(1)
        expect(page.locator("#intervals")).to_contain_text(start)
        assert page.locator("#headline").bounding_box()["y"] < height
        assert page.locator("#guanshi-chart").bounding_box()["y"] < height
        capture(page, f"{width}-{symbol}-asof")
        assert_fits_viewport(page)
        page.locator("#open-evidence").click()
        evidence = page.locator("#evidence-body")
        expect(evidence).to_be_visible()
        expect(evidence).to_contain_text("历史重算")
        expect(evidence.get_by_role("link", name="原始模型记录")).to_have_count(1)
        evidence_before = evidence.inner_text()
        interval_before = interval.get_attribute("d")
        sessions = page.locator(".gs-plot [data-session]")
        dates = sessions.evaluate_all("(els) => els.map(e => e.dataset.session)")
        assert dates and max(dates) == asof
        assert not page.locator(".gs-plot [data-later]").count()
        expect(page.locator(".gs-plot")).to_contain_text("日 K 线")
        expect(page.locator(".gs-plot")).to_contain_text("成交量")
        page.locator("#later").click()
        later = page.locator(".gs-plot [data-later]")
        expect(later.first).to_be_visible()
        new_dates = later.evaluate_all("(els) => els.map(e => e.dataset.session)")
        assert min(new_dates) > asof and max(new_dates) >= end
        assert interval.get_attribute("d") == interval_before
        assert evidence.inner_text() == evidence_before
        capture(page, f"{width}-{symbol}-later")
        page.locator("#later").click()
        expect(later).to_have_count(0)
        if symbol == "sh600519":
            page.go_back()
        else:
            page.locator("#back").click()
        expect(row).to_be_focused()
        expect(page.locator("#filter")).to_have_value(name)
        expect(page.locator("#my-tab")).to_have_attribute("aria-pressed", "true")

    page.locator("#filter").fill("振华重工")
    # Future coverage may grow. CI keeps a negative case; the dated acceptance run
    # sets GUANSHI_REAL_ARCHIVE=1 to exercise the actual unmodified published pool.
    if not os.environ.get("GUANSHI_REAL_ARCHIVE"):
        page.route("**/stock/600320*.json", lambda route: route.fulfill(status=404, body="{}"))
    page.locator('#rows a[data-asset="sh600320"]').click()
    expect(page.locator("#headline")).to_contain_text("暂无已归档")
    expect(page.locator("#quote-note")).to_be_empty()
    expect(page.locator(".gs-plot [data-session]")).to_have_count(0)
    expect(page.locator("#later")).to_be_hidden()
    page.locator("#open-evidence").click()
    expect(page.locator("#evidence-body")).to_contain_text("未发布")
    capture(page, f"{width}-uncovered")
    page.locator("#back").click()
    expect(page.locator("#filter")).to_have_value("振华重工")
    assert_fits_viewport(page)


@pytest.mark.parametrize("width", [390, 1440])
def test_sealed_index_preserves_original_reading(page: Page, width: int) -> None:
    from playwright.sync_api import expect

    catalog = page.request.get(f"{BASE}/lab/mock/data/guanshi/sh000001_seals.json")
    assert catalog.ok
    records = sorted(catalog.json()["records"], key=lambda record: record["asof"])
    assert len(records) >= 2
    previous, following = records[-2:]
    cutoff = previous["asof"]
    later_day = next(d for d in following["record"]["price_history"]["dates"] if d > cutoff)
    page.set_viewport_size({"width": width, "height": 844})
    page.goto(f"{BASE}/guanshi.html?asset=sh000001&asof={cutoff}")
    page.locator("#open-evidence").click()
    evidence = page.locator("#evidence-body")
    expect(evidence).to_contain_text("封存")
    expect(evidence).to_contain_text(cutoff)
    expect(page.locator(".gs-plot")).to_have_attribute("data-cutoff", cutoff)
    expect(page.locator(f".gs-plot [data-session='{cutoff}']")).to_have_count(1)
    expect(page.locator(f".gs-plot [data-session='{later_day}']")).to_have_count(0)
    original = evidence.inner_text()
    page.locator("#later").click()
    expect(page.locator(f".gs-plot [data-later][data-session='{later_day}']")).to_have_count(1)
    assert evidence.inner_text() == original
    assert_fits_viewport(page)
    capture(page, f"{width}-original-seal")
