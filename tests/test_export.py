"""Encrypted app data export (site-data/data.json) for the Flutter app on GitHub Pages."""
import json

import pytest
from cryptography.exceptions import InvalidTag

from orchestration import export_app

PW = "correct horse battery staple"


class AppStore:
    def __init__(self):
        self.close = 10.0

    def app_run(self, before_id=None):
        return {"id": 2, "as_of": "2026-11-14", "status": "ok", "model": "m"} if before_id is None else \
            ({"id": 1, "as_of": "2026-11-07", "status": "ok", "model": "m"} if before_id == 2 else None)

    def suggestions_for_run(self, run_id):
        stance = "bullish" if run_id == 2 else "neutral"
        return [{"id": run_id, "run_id": run_id, "ticker": "ANF", "horizon": "long", "stance": stance,
                 "thesis": "t", "sources": ["chunk_7", "bad"], "confidence": 0.6, "as_of": "2026-11-14"}]

    def ticker_suggestions(self, ticker, limit=30):
        return self.suggestions_for_run(2) + self.suggestions_for_run(1)

    def app_latest_screen(self):
        return {"as_of": "2026-11-15", "rows": [
            {"ticker": "ANF", "rank": 1, "selected": True, "metrics": {"sector": "Consumer Discretionary"}},
            {"ticker": "XOM", "rank": 400, "selected": False, "metrics": {}}]}

    def app_prices(self, tickers, since):
        return [{"ticker": t, "date": "2026-11-13", "close": self.close, "adj_close": self.close} for t in tickers]

    def app_citations(self, ids):
        assert len(ids) <= 20
        return [{"id": i, "ticker": "ANF", "source": "filing", "doc_type": "10-Q", "published_at": "2026-09-04",
                 "content": "Tariffs...", "title": "ANF 10-Q", "url": "https://www.sec.gov/x"} for i in ids]


def read(path, pw=PW):
    doc = json.loads(path.read_text())
    return doc, json.loads(export_app.decrypt(doc, pw))


def test_bundle_has_what_the_app_reads():
    b = export_app.build_bundle(AppStore())
    assert [r["id"] for r in b["runs"]] == [2, 1]
    assert set(b["suggestions"]) == {"2", "1"}
    assert [p["ticker"] for p in b["screen"]["picks"]] == ["ANF"] and b["screen"]["screened"] == 2
    assert set(b["prices"]) == {"ANF", "SPY"} and b["prices"]["ANF"][0] == ["2026-11-13", 10.0, 10.0]
    assert list(b["citations"]) == ["7"]


def test_round_trip_and_wrong_password(tmp_path):
    out = tmp_path / "data.json"
    assert export_app.export(AppStore(), PW, out, iterations=1000) == "written"
    doc, plain = read(out)
    assert doc["kdf"] == "pbkdf2-sha256" and doc["iter"] == 1000
    assert plain["data"]["screen"]["picks"][0]["ticker"] == "ANF"
    assert "ANF" not in out.read_text()  # nothing readable without the password
    with pytest.raises(InvalidTag):
        export_app.decrypt(doc, "wrong password!!")


def test_unchanged_data_is_not_rewritten_and_salt_is_kept(tmp_path):
    out, store = tmp_path / "data.json", AppStore()
    export_app.export(store, PW, out, iterations=1000)
    first = json.loads(out.read_text())
    assert export_app.export(store, PW, out, iterations=1000) == "unchanged"
    assert json.loads(out.read_text()) == first
    store.close = 11.0
    assert export_app.export(store, PW, out, iterations=1000) == "written"
    second = json.loads(out.read_text())
    assert second["salt"] == first["salt"]  # devices that remember the key keep working
    assert second["iv"] != first["iv"]      # but every encryption gets a fresh IV


def test_new_password_re_encrypts_with_a_new_salt(tmp_path):
    out = tmp_path / "data.json"
    export_app.export(AppStore(), PW, out, iterations=1000)
    old = json.loads(out.read_text())
    assert export_app.export(AppStore(), "another long password", out, iterations=1000) == "new password"
    new, plain = read(out, "another long password")
    assert new["salt"] != old["salt"] and plain["data"]["runs"]


def test_short_password_refused(tmp_path):
    with pytest.raises(ValueError):
        export_app.export(AppStore(), "short", tmp_path / "data.json", iterations=1000)
