These are byte-for-byte copies of published JSON used through `lppl-data.js`:

- `sh000001_latest.json` from `_site/lab/mock/data/sh000001_latest.json`, as of 2026-10-30; source `web/mock/data/sh000001_latest.json`.
- `stock_600519.json` from `_site/lab/mock/data/stock/600519.json`, as of 2026-11-13; source `stock-results:stock/600519.json`.
- `stock_600519_market.json` from `LPPL.stock.market('600519')`, as of 2026-11-17; source `GET /market?code=600519` at the configured query API.

The parity tests read only these published payloads; they do not use demo data or calculate model values.
