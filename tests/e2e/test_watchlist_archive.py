from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest


BASE = os.environ.get("E2E_BASE_URL", "http://127.0.0.1:8765")
ASSET = "index:sh000001"
TAPE = "watchlist-archive/index-sh000001.json"


def observation(day, start, end):
    return {
        "asof": day, "sealed_at": f"{day}T17:00:00+08:00",
        "public_first_published_at": None, "model_version": "fixture",
        "source_url": f"https://github.com/CareyPang/LPPL/blob/{'a' * 40}/forward_log/{day}/sh000001.json",
        "provenance": "index_seal",
        "windows": [{"scale": "6-12m", "start": start, "end": end, "evidence": "research_candidate"}],
    }


@pytest.mark.e2e
@pytest.mark.parametrize("width", [1280, 390])
def test_watchlist_archive_intervening_revisions_and_offline_retry(page, width):
    from playwright.sync_api import expect

    page.set_viewport_size({"width": width, "height": 900})
    page.add_init_script("""
      localStorage.setItem('lppl.watchlist.idx.v1', '["sh000001"]');
      const nativeFetch = window.fetch.bind(window);
      window.fetch = (input, init) => {
        if (window.offlineArchive && String(input).includes('watchlist-archive/'))
          return Promise.reject(new TypeError('offline archive'));
        return nativeFetch(input, init);
      };
    """)
    rows = [
        observation("2026-11-16", "2026-12-01", "2026-12-04"),
        observation("2026-11-17", "2026-12-07", "2026-12-10"),
        observation("2026-11-18", "2026-12-01", "2026-12-04"),
    ]
    page.route("**/watchlist-archive/index.json", lambda r: r.fulfill(json={
        "schema_version": 1, "stock_jobs_available": True, "assets": {ASSET: {"path": TAPE}}
    }))
    page.route("**/" + TAPE, lambda r: r.fulfill(json={
        "schema_version": 1, "asset_id": ASSET, "observations": rows, "gaps": [],
        "events": [{"kind": kind, "previous": i - 1 if i else None, "current": i}
                   for i, kind in enumerate(["baseline", "window_revised", "window_revised"])]
    }))
    page.goto(BASE + "/research-workspace.html")
    page.locator(f'[data-select="{ASSET}"]').click()
    cards = page.locator("#archive-records article")
    expect(cards).to_have_count(3)
    expect(cards.nth(0)).to_contain_text("2026-11-18")
    expect(cards.nth(0)).to_contain_text("2026-12-07 至 2026-12-10")
    expect(cards.nth(1)).to_contain_text("2026-11-17")
    expect(cards.nth(1)).to_contain_text("2026-12-01 至 2026-12-04")
    expect(cards.nth(0).get_by_text("本次原档", exact=False)).to_have_attribute("href", rows[2]["source_url"])

    page.locator("#archive-mode").select_option("close")
    page.locator("#archive-cutoff").fill("2026-11-17")
    expect(cards).to_have_count(1)
    expect(page.locator("#archive-records")).not_to_contain_text("2026-12-07")
    # Expire the adapter's 30s result cache and simulate transport failure.
    page.evaluate("""() => {
      window.offlineArchive = true;
      const now = Date.now;
      Date.now = () => now() + 31000;
    }""")
    page.locator("#refresh-results").click()
    expect(page.locator("#archive-retry")).to_be_visible()
    expect(cards).to_have_count(1)
    page.evaluate("window.offlineArchive = false")
    page.locator("#archive-retry").click()
    expect(page.locator("#archive-retry")).to_be_hidden()
    expect(page.locator("#archive-state")).to_contain_text("1 份原档")
    expect(page.locator("#archive-cutoff")).to_have_value("2026-11-17")
    page.locator("#archive-mode").select_option("all")
    expect(cards).to_have_count(3)


@pytest.mark.e2e
def test_exact_chart_and_return_keep_archive_close_filter(page):
    from playwright.sync_api import expect

    # Use a checked-in real seal so the hash covers the exact response bytes.
    day = "2026-11-17"
    key = f"forward_log/{day}/sh000001.json"
    raw = subprocess.check_output(["git", "cat-file", "blob", "HEAD:" + key], cwd=Path(__file__).resolve().parents[2])
    payload = json.loads(raw)
    digest = hashlib.sha256(raw).hexdigest()
    chart_path = f"watchlist-archive/originals/{digest}.json"
    row = {
        "asof": day, "sealed_at": f"{day}T21:26:36+08:00", "provenance": "index_seal",
        "model_version": payload["model_version"], "data_version": payload["data_version"],
        "source_url": f"https://github.com/CareyPang/LPPL/blob/34e4efc668c497e420a768cc997ca1df90659297/{key}",
        "sha256": digest, "chart_path": chart_path, "has_bars": True,
        "chart_content_sha256": "bba4ba7797a6c4a12fbda832202949d23b418e6db5aee06555a610b15f0803ba",
        "status": "no_qualified_fit", "evidence": "dev_only", "windows": [],
    }
    page.add_init_script("""localStorage.setItem('lppl.watchlist.idx.v1','["sh000001"]')""")
    page.route("**/watchlist-archive/index.json", lambda r: r.fulfill(json={
        "schema_version": 1, "stock_jobs_available": False, "assets": {ASSET: {"path": TAPE}},
    }))
    page.route("**/" + TAPE, lambda r: r.fulfill(json={
        "schema_version": 1, "asset_id": ASSET, "observations": [row], "gaps": [],
        "events": [{"kind": "baseline", "previous": None, "current": 0}],
    }))
    page.route("**/" + chart_path, lambda r: r.fulfill(body=raw, content_type="application/json"))
    page.goto(BASE + "/research-workspace.html")
    page.locator("#list-search").fill("000001")
    page.locator(f'[data-select="{ASSET}"]').click()
    page.locator("#archive-mode").select_option("close")
    page.locator("#archive-cutoff").fill("2026-11-18")
    link = page.locator('#archive-records > a[href^="chart.html"]').first
    link.click()
    chart_url = page.url
    query = parse_qs(urlsplit(page.url).query)
    assert query["asof"] == [day] and query["archive"] == [digest]
    expect(page.locator("#chart-page")).to_have_attribute("data-market-as-of", day)
    expect(page.locator("#error-panel")).to_be_hidden()
    page.locator("#return-link").click()
    expect(page.locator("#list-search")).to_have_value("000001")
    expect(page.locator("#archive-mode")).to_have_value("close")
    expect(page.locator("#archive-cutoff")).to_have_value("2026-11-18")
    expect(page.locator("#archive-state")).to_contain_text("1 份原档")
    # A changed original with identical identity/version must fail before any fallback.
    payload["price_history"]["close"][-1] += 1
    page.route("**/" + chart_path, lambda r: r.fulfill(json=payload))
    new_requests = []
    page.on("request", lambda request: new_requests.append(urlsplit(request.url).path))
    page.goto(chart_url)
    expect(page.locator("#error-panel")).to_be_visible()
    expect(page.locator("#error-message")).to_contain_text("指纹")
    expect(page.locator("#chart-page")).not_to_have_attribute("data-loaded", "true")
    # The separate watchlist menu reads its latest snapshot; the chart stays empty.
    assert not any(path.endswith("_history.json") or "/replay" in path for path in new_requests)
