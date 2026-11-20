"""Walk the reader's route on the built site, including its real date-stamped archives."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlsplit

import pytest

if TYPE_CHECKING:
    from playwright.sync_api import Browser, Page, Route

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


def moutai_replay_state(page: Page) -> tuple:
    """Read exactly what is on the chart before and after revealing subsequent prices."""
    from playwright.sync_api import expect

    page.locator("#asof").select_option("2025-05-23")
    page.locator("#open-evidence").click()
    expect(page.locator("#evidence-body")).to_contain_text("历史重算")
    evidence = page.locator("#evidence-body").inner_text()
    sources = page.locator("#evidence-body a").evaluate_all("(links) => links.map(a => a.href)")
    windows = page.locator("#intervals").inner_text()
    assert "2025-06-20" in windows and "2025-07-08" in windows
    candles = page.locator(".gs-plot [data-session]")
    original = candles.evaluate_all("(nodes) => nodes.map(n => n.outerHTML)")
    expect(page.locator(".gs-plot [data-later]")).to_have_count(0)
    page.locator("#later").click()
    later = page.locator(".gs-plot [data-later]")
    expect(later.first).to_be_visible()
    revealed = later.evaluate_all("(nodes) => nodes.map(n => n.outerHTML)")
    return evidence, sources, windows, original, revealed


@pytest.mark.parametrize(("width", "height"), [(1440, 900), (390, 844)])
def test_moutai_manual_refresh_preserves_original_chart_and_survives_outage(
    browser: Browser, width: int, height: int,
) -> None:
    """Controlled transport regression. Every OHLCV number comes from the archived Worker GET."""
    from playwright.sync_api import expect

    root = Path(__file__).resolve().parents[2]
    archive_path = "/market/archives/sh600519_2026-11-17.json"
    source = root / ("web/mock/data" + archive_path)
    older = json.loads(source.read_text(encoding="utf-8"))
    # Crop the local starting archive to the previous close. Omit one actual
    # historical session to make a chart that leaks refreshed bars visibly different.
    older["price"] = [bar for bar in older["price"][:-1] if bar["date"] != "2025-05-22"]
    older["latest"] = older["price"][-1]
    older["asof"] = older["cutoff"] = older["latest"]["date"]
    market_requests = []

    def serve(route: Route) -> None:
        url = urlsplit(route.request.url)
        if url.path.endswith("/market"):
            market_requests.append((route.request.method, parse_qs(url.query)))
            if len(market_requests) == 1:
                route.fulfill(path=source, content_type="application/json")
            else:
                route.fulfill(status=503, json={"error": "offline acceptance"})
        elif url.netloc != urlsplit(BASE).netloc or route.request.method != "GET":
            route.abort()
            pytest.fail(f"unexpected request: {route.request.method} {url.netloc}{url.path}")
        elif url.path.endswith(archive_path):
            route.fulfill(json=older)
        elif url.path.endswith("/stock/600519.json"):
            route.fulfill(path=root / "frontend/tests/fixtures/stock_600519.json")
        else:
            route.continue_()

    with browser.new_context(viewport={"width": width, "height": height}, service_workers="block") as ctx:
        # Point the existing client at the test origin. No external quote request leaves Chromium.
        ctx.add_init_script("window.LPPL_QUERY_API = location.origin + '/controlled-quote-source'")
        ctx.route("**/*", serve)
        page = ctx.new_page()
        page.clock.set_fixed_time(datetime(2026, 11, 18, 8, tzinfo=UTC))
        page.goto(f"{BASE}/guanshi.html")
        row = page.locator('#rows a[data-asset="sh600519"]')
        row.click()
        original = moutai_replay_state(page)
        page.locator("#asof").select_option(older["asof"])
        assert not market_requests
        refresh = page.locator("#refresh-quote")
        refresh.click()
        cutoff = page.locator("#cutoffs")
        expect(cutoff).to_contain_text("行情截至 2026-11-17")
        expect(cutoff).to_contain_text("模型截至 2026-11-13")
        last = page.locator(".gs-plot [data-session='2026-11-17']")
        expect(last).to_have_count(1)
        readout = page.get_by_role("slider").get_attribute("aria-valuetext")
        assert "1,457.7" in readout
        refresh.click()
        expect(page.locator("#quote-feedback")).to_contain_text("暂不可用")
        expect(last).to_have_count(1)
        expect(refresh).to_be_enabled()
        assert page.get_by_role("slider").get_attribute("aria-valuetext") == readout
        assert moutai_replay_state(page) == original
        page.locator("#back").click()
        row.click()
        expect(cutoff).to_contain_text("行情截至 2026-11-17")
        assert market_requests == [("GET", {"code": ["600519"]})] * 2
        assert_fits_viewport(page)


@pytest.mark.skipif(os.getenv("GUANSHI_LIVE_QUOTE") != "1", reason="requires a local Worker with real upstream access")
@pytest.mark.parametrize(("width", "height"), [(1440, 900), (390, 844)])
def test_real_worker_update_then_offline(browser: Browser, width: int, height: int) -> None:
    """Opt-in proof of a genuinely newer bar. No response is routed, replaced or replayed."""
    from playwright.sync_api import expect

    assert urlsplit(BASE).hostname == "127.0.0.1"
    with browser.new_context(viewport={"width": width, "height": height}, service_workers="block") as ctx:
        page = ctx.new_page()
        page.goto(f"{BASE}/guanshi.html?asset=sh600519")
        refresh = page.locator("#refresh-quote")
        expect(refresh).to_be_visible()
        select = page.locator("#asof")
        archived_asof = select.input_value()
        original = moutai_replay_state(page)
        select.select_option(archived_asof)
        model_cutoff = page.locator("#cutoffs span").nth(1).inner_text()
        with page.expect_response("http://127.0.0.1:8798/market?code=600519") as received:
            refresh.click()
        response = received.value
        assert response.ok and response.request.method == "GET"
        payload = response.json()
        assert payload["source"] == "tencent_fqkline" and payload["stale"] is False
        assert payload["asof"] > archived_asof, "the real upstream did not supply a newer session"
        expect(page.locator("#quote-feedback")).to_contain_text("已读取截至 " + payload["asof"])
        latest = payload["price"][-1]
        assert latest == payload["latest"] and latest["date"] == payload["asof"]
        slider = page.get_by_role("slider")
        reading = slider.get_attribute("aria-valuetext")
        assert reading.startswith(payload["asof"])
        for label, key in (("开", "open"), ("高", "high"), ("低", "low"), ("收", "close")):
            assert label + " " + f"{latest[key]:,.2f}".rstrip("0").rstrip(".") in reading
        active = page.locator(".gs-plot [data-session]")
        candles = active.evaluate_all("(nodes) => nodes.map(n => n.outerHTML)")
        expect(page.locator("#cutoffs span").nth(1)).to_have_text(model_cutoff)
        capture(page, f"{width}-real-update")

        ctx.set_offline(True)
        refresh.click()
        expect(page.locator("#quote-feedback")).to_contain_text("暂不可用")
        expect(page.locator("#quote-feedback")).to_contain_text(payload["asof"])
        expect(refresh).to_be_enabled()
        assert active.evaluate_all("(nodes) => nodes.map(n => n.outerHTML)") == candles
        assert slider.get_attribute("aria-valuetext") == reading
        capture(page, f"{width}-offline-retained")
        # This date switch and its later-price reveal must even work offline.
        assert moutai_replay_state(page) == original
        assert_fits_viewport(page)
        capture(page, f"{width}-original-replay")
        if output := os.getenv("GUANSHI_CAPTURE_DIR"):
            receipt = {
                "viewport": [width, height], "read_at_utc": datetime.now(UTC).isoformat(),
                "request": response.url, "status": response.status, "source": payload["source"],
                "generated_at": payload["generated_at"], "cache": payload["cache"],
                "archive_asof": archived_asof, "model_cutoff": model_cutoff,
                "source_bars": len(payload["price"]), "latest": latest, "readout": reading,
                "response_sha256": sha256(response.body()).hexdigest(),
                "history_before_and_after_sha256": sha256(json.dumps(original, ensure_ascii=False).encode()).hexdigest(),
                "original_quote_and_model_sources": original[1],
                "saved_after_network_failure": True,
            }
            (Path(output) / f"{width}-real-update.json").write_text(
                json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
