"""Live progress view: no-op without a workflow, plain lines without a terminal, live block renders."""
import io

import pytest

from common import progress


def test_without_a_workflow_everything_is_a_no_op():
    assert not progress.active()
    with progress.step("Prices", total=3) as st:
        st.advance(note="AAPL")
        progress.problem()
        progress.add_rows(10)
    assert list(progress.each("News", [1, 2])) == [1, 2]
    progress.skip("Filings")


def test_plain_mode_prints_one_line_per_step(capsys, monkeypatch):
    monkeypatch.setenv("TI_PLAIN_PROGRESS", "1")
    with progress.workflow("Daily refresh", ["Prices", "News", "Macro"]):
        for _ in progress.each("Prices", ["AAPL", "MSFT"]):
            progress.add_rows(5)
        for t in progress.each("News", ["AAPL", "MSFT"]):
            if t == "MSFT":
                progress.problem()
    out = capsys.readouterr().out
    assert "== TI Agent · Daily refresh" in out
    assert "▶ Prices" in out and "✓ Prices (2/2, 10 rows)" in out
    assert "! News (2/2, 1 failed)" in out
    assert "! finished with warnings" in out
    assert not progress.active()


def test_a_crash_marks_the_step_and_the_run_failed(capsys, monkeypatch):
    monkeypatch.setenv("TI_PLAIN_PROGRESS", "1")
    with pytest.raises(RuntimeError):
        with progress.workflow("Weekly screen", ["Prices", "Retention"]):
            with progress.step("Prices"):
                raise RuntimeError("out of memory")
    out = capsys.readouterr().out
    assert "✗ Prices (RuntimeError: out of memory)" in out
    assert "✗ failed" in out
    assert not progress.active()


def test_nested_workflows_join_the_outer_one(capsys, monkeypatch):
    monkeypatch.setenv("TI_PLAIN_PROGRESS", "1")
    with progress.workflow("Daily refresh", ["Prices"]) as outer:
        with progress.workflow("Ingest", ["Prices", "News"]) as inner:
            assert inner is outer
            with progress.step("Prices"):
                pass
    out = capsys.readouterr().out
    assert out.count("== TI Agent") == 1
    assert "– News" in out  # planned but never run -> skipped


def test_live_block_renders():
    from rich.console import Console

    wf = progress.Workflow("Weekly AI run · 2 picks", ["Load AI model", "ANF", "SN"])
    wf.begin(wf.steps[0])
    wf.steps[0].set_result("trading-analyst")
    wf.end(wf.steps[0], progress.OK)
    wf.begin(wf.steps[1])
    wf.steps[1].set_total(10)
    wf.steps[1].advance(4, note="step 4 · search_knowledge")
    buf = io.StringIO()
    Console(file=buf, width=100, force_terminal=False, color_system=None).print(wf)
    text = buf.getvalue()
    assert "TI Agent · Weekly AI run · 2 picks" in text
    assert "✓ Load AI model" in text and "trading-analyst" in text
    assert "4/10" in text and "step 4 · search_knowledge" in text
    assert "○ SN" in text
