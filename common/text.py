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
