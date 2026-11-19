import os
from pathlib import Path

from playwright.sync_api import Page, expect

BASE_URL = os.environ.get("E2E_BASE_URL", "http://127.0.0.1:8765")
GROWTH_FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "frontend"
    / "tests"
    / "fixtures"
    / "growth_latest.json"
)


def test_growth_position_card_displays_quarterly_and_weekly_values(page: Page) -> None:
    page.route(
        "**/lab/mock/data/growth/growth_latest.json",
        lambda route: route.fulfill(path=str(GROWTH_FIXTURE)),
    )
    page.set_viewport_size({"width": 1280, "height": 900})
    page.goto(f"{BASE_URL}/market.html#s-val")

    card = page.locator("#s-growth .growth-card").filter(
        has_text="公募成长仓位"
    )
    expect(card).to_have_count(1)
    expect(card).to_be_visible()
    expect(card).to_contain_text("正式季度值：57.40%")
    expect(card).to_contain_text("2026Q3")
    expect(card).to_contain_text("数据截至 2026-09-30")
    expect(card).to_contain_text("n=50")
    expect(card).to_contain_text("覆盖率 80.00%")
    expect(card).to_contain_text("周度代理（回归估算，不是正式值）")
    expect(card).to_contain_text("截至 2026-11-13")
    expect(card).to_contain_text("n=52 周")
    expect(card).to_contain_text("R² 0.6543")
    expect(card).to_contain_text("申万一级行业分类")
    expect(card).to_contain_text("非负最小二乘回归")
