from datetime import date

import pandas as pd

from ingestion import edgar, finnhub, fred, prices


def test_finnhub_to_documents_dedupes_and_skips_empty():
    items = [
        {"id": 1, "headline": "Apple beats", "summary": "Q4  strong", "datetime": 1731283200,
         "url": "https://x/1", "source": "Reuters", "category": "company", "related": "AAPL"},
        {"id": 1, "headline": "Apple beats", "summary": "dup", "datetime": 1731283200},
        {"id": 2, "headline": "", "summary": "no headline", "datetime": 1731283200},
        {"id": 3, "headline": "No time", "summary": ""},
    ]
    docs = finnhub.to_documents("AAPL", items)
    assert len(docs) == 1
    d = docs[0]
    assert d["source_id"] == "finnhub:1" and d["source"] == "news" and d["ticker"] == "AAPL"
    assert d["published_at"].startswith("2024-11-11T00:00:00")
    assert d["doc_type"] == "Reuters"


def _submissions():
    return {
        "filings": {
            "recent": {
                "accessionNumber": ["0000320193-24-000123", "0000320193-24-000100", "0000320193-23-000001"],
                "filingDate": ["2024-11-01", "2024-10-15", "2023-01-01"],
                "form": ["10-K", "4", "10-Q"],
                "primaryDocument": ["aapl-20240928.htm", "x.xml", "q.htm"],
                "reportDate": ["2024-09-28", "", "2022-12-31"],
                "acceptanceDateTime": ["2024-11-01T18:04:43.000Z", "", ""],
            }
        }
    }


def test_edgar_parse_filters_form_and_date():
    rows = edgar.parse_recent_filings(_submissions(), since=date(2024, 1, 1))
    assert [r["form"] for r in rows] == ["10-K"]
    assert edgar._published_at(rows[0]).startswith("2024-11-01T18:04:43")


def test_edgar_published_at_falls_back_to_end_of_day():
    assert edgar._published_at({"filing_date": "2024-11-01", "accepted": None}) == "2024-11-01T23:59:00+00:00"


class _Resp:
    def __init__(self, payload=None, text=""):
        self._payload, self.text = payload, text

    def json(self):
        return self._payload

    def raise_for_status(self):
        pass


class _Session:
    def __init__(self):
        self.urls = []

    def get(self, url, **kw):
        self.urls.append(url)
        if "submissions" in url:
            return _Resp(_submissions())
        return _Resp(text="<html><body><p>Item 1A. Risk Factors.</p>" + "<p>Long text.</p>" * 50 + "</body></html>")


def test_edgar_fetch_filings_builds_docs_and_truncates(monkeypatch):
    monkeypatch.setattr(edgar, "MIN_INTERVAL_S", 0)
    s = _Session()
    docs = edgar.fetch_filings(s, "AAPL", 320193, date(2024, 1, 1), max_chars=100)
    assert len(docs) == 1
    d = docs[0]
    assert d["source_id"] == "edgar:0000320193-24-000123"
    assert d["url"].endswith("/320193/000032019324000123/aapl-20240928.htm")
    assert len(d["body"]) == 100 and d["meta"]["truncated"] is True
    assert "Risk Factors" in d["body"]


def test_edgar_fetch_filings_skips_known(monkeypatch):
    monkeypatch.setattr(edgar, "MIN_INTERVAL_S", 0)
    s = _Session()
    docs = edgar.fetch_filings(s, "AAPL", 320193, date(2024, 1, 1), 100, skip_ids={"edgar:0000320193-24-000123"})
    assert docs == [] and len(s.urls) == 1  # only the submissions call


def test_fred_parse_skips_missing():
    rows = fred.parse_observations("DGS10", {"observations": [
        {"date": "2024-11-08", "value": "4.31"}, {"date": "2024-11-11", "value": "."}]})
    assert rows == [{"series_id": "DGS10", "date": "2024-11-08", "value": 4.31}]


def test_prices_frame_to_rows():
    idx = pd.DatetimeIndex(["2024-11-07", "2024-11-08"], tz="America/New_York")
    df = pd.DataFrame(
        {"Open": [1.0, 2.0], "High": [1.5, 2.5], "Low": [0.5, 1.5], "Close": [1.2, float("nan")],
         "Adj Close": [1.1, 2.1], "Volume": [100, 200]},
        index=idx,
    )
    rows = prices.frame_to_rows("AAPL", df)
    assert rows == [{"ticker": "AAPL", "date": "2024-11-07", "open": 1.0, "high": 1.5, "low": 0.5,
                     "close": 1.2, "adj_close": 1.1, "volume": 100}]
