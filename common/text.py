"""Text normalisation shared by ingestion and processing."""
from __future__ import annotations

import re
import unicodedata

from bs4 import BeautifulSoup

_WS = re.compile(r"[ \t\u00a0]+")
_BLANKS = re.compile(r"\n\s*\n+")


def normalize(text: str) -> str:
    """Unicode-normalise, collapse whitespace, keep paragraph breaks."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _WS.sub(" ", text)
    lines = [line.strip() for line in text.split("\n")]
    text = "\n".join(lines)
    text = _BLANKS.sub("\n\n", text)
    return text.strip()


def html_to_text(html: str) -> str:
    """Strip HTML (incl. inline-XBRL filings) to readable text."""
    if not html:
        return ""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "head", "noscript"]):
        tag.decompose()
    # Hidden iXBRL header blocks in SEC filings.
    for tag in soup.find_all(["ix:header"]):
        tag.decompose()
    for tag in soup.find_all(style=re.compile(r"display\s*:\s*none", re.I)):
        tag.decompose()
    text = soup.get_text(separator="\n")
    return normalize(text)


_STATE_SUFFIX = re.compile(r"\s*/[A-Z]{2,3}/?\s*$")
_KEEP_UPPER = {"AI", "AT&T", "CVS", "IBM", "NVR", "US", "USA", "II", "III", "LLC", "PLC", "NV", "SA", "AG", "SE"}


def company_name(name: str | None) -> str | None:
    """'ABERCROMBIE & FITCH CO /DE/' -> 'Abercrombie & Fitch Co'. Names already in mixed case only lose
    a trailing state suffix; all-caps names are title-cased, keeping acronyms (no vowels, or known)."""
    if not name:
        return None
    name = _STATE_SUFFIX.sub("", name.strip())
    if any(ch.islower() for ch in name):
        return name

    def word(w: str) -> str:
        core = w.strip(".,()")
        if core in _KEEP_UPPER or (core.isalpha() and not set(core) & set("AEIOUY")):
            return w
        return "-".join(p[:1] + p[1:].lower() for p in w.split("-"))

    return " ".join(word(w) for w in name.split())
