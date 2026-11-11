"""S&P 500 universe + weekly momentum/quality screen."""
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from ingestion import finnhub, prices, universe
from quant import screen
from tests.fakes import FakeStore


def _wiki_html(n=450):
    rows = "".join(
        f"<tr><td>{'BRK.B' if i == 0 else f'T{i:03d}'}</td><td>Company {i}</td><td>Tech</td><td>{1000 + i}</td></tr>"
        for i in range(n))
    return ("<table><tr><th>Symbol</th><th>Security</th><th>GICS Sector</th><th>CIK</th></tr>"
            f"{rows}</table><table><tr><th>Date</th><th>Added</th></tr><tr><td>x</td><td>y</td></tr></table>")


def test_parse_constituents_normalises_symbols():
    rows = universe.parse_constituents(_wiki_html())
    assert len(rows) == 450
    assert rows[0] == {"symbol": "BRK-B", "name": "Company 0", "sector": "Tech", "cik": 1000}
    assert universe.to_finnhub_symbol("BRK-B") == "BRK.B"


def test_universe_merges_both_indexes(monkeypatch):
    lists = {"S&P 500": [{"symbol": "AAA", "name": "A", "sector": "Tech", "cik": 1, "index": "S&P 500"},
                         {"symbol": "BOTH", "name": "B", "sector": "Tech", "cik": 2, "index": "S&P 500"}],
             "S&P 400": [{"symbol": "MID", "name": "M", "sector": "Energy", "cik": None, "index": "S&P 400"},
                         {"symbol": "BOTH", "name": "B", "sector": "Tech", "cik": None, "index": "S&P 400"}]}
    monkeypatch.setattr(universe, "fetch_index", lambda name, session=None: lists[name])
    got = {r["symbol"]: r["index"] for r in universe.fetch_universe()}
    assert got == {"AAA": "S&P 500", "BOTH": "S&P 500", "MID": "S&P 400"}


def test_parse_constituents_rejects_a_changed_page():
    with pytest.raises(ValueError):
        universe.parse_constituents(_wiki_html(n=30))


def test_finnhub_gets_dotted_symbol():
    seen = {}

    class S:
        def get(self, url, params):
            seen.update(params)

            class R:
                def raise_for_status(self): pass
                def json(self): return []
            return R()
    finnhub.fetch_company_news(S(), "BRK-B", date(2026, 1, 1), date(2026, 1, 5), "tok")
    assert seen["symbol"] == "BRK.B"


def _series(daily_return, n=300, start=100.0, noise=0.0, seed=0):
    rng = np.random.default_rng(seed)
    r = daily_return + noise * rng.standard_normal(n)
    idx = pd.bdate_range("2025-06-02", periods=n)
    return pd.Series(start * np.cumprod(1 + r), index=idx)


def test_momentum_metrics_needs_a_year_and_measures_relative_strength():
    assert screen.momentum_metrics(_series(0.001, n=200), None) is None
    m = screen.momentum_metrics(_series(0.002), _series(0.0005))
    assert m["mom_12_1"] > 0.3 and m["rel_6m"] > 0 and m["rel_3m"] > 0 and m["vol_6m"] >= 0
    # 12-1 skips the most recent month
    s = _series(0.002)
    assert m["mom_12_1"] == pytest.approx(s.iloc[-22] / s.iloc[-253] - 1)


@pytest.mark.parametrize("f,ok,note", [
    ({"period_end": "2026-09-30", "net_margin": 0.2, "fcf_ttm": 5e9}, True, None),
    ({"period_end": "2026-09-30", "net_margin": 0.2, "fcf_ttm": None}, True, "free cash flow not reported"),
    ({"period_end": "2026-09-30", "net_margin": -0.1, "fcf_ttm": 5e9}, False, "not profitable (TTM)"),
    ({"period_end": "2026-09-30", "net_margin": 0.1, "fcf_ttm": -1e9}, False, "negative free cash flow (TTM)"),
    ({"period_end": "2025-01-31", "stale": True, "net_margin": 0.1}, False, "financials out of date"),
    ({"period_end": None}, False, "no SEC financials"),
])
def test_quality_filter(f, ok, note):
    passed, notes = screen.quality_check(f)
    assert passed is ok and (note is None or note in notes)


def test_scoring_ranks_only_quality_names_and_selects_top_n():
    def c(t, mom, rel, vol, q=True):
        return {"ticker": t, "quality_pass": q,
                "metrics": {"mom_12_1": mom, "rel_6m": rel, "rel_3m": rel, "vol_6m": vol}}
    cands = [c("A", 0.6, 0.2, 0.25), c("B", 0.3, 0.1, 0.25), c("C", 0.9, 0.4, 0.3, q=False),
             c("D", -0.1, -0.1, 0.25), c("E", 0.6, 0.2, 0.9)]
    screen.score_candidates(cands, top_n=2)
    by = {x["ticker"]: x for x in cands}
    assert by["C"]["rank"] is None and not by["C"]["selected"]      # strongest, but fails quality
    assert by["A"]["rank"] == 1                                      # same momentum as E, lower vol
    assert by["E"]["rank"] < by["D"]["rank"]
    assert sorted(x["rank"] for x in cands if x["selected"]) == [1, 2]   # top_n=2 -> exactly ranks 1 and 2
    assert by["E"]["score"] < by["A"]["score"]                           # volatility penalty


def test_run_screen_end_to_end_with_point_in_time_data(monkeypatch):
    store = FakeStore()
    as_of = date(2026, 8, 1)
    trends = {"SPY": 0.0005, "UP": 0.003, "MID": 0.001, "DOWN": -0.001, "LOSS": 0.004}
    for t, d in trends.items():
        s = _series(d, n=320, noise=0.005, seed=len(t))
        store.upsert_prices([{"ticker": t, "date": i.date().isoformat(), "close": float(v), "adj_close": float(v)}
                             for i, v in s.items()])
    # A future price must never be used.
    store.upsert_prices([{"ticker": "DOWN", "date": "2026-08-05", "close": 1e6, "adj_close": 1e6}])
    quality = {"UP": 0.2, "MID": 0.1, "DOWN": 0.1, "LOSS": -0.05}
    calls = []

    def fake_fund(facts, as_of_, last_close):
        t = calls.pop(0)
        return {"period_end": "2026-06-30", "stale": False, "net_margin": quality[t], "fcf_ttm": 1e9}

    orig_get = store.get_fundamentals
    monkeypatch.setattr(store, "get_fundamentals", lambda t, before: calls.append(t) or orig_get(t, before))
    monkeypatch.setattr(screen.fund, "fundamental_features", fake_fund)

    rows = screen.run_screen(store, ["UP", "MID", "DOWN", "LOSS"], as_of, "SPY", top_n=2,
                             info={"UP": {"sector": "Tech", "index": "S&P 400"}})
    by = {r["ticker"]: r for r in rows}
    assert by["UP"]["rank"] == 1 and by["UP"]["selected"]
    assert by["UP"]["metrics"]["sector"] == "Tech" and by["UP"]["metrics"]["index"] == "S&P 400"
    m = by["UP"]["metrics"]
    assert m["low_52w"] <= m["sma_200"] <= m["high_52w"] and m["low_52w"] <= m["last_close"] <= m["high_52w"]
    assert by["LOSS"]["quality_pass"] is False and by["LOSS"]["rank"] is None
    assert "not profitable (TTM)" in by["LOSS"]["metrics"]["notes"]
    assert by["DOWN"]["metrics"]["mom_12_1"] < 0                    # the 1e6 future print was ignored
    assert sum(r["selected"] for r in rows) == 2 and all(r["as_of"] == "2026-08-01" for r in rows)


def test_focus_tickers_prefers_latest_selected_then_falls_back():
    store = FakeStore()
    assert universe.focus_tickers(store, ["AAPL"]) == ["AAPL"]
    assert universe.focus_tickers(None, ["AAPL"]) == ["AAPL"]
    store.upsert_screens([
        {"as_of": "2026-11-07", "ticker": "OLD", "rank": 1, "selected": True},
        {"as_of": "2026-11-14", "ticker": "B", "rank": 2, "selected": True},
        {"as_of": "2026-11-14", "ticker": "A", "rank": 1, "selected": True},
        {"as_of": "2026-11-14", "ticker": "Z", "rank": 30, "selected": False},
    ])
    assert universe.focus_tickers(store, ["AAPL"]) == ["A", "B"]


def test_split_batch_download():
    idx = pd.to_datetime(["2026-11-10", "2026-11-11"])
    cols = pd.MultiIndex.from_product([["AAA", "BBB"], ["Open", "High", "Low", "Close", "Adj Close", "Volume"]])
    df = pd.DataFrame([[1, 2, 0.5, 1.5, 1.4, 100, np.nan, np.nan, np.nan, np.nan, np.nan, np.nan],
                       [1, 2, 0.5, 1.6, 1.5, 120, np.nan, np.nan, np.nan, np.nan, np.nan, np.nan]],
                      index=idx, columns=cols)
    out = prices.split_download(df, ["AAA", "BBB"])
    assert list(out) == ["AAA"] and out["AAA"][1] == {"ticker": "AAA", "date": "2026-11-11", "open": 1.0, "high": 2.0,
                                                       "low": 0.5, "close": 1.6, "adj_close": 1.5, "volume": 120}


def test_financials_are_judged_on_profitability_only():
    f = {"period_end": "2026-09-30", "net_margin": 0.3, "fcf_ttm": -5e9}
    assert screen.quality_check(f)[0] is False
    ok, notes = screen.quality_check(f, "Financials")
    assert ok and "financials: free cash flow not used" in notes
    assert screen.quality_check({**f, "net_margin": -0.1}, "Financials")[0] is False


def test_sixteen_week_fiscal_quarter_still_builds_ttm():
    from quant import fundamentals as q
    # Costco-style year: 12, 12, 12 and 16-week quarters reported as YTD chains.
    s = date(2024, 9, 2)
    ends = [s + timedelta(weeks=w) - timedelta(days=1) for w in (12, 24, 36, 52)]
    periods = {(s, e): float(v) for e, v in zip(ends, (60, 120, 180, 270))}
    quarters = q.quarterly(periods)
    assert len(quarters) == 4 and quarters[ends[-1]] == 90.0
    assert q.ttm(quarters) == (270.0, ends[-1])
