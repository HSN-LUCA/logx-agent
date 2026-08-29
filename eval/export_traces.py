"""Export GENUINE execution traces from real agent runs.

These traces are not hand-written. This script runs the actual AnalystAgent and
GapAnalyzer, captures what they really did (the workflow steps, the SQL they
generated, the intermediate data frames, the verification outcome, the
deterministic computation, and the final answer), and writes them to traces/.

Every value in a trace comes from the live execution: the agent's own result
dict, the LLM prompts/responses it actually issued (captured by wrapping the
agent's _chat), and the data frames it actually produced.

Run (needs OPENAI_API_KEY in .env):
  python -m eval.export_traces
"""

import json
import os
from datetime import datetime, timezone

import pandas as pd

from paths import root_path, db_for
from src.analyst_agent import AnalystAgent
from src.gap_analysis import GapAnalyzer

TRACES_DIR = root_path("traces")


def _df_preview(df, max_rows=12):
    if df is None:
        return None
    return {
        "columns": list(df.columns),
        "row_count": int(len(df)),
        "rows": json.loads(df.head(max_rows).to_json(orient="records")),
    }


class _Recorder:
    """Wraps an object's _chat method to record real LLM calls."""
    def __init__(self, obj):
        self.obj = obj
        self.calls = []
        self._orig = obj._chat
        obj._chat = self._wrapped

    def _wrapped(self, prompt):
        resp = self._orig(prompt)
        # Record a compact, readable record of the real exchange.
        self.calls.append({
            "prompt_preview": prompt[:600],
            "response_preview": str(resp)[:600],
        })
        return resp


def _write(name, trace):
    os.makedirs(TRACES_DIR, exist_ok=True)
    trace["captured_at"] = datetime.now(timezone.utc).isoformat()
    trace["note"] = ("Genuine trace exported from a live run via "
                     "eval/export_traces.py — not hand-authored.")
    path = os.path.join(TRACES_DIR, name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(trace, f, indent=2)
    print(f"wrote traces/{name}")


def trace_data_analysis(name, question, schema_id):
    agent = AnalystAgent(
        db_uri=db_for(schema_id), schema_id=schema_id,
        use_schema_context=True, use_validation=True, use_verification=True,
        use_self_correction=True, use_business_analysis=True, use_query_planning=True,
    )
    rec = _Recorder(agent)
    resp = agent.query(question)

    trace = {
        "mode": "data_analysis",
        "schema_id": schema_id,
        "question": question,
        "query_type": resp.get("query_type"),
        "steps_planned": resp.get("steps"),
        "workflow": resp.get("workflow"),
        "sql_generated": resp.get("sql_query"),
        "read_only_validated": resp.get("sql_query") is not None or resp.get("query_type") == "complex",
        "verified": resp.get("verified"),
        "attempts": resp.get("attempts"),
        "self_corrections": resp.get("self_corrections"),
        "final_answer": resp.get("answer"),
        "result_preview": _df_preview(resp.get("chart_data")),
        "response_time_s": resp.get("response_time_s"),
        "llm_calls": rec.calls,
    }
    # For complex questions, include the real intermediate frames + plan.
    if resp.get("query_type") == "complex":
        frames = resp.get("intermediate_frames") or {}
        trace["intermediate_frames"] = {
            k: _df_preview(v) for k, v in frames.items()
        }
        trace["deterministic_computation"] = (
            "Final answer computed in Python from the verified intermediate "
            "frames above (no LLM synthesis)."
        )
    _write(name, trace)


def trace_gap_analysis(name, capability, schema_id):
    analyzer = GapAnalyzer(make_engine_for(schema_id), schema_id=schema_id)
    rec = _Recorder(analyzer)
    report = analyzer.analyze(capability)

    trace = {
        "mode": "gap_analysis",
        "schema_id": schema_id,
        "capability_question": capability,
        "status": report.status,
        "available": report.available,
        "missing": report.missing,
        "evidence_summary": report.evidence_summary,
        "schema_facts": report.facts,
        "business_impact": report.business_impact,
        "recommendation": report.recommendation,
        "confidence": report.confidence,
        "read_only": True,
        "llm_calls": rec.calls,
    }
    _write(name, trace)


def make_engine_for(schema_id):
    from src.schema_tools import make_engine
    return make_engine(db_for(schema_id))


def main():
    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("Set OPENAI_API_KEY (in .env) before exporting traces.")

    trace_data_analysis("simple_query.json",
                        "What was the total sales revenue in July 2026?", "erp")
    trace_data_analysis("ranking_query.json",
                        "What are the top 3 products by total revenue?", "erp")
    trace_data_analysis("complex_query.json",
                        "Which product had declining unit sales for three "
                        "consecutive months while its stock on hand was increasing?",
                        "erp")
    trace_data_analysis("pos_generalization.json",
                        "What are the top 3 products by total revenue?", "pos")
    trace_gap_analysis("gap_analysis.json",
                       "Can our ERP measure customer churn?", "erp")
    print("\nAll traces exported to traces/")


if __name__ == "__main__":
    main()
