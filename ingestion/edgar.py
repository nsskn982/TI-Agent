"""SEC EDGAR filings (10-K, 10-Q, 8-K). EDGAR asks for <=10 req/s and a contact User-Agent."""
from __future__ import annotations

import logging
import time
from datetime import date, datetime, timezone

import requests

from common.text import html_to_text

log = logging.getLogger(__name__)

TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{doc}"

DEFAULT_FORMS = ("10-K", "10-Q", "8-K")
MIN_INTERVAL_S = 0.15
# A filing's main document can be hundreds of MB of inline-XBRL markup. Only the first
# MAX_FILING_CHARS of *text* are kept, so read at most this many bytes of HTML.
MAX_DOCUMENT_BYTES = 25_000_000


def _get(session: requests.Session, url: str) -> requests.Response:
    time.sleep(MIN_INTERVAL_S)
    resp = session.get(url)
    resp.raise_for_status()
    return resp


def _get_text_capped(session: requests.Session, url: str, max_bytes: int = MAX_DOCUMENT_BYTES) -> tuple[str, bool]:
    """Download at most `max_bytes` (streamed, so a huge document never sits in memory).
    Returns (text, cut_short)."""
    time.sleep(MIN_INTERVAL_S)
    with session.get(url, stream=True) as resp:
        resp.raise_for_status()
        buf, size, cut = [], 0, False
        for chunk in resp.iter_content(1 << 16):
            buf.append(chunk)
            size += len(chunk)
            if size >= max_bytes:
                cut = True
                break
        raw = b"".join(buf)[:max_bytes]
        return raw.decode(resp.encoding or "utf-8", errors="replace"), cut


def load_cik_map(session: requests.Session) -> dict[str, dict]:
    """{'AAPL': {'cik': 320193, 'name': 'Apple Inc.'}, ...}"""
    data = _get(session, TICKER_MAP_URL).json()
    out = {}
    for row in data.values():
        out[row["ticker"].upper()] = {"cik": int(row["cik_str"]), "name": row["title"]}
    return out


def parse_recent_filings(submissions: dict, since: date, forms: tuple[str, ...] = DEFAULT_FORMS) -> list[dict]:
    recent = submissions.get("filings", {}).get("recent", {})
    cols = ("accessionNumber", "filingDate", "form", "primaryDocument", "reportDate", "acceptanceDateTime")
    rows = zip(*(recent.get(c, []) for c in cols))
    out = []
    for acc, filed, form, doc, report, accepted in rows:
        if form not in forms or not doc:
            continue
        if date.fromisoformat(filed) < since:
            continue
        out.append(
            {
                "accession": acc,
                "filing_date": filed,
                "form": form,
                "primary_document": doc,
                "report_date": report or None,
                "accepted": accepted or None,
            }
        )
    return out


def _published_at(filing: dict) -> str:
    # acceptanceDateTime is the moment the filing became public; prefer it for no-lookahead.
    accepted = filing.get("accepted")
    if accepted:
        try:
            return datetime.fromisoformat(accepted.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
        except ValueError:
            pass
    # Fall back to end of filing day so same-day as-of queries don't see it early.
    d = date.fromisoformat(filing["filing_date"])
    return datetime(d.year, d.month, d.day, 23, 59, tzinfo=timezone.utc).isoformat()


def fetch_filings(
    session: requests.Session,
    symbol: str,
    cik: int,
    since: date,
    max_chars: int,
    forms: tuple[str, ...] = DEFAULT_FORMS,
    skip_ids: set[str] | None = None,
) -> list[dict]:
    submissions = _get(session, SUBMISSIONS_URL.format(cik=cik)).json()
    docs = []
    for f in parse_recent_filings(submissions, since, forms):
        source_id = f"edgar:{f['accession']}"
        if skip_ids and source_id in skip_ids:
            continue
        url = ARCHIVE_URL.format(cik=cik, acc=f["accession"].replace("-", ""), doc=f["primary_document"])
        html, cut = _get_text_capped(session, url)
        if cut:
            log.info("%s %s: document over %d MB, reading the first part only", symbol, f["accession"],
                     MAX_DOCUMENT_BYTES // 1_000_000)
        text = html_to_text(html)
        truncated = cut or len(text) > max_chars
        docs.append(
            {
                "ticker": symbol,
                "source": "filing",
                "source_id": source_id,
                "doc_type": f["form"],
                "title": f"{symbol} {f['form']} filed {f['filing_date']}",
                "url": url,
                "published_at": _published_at(f),
                "body": text[:max_chars],
                "meta": {
                    "cik": cik,
                    "report_date": f["report_date"],
                    "chars": len(text),
                    "truncated": truncated,
                },
            }
        )
    return docs
