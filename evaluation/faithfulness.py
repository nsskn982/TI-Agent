"""Citation faithfulness: do the cited passages support what the view says?

    python -m evaluation.faithfulness sample --n 60     # write a CSV for two annotators
    python -m evaluation.faithfulness score FILE.csv     # support rates and Cohen's kappa

Each item pairs one view (its thesis, bull case, bear case and valuation) with one passage it cites.
Two people label every item independently, without seeing each other's labels:

    supported     the passage backs at least one specific claim in the view
    partial       related, but the claim goes beyond what the passage says
    unsupported   the passage does not back anything the view claims

The sample is stratified by horizon and by source (filing or news) and seeded, so it can be
recreated. `score` writes reports/faithfulness.json, which the evaluation report includes.
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

from common.config import ROOT
from evaluation.metrics import cohen_kappa

OUT_DIR = ROOT / "evaluation" / "annotations"
REPORT = ROOT / "reports" / "faithfulness.json"
LABELS = ("supported", "partial", "unsupported")
COLUMNS = ["item", "suggestion_id", "ticker", "horizon", "as_of", "source", "doc_type", "chunk_id",
           "view_text", "passage", "annotator_a", "annotator_b", "notes"]


def view_text(r: dict) -> str:
    parts = [("Thesis", r.get("thesis")), ("Bull case", r.get("bull_case")),
             ("Bear case", r.get("bear_case")), ("Valuation", r.get("valuation"))]
    return "\n".join(f"{k}: {v}" for k, v in parts if v)


def stratified_sample(pairs: list[dict], n: int, seed: int = 0) -> list[dict]:
    """Proportional sample across (horizon, source) strata; at least one item per non-empty stratum."""
    strata: dict[tuple, list[dict]] = defaultdict(list)
    for p in pairs:
        strata[(p["horizon"], p["source"])].append(p)
    rng = random.Random(seed)
    total = len(pairs)
    out = []
    for key in sorted(strata):
        items = strata[key]
        k = min(len(items), max(1, round(n * len(items) / total)))
        out.extend(rng.sample(items, k))
    rng.shuffle(out)
    return out[:n] if len(out) > n else out


def sample(store, n: int, seed: int, out: Path | None = None) -> Path:
    pairs = store.faithfulness_pairs("full")
    if not pairs:
        raise SystemExit("No cited views yet.")
    chosen = stratified_sample(pairs, n, seed)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = out or OUT_DIR / f"faithfulness_{date.today():%Y%m%d}_n{len(chosen)}_seed{seed}.csv"
    with out.open("w", encoding="utf-8-sig", newline="") as fh:  # utf-8-sig: opens cleanly in Excel
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        for i, p in enumerate(chosen, 1):
            w.writerow({"item": i, "suggestion_id": p["suggestion_id"], "ticker": p["ticker"],
                        "horizon": p["horizon"], "as_of": str(p["as_of"])[:10], "source": p["source"],
                        "doc_type": p.get("doc_type") or "", "chunk_id": f"chunk_{p['chunk_id']}",
                        "view_text": view_text(p), "passage": p["content"],
                        "annotator_a": "", "annotator_b": "", "notes": ""})
    return out


def score(path: Path) -> dict:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    norm = lambda x: (x or "").strip().lower()  # noqa: E731
    a = [norm(r["annotator_a"]) for r in rows]
    b = [norm(r["annotator_b"]) for r in rows]
    bad = sorted({x for x in a + b if x and x not in LABELS})
    if bad:
        raise SystemExit(f"Unknown labels {bad}; use one of {', '.join(LABELS)}")

    def rate(xs):
        xs = [x for x in xs if x]
        return None if not xs else round(sum(x == "supported" for x in xs) / len(xs), 3)

    by_source = defaultdict(list)
    for r, x, y in zip(rows, a, b):
        if x and y:
            by_source[r["source"]].append(x == y == "supported")
    kappa = cohen_kappa(a, b)
    result = {
        "file": path.name, "items": len(rows), "labelled_by_both": sum(bool(x and y) for x, y in zip(a, b)),
        "support_rate_a": rate(a), "support_rate_b": rate(b),
        "both_supported_rate": round(sum(x == y == "supported" for x, y in zip(a, b) if x and y)
                                     / max(1, sum(bool(x and y) for x, y in zip(a, b))), 3),
        "kappa": None if kappa is None else round(kappa, 3),
        "labels_a": dict(Counter(x for x in a if x)), "labels_b": dict(Counter(x for x in b if x)),
        "both_supported_by_source": {k: round(sum(v) / len(v), 3) for k, v in by_source.items()},
    }
    REPORT.parent.mkdir(exist_ok=True)
    REPORT.write_text(json.dumps(result, indent=1), encoding="utf-8")
    return result


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Citation-faithfulness annotation")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sample", help="Write a CSV of (view, cited passage) items to label")
    s.add_argument("--n", type=int, default=60)
    s.add_argument("--seed", type=int, default=0)
    sc = sub.add_parser("score", help="Support rates and agreement from a labelled CSV")
    sc.add_argument("file", type=Path)
    args = p.parse_args(argv)
    if args.cmd == "sample":
        from common.store import Store

        out = sample(Store(), args.n, args.seed)
        print(f"Wrote {out}\nLabel each row in annotator_a and annotator_b with: {', '.join(LABELS)}")
        return 0
    print(json.dumps(score(args.file), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
