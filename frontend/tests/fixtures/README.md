These are byte-for-byte copies of published JSON used through `lppl-data.js`:

- `sh000001_latest.json` from `_site/lab/mock/data/sh000001_latest.json`, as of 2026-10-30; source `web/mock/data/sh000001_latest.json`.
- `stock_600519.json` from `_site/lab/mock/data/stock/600519.json`, as of 2026-11-13; source `stock-results:stock/600519.json`.
- `stock_600519_market.json` from `LPPL.stock.market('600519')`, as of 2026-11-17; source `GET /market?code=600519` at the configured query API.
- `stock_601838.json` from `_site/lab/mock/data/stock/601838.json`, as of 2026-11-13; source `stock-results:stock/601838.json`. The published payload contains a 6–12 month `scale_windows` main interval, not an explicit cluster array.
- `stock_601838_market.json` from `GET /market?code=601838` at the configured query API, as of 2026-11-17; 640 unadjusted vendor-native bars.
- `sh000001_history.json` from `_site/lab/mock/data/sh000001_history.json`; byte-for-byte source `web/mock/data/sh000001_history.json`. The parity test selects its 2025-08-11 frame, which has primary and secondary 6–12 month clusters extending beyond that frame's last bar.

The parity tests read only these published payloads; they do not use demo data or calculate model values.
