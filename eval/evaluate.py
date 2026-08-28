"""Automated evaluation harness for the AI ERP Data Analyst Agent.

The same harness scores ANY runner that exposes:

    runner.name -> str
    runner.query(question: str) -> dict with keys:
        success (bool), answer (str|None), sql_query (str|None), error (str|None)

This guarantees the baseline and the final agent are judged on identical cases
with identical scoring, which is exactly what the hackathon requires.

Metrics recorded per case and aggregated:
  * correct          answer matches ground truth (primary outcome)
  * sql_valid        the agent produced SQL that executes without error on erp.db
  * answer_accuracy  fraction of correct answers
  * exec_error       an exception/error was returned
  * response_time_s  wall-clock time for the query

Usage:
  python evaluate.py --runner baseline           # keyword baseline (no LLM)
  python evaluate.py --runner agent              # LangChain agent (needs API key)

Outputs:
  results_<runner>.json   full per-case detail
  results_<runner>.md     human-readable summary table (for the changelog/report)
"""

import argparse
import json
import re
import sqlite3
import time

import importlib

NUMERIC_TOLERANCE = 0.01  # 1% relative tolerance for scalar/percentage answers


def load_schema(schema):
    """Return (EVAL_CASES, DB_PATH, ground_truth_file) for a schema id."""
    from paths import ground_truth_for

    module_name = "eval.eval_questions" if schema == "erp" else f"eval.eval_questions_{schema}"
    mod = importlib.import_module(module_name)
    gt_file = ground_truth_for(schema)
    return mod.EVAL_CASES, mod.DB_PATH, gt_file


# Default (ERP) so module-level references and the keyword baseline keep working.
EVAL_CASES, DB_PATH, GROUND_TRUTH_FILE = load_schema("erp")


# --------------------------------------------------------------------------- #
# Answer matching
# --------------------------------------------------------------------------- #
def _numbers_in(text):
    """Extract numeric values from free text, ignoring thousands separators."""
    if text is None:
        return []
    cleaned = str(text).replace(",", "")
    return [float(x) for x in re.findall(r"-?\d+\.?\d*", cleaned)]


def _matches_scalar(answer_text, expected, tol=NUMERIC_TOLERANCE):
    if expected is None:
        return False
    nums = _numbers_in(answer_text)
    for n in nums:
        if expected == 0:
            if abs(n) < 1e-9:
                return True
        elif abs(n - expected) <= abs(expected) * tol:
            return True
    return False


def _contains_label(answer_text, label):
    return label.lower() in str(answer_text or "").lower()


def score_answer(gt_entry, answer_text):
    """Return True if the agent's natural-language answer matches ground truth."""
    chk = gt_entry["check"]

    if chk in ("scalar", "scalar_pct"):
        return _matches_scalar(answer_text, gt_entry.get("expected_value"))

    if chk == "top_label":
        labels = gt_entry.get("expected_labels", [])
        return bool(labels) and _contains_label(answer_text, labels[0])

    if chk == "ordered_labels":
        # All expected labels must appear (order rewarded but not required here).
        return all(_contains_label(answer_text, l) for l in gt_entry.get("expected_labels", []))

    if chk == "label_set":
        return all(_contains_label(answer_text, l) for l in gt_entry.get("expected_labels", []))

    if chk == "label_value_pairs":
        # Require each label present and its value within tolerance.
        for label, value in gt_entry.get("expected_pairs", []):
            if not _contains_label(answer_text, label):
                return False
            if not _matches_scalar(answer_text, value):
                return False
        return True

    return False


def sql_is_valid(sql_query, db_path=None):
    """Does the produced SQL execute against the target DB without error?"""
    if not sql_query:
        return False
    try:
        conn = sqlite3.connect(db_path or DB_PATH)
        conn.execute(str(sql_query))
        conn.close()
        return True
    except Exception:
        return False


# --------------------------------------------------------------------------- #
# Baseline runner (no LLM) -- an honestly weak keyword matcher.
# --------------------------------------------------------------------------- #
class KeywordBaseline:
    """A deliberately simple baseline: no schema context, no verification.

    It maps a few keywords to canned SQL. It intentionally has no real language
    understanding, so it will get simple cases occasionally right and everything
    else wrong -- which is the point of a fair, weak baseline.
    """

    name = "baseline"

    def query(self, question):
        q = question.lower()
        sql = None
        try:
            if "how many customers" in q:
                sql = "SELECT COUNT(*) FROM customers;"
            elif "total sales revenue" in q and "all time" in q:
                sql = "SELECT SUM(line_total) FROM invoice_lines;"
            elif "revenue" in q and "july" in q:
                sql = (
                    "SELECT SUM(il.line_total) FROM invoice_lines il "
                    "JOIN invoices i ON i.invoice_id=il.invoice_id "
                    "WHERE i.invoice_date LIKE '2026-07%';"
                )
            # Everything else: the baseline has no idea.
            if sql is None:
                return {"success": False, "answer": "I don't know how to answer that.",
                        "sql_query": None, "error": "no_rule_matched"}

            conn = sqlite3.connect(DB_PATH)
            row = conn.execute(sql).fetchone()
            conn.close()
            val = row[0] if row else None
            return {"success": True, "answer": f"The result is {val}.",
                    "sql_query": sql, "error": None}
        except Exception as e:
            return {"success": False, "answer": None, "sql_query": sql, "error": str(e)}


def get_llm_baseline_runner():
    """Plain single-chain LLM baseline (schema only, no verification).

    This is the 'general-purpose agent with basic tools' baseline. Uses the
    original DatabaseAIAgent. Requires an OpenAI API key.
    """
    from src.ai_agent import DatabaseAIAgent

    class LLMBaselineRunner:
        name = "llm_baseline"

        def __init__(self):
            self.agent = DatabaseAIAgent(db_path=DB_PATH)

        def query(self, question):
            return self.agent.query(question)

    return LLMBaselineRunner()


# Cumulative capability presets: each turns on one more iteration than the last,
# so the accuracy delta between consecutive runners isolates that iteration's
# contribution. All require an OpenAI API key.
ANALYST_PRESETS = {
    # Iteration 1 only: schema discovery + business context, nothing else.
    "it1": dict(use_schema_context=True, use_validation=False,
                use_verification=False, use_self_correction=False,
                use_business_analysis=False),
    # + Iteration 2: read-only validation.
    "it2": dict(use_schema_context=True, use_validation=True,
                use_verification=False, use_self_correction=False,
                use_business_analysis=False),
    # + Iteration 3: result verification.
    "it3": dict(use_schema_context=True, use_validation=True,
                use_verification=True, use_self_correction=False,
                use_business_analysis=False),
    # + Iteration 4: self-correction.
    "it4": dict(use_schema_context=True, use_validation=True,
                use_verification=True, use_self_correction=True,
                use_business_analysis=False),
    # Final: + Iteration 5 business-analysis output. The full agent.
    "final": dict(use_schema_context=True, use_validation=True,
                  use_verification=True, use_self_correction=True,
                  use_business_analysis=True),
}


def get_analyst_runner(preset, db_uri=DB_PATH, schema_id="erp"):
    """Build an AnalystAgent runner for a cumulative capability preset."""
    from src.analyst_agent import AnalystAgent

    flags = ANALYST_PRESETS[preset]

    class AnalystRunner:
        name = f"analyst_{preset}" if db_uri == DB_PATH else f"analyst_{preset}_{schema_id}"

        def __init__(self):
            self.agent = AnalystAgent(db_uri=db_uri, schema_id=schema_id, **flags)

        def query(self, question):
            return self.agent.query(question)

    return AnalystRunner()


# --------------------------------------------------------------------------- #
# Evaluation loop
# --------------------------------------------------------------------------- #
def run_eval(runner, cases=None, ground_truth_file=None, db_path=None):
    cases = cases if cases is not None else EVAL_CASES
    ground_truth_file = ground_truth_file or GROUND_TRUTH_FILE
    with open(ground_truth_file, encoding="utf-8") as f:
        ground_truth = json.load(f)

    results = []
    for case in cases:
        gt = ground_truth[case["id"]]

        start = time.perf_counter()
        try:
            out = runner.query(case["question"])
        except Exception as e:
            out = {"success": False, "answer": None, "sql_query": None, "error": str(e)}
        elapsed = round(time.perf_counter() - start, 3)

        answer_text = out.get("answer")
        sql_query = out.get("sql_query")
        exec_error = bool(out.get("error")) or not out.get("success", False)

        correct = score_answer(gt, answer_text) if not exec_error else False
        valid_sql = sql_is_valid(sql_query, db_path=db_path)

        results.append({
            "id": case["id"],
            "category": case["category"],
            "question": case["question"],
            "expected": gt.get("expected_value") or gt.get("expected_labels") or gt.get("expected_pairs"),
            "agent_answer": answer_text,
            "sql_query": str(sql_query) if sql_query else None,
            "correct": correct,
            "sql_valid": valid_sql,
            "exec_error": exec_error,
            "error": out.get("error"),
            "response_time_s": elapsed,
        })

    return results


def summarize(runner_name, results):
    n = len(results)
    correct = sum(r["correct"] for r in results)
    sql_valid = sum(r["sql_valid"] for r in results)
    errors = sum(r["exec_error"] for r in results)
    avg_time = round(sum(r["response_time_s"] for r in results) / n, 3) if n else 0

    summary = {
        "runner": runner_name,
        "total_cases": n,
        "correct": correct,
        "answer_accuracy_pct": round(correct * 100.0 / n, 1) if n else 0,
        "sql_valid": sql_valid,
        "sql_validity_pct": round(sql_valid * 100.0 / n, 1) if n else 0,
        "exec_errors": errors,
        "avg_response_time_s": avg_time,
    }
    return summary


def write_reports(runner_name, results, summary):
    from paths import root_path

    with open(root_path(f"results_{runner_name}.json"), "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "cases": results}, f, indent=2)

    lines = []
    lines.append(f"# Evaluation results: {runner_name}\n")
    lines.append(
        f"- Cases: {summary['total_cases']}\n"
        f"- Correct answers: {summary['correct']} "
        f"({summary['answer_accuracy_pct']}%)\n"
        f"- SQL valid: {summary['sql_valid']} "
        f"({summary['sql_validity_pct']}%)\n"
        f"- Execution errors: {summary['exec_errors']}\n"
        f"- Avg response time: {summary['avg_response_time_s']}s\n"
    )
    lines.append("\n| ID | Category | Correct | SQL valid | Time (s) | Question |")
    lines.append("|----|----------|:-------:|:---------:|:--------:|----------|")
    for r in results:
        lines.append(
            f"| {r['id']} | {r['category']} | "
            f"{'yes' if r['correct'] else 'no'} | "
            f"{'yes' if r['sql_valid'] else 'no'} | "
            f"{r['response_time_s']} | {r['question']} |"
        )
    with open(root_path(f"results_{runner_name}.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def main():
    parser = argparse.ArgumentParser(
        description="Evaluate a business-database query runner on the fixed eval set."
    )
    parser.add_argument(
        "--runner",
        choices=["baseline", "llm_baseline", "it1", "it2", "it3", "it4", "final"],
        default="baseline",
        help=(
            "baseline=keyword (no LLM); llm_baseline=plain LangChain chain; "
            "it1..it4=cumulative analyst iterations; final=full analyst agent."
        ),
    )
    parser.add_argument(
        "--schema-id", default="erp", choices=["erp", "pos"],
        help="Which schema to evaluate against (selects question set, DB and ground truth).",
    )
    parser.add_argument(
        "--db", default=None,
        help="Override the database path (defaults to the schema's own DB).",
    )
    args = parser.parse_args()

    # Load the question set, default DB and ground-truth file for the schema.
    cases, schema_db, gt_file = load_schema(args.schema_id)
    db_path = args.db or schema_db

    if args.runner == "baseline":
        runner = KeywordBaseline()
    elif args.runner == "llm_baseline":
        runner = get_llm_baseline_runner()
    else:
        runner = get_analyst_runner(args.runner, db_uri=db_path, schema_id=args.schema_id)

    results = run_eval(runner, cases=cases, ground_truth_file=gt_file, db_path=db_path)
    summary = summarize(runner.name, results)
    write_reports(runner.name, results, summary)

    print(json.dumps(summary, indent=2))
    print(f"\nWrote results_{runner.name}.json and results_{runner.name}.md")


if __name__ == "__main__":
    main()
