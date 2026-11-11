import pytest

from common.text import html_to_text, normalize
from processing.chunk import chunk_text, split_sentences


def test_normalize_collapses_whitespace_keeps_paragraphs():
    assert normalize("  a  b \r\n\r\n\n  c  ") == "a b\n\nc"


def test_html_to_text_drops_scripts_and_hidden_xbrl():
    html = """<html><head><title>x</title><style>p{}</style></head><body>
    <div style="display:none"><ix:header>hidden facts</ix:header></div>
    <p>Revenue grew&nbsp;8%.</p><script>alert(1)</script><p>Margins fell.</p></body></html>"""
    text = html_to_text(html)
    assert "Revenue grew 8%." in text
    assert "Margins fell." in text
    assert "hidden" not in text and "alert" not in text and "p{}" not in text


def test_split_sentences():
    assert split_sentences("One. Two! Three? four") == ["One.", "Two!", "Three? four"]


def test_chunks_respect_max_words_and_overlap():
    sentences = [f"Sentence number {i} has exactly seven words." for i in range(100)]
    chunks = chunk_text(" ".join(sentences), max_words=50, overlap_words=14)
    assert len(chunks) > 1
    assert all(len(c.split()) <= 50 for c in chunks)
    # Overlap: each chunk starts with the last two sentences of the previous one.
    for prev, nxt in zip(chunks, chunks[1:]):
        assert nxt.startswith(" ".join(prev.split()[-14:]))
    # Nothing lost.
    joined = " ".join(chunks)
    assert all(s in joined for s in sentences)


def test_long_sentence_is_hard_split():
    text = " ".join(["word"] * 500)
    chunks = chunk_text(text, max_words=180, overlap_words=0)
    assert all(len(c.split()) <= 180 for c in chunks)
    assert sum(len(c.split()) for c in chunks) == 500


def test_short_text_single_chunk_and_empty():
    assert chunk_text("Tiny.") == ["Tiny."]
    assert chunk_text("") == []


def test_bad_overlap():
    with pytest.raises(ValueError):
        chunk_text("x", max_words=10, overlap_words=10)
