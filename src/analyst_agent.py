"""AI Data Analyst Agent for Business Databases.

A schema-agnostic agent that answers natural-language questions about a business
database. Capabilities are individually toggleable so each iteration in
STRATEGY.md can be measured on its own with the shared evaluation harness.

Pipeline (capabilities in brackets are optional and flag-controlled):

    question
      -> [schema discovery + business context]      (Iteration 1)
      -> SQL generation (LLM)
      -> [read-only validation]                     (Iteration 2)
      -> execute
      -> [result verification]                      (Iteration 3)
      -> [self-correction on failure, capped]       (Iteration 4)
      -> [business-analysis formatting]             (Iteration 5)
      -> answer + evidence

The LLM-dependent steps (SQL generation, and optionally verification/analysis)
require an OpenAI API key. The deterministic steps (schema discovery, read-only
validation, execution, structural verification) run without any API call and are
independently testable.
"""

import os
import re
import time

import pandas as pd
from dotenv import load_dotenv

from src.schema_tools import make_engine, discover_schema, render_schema_summary
from src.business_context import render_business_context
from paths import ERP_DB

load_dotenv()

# Statements that must never run against a business database (read-only guard).
_FORBIDDEN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|REPLACE|MERGE|GRANT|REVOKE|ATTACH|PRAGMA)\b",
    re.IGNORECASE,
)


class SQLValidationError(Exception):
    pass


def validate_read_only(sql):
    """Iteration 2: reject anything that is not a single read-only SELECT."""
    if not sql or not sql.strip():
        raise SQLValidationError("empty SQL")
    stripped = sql.strip().rstrip(";")
    # Only one statement allowed.
    if ";" in stripped:
        raise SQLValidationError("multiple statements are not allowed")
    if _FORBIDDEN.search(stripped):
        raise SQLValidationError("only read-only SELECT queries are allowed")
    if not re.match(r"^\s*(SELECT|WITH)\b", stripped, re.IGNORECASE):
        raise SQLValidationError("query must start with SELECT or WITH")
    return stripped


def _fmt_number(value):
    """Format a number for humans without changing its value.

    Integers print without a decimal; other numbers keep their exact value with
    thousands separators. Non-numbers pass through as their string form.
    """
    try:
        f = float(value)
    except (TypeError, ValueError):
        return str(value)
    if f == int(f):
        return f"{int(f):,}"
    # Keep the exact value; group thousands, trim trailing zeros.
    return f"{f:,}".rstrip("0").rstrip(".") if "." in f"{f}" else f"{f:,}"


def present_result(df):
    """Deterministically render a verified result dataframe as readable text.

    Preserves exact values. Handles the shapes our questions produce:
      * single scalar        -> "<column> is <value>."
      * single row           -> "<colA>: <valA>; <colB>: <valB>."
      * one label + one value column, multiple rows (ranking / breakdown)
                             -> a numbered list "1. <label> - <value>"
      * anything else        -> a compact table.
    Always appends the full row count for transparency.
    """
    if df is None or len(df) == 0:
        return "No matching data was found."

    rows, cols = df.shape

    # Single scalar answer.
    if rows == 1 and cols == 1:
        col = df.columns[0]
        val = df.iloc[0, 0]
        return f"{col.replace('_', ' ').capitalize()} is {_fmt_number(val)}."

    # Single row, few columns: "col: value" pairs.
    if rows == 1:
        parts = [f"{c.replace('_', ' ')}: {_fmt_number(df.iloc[0][c])}" for c in df.columns]
        return "; ".join(parts) + "."

    # Ranking / breakdown: a label column + a single numeric value column.
    if cols == 2:
        label_col, value_col = df.columns[0], df.columns[1]
        lines = [
            f"{i + 1}. {df.iloc[i][label_col]} - {_fmt_number(df.iloc[i][value_col])}"
            for i in range(rows)
        ]
        header = f"{rows} results, by {value_col.replace('_', ' ')}:"
        return header + "\n" + "\n".join(lines)

    # A single-column list of labels (e.g. distinct customers).
    if cols == 1:
        col = df.columns[0]
        items = ", ".join(str(v) for v in df[col].tolist())
        return f"{rows} {col.replace('_', ' ')}: {items}."

    # Fallback: compact table, values unchanged.
    return f"{rows} rows:\n" + df.to_string(index=False)


# Workflow step labels surfaced to the UI (describe what the agent did).
SIMPLE_WORKFLOW = [
    "Understanding question",
    "Discovering schema",
    "Generating SQL",
    "Validating SQL",
    "Executing query",
    "Verifying result",
    "Answer ready",
]

COMPLEX_WORKFLOW = [
    "Understanding question",
    "Detecting complex query",
    "Planning sub-queries",
    "Executing sub-queries",
    "Verifying results",
    "Deterministic analysis",
    "Answer ready",
]


class AnalystAgent:
    def __init__(
        self,
        db_uri=ERP_DB,
        schema_id="erp",
        use_schema_context=True,
        use_validation=True,
        use_verification=True,
        use_self_correction=True,
        use_business_analysis=True,
        use_query_planning=False,
        max_retries=2,
        llm=None,
    ):
        self.engine = make_engine(db_uri)
        self.schema_id = schema_id
        self.use_schema_context = use_schema_context
        self.use_validation = use_validation
        self.use_verification = use_verification
        self.use_self_correction = use_self_correction
        self.use_business_analysis = use_business_analysis
        self.use_query_planning = use_query_planning
        self.max_retries = max_retries

        # Discover schema once at construction (cheap, no LLM).
        self.schema = discover_schema(self.engine)
        self.schema_summary = render_schema_summary(self.schema)
        self.context_text = (
            render_business_context(schema_id) if use_schema_context else ""
        )

        # LLM is injected for testability; built lazily from env if not provided.
        self._llm = llm

    # ---- LLM plumbing ---------------------------------------------------- #
    @property
    def llm(self):
        if self._llm is None:
            from langchain_openai import ChatOpenAI

            self._llm = ChatOpenAI(
                temperature=0,
                model=os.getenv("OPENAI_MODEL", "gpt-3.5-turbo"),
                openai_api_key=os.getenv("OPENAI_API_KEY"),
            )
        return self._llm

    def _chat(self, prompt):
        """Send a single prompt to the LLM and return raw text."""
        resp = self.llm.invoke(prompt)
        return getattr(resp, "content", str(resp))

    # ---- SQL generation (Iteration 1 grounding) -------------------------- #
    def _generation_prompt(self, question, prior_error=None):
        parts = [
            "You are a careful data analyst. Write ONE read-only SQL SELECT query "
            "(SQLite dialect) that answers the user's question.",
            "Return ONLY the SQL, with no explanation and no markdown fences.",
            "",
            "DATABASE SCHEMA:",
            self.schema_summary,
        ]
        if self.context_text:
            parts += ["", self.context_text]
        if prior_error:
            parts += [
                "",
                "Your previous attempt failed. Fix it.",
                f"PROBLEM: {prior_error}",
            ]
        parts += ["", f"QUESTION: {question}", "", "SQL:"]
        return "\n".join(parts)

    @staticmethod
    def _clean_sql(text):
        """Strip markdown fences / stray prose the model may add."""
        t = text.strip()
        t = re.sub(r"^```(?:sql)?", "", t, flags=re.IGNORECASE).strip()
        t = re.sub(r"```$", "", t).strip()
        # Keep from the first SELECT/WITH onward.
        m = re.search(r"(SELECT|WITH)\b", t, re.IGNORECASE)
        return t[m.start():].strip() if m else t

    def generate_sql(self, question, prior_error=None):
        raw = self._chat(self._generation_prompt(question, prior_error))
        return self._clean_sql(raw)

    # ---- Execution ------------------------------------------------------- #
    def execute_sql(self, sql):
        return pd.read_sql(sql, self.engine)

    # ---- Result verification (Iteration 3) ------------------------------- #
    def verify_result(self, question, sql, df):
        """Return (ok, reason). A deterministic structural check first; then an
        optional LLM judgment for intent alignment."""
        # Structural checks (no LLM).
        if df is None:
            return False, "no result returned"
        if len(df) == 0:
            return False, "query returned zero rows"

        if not self.use_verification:
            return True, "verification disabled"

        # LLM intent check: does the result plausibly answer the question?
        preview = df.head(10).to_string(index=False)
        prompt = (
            "You are verifying whether a SQL result answers a business question. "
            "Answer strictly with 'YES' or 'NO: <short reason>'.\n\n"
            f"QUESTION: {question}\n"
            f"SQL: {sql}\n"
            f"RESULT (up to 10 rows):\n{preview}\n\n"
            "Does the result correctly and directly answer the question?"
        )
        try:
            verdict = self._chat(prompt).strip()
        except Exception as e:
            # If the judge call fails, fall back to the structural pass.
            return True, f"verifier unavailable ({e}); structural check passed"

        if verdict.upper().startswith("YES"):
            return True, "verified"
        return False, verdict

    # ---- Presentation layer (Iteration 5, deterministic) ----------------- #
    def format_answer(self, question, sql, df):
        """Turn the VERIFIED result dataframe into human-friendly text.

        This layer is deterministic on purpose: it formats the exact values that
        were verified and never sends them back through an LLM to be rewritten.
        A prose rewrite was tried earlier and it dropped exact figures/labels
        (lowering accuracy), so presentation must preserve the verified value,
        format around it, never replace it.
        """
        if not self.use_business_analysis:
            # Plain: just stringify the result compactly.
            return df.to_string(index=False)
        return present_result(df)

    # ---- Query planning (Iteration 7) ------------------------------------ #
    def plan_query(self, question):
        """Return ('simple', None) or ('complex', pattern).

        Uses a cheap deterministic pattern detector. (An LLM classifier could be
        added here, but the detector is precise for the known patterns and needs
        no API call.) Only routes to COMPLEX when a known, hand-verified pattern
        matches; everything else stays on the reliable simple path.
        """
        from src.query_planner import detect_pattern

        pattern = detect_pattern(question)
        if pattern is not None:
            return "complex", pattern
        return "simple", None

    def _run_complex(self, question, pattern, start):
        """Answer a COMPLEX question by decomposing into simple sub-queries and
        computing the final answer deterministically over the verified frames."""
        frames = {}
        sub_attempts = 0
        subquery_map = pattern.subqueries(self.schema_id)
        n_steps = len(subquery_map)
        # Build a workflow with one line per sub-query for transparency.
        complex_workflow = [
            "Understanding question",
            "Detecting complex query",
            "Planning sub-queries",
        ] + [f"Executing sub-query {i + 1}" for i in range(n_steps)] + [
            "Verifying results",
            "Deterministic analysis",
            "Answer ready",
        ]
        try:
            for name, sub_question in subquery_map.items():
                # Each sub-question rides the existing, reliable single-query path.
                sub = self._run_simple(sub_question, time.perf_counter())
                sub_attempts += sub.get("attempts", 1)
                if not sub.get("success") or sub.get("chart_data") is None:
                    return self._result(
                        False, "Sorry, I couldn't answer that reliably.",
                        sub.get("sql_query"), None,
                        reason=f"sub-query '{name}' failed: {sub.get('reason')}",
                        attempts=sub_attempts, self_corrections=0,
                        start=start, verified=False, error=sub.get("error"),
                        query_type="complex", steps=n_steps, workflow=complex_workflow,
                        intermediate_frames=dict(frames),
                    )
                frames[name] = sub["chart_data"]

            # Deterministic computation over verified data frames (no LLM).
            answer_label, detail = pattern.compute(frames)
            if answer_label is None:
                return self._result(
                    True, detail, None, None, reason="pattern found no match",
                    attempts=sub_attempts, self_corrections=0,
                    start=start, verified=False,
                    query_type="complex", steps=n_steps, workflow=complex_workflow,
                    intermediate_frames=dict(frames),
                )

            result_df = pd.DataFrame({"answer": [answer_label]})
            answer = detail if self.use_business_analysis else str(answer_label)
            return self._result(
                True, answer, None, result_df, reason="ok (planned + deterministic)",
                attempts=sub_attempts, self_corrections=0,
                start=start, verified=True,
                query_type="complex", steps=n_steps, workflow=complex_workflow,
                intermediate_frames=dict(frames),
            )
        except Exception as e:
            return self._result(
                False, "Sorry, I couldn't answer that reliably.", None, None,
                reason=str(e), attempts=sub_attempts, self_corrections=0,
                start=start, verified=False, error=str(e),
                query_type="complex", steps=n_steps, workflow=complex_workflow,
                intermediate_frames=dict(frames),
            )

    # ---- Orchestration --------------------------------------------------- #
    def query(self, question):
        start = time.perf_counter()

        # Iteration 7: route complex, multi-step questions to the planner.
        if self.use_query_planning:
            route, pattern = self.plan_query(question)
            if route == "complex":
                return self._run_complex(question, pattern, start)

        return self._run_simple(question, start)

    def _run_simple(self, question, start):
        attempts = 0
        self_corrections = 0
        prior_error = None
        last_sql = None

        max_attempts = (self.max_retries + 1) if self.use_self_correction else 1

        while attempts < max_attempts:
            attempts += 1
            try:
                sql = self.generate_sql(question, prior_error=prior_error)
                last_sql = sql

                if self.use_validation:
                    sql = validate_read_only(sql)

                df = self.execute_sql(sql)

                ok, reason = self.verify_result(question, sql, df)
                if not ok:
                    prior_error = f"result check failed: {reason}"
                    if self.use_self_correction and attempts < max_attempts:
                        self_corrections += 1
                        continue
                    # Out of retries: return what we have, flagged.
                    answer = self.format_answer(question, sql, df)
                    return self._result(
                        True, answer, sql, df, reason=prior_error,
                        attempts=attempts, self_corrections=self_corrections,
                        start=start, verified=False,
                        query_type="simple", steps=1, workflow=SIMPLE_WORKFLOW,
                    )

                answer = self.format_answer(question, sql, df)
                return self._result(
                    True, answer, sql, df, reason="ok",
                    attempts=attempts, self_corrections=self_corrections,
                    start=start, verified=True,
                    query_type="simple", steps=1, workflow=SIMPLE_WORKFLOW,
                )

            except Exception as e:
                prior_error = str(e)
                if self.use_self_correction and attempts < max_attempts:
                    self_corrections += 1
                    continue
                return self._result(
                    False, "Sorry, I couldn't answer that reliably.", last_sql,
                    None, reason=prior_error, attempts=attempts,
                    self_corrections=self_corrections, start=start, verified=False,
                    error=prior_error,
                    query_type="simple", steps=1, workflow=SIMPLE_WORKFLOW,
                )

    def _result(self, success, answer, sql, df, reason, attempts,
                self_corrections, start, verified, error=None,
                query_type="simple", steps=1, workflow=None,
                intermediate_frames=None):
        return {
            "success": success,
            "answer": answer,
            "sql_query": sql,
            "chart_data": df,
            "has_chart": df is not None and len(df) > 0,
            "verified": verified,
            "attempts": attempts,
            "self_corrections": self_corrections,
            "reason": reason,
            "error": error,
            "response_time_s": round(time.perf_counter() - start, 3),
            # UI metadata (additive; not used by the evaluation harness).
            "query_type": query_type,
            "steps": steps,
            "workflow": workflow or [],
            "intermediate_frames": intermediate_frames or {},
        }

    def get_table_info(self):
        return self.schema_summary
