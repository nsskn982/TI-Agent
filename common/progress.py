"""Live, step-by-step progress for the run scripts (run_daily / run_screen / run_weekly).

    with progress.workflow("Daily refresh", ["Prices", "News", "Chunk + embed"]):
        with progress.step("Prices", total=len(tickers)) as st:
            for t in tickers:
                ...
                st.advance(note=t)

In a terminal it draws one block that updates in place, like a CI run:

    TI Agent · Daily refresh                                   2m 14s
      ✓ Prices          21/21  ━━━━━━━━━━━━━━━━━━━━  126 rows      4s
      ⠹ News             7/20  ━━━━━━━╸            CNC           12s
      ○ Filings

Detailed log lines go to the log file only (TI_LOG_FILE); warnings and errors still print,
above the block. Without a terminal (a scheduled task, a pipe, tests) it prints one plain
line per step instead. With no workflow open every call is a no-op, so library code can
report progress unconditionally.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
import time
from contextlib import contextmanager
from typing import Iterator

_current: "Workflow | None" = None
_lock = threading.RLock()

QUEUED, RUNNING, OK, WARN, FAILED, SKIPPED = "queued", "running", "ok", "warn", "failed", "skipped"
_ASCII = str.maketrans({"▶": ">", "✓": "+", "✗": "x", "–": "-", "·": "|", "…": "..."})


def _dur(sec: float | None) -> str:
    if sec is None:
        return ""
    sec = int(round(sec))
    if sec < 60:
        return f"{sec}s"
    m, s = divmod(sec, 60)
    if m < 60:
        return f"{m}m {s:02d}s"
    h, m = divmod(m, 60)
    return f"{h}h {m:02d}m"


class Step:
    def __init__(self, name: str):
        self.name = name
        self.state = QUEUED
        self.total: int | None = None
        self.done = 0
        self.note = ""
        self.result = ""          # shown after the step ends, e.g. "126 rows"
        self.problems = 0
        self.started: float | None = None
        self.ended: float | None = None

    # ---- called by pipeline code
    def advance(self, n: int = 1, note: str | None = None) -> None:
        with _lock:
            self.done += n
            if note is not None:
                self.note = note

    def set_total(self, total: int | None) -> None:
        with _lock:
            self.total = total

    def set_note(self, note: str) -> None:
        with _lock:
            self.note = note

    def set_result(self, text: str) -> None:
        with _lock:
            self.result = text

    def problem(self, n: int = 1) -> None:
        with _lock:
            self.problems += n

    @property
    def elapsed(self) -> float | None:
        if self.started is None:
            return None
        return (self.ended or time.monotonic()) - self.started


class _NullStep(Step):
    def __init__(self):
        super().__init__("")

    def advance(self, n: int = 1, note: str | None = None) -> None:
        pass


class Workflow:
    def __init__(self, title: str, steps: list[str] | None = None):
        self.title = title
        self.steps: list[Step] = [Step(s) for s in steps or []]
        self.started = time.monotonic()
        self.ended: float | None = None
        self.state = RUNNING
        self.active: Step | None = None
        self.live = None
        self.plain = not _interactive()

    def _get(self, name: str) -> Step:
        for s in self.steps:
            if s.name == name and s.state == QUEUED:
                return s
        s = Step(name)
        self.steps.append(s)
        return s

    def plan(self, names: list[str]) -> None:
        """Add steps that will run later (shown as queued)."""
        with _lock:
            known = {s.name for s in self.steps}
            self.steps.extend(Step(n) for n in names if n not in known)

    # ---- rendering
    def _print_plain(self, text: str) -> None:
        try:
            print(text, flush=True)
        except UnicodeEncodeError:  # a pipe or file on Windows (cp1252) can't show the symbols
            print(text.translate(_ASCII).encode("ascii", "replace").decode("ascii"), flush=True)

    def __rich__(self):
        from rich.console import Group
        from rich.progress_bar import ProgressBar
        from rich.spinner import Spinner
        from rich.table import Table
        from rich.text import Text

        with _lock:
            head = Table.grid(expand=True)
            head.add_column(ratio=1)
            head.add_column(justify="right")
            color = {RUNNING: "yellow", OK: "green", WARN: "yellow", FAILED: "red"}.get(self.state, "white")
            head.add_row(Text.assemble(("TI Agent", "bold"), " · ", (self.title, f"bold {color}")),
                         Text(_dur((self.ended or time.monotonic()) - self.started), style="dim"))

            grid = Table.grid(padding=(0, 1), expand=True)
            width = max(len(s.name) for s in self.steps) if self.steps else 10
            grid.add_column(width=1, no_wrap=True)                                        # icon
            grid.add_column(min_width=min(width, 34), max_width=34, no_wrap=True, overflow="ellipsis")  # name
            grid.add_column(justify="right", no_wrap=True)                                # n/total
            grid.add_column(width=20, no_wrap=True)                                       # bar
            grid.add_column(ratio=1, no_wrap=True, overflow="ellipsis")                   # note / result
            grid.add_column(justify="right", width=7, no_wrap=True)                       # time
            for s in self.steps:
                if s.state == RUNNING:
                    icon = Spinner("dots", style="yellow")
                else:
                    icon = Text(*{QUEUED: ("○", "dim"), OK: ("✓", "green"), WARN: ("!", "bold yellow"),
                                  FAILED: ("✗", "bold red"), SKIPPED: ("–", "dim")}[s.state])
                name = Text(s.name, style="dim" if s.state in (QUEUED, SKIPPED) else "")
                count = Text(f"{s.done:,}/{s.total:,}" if s.total else (f"{s.done:,}" if s.done else ""), style="dim")
                bar = (ProgressBar(total=s.total, completed=min(s.done, s.total), width=20,
                                   complete_style="green" if s.state == OK else "yellow", finished_style="green")
                       if s.total and s.state != QUEUED else Text(""))
                info = s.result if s.state not in (RUNNING, QUEUED) else s.note
                if s.problems:
                    info = f"{info}  ({s.problems} failed)" if info else f"{s.problems} failed"
                grid.add_row(icon, name, count, bar,
                             Text(info, style="red" if s.state == FAILED else ("yellow" if s.problems else "dim")),
                             Text(_dur(s.elapsed) if s.state != QUEUED else "", style="dim"))
            return Group(head, grid)

    # ---- lifecycle
    def start(self) -> None:
        if self.plain:
            self._print_plain(f"== TI Agent · {self.title}")
            return
        from rich.console import Console
        from rich.live import Live

        self.live = Live(self, console=Console(stderr=False), refresh_per_second=8, transient=False,
                         redirect_stdout=True, redirect_stderr=True)
        self.live.start()

    def begin(self, step: Step) -> None:
        with _lock:
            step.state, step.started = RUNNING, time.monotonic()
            self.active = step
        if self.plain:
            self._print_plain(f"▶ {step.name}")

    def end(self, step: Step, state: str) -> None:
        with _lock:
            step.state, step.ended = state, time.monotonic()
            if self.active is step:
                self.active = None
        if self.plain:
            icon = {OK: "✓", WARN: "!", FAILED: "✗", SKIPPED: "–"}[state]
            bits = [b for b in (f"{step.done:,}/{step.total:,}" if step.total else "", step.result,
                                f"{step.problems} failed" if step.problems else "") if b]
            self._print_plain(f"{icon} {step.name}" + (f" ({', '.join(bits)})" if bits else "") + f"  {_dur(step.elapsed)}")

    def finish(self, state: str | None = None) -> None:
        with _lock:
            skipped = [s for s in self.steps if s.state == QUEUED]
            for s in skipped:
                s.state = SKIPPED
            if state is None:
                state = FAILED if any(s.state == FAILED for s in self.steps) else (
                    WARN if any(s.state == WARN for s in self.steps) else OK)
            self.state, self.ended = state, time.monotonic()
        if self.live is not None:
            self.live.refresh()
            self.live.stop()
        elif self.plain:
            for s in skipped:
                self._print_plain(f"– {s.name}  skipped")
        verdict = {OK: "✓ finished", WARN: "! finished with warnings", FAILED: "✗ failed"}.get(state, state)
        self._print_plain(f"{verdict} in {_dur(self.ended - self.started)}")


def _interactive() -> bool:
    if os.environ.get("TI_PLAIN_PROGRESS"):
        return False
    try:
        return sys.stdout.isatty()
    except Exception:
        return False


def _quiet_console_logs() -> list[tuple[logging.Handler, int]]:
    """While the live view runs, only warnings and errors reach the console; the file keeps everything."""
    changed = []
    for h in logging.getLogger().handlers:
        if type(h) is logging.StreamHandler:
            changed.append((h, h.level))
            h.setLevel(logging.WARNING)
    return changed


@contextmanager
def workflow(title: str, steps: list[str] | None = None) -> Iterator[Workflow]:
    """Open the live view. Nested calls (a run script calling another) join the outer one."""
    global _current
    with _lock:
        outer = _current
    if outer is not None:
        outer.plan(steps or [])
        yield outer
        return
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")   # model downloads would draw over the view
    os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
    wf = Workflow(title, steps)
    restore = [] if wf.plain else _quiet_console_logs()
    with _lock:
        _current = wf
    wf.start()
    # The live view swaps sys.stderr for a proxy that prints above the block; point the console
    # log handlers at it (they captured the original stream when logging was set up).
    streams = [(h, h.setStream(sys.stderr)) for h, _ in restore]
    failed = False
    try:
        yield wf
    except BaseException:
        failed = True
        raise
    finally:
        wf.finish(FAILED if failed else None)
        with _lock:
            _current = None
        for h, old_stream in streams:
            h.setStream(old_stream)
        for h, level in restore:
            h.setLevel(level)


@contextmanager
def step(name: str, total: int | None = None) -> Iterator[Step]:
    """One step of the open workflow. An exception marks it failed (and is re-raised);
    `st.problem()` marks it done-with-warnings."""
    wf = _current
    if wf is None:
        yield _NullStep()
        return
    s = wf._get(name)
    s.total = total
    wf.begin(s)
    try:
        yield s
    except BaseException as exc:
        s.result = s.result or f"{type(exc).__name__}: {exc}"[:120]
        wf.end(s, FAILED)
        raise
    else:
        wf.end(s, WARN if s.problems else OK)


def each(name: str, items, note=str):
    """Loop over items as one step: `for t in progress.each("Prices", tickers): ...`.
    Shows n/total and the current item; `progress.problem()` inside counts a failure."""
    items = list(items)
    wf = _current
    if wf is None:
        yield from items
        return
    s = wf._get(name)
    s.total = len(items)
    wf.begin(s)
    try:
        for it in items:
            s.set_note(note(it))
            yield it
            s.advance()
    except GeneratorExit:  # the loop was left early (break or an exception): keep the counts so far
        pass
    finally:
        wf.end(s, WARN if s.problems else OK)


def add_rows(n: int, unit: str = "rows") -> None:
    """Count rows written by the running step (shown as its result)."""
    st = current_step()
    with _lock:
        st.rows = getattr(st, "rows", 0) + n
        st.result = f"{st.rows:,} {unit}"


def skip(name: str, why: str = "") -> None:
    wf = _current
    if wf is None:
        return
    s = wf._get(name)
    s.result = why
    s.started = s.ended = time.monotonic()
    wf.end(s, SKIPPED)


def current_step() -> Step:
    wf = _current
    return (wf.active if wf and wf.active else None) or _NullStep()


def problem(n: int = 1) -> None:
    """Count a failed item (one ticker, one document) against the running step."""
    current_step().problem(n)


def active() -> bool:
    return _current is not None
