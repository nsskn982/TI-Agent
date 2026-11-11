"""Turn `flutter test --reporter json` output into GitHub error annotations.

Each failing test becomes one `::error` line holding its error, stack trace head and any
framework messages it printed (e.g. "A RenderFlex overflowed by 120 pixels"). Annotations
show on the run's summary page, so failures can be read without opening the raw log.

    python3 tool/annotate_tests.py test-results.jsonl
"""
import json
import sys


def _escape(s: str) -> str:
    # GitHub workflow-command escaping for the message part.
    return s.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def main(path: str) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Flutter messages use box-drawing chars
    names: dict[int, str] = {}
    details: dict[int, list[str]] = {}
    failed: list[int] = []
    for line in open(path, encoding="utf-8", errors="replace"):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        kind = ev.get("type")
        if kind == "testStart":
            names[ev["test"]["id"]] = ev["test"].get("name", "?")
        elif kind == "error":
            stack = "\n".join(ev.get("stackTrace", "").splitlines()[:6])
            details.setdefault(ev["testID"], []).append(ev.get("error", "") + "\n" + stack)
        elif kind == "print":
            details.setdefault(ev["testID"], []).append(ev.get("message", ""))
        elif kind == "testDone" and ev.get("result") != "success" and not ev.get("hidden"):
            failed.append(ev["testID"])

    for tid in failed:
        text = "\n".join(details.get(tid, ["(no details)"]))[:6000]
        print(f"::error title=Test failed: {_escape(names.get(tid, '?'))[:200]}::{_escape(text)}")
    print(f"{len(failed)} failing test(s) annotated")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
