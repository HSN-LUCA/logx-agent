"""Compute and persist verified ground-truth answers for every evaluation case.

Runs each case's reference_sql against erp.db and stores the result in
ground_truth.json. Because the answers are derived from the same database the
agent queries, they cannot drift from the data.

Run:  python ground_truth.py
"""

import argparse
import importlib
import json
import sqlite3


def load_cases(schema):
    """Load the (EVAL_CASES, DB_PATH) for a schema id ('erp' or 'pos')."""
    module_name = "eval.eval_questions" if schema == "erp" else f"eval.eval_questions_{schema}"
    mod = importlib.import_module(module_name)
    return mod.EVAL_CASES, mod.DB_PATH


def compute(cases, db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    out = {}

    for case in cases:
        cur = conn.execute(case["reference_sql"])
        rows = [tuple(r) for r in cur.fetchall()]

        entry = {
            "id": case["id"],
            "category": case["category"],
            "question": case["question"],
            "reference_sql": case["reference_sql"],
            "check": case["check"],
            "rows": rows,
        }

        # Derive the key fact(s) an answer must contain, based on the check type.
        chk = case["check"]
        if chk in ("scalar", "scalar_pct"):
            entry["expected_value"] = rows[0][0] if rows else None
        elif chk in ("top_label",):
            entry["expected_labels"] = [rows[0][0]] if rows else []
        elif chk in ("ordered_labels",):
            entry["expected_labels"] = [r[0] for r in rows]
        elif chk in ("label_set",):
            entry["expected_labels"] = sorted(r[0] for r in rows)
        elif chk in ("label_value_pairs",):
            entry["expected_pairs"] = [[r[0], r[1]] for r in rows]

        if "note" in case:
            entry["note"] = case["note"]
        out[case["id"]] = entry

    conn.close()
    return out


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compute ground-truth answers.")
    parser.add_argument("--schema", default="erp", choices=["erp", "pos"],
                        help="Which schema's question set to compute ground truth for.")
    args = parser.parse_args()

    from paths import ground_truth_for

    cases, db_path = load_cases(args.schema)
    output = ground_truth_for(args.schema)

    gt = compute(cases, db_path)
    with open(output, "w", encoding="utf-8") as f:
        json.dump(gt, f, indent=2)

    print(f"Wrote {output} with {len(gt)} ground-truth answers (schema={args.schema}).\n")
    for cid, e in gt.items():
        key = (
            e.get("expected_value")
            or e.get("expected_labels")
            or e.get("expected_pairs")
        )
        print(f"  {cid} [{e['category']}] {e['question']}")
        print(f"       -> {key}")
