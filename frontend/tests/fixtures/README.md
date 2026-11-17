# Browser and chart fixtures

## Browser smoke fixtures

The market responses are byte copies of published Worker `GET /market` payloads. They are routed only for browser tests; other external API requests receive an offline 503 JSON response.

- `stock_600519_market.json`: `GET /market?code=600519`, as of 2026-11-17; source payload SHA-256 `080d6ff89a350e119c6d38e5efeb6f86086ae1b8353c17dc75e64a4200113e05`.
- `stock_601838_market.json`: `GET /market?code=601838`, as of 2026-11-17; source payload SHA-256 `c39d55c92f5f8f260357b91c36e032e03c414e0194cbf9f9e0a2a0eb30559ddb`.

## Chart parity fixtures

These fixtures use published data through `lppl-data.js`; entries marked “trimmed” preserve only the fields or frames used by the tests.

- `sh000001_latest.json` from `_site/lab/mock/data/sh000001_latest.json`, as of 2026-10-30; source `web/mock/data/sh000001_latest.json`.
- `stock_600519.json` from `_site/lab/mock/data/stock/600519.json`, as of 2026-11-13; source `stock-results:stock/600519.json`.
- `stock_600519_market.json` from `LPPL.stock.market('600519')`, as of 2026-11-17; source `GET /market?code=600519` at the configured query API.
- `stock_601838.json` (trimmed) from `_site/lab/mock/data/stock/601838.json`, as of 2026-11-13; original SHA-256 `f232eba59d1fea0f72747d6ca2809c9ea566e79ad22ec801504bb0dc2c8581fe`. Retains `asof` and `top.scale_windows`; its `future_calendar` is copied from the published CN market calendar in `sh000001_history.json` because the stock result itself has no calendar field.
- `stock_601838_market.json` from `GET /market?code=601838` at the configured query API, as of 2026-11-17; 640 unadjusted vendor-native bars.
- `sh000001_history.json` (trimmed) from `_site/lab/mock/data/sh000001_history.json` / `web/mock/data/sh000001_history.json`; original SHA-256 `de73f1d73372f4b177018fe4a1422bbf6e5d42e42354539f4c086a0b74efe321`. Retains the original top-level metadata and `future_calendar`, with only frame `2025-08-11`; that frame has primary and secondary 6–12 month clusters extending beyond its last bar.

The parity tests read only these published payloads; they do not use demo data or calculate model values.
