# TI Agent evaluation

Generated 2026-11-14T20:42:19+00:00. Excess returns are over the benchmark; intervals are 95% week-block bootstrap intervals. Protocol: docs/paper, section 8.

## Status

- Weeks with views: **1** (40 views of the full system)
- Weeks whose 1–3 month views have closed at 63 trading days: **0 of 12** needed for the primary analysis
- Primary analysis: **not yet: results below are preliminary**

## Views

| Variant / horizon | Scored | Hit rate (own horizon) | p (> 50%) | Bullish excess | Bearish excess | Long − short | Brier | ECE |
|---|---:|---:|---:|---|---|---|---:|---:|
| full/21 | 0 | — | — | — | — | — | — | — |
| full/63 | 0 | — | — | — | — | — | — | — |
| full/252 | 0 | — | — | — | — | — | — | — |
| no_retrieval/21 | 0 | — | — | — | — | — | — | — |
| no_retrieval/63 | 0 | — | — | — | — | — | — | — |
| no_retrieval/252 | 0 | — | — | — | — | — | — | — |

## Baselines

| Baseline / horizon | Stocks scored | Mean excess | Beat the benchmark |
|---|---:|---|---:|
| screen_picks/21 | 0 | — | — |
| screen_picks/63 | 0 | — | — |
| screen_picks/252 | 0 | — | — |
| random_quality/21 | 0 | — | — |
| random_quality/63 | 0 | — | — |
| random_quality/252 | 0 | — | — |
| quality_universe/21 | 0 | — | — |
| quality_universe/63 | 0 | — | — |
| quality_universe/252 | 0 | — | — |

## Comparisons (paired by week)

- bullish_vs_screen_picks/21: — over 0 week(s)
- bullish_vs_screen_picks/63: — over 0 week(s)
- bullish_vs_screen_picks/252: — over 0 week(s)

## Citation faithfulness

- No annotations yet (`python -m evaluation.faithfulness sample`).
