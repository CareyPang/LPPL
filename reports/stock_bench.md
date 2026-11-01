# 个股引擎基准测试

- 日期：2026-11-01
- CPU：8 核（`os.cpu_count()`）
- 并行度：8 workers
- Data: Tencent raw daily × Sina HFQ; all ten stocks loaded successfully through 2026-10-30.
- Timing: load is measured once per code; subsequent predictions/history reuse that loaded frame. History cold/warm used an isolated cache under `data/stock/bench_20261101/`.
- LPPLS box: `v1` (the environment's `LPPLS_BOX` setting).

| Code | Load (s) | `stk_lite` predict (s) | `stk_full` predict (s) | 104-week history cold (s) | Warm (s) |
|---|---:|---:|---:|---:|---:|
| 000001 | 25.825 | 1.778 | 12.209 | 72.238 | 6.660 |
| 000002 | 25.158 | 1.223 | 12.917 | 74.439 | 6.058 |
| 000063 | 20.223 | 1.392 | 12.758 | 78.761 | 6.492 |
| 000066 | 20.277 | 1.123 | 16.192 | 83.444 | 4.711 |
| 000069 | 20.271 | 1.023 | 12.949 | 78.632 | 6.159 |
| 000100 | 15.963 | 0.953 | 11.798 | 69.391 | 5.201 |
| 000157 | 17.582 | 1.388 | 14.737 | 77.168 | 5.769 |
| 000166 | 9.854 | 1.599 | 25.983 | 95.833 | 5.554 |
| 000301 | 19.196 | 1.801 | 15.815 | 83.109 | 8.187 |
| 000333 | 9.878 | 1.121 | 16.471 | 86.080 | 8.656 |

No load, prediction, or history failures occurred. Each history run returned 104 weekly frames.
