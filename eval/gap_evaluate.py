"""Separate evaluation harness for Iteration 8 Gap & Capability Analysis.

Completely independent of eval/evaluate.py and the 12-question Data Analysis
set. It does not import, run, or alter any of that.

It evaluates the DETERMINISTIC core of Gap Analysis: for each capability, it
feeds the case's predefined required concepts (from gap_questions.py) into the
same matcher GapAnalyzer uses, against the actually-discovered schema, and
checks the resulting status against the expected status.

Evaluating the deterministic matcher (rather than the LLM's concept phrasing)
is intentional: status accuracy should reflect the schema-grounded logic, not
LLM wording variance. Evidence is printed for review.

Run:
  python -m eval.gap_evaluate --schema erp
  python -m eval.gap_evaluate --schema pos
"""

import argparse

from paths import db_for
from src.schema_tools import make_engine, discover_schema
from src.gap_analysis import (
    RequiredConcept, _schema_tokens, _match_concept, _decide_status,
)
from eval.gap_questions import GAP_CASES


def evaluate(schema_id):
    engine = make_engine(db_for(schema_id))
    schema = discover_schema(engine)
    entries = _schema_tokens(schema)

    results = []
    for case in GAP_CASES:
        concepts = [
            RequiredConcept(name=c["name"], keywords=c["keywords"],
                            essential=c.get("essential", True))
            for c in case["concepts"]
        ]
        for c in concepts:
            c.available, c.evidence = _match_concept(c, entries)

        status = _decide_status(concepts)
        correct = status == case["expected_status"]
        results.append({
            "id": case["id"],
            "capability": case["capability"],
            "expected": case["expected_status"],
            "got": status,
            "correct": correct,
            "concepts": [
                {"name": c.name, "available": c.available, "evidence": c.evidence}
                for c in concepts
            ],
        })
    return results


def main():
    parser = argparse.ArgumentParser(description="Evaluate Gap Analysis status accuracy.")
    parser.add_argument("--schema", default="erp", choices=["erp", "pos"])
    args = parser.parse_args()

    results = evaluate(args.schema)
    correct = sum(r["correct"] for r in results)
    total = len(results)

    print(f"Gap Analysis evaluation ({args.schema}): "
          f"{correct}/{total} status correct ({round(correct * 100 / total, 1)}%)\n")
    for r in results:
        flag = "OK " if r["correct"] else "MISS"
        print(f"  [{flag}] {r['id']} {r['capability']}")
        print(f"         expected={r['expected']}  got={r['got']}")
        for c in r["concepts"]:
            mark = "found" if c["available"] else "absent"
            ev = (" <- " + ", ".join(c["evidence"][:3])) if c["evidence"] else ""
            print(f"           - {c['name']}: {mark}{ev}")
        print()


if __name__ == "__main__":
    main()
