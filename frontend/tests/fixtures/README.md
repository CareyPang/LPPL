# Browser smoke fixtures

The market responses are byte copies of published Worker `GET /market` payloads. They are routed only for browser tests; other external API requests receive an offline 503 JSON response.

- `stock_600519_market.json`: `GET /market?code=600519`, as of 2026-11-17; source payload SHA-256 `080d6ff89a350e119c6d38e5efeb6f86086ae1b8353c17dc75e64a4200113e05`.
- `stock_601838_market.json`: `GET /market?code=601838`, as of 2026-11-17; source payload SHA-256 `c39d55c92f5f8f260357b91c36e032e03c414e0194cbf9f9e0a2a0eb30559ddb`.
