from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from ingestion.fundamentals import parse_companyfacts
from quant import fundamentals as F
from quant import indicators as I
from quant.macro import macro_features
from quant.sentiment import sentiment_features


def series(values, start="2025-01-01"):
    return pd.Series(values, index=pd.bdate_range(start, periods=len(values)), dtype=float)


# ------------------------------------------------------------------ indicators
def test_returns_and_sma():
    s = series(np.arange(1, 301))
    assert I.trailing_return(s, 21) == pytest.approx(300 / 279 - 1)
    assert I.sma(s, 50) == pytest.approx(np.arange(251, 301).mean())
    assert I.trailing_return(s, 400) is None


def test_rsi_extremes_and_midpoint():
    assert I.rsi(series(np.arange(1, 50))) == 100.0
    assert I.rsi(series(np.arange(50, 1, -1))) == pytest.approx(0.0)
    zigzag = series([100 + (1 if i % 2 else -1) for i in range(100)])
    assert I.rsi(zigzag) == pytest.approx(50, abs=5)


def test_volatility_drawdown_beta():
    rng = np.random.default_rng(0)
    bench = series(100 * np.exp(np.cumsum(rng.normal(0, 0.01, 300))))
    stock = series(bench.values ** 2 / 100)  # log-returns doubled => beta ~2
    assert I.beta(stock, bench) == pytest.approx(2, abs=0.1)
    assert I.volatility(bench, 252) == pytest.approx(0.01 * np.sqrt(252), rel=0.15)
    assert I.max_drawdown(series([100, 120, 60, 90])) == pytest.approx(-0.5)


def test_price_features_shape():
    s = series(np.linspace(100, 150, 300))
    f = I.price_features(s, s)
    assert f["last_close"] == 150 and f["last_date"] == s.index[-1].isoformat()[:10]
    assert f["pct_from_52w_high"] == 0 and f["rsi_14"] == 100.0
    assert f["beta_1y"] == pytest.approx(1) and f["rel_strength_3m"] == pytest.approx(0)
    assert I.price_features(pd.Series(dtype=float)) == {}


# ------------------------------------------------------------------ fundamentals
def fact(concept, start, end, value, filed, unit="USD", accn="a"):
    return {"concept": concept, "unit": unit, "period_start": start, "period_end": end,
            "value": value, "filed": filed, "accn": accn}


REV = "us-gaap:Revenues"


def ytd_year(fy_start, q, filed_offsets=(40, 40, 40, 60), concept=REV, scale=1.0):
    """Facts for one fiscal year the way 10-Qs/10-Ks report them: Q1 3m, H1 6m, 9M, FY."""
    s = date.fromisoformat(fy_start)
    ends = [s + timedelta(days=d) for d in (90, 181, 272, 364)]
    cum = np.cumsum(q) * scale
    return [fact(concept, s.isoformat(), e.isoformat(), float(v), (e + timedelta(days=o)).isoformat())
            for e, v, o in zip(ends, cum, filed_offsets)]


def test_quarterly_derived_from_ytd_chain():
    facts = ytd_year("2025-01-01", [10, 20, 30, 40])
    q = F.quarterly(F.point_in_time(facts, [REV], date(2027, 1, 1)))
    assert sorted(q.values()) == [10, 20, 30, 40]
    assert F.ttm(q)[0] == 100


def test_point_in_time_hides_unfiled_and_prefers_restatement():
    facts = ytd_year("2025-01-01", [10, 20, 30, 40])
    # Before the 10-K is filed, Q4 is unknown -> no TTM.
    q = F.quarterly(F.point_in_time(facts, [REV], date(2026, 1, 15)))
    assert len(q) == 3 and F.ttm(q) is None
    # A later restatement of Q1 wins only once it is filed.
    restated = fact(REV, "2025-01-01", "2025-04-01", 12.0, "2026-06-01", accn="b")
    early = F.point_in_time(facts + [restated], [REV], date(2026, 5, 1))
    late = F.point_in_time(facts + [restated], [REV], date(2026, 7, 1))
    assert early[(date(2025, 1, 1), date(2025, 4, 1))] == 10
    assert late[(date(2025, 1, 1), date(2025, 4, 1))] == 12


def test_concept_priority_merges_tag_switch():
    old = ytd_year("2024-01-01", [5, 5, 5, 5], concept="us-gaap:SalesRevenueNet")
    new = ytd_year("2025-01-01", [10, 20, 30, 40], concept=REV)
    concepts = ["us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax", REV, "us-gaap:SalesRevenueNet"]
    q = F.quarterly(F.point_in_time(old + new, concepts, date(2027, 1, 1)))
    assert len(q) == 8
    cur = F.ttm(q)
    prev = F.ttm(q, cur[1] - timedelta(days=330))
    assert (cur[0], prev[0]) == (100, 20)


def test_fundamental_features_ratios():
    facts = (
        ytd_year("2024-01-01", [20, 20, 20, 20]) + ytd_year("2025-01-01", [25, 25, 25, 25])
        + ytd_year("2025-01-01", [1, 1, 1, 1], concept="us-gaap:EarningsPerShareDiluted", scale=1)
        + ytd_year("2025-01-01", [5, 5, 5, 5], concept="us-gaap:NetIncomeLoss")
        + [fact("dei:EntityCommonStockSharesOutstanding", "2026-01-20", "2026-01-20", 10, "2026-02-01", "shares"),
           fact("us-gaap:StockholdersEquity", "2025-12-31", "2025-12-31", 50, "2026-02-01"),
           fact("us-gaap:LongTermDebtNoncurrent", "2025-12-31", "2025-12-31", 25, "2026-02-01")]
    )
    for f in facts:
        f["unit"] = "USD/shares" if "EarningsPerShare" in f["concept"] else f["unit"]
    out = F.fundamental_features(facts, date(2026, 3, 15), last_close=80.0)
    assert out["revenue_ttm"] == 100 and out["revenue_growth_yoy"] == pytest.approx(0.25)
    assert out["net_margin"] == pytest.approx(0.2)
    assert out["eps_ttm"] == 4 and out["pe_ttm"] == 20
    assert out["market_cap"] == 800 and out["debt_to_equity"] == 0.5
    assert out["stale"] is False and out["gross_margin"] is None


def test_parse_companyfacts():
    payload = {"facts": {
        "us-gaap": {"Revenues": {"units": {"USD": [
            {"start": "2025-01-01", "end": "2025-03-31", "val": 10, "filed": "2025-05-01", "form": "10-Q",
             "fp": "Q1", "fy": 2025, "accn": "x"},
            {"start": "2020-01-01", "end": "2020-03-31", "val": 1, "filed": "2020-05-01", "form": "10-Q", "accn": "o"},
            {"start": "2025-01-01", "end": "2025-03-31", "val": 10, "filed": "2025-05-01", "form": "8-K", "accn": "y"},
        ]}}},
        "dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": [
            {"end": "2025-04-20", "val": 100, "filed": "2025-05-01", "form": "10-Q", "accn": "x"}]}}},
    }}
    rows = parse_companyfacts("AAPL", payload, date(2024, 1, 1))
    assert len(rows) == 2
    inst = next(r for r in rows if r["concept"].startswith("dei"))
    assert inst["period_start"] == inst["period_end"] == "2025-04-20"


# ------------------------------------------------------------------ macro + sentiment
def test_macro_respects_release_lag():
    rows = [{"series_id": "CPIAUCSL", "date": d, "value": v} for d, v in
            [("2025-10-01", 300.0), ("2026-09-01", 309.0), ("2026-10-01", 310.0)]]
    rows += [{"series_id": "DGS10", "date": "2026-11-09", "value": 4.1}]
    out = macro_features(rows, date(2026, 11, 11))
    # Oct CPI (obs 10-01) is not public by 11-11 with a 45-day lag; Sep CPI is.
    assert out["CPIAUCSL"]["date"] == "2026-09-01" and out["CPIAUCSL"]["value"] == 309
    assert out["DGS10"]["value"] == 4.1
    assert macro_features(rows, date(2026, 11, 20))["CPIAUCSL"]["yoy"] == pytest.approx(310 / 300 - 1)


def test_sentiment_features_windows():
    as_of = date(2026, 11, 11)
    rows = [{"published_at": f"2026-11-{d:02d}T12:00:00+00:00", "sentiment": s}
            for d, s in [(10, 0.8), (9, 0.6), (1, -0.5)]]
    rows.append({"published_at": "2026-11-11T09:00:00+00:00", "sentiment": -1.0})  # same day: excluded
    f = sentiment_features(rows, as_of)
    assert (f["n_7d"], f["n_30d"]) == (2, 3)
    assert f["mean_7d"] == pytest.approx(0.7)
    assert f["mean_30d"] == pytest.approx(0.3)
    assert sentiment_features([], as_of)["n_30d"] == 0
