"""Phase 2 gate: relevant chunks on 10 test queries.

    python -m retrieval.evaluate                 # hybrid
    python -m retrieval.evaluate --rerank        # + cross-encoder
    python -m retrieval.evaluate --as-of 2026-06-01 --k 5 --show 3

Automatic checks per query (all must hold):
  * k hits returned, all for the requested ticker/source
  * every hit published strictly before the as-of date (no lookahead)
  * an expected keyword appears in at least one of the top-3 hits
Then eyeball the printed snippets: the gate is "relevant", not just "matching".
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

from common import logging_setup

QUERIES = Path(__file__).with_name("eval_queries.json")


def check(case: dict, hits, as_of: date, k: int) -> list[str]:
    problems = []
    if len(hits) < k:
        problems.append(f"only {len(hits)}/{k} hits")
    if any(h.ticker != case["ticker"] for h in hits):
        problems.append("wrong ticker in results")
    if case.get("source") and any(h.source != case["source"] for h in hits):
        problems.append("wrong source in results")
    cutoff = datetime(as_of.year, as_of.month, as_of.day).isoformat()
    if any(h.published_at[:19] >= cutoff for h in hits):
        problems.append("LOOKAHEAD: hit published on/after as-of")
    top = " ".join(h.content.lower() for h in hits[:3])
    if not any(kw in top for kw in case["expect_any"]):
        problems.append(f"no expected keyword {case['expect_any']} in top 3")
    return problems


def main(argv: list[str] | None = None) -> int:
    logging_setup.setup()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    p.add_argument("--k", type=int, default=5)
    p.add_argument("--show", type=int, default=3, help="snippets to print per query")
    p.add_argument("--rerank", action="store_true")
    p.add_argument("--queries", type=Path, default=QUERIES)
    args = p.parse_args(argv)

    from common.store import Store
    from processing.embed import Embedder
    from retrieval.search import Retriever

    retriever = Retriever(Store(), Embedder())
    cases = json.loads(args.queries.read_text(encoding="utf-8"))
    passed = 0
    for i, case in enumerate(cases, 1):
        hits = retriever.search(case["query"], args.as_of, k=args.k, ticker=case["ticker"],
                                source=case.get("source"), rerank=args.rerank)
        problems = check(case, hits, args.as_of, args.k)
        passed += not problems
        flag = "PASS" if not problems else "FAIL"
        print(f"\n[{flag}] {i}. {case['ticker']} | {case['query']}" + (f"  -> {'; '.join(problems)}" if problems else ""))
        for h in hits[: args.show]:
            snippet = " ".join(h.content.split())[:220]
            print(f"   {h.citation:<12} {h.published_at[:10]} {h.doc_type or h.source:<10} "
                  f"v#{h.vector_rank} k#{h.keyword_rank}  {snippet}")
    print(f"\n{passed}/{len(cases)} queries passed automatic checks (as_of={args.as_of}, rerank={args.rerank})")
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    sys.exit(main())
