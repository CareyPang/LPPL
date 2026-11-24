# Bottom repair V2 price-score evaluation

- Daily inputs: qfq OHLC from the local cache; weekly `fco_neg_intensity` frames are used only for OLD50.
- Session segments: dev through 2018-12-31; cal 2019-01-01–2021-12-31; test 2022-01-01–2025-08-29; later sessions are live.
- Candidate label windows require t−60 through t+61 to exist wholly inside the event segment. State events use a 20-session cooldown per index/state.
- Outcomes use next-session open O(t+1); all prices are gross index prices with no costs. Indices are not tradable; ETF execution is a later round.
- Random baselines: 2000 draws, seed 20261124; sample B0 events without replacement per index.
- Runtime: 95.908 seconds.

## Per-state, per-segment results

| State | Segment | Events | Within5_60 share | Random median / P5 / P95 | Median entry_dist_60 | Win R20 | Random win R20 P95 | Median R20 | Median MAE20 | Random median MAE20 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| V2_low_shock_50 | dev | 716 | 9.1% | 8.7% / 8.1% / 9.2% | 14.4% | 48.2% | 48.9% | -0.4% | -4.8% | -4.9% |
| V2_low_shock_50 | cal | 54 | 27.8% | 31.5% / 27.8% / 37.0% | 6.6% | 66.7% | 64.8% | 2.0% | -2.6% | -3.1% |
| V2_low_shock_50 | test | 180 | 9.4% | 12.2% / 11.1% / 13.3% | 12.1% | 41.7% | 45.6% | -1.2% | -4.2% | -3.7% |
| V2_low_shock_60 | dev | 662 | 9.4% | 8.6% / 7.9% / 9.4% | 14.2% | 48.5% | 49.2% | -0.3% | -4.6% | -4.9% |
| V2_low_shock_60 | cal | 50 | 38.0% | 32.0% / 26.0% / 38.0% | 6.0% | 66.0% | 66.0% | 2.4% | -2.7% | -3.2% |
| V2_low_shock_60 | test | 166 | 5.4% | 12.7% / 10.8% / 13.9% | 12.0% | 43.4% | 46.4% | -1.1% | -4.1% | -3.7% |
| V2_low_shock_70 | dev | 601 | 8.3% | 8.7% / 7.7% / 9.7% | 14.4% | 45.8% | 49.6% | -1.1% | -4.9% | -4.9% |
| V2_low_shock_70 | cal | 46 | 30.4% | 32.6% / 26.1% / 37.0% | 6.3% | 67.4% | 65.2% | 2.4% | -2.7% | -3.1% |
| V2_low_shock_70 | test | 153 | 5.2% | 12.4% / 9.8% / 14.4% | 11.9% | 42.5% | 47.1% | -1.5% | -4.5% | -3.8% |
| V2_short_50 | dev | 581 | 7.6% | 8.7% / 7.6% / 9.6% | 14.6% | 49.7% | 49.7% | -0.1% | -4.7% | -4.9% |
| V2_short_50 | cal | 38 | 21.1% | 31.6% / 23.7% / 39.5% | 6.7% | 73.7% | 68.4% | 3.0% | -2.7% | -3.2% |
| V2_short_50 | test | 151 | 4.0% | 11.9% / 9.9% / 13.9% | 12.0% | 43.0% | 47.0% | -0.7% | -4.2% | -3.8% |
| V2_short_60 | dev | 512 | 6.2% | 8.8% / 7.4% / 10.0% | 15.2% | 49.2% | 50.2% | -0.1% | -4.3% | -4.9% |
| V2_short_60 | cal | 32 | 9.4% | 31.2% / 21.9% / 40.6% | 7.6% | 71.9% | 68.8% | 2.7% | -2.8% | -3.2% |
| V2_short_60 | test | 130 | 3.1% | 12.3% / 9.2% / 14.6% | 12.4% | 42.3% | 47.7% | -0.9% | -4.0% | -3.8% |
| V2_short_70 | dev | 441 | 5.7% | 8.6% / 7.3% / 10.2% | 15.4% | 48.5% | 50.6% | -0.2% | -4.3% | -4.9% |
| V2_short_70 | cal | 23 | 4.3% | 30.4% / 17.4% / 43.5% | 8.2% | 73.9% | 73.9% | 0.5% | -3.7% | -3.1% |
| V2_short_70 | test | 105 | 1.0% | 11.4% / 8.6% / 15.2% | 12.7% | 44.8% | 48.6% | -1.1% | -3.9% | -3.8% |
| V2_medium_50 | dev | 562 | 5.9% | 8.7% / 7.7% / 9.6% | 15.5% | 47.5% | 49.6% | -0.4% | -4.6% | -4.9% |
| V2_medium_50 | cal | 45 | 13.3% | 33.3% / 26.7% / 40.0% | 7.7% | 66.7% | 66.7% | 2.2% | -3.5% | -3.1% |
| V2_medium_50 | test | 131 | 0.8% | 12.2% / 9.2% / 14.5% | 12.7% | 45.0% | 47.4% | -0.9% | -3.7% | -3.8% |
| V2_medium_60 | dev | 434 | 4.4% | 8.8% / 7.1% / 10.1% | 16.3% | 49.1% | 50.7% | -0.1% | -4.4% | -4.9% |
| V2_medium_60 | cal | 27 | 0.0% | 29.6% / 18.5% / 40.7% | 8.3% | 63.0% | 70.4% | 0.5% | -4.4% | -3.1% |
| V2_medium_60 | test | 99 | 0.0% | 12.1% / 8.1% / 15.2% | 14.5% | 43.4% | 49.5% | -1.0% | -3.7% | -3.8% |
| V2_medium_70 | dev | 302 | 3.0% | 8.6% / 6.6% / 10.9% | 17.7% | 50.3% | 51.7% | 0.1% | -4.1% | -4.9% |
| V2_medium_70 | cal | 11 | 0.0% | 18.2% / 9.1% / 36.4% | 10.2% | 63.6% | 81.8% | 5.8% | -1.9% | -2.6% |
| V2_medium_70 | test | 69 | 0.0% | 11.6% / 5.8% / 15.9% | 15.8% | 47.8% | 50.7% | -0.6% | -3.9% | -3.9% |
| OLD50 | dev | 326 | 10.7% | 8.6% / 6.7% / 10.7% | 13.9% | 50.6% | 51.2% | 0.1% | -4.1% | -5.0% |
| OLD50 | cal | 16 | 6.2% | 37.5% / 18.8% / 50.0% | 7.8% | 75.0% | 75.0% | 3.5% | -1.8% | -2.8% |
| OLD50 | test | 76 | 26.3% | 9.2% / 5.3% / 14.5% | 11.2% | 64.5% | 48.7% | 2.4% | -3.1% | -4.1% |
| STOPFALL | dev | 475 | 5.9% | 8.6% / 7.4% / 9.9% | 15.0% | 47.8% | 50.5% | -0.4% | -4.3% | -4.9% |
| STOPFALL | cal | 31 | 0.0% | 29.0% / 22.6% / 38.9% | 7.7% | 71.0% | 71.0% | 2.2% | -3.4% | -3.1% |
| STOPFALL | test | 113 | 0.9% | 12.4% / 8.8% / 15.0% | 12.9% | 43.4% | 48.7% | -1.4% | -3.7% | -3.8% |
| B0 | dev | 792 | 8.7% | 8.7% / 8.7% / 8.7% | 14.7% | 48.0% | 48.0% | -0.4% | -4.9% | -4.9% |
| B0 | cal | 68 | 33.8% | 33.8% / 33.8% / 33.8% | 7.1% | 60.3% | 60.3% | 1.9% | -3.1% | -3.1% |
| B0 | test | 204 | 12.3% | 12.3% / 12.3% / 12.3% | 11.6% | 43.6% | 43.6% | -0.6% | -3.7% | -3.7% |

## Per-index candidate and event counts

Each event column is the independent event count for that index and segment.

### dev

| Index | Candidate days | V2_low_shock_50 | V2_low_shock_60 | V2_low_shock_70 | V2_short_50 | V2_short_60 | V2_short_70 | V2_medium_50 | V2_medium_60 | V2_medium_70 | OLD50 | STOPFALL | B0 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| sh000001 | 3886 | 193 | 180 | 160 | 156 | 136 | 119 | 152 | 118 | 81 | 64 | 125 | 217 |
| sh000016 | 2097 | 107 | 97 | 89 | 88 | 78 | 68 | 90 | 66 | 41 | 56 | 73 | 117 |
| sh000300 | 1747 | 90 | 83 | 73 | 73 | 66 | 56 | 70 | 52 | 39 | 52 | 62 | 100 |
| sh000905 | 1337 | 73 | 66 | 61 | 57 | 48 | 42 | 53 | 41 | 30 | 41 | 46 | 79 |
| sh000688 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| sz399001 | 3874 | 194 | 178 | 165 | 156 | 138 | 115 | 146 | 117 | 83 | 79 | 126 | 215 |
| sz399006 | 1177 | 59 | 58 | 53 | 51 | 46 | 41 | 51 | 40 | 28 | 34 | 43 | 64 |

### cal

| Index | Candidate days | V2_low_shock_50 | V2_low_shock_60 | V2_low_shock_70 | V2_short_50 | V2_short_60 | V2_short_70 | V2_medium_50 | V2_medium_60 | V2_medium_70 | OLD50 | STOPFALL | B0 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| sh000001 | 61 | 5 | 4 | 4 | 3 | 2 | 1 | 3 | 1 | 0 | 2 | 2 | 7 |
| sh000016 | 130 | 7 | 7 | 6 | 5 | 5 | 3 | 5 | 3 | 0 | 0 | 4 | 8 |
| sh000300 | 115 | 8 | 7 | 7 | 6 | 4 | 3 | 7 | 2 | 1 | 0 | 4 | 12 |
| sh000905 | 165 | 9 | 8 | 8 | 8 | 7 | 5 | 8 | 6 | 3 | 8 | 6 | 11 |
| sh000688 | 120 | 7 | 7 | 7 | 5 | 5 | 4 | 6 | 6 | 4 | 0 | 5 | 8 |
| sz399001 | 105 | 7 | 7 | 6 | 5 | 4 | 3 | 7 | 4 | 0 | 3 | 4 | 10 |
| sz399006 | 149 | 11 | 10 | 8 | 6 | 5 | 4 | 9 | 5 | 3 | 3 | 6 | 12 |

### test

| Index | Candidate days | V2_low_shock_50 | V2_low_shock_60 | V2_low_shock_70 | V2_short_50 | V2_short_60 | V2_short_70 | V2_medium_50 | V2_medium_60 | V2_medium_70 | OLD50 | STOPFALL | B0 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| sh000001 | 235 | 13 | 12 | 11 | 12 | 9 | 8 | 10 | 7 | 5 | 4 | 8 | 16 |
| sh000016 | 447 | 24 | 23 | 20 | 18 | 18 | 14 | 17 | 13 | 7 | 7 | 15 | 26 |
| sh000300 | 483 | 26 | 23 | 21 | 20 | 18 | 14 | 18 | 12 | 8 | 6 | 15 | 30 |
| sh000905 | 462 | 24 | 23 | 22 | 22 | 16 | 12 | 17 | 14 | 11 | 10 | 15 | 27 |
| sh000688 | 577 | 28 | 25 | 24 | 24 | 19 | 19 | 20 | 16 | 9 | 20 | 18 | 33 |
| sz399001 | 610 | 30 | 28 | 25 | 25 | 21 | 16 | 22 | 15 | 11 | 12 | 18 | 33 |
| sz399006 | 740 | 35 | 32 | 30 | 30 | 29 | 22 | 27 | 22 | 18 | 17 | 24 | 39 |

## Dev-only V2 selection

**Selected: V2_low_shock_60**; dev events=662; within5_60=9.4%; random median=8.6%; lift=0.8%.

Selection maximizes dev within5_60 share minus its random median among variants with at least 30 dev events; ties prefer higher T, then low_shock, short, medium.

## Verdicts

| State | Verdict | Dev within5_60 / random P95 | Dev median MAE20 / random median | Test within5_60 / random P95 | Test median MAE20 / random median | Win R20 / random P95 (dev; test, report only) |
|---|---|---:|---:|---:|---:|---:|
| V2_low_shock_60 | NOT_VALID | 9.4% / 9.4% | -4.6% / -4.9% | 5.4% / 13.9% | -4.1% / -3.7% | 48.5% / 49.2%; 43.4% / 46.4% |
| OLD50 | NOT_VALID | 10.7% / 10.7% | -4.1% / -5.0% | 26.3% / 14.5% | -3.1% / -4.1% | 50.6% / 51.2%; 64.5% / 48.7% |
| STOPFALL | NOT_VALID | 5.9% / 9.9% | -4.3% / -4.9% | 0.9% / 15.0% | -3.7% / -3.8% | 47.8% / 50.5%; 43.4% / 48.7% |

Verdict rule: VALID requires both dev and test to have at least 15 events, within5_60 strictly above random P95, and median MAE20 at least the random median. Test events below 15 yields NOT_ESTABLISHED. R20 win-rate comparisons are report-only.

## Head-to-head: selected V2 minus OLD50

| Segment | Metric | V2−OLD50 | 95% bootstrap CI | V2 events | OLD50 events |
|---|---|---:|---:|---:|---:|
| dev | within5_60_share | -0.014 | [-0.053, 0.026] | 662 | 326 |
| dev | median_R20 | -0.004 | [-0.016, 0.010] | 662 | 326 |
| test | within5_60_share | -0.209 | [-0.308, -0.109] | 166 | 76 |
| test | median_R20 | -0.035 | [-0.057, -0.018] | 166 | 76 |

## Data coverage and exclusions

| Index | Raw OHLC rows | Duplicate rows dropped | Invalid OHLC rows dropped | Valid rows | Date range | Dev / Cal / Test / Live sessions |
|---|---:|---:|---:|---:|---|---|
| sh000001 | 8578 | 0 | 0 | 8578 | 1990-12-19–2026-10-28 | 6683 / 730 / 887 / 278 |
| sh000016 | 5540 | 0 | 0 | 5540 | 2004-01-02–2026-10-28 | 3645 / 730 / 887 / 278 |
| sh000300 | 5236 | 0 | 0 | 5236 | 2005-04-08–2026-10-28 | 3341 / 730 / 887 / 278 |
| sh000905 | 4807 | 0 | 0 | 4807 | 2007-01-15–2026-10-28 | 2912 / 730 / 887 / 278 |
| sh000688 | 1648 | 0 | 0 | 1648 | 2020-01-02–2026-10-23 | 0 / 486 / 887 / 275 |
| sz399001 | 8219 | 0 | 0 | 8219 | 1993-01-03–2026-10-28 | 6324 / 730 / 887 / 278 |
| sz399006 | 3982 | 0 | 0 | 3982 | 2010-06-02–2026-10-28 | 2087 / 730 / 887 / 278 |

Candidate diagnostics (DD252 pass days, label-window exclusions, final candidates) and missing V2-score counts are in the JSON per-index ledger. Random-baseline shortfalls are recorded per state/segment/index in the JSON.
