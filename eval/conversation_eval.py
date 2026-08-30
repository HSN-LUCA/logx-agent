"""Separate evaluation harness for Iteration 9 conversational follow-ups.

Independent of eval/evaluate.py and eval/gap_evaluate.py. Runs each multi-turn
scenario: turn 1 standalone, then each follow-up with a ConversationContext
built from the previous VERIFIED result. Confirms the follow-up is re-queried
and verified (previous answer is never the source of truth).

Metrics reported (real, not claimed):
  * conversation accuracy   final answer contains the expected value(s)
  * reference resolution     follow-up turns were detected & rewritten
  * SQL validity             follow-up produced valid SQL
  * execution errors         any turn errored
  * verification success     follow-up turns passed result verification

Run (needs OPENAI_API_KEY):
  python -m eval.conversation_eval
"""

import re

from paths import db_for
from src.analyst_agent import AnalystAgent
from src.conversation import build_context_from_result
from eval.conversation_questions import CONVERSATION_SCENARIOS


def _agent(schema_id):
    return AnalystAgent(
        db_uri=db_for(schema_id), schema_id=schema_id,
        use_schema_context=True, use_validation=True, use_verification=True,
        use_self_correction=True, use_business_analysis=True, use_query_planning=True,
    )


def _contains(answer, needle):
    a = str(answer or "").lower().replace(",", "")
    return needle.lower().replace(",", "") in a


def run_scenario(scenario):
    agent = _agent(scenario["schema_id"])
    context = None
    turns = []
    for i, q in enumerate(scenario["turns"]):
        resp = agent.query(q, context=context)
        turns.append({"q": q, "resp": resp})
        # Build context from this verified result for the next turn.
        asked = resp.get("resolved_question") or q
        context = build_context_from_result(scenario["schema_id"], asked, resp)

    final = turns[-1]["resp"]
    followups = turns[1:]

    # Conversation accuracy: final answer contains expected value(s).
    expected = scenario["expect_contains"]
    if expected:
        correct = all(_contains(final.get("answer"), e) for e in expected)
    else:
        # C4-style: no static expected; count correct if it produced a verified
        # numeric answer via a follow-up that was re-queried (grounded in DB).
        correct = bool(final.get("verified")) and final.get("sql_query") is not None

    return {
        "id": scenario["id"],
        "schema": scenario["schema_id"],
        "tests": scenario["tests"],
        "final_answer": str(final.get("answer"))[:120],
        "resolved": [t["resp"].get("resolved_question") for t in followups],
        "reference_resolved": all(t["resp"].get("was_followup") for t in followups),
        "sql_valid": all(t["resp"].get("sql_query") is not None for t in followups),
        "exec_error": any(t["resp"].get("error") for t in turns),
        "verified": all(t["resp"].get("verified") for t in followups),
        "correct": correct,
    }


def main():
    import os
    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("Set OPENAI_API_KEY (in .env) to run the conversation eval.")

    results = [run_scenario(s) for s in CONVERSATION_SCENARIOS]
    n = len(results)
    acc = sum(r["correct"] for r in results)
    ref = sum(r["reference_resolved"] for r in results)
    sqlv = sum(r["sql_valid"] for r in results)
    errs = sum(r["exec_error"] for r in results)
    ver = sum(r["verified"] for r in results)

    print(f"Conversational follow-up evaluation: {n} scenarios\n")
    for r in results:
        flag = "OK " if r["correct"] else "MISS"
        print(f"  [{flag}] {r['id']} ({r['schema']}) — {r['tests']}")
        print(f"         resolved: {r['resolved']}")
        print(f"         final: {r['final_answer']}")
        print(f"         ref_resolved={r['reference_resolved']} sql_valid={r['sql_valid']} "
              f"verified={r['verified']} exec_error={r['exec_error']}\n")

    print("SUMMARY (real measured):")
    print(f"  Conversation accuracy:      {acc}/{n} ({round(acc*100/n,1)}%)")
    print(f"  Reference resolution:       {ref}/{n}")
    print(f"  SQL validity (follow-ups):  {sqlv}/{n}")
    print(f"  Verification success:       {ver}/{n}")
    print(f"  Execution errors:           {errs}/{n}")


if __name__ == "__main__":
    main()
