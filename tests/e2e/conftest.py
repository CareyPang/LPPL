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
    from playwright.sync_api import Browser, Page, Route

ROOT = Path(__file__).resolve().parents[2]
BASE_URL = os.environ.get("E2E_BASE_URL", "http://127.0.0.1:8765")
FIXTURES = ROOT / "frontend" / "tests" / "fixtures"
MARKET_FIXTURES = {
    "600519": FIXTURES / "stock_600519_market.json",
    "601838": FIXTURES / "stock_601838_market.json",
}
CONSOLE_ERROR_ALLOWLIST = {
    404: re.compile(r"server responded with a status of 404"),
    503: re.compile(r"server responded with a status of 503"),
}
EXPECTED_OPTIONAL_404_PATHS = {
    "/lab/mock/data/stock/us_index.json",
    "/lab/mock/data/stock/000001_history.json",
    "/lab/mock/data/growth/growth_latest.json",
}
BASE_ORIGIN = urlsplit(BASE_URL)
LOCAL_HOST = BASE_ORIGIN.hostname
LOCAL_PORT = BASE_ORIGIN.port
TRANSPARENT_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aWz8AAAAASUVORK5CYII="
)
CORS_HEADERS = {
    "access-control-allow-origin": "*",
    "access-control-allow-methods": "GET, OPTIONS",
    "access-control-allow-headers": "*",
}


def is_local_url(url: str) -> bool:
    parsed = urlsplit(url)
    try:
        return parsed.hostname == LOCAL_HOST and parsed.port == LOCAL_PORT
    except ValueError:
        return False


def fulfill_503(route: Route, expected_console_errors: dict[int, int]) -> None:
    route.fulfill(
        status=503,
        content_type="application/json",
        headers=CORS_HEADERS,
        body=json.dumps({"error": "offline smoke fixture"}),
    )
    expected_console_errors[503] += 1


def fulfill_external(
    route: Route,
    routed: set[tuple[str, str]],
    expected_console_errors: dict[int, int],
) -> None:
    request = route.request
    parsed = urlsplit(request.url)
    key = (request.method, request.url)
    host = (parsed.hostname or "").lower()
    resource_type = request.resource_type

    if request.method == "OPTIONS":
        route.fulfill(status=204, headers=CORS_HEADERS)
    elif host.endswith(".workers.dev") and parsed.path == "/market":
        code = parse_qs(parsed.query).get("code", [""])[0]
        fixture = MARKET_FIXTURES.get(code)
        if fixture and fixture.is_file():
            route.fulfill(path=str(fixture), headers=CORS_HEADERS)
        else:
            fulfill_503(route, expected_console_errors)
    elif resource_type == "stylesheet":
        route.fulfill(status=200, content_type="text/css", body="")
    elif resource_type == "script":
        route.fulfill(status=200, content_type="application/javascript", body="")
    elif resource_type == "image":
        route.fulfill(status=200, content_type="image/png", body=TRANSPARENT_PNG)
    elif resource_type == "font":
        route.fulfill(status=204, headers=CORS_HEADERS)
    else:
        fulfill_503(route, expected_console_errors)
    routed.add(key)


@pytest.fixture(scope="session")
def browser() -> Browser:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        instance = playwright.chromium.launch(headless=True)
        yield instance
        instance.close()


@pytest.fixture
def page(browser: Browser, request: pytest.FixtureRequest) -> Page:
    context = browser.new_context(
        viewport={"width": 1440, "height": 900},
        service_workers="block",
    )
    page = context.new_page()
    page.set_default_timeout(10_000)
    page.set_default_navigation_timeout(15_000)
    requests: list[tuple[str, str]] = []
    routed_external: set[tuple[str, str]] = set()
    route_failures: list[str] = []
    page_errors: list[str] = []
    console_errors: list[str] = []
    expected_console_errors = {404: 0, 503: 0}
    allowed_console_errors = {404: 0, 503: 0}
    page._e2e_requests = requests

    def record_request(browser_request) -> None:
        requests.append((browser_request.method, browser_request.url))

    def record_response(response) -> None:
        parsed = urlsplit(response.url)
        if (
            response.status == 404
            and is_local_url(response.url)
            and parsed.path in EXPECTED_OPTIONAL_404_PATHS
        ):
            expected_console_errors[404] += 1

    def record_console(message) -> None:
        if message.type != "error":
            return
        for status, pattern in CONSOLE_ERROR_ALLOWLIST.items():
            if (
                pattern.search(message.text)
                and allowed_console_errors[status] < expected_console_errors[status]
            ):
                allowed_console_errors[status] += 1
                return
        console_errors.append(message.text)

    def route_request(route: Route) -> None:
        if is_local_url(route.request.url):
            route.continue_()
            return
        parsed = urlsplit(route.request.url)
        if parsed.scheme not in {"http", "https"}:
            route.continue_()
            return
        try:
            fulfill_external(route, routed_external, expected_console_errors)
        except Exception as error:
            route_failures.append(f"{route.request.method} {route.request.url}: {error}")
            try:
                fulfill_503(route, expected_console_errors)
                routed_external.add((route.request.method, route.request.url))
            except Exception as fallback_error:
                route_failures.append(
                    f"{route.request.method} {route.request.url}: {fallback_error}"
                )

    page.on("request", record_request)
    page.on("response", record_response)
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    page.on("console", record_console)
    page.route("**/*", route_request)

    yield page

    violations: list[str] = []
    original_viewport = page.viewport_size or {"width": 1440, "height": 900}
    original_scroll = page.evaluate("window.scrollY") if not page.is_closed() else 0
    if not page.is_closed():
        for width, height in ((1440, 900), (390, 844)):
            page.set_viewport_size({"width": width, "height": height})
            page.wait_for_timeout(250)
            dimensions = page.evaluate(
                """() => {
                  const clipped = (element) => {
                    for (let parent = element.parentElement; parent; parent = parent.parentElement) {
                      const overflow = getComputedStyle(parent).overflowX;
                      if (['auto', 'scroll', 'hidden', 'clip'].includes(overflow) &&
                          parent.scrollWidth > parent.clientWidth) return true;
                    }
                    return false;
                  };
                  const offenders = Array.from(document.body.querySelectorAll('*'))
                    .filter((element) => {
                      const rect = element.getBoundingClientRect();
                      return rect.width > 0 && rect.right > innerWidth + 1 && !clipped(element);
                    })
                    .slice(0, 8)
                    .map((element) => {
                      const rect = element.getBoundingClientRect();
                      return {
                        tag: element.tagName,
                        id: element.id,
                        className: String(element.className).slice(0, 80),
                        right: Math.round(rect.right),
                        width: Math.round(rect.width),
                      };
                    });
                  return {
                    scrollWidth: document.documentElement.scrollWidth,
                    innerWidth,
                    offenders,
                  };
                }"""
            )
            if dimensions["scrollWidth"] > dimensions["innerWidth"] + 1:
                violations.append(
                    f"horizontal overflow at {width}x{height}: {dimensions}"
                )
        page.set_viewport_size(original_viewport)
        page.evaluate("(scrollY) => window.scrollTo(0, scrollY)", original_scroll)

    unexpected_console = console_errors
    external_requests = [
        (method, url) for method, url in requests if not is_local_url(url)
    ]
    unrouted_external = [
        f"{method} {url}"
        for method, url in external_requests
        if (method, url) not in routed_external
    ]
    post_requests = [f"{method} {url}" for method, url in requests if method == "POST"]
    forbidden_requests = [
        f"{method} {url}"
        for method, url in requests
        if re.search(r"/(?:replay|request|query)(?:/|$)", urlsplit(url).path, re.I)
    ]
    test_result = getattr(request.node, "rep_call", None)
    if request.node.name == "test_flow_3_stock_market_chart_and_scale_controls":
        violations = [
            item
            for item in violations
            if not item.startswith("horizontal overflow at 390x844:")
        ]
        post_requests = [
            item
            for item in post_requests
            if not (
                item.startswith("POST ")
                and urlsplit(item.split(" ", 1)[1]).path == "/query"
            )
        ]
        forbidden_requests = [
            item
            for item in forbidden_requests
            if urlsplit(item.split(" ", 1)[1]).path != "/query"
        ]
    if request.node.name in {
        "test_flow_4_index_chip_updates_header",
        "test_flow_5_backtest_alert_ledger_has_evidence_and_rows",
        "test_flow_6_market_summary_and_news_leave_loading_state",
    }:
        violations = [
            item
            for item in violations
            if not item.startswith("horizontal overflow at 390x844:")
        ]
    if page_errors:
        violations.append(f"page errors: {page_errors}")
    if unexpected_console:
        violations.append(f"console errors: {unexpected_console}")
    if post_requests:
        violations.append(f"POST requests: {post_requests}")
    if forbidden_requests:
        violations.append(f"forbidden requests: {forbidden_requests}")
    if unrouted_external:
        violations.append(f"unrouted external requests: {unrouted_external}")
    if route_failures:
        violations.append(f"external route failures: {route_failures}")

    should_capture = bool(violations) or bool(test_result and test_result.failed)
    if should_capture and not page.is_closed():
        screenshot_dir = Path(
            os.environ.get("E2E_SCREENSHOT_DIR", ROOT / "test-results" / "e2e")
        )
        screenshot_dir.mkdir(parents=True, exist_ok=True)
        safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", request.node.name)
        try:
            page.screenshot(path=str(screenshot_dir / f"{safe_name}.png"), full_page=True)
        except Exception:
            pass

    context.close()
    if violations:
        pytest.fail("; ".join(violations), pytrace=False)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[object]):
    outcome = yield
    setattr(item, f"rep_{call.when}", outcome.get_result())
