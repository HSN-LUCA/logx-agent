"""Iteration 9: short-term conversational context and follow-up resolution.

The goal is narrow: let a user ask natural follow-up questions ("which month was
highest?", "what about the second one?") about the previous analysis, without
turning the agent into a long-term memory system.

Core safety principle:

    Previous verified result -> small structured context -> resolve the follow-up
    into a STANDALONE question -> re-query the database -> verify again.

The previous answer is CONTEXT, never truth. The LLM resolver only rewrites the
follow-up (or asks for clarification); it never answers the question itself. The
rewritten question then goes through the existing, unchanged SQL -> validation ->
execution -> verification pipeline, so the database remains the source of truth.

Context is limited to the current session and the latest verified turn, and the
result preview is capped at MAX_PREVIEW_ROWS.
"""

import re
from dataclasses import dataclass, field

MAX_PREVIEW_ROWS = 10

# Marker for a clarification response from the resolver (never guesses).
CLARIFY_PREFIX = "CLARIFY:"

# Words/phrases that suggest a question depends on prior context. Deterministic
# pre-check: if none are present, the question is treated as standalone and the
# resolver is skipped entirely (so fresh questions behave exactly as before).
_FOLLOWUP_MARKERS = (
    " it ", " it?", "it.", " its ", " they ", " them ", " those ", " these ",
    " that ", " this ", " same ", "what about", "how about", "and what",
    "the first", "the second", "the third", "the last", "the top one",
    "the highest", "the lowest", "that month", "that product", "that customer",
    "that branch", "same period", "same month", "same customer", "which one",
    "of them", "of these", "of those", "the previous",
    # Bare superlatives / short elliptical follow-ups (e.g. "which month was
    # highest?", "and the lowest?", "which was the most?").
    "highest", "lowest", "which month", "which product", "which customer",
    "which branch", "which one", "most", "least", "first one", "second one",
    "contributed the most", "and the",
)


@dataclass
class ConversationContext:
    """Small, bounded context describing the latest verified turn."""
    schema_id: str = ""
    previous_question: str = ""
    previous_answer: str = ""
    previous_sql: str = ""
    result_columns: list = field(default_factory=list)
    result_rows: list = field(default_factory=list)  # <= MAX_PREVIEW_ROWS dicts

    def is_empty(self):
        return not self.previous_question


def build_context_from_result(schema_id, question, result):
    """Build context from a VERIFIED result dict produced by AnalystAgent.query.

    Only called for successful, verified turns. The result preview is capped.
    """
    df = result.get("chart_data")
    columns, rows = [], []
    if df is not None and len(df) > 0:
        columns = [str(c) for c in df.columns]
        preview = df.head(MAX_PREVIEW_ROWS)
        # Convert to plain JSON-able dicts (stringify values defensively).
        for _, r in preview.iterrows():
            rows.append({str(k): (None if v is None else _plain(v))
                         for k, v in r.items()})

    return ConversationContext(
        schema_id=schema_id,
        previous_question=question or "",
        previous_answer=str(result.get("answer") or ""),
        previous_sql=str(result.get("sql_query") or ""),
        result_columns=columns,
        result_rows=rows,
    )


def _plain(v):
    try:
        # Keep ints/floats as numbers; everything else as string.
        import numbers

        if isinstance(v, numbers.Number):
            return v
    except Exception:
        pass
    return str(v)


def looks_like_followup(question):
    """Deterministic heuristic: does this question likely depend on prior context?"""
    q = f" {(question or '').lower().strip()} "
    return any(m in q for m in _FOLLOWUP_MARKERS)


def _context_block(context):
    """Render the structured context compactly for the resolver prompt."""
    lines = [
        f"PREVIOUS QUESTION: {context.previous_question}",
        f"PREVIOUS ANSWER (context only, not authoritative): {context.previous_answer}",
    ]
    if context.previous_sql:
        lines.append(f"PREVIOUS SQL: {context.previous_sql}")
    if context.result_columns:
        lines.append(f"PREVIOUS RESULT COLUMNS: {', '.join(context.result_columns)}")
    if context.result_rows:
        lines.append("PREVIOUS RESULT ROWS (up to 10, for resolving references "
                     "like 'the second one'):")
        for i, row in enumerate(context.result_rows, 1):
            compact = ", ".join(f"{k}={v}" for k, v in row.items())
            lines.append(f"  {i}. {compact}")
    return "\n".join(lines)


def resolve_prompt(question, context):
    return (
        "You resolve conversational follow-up questions for a data analyst. "
        "Given the previous turn's context and a NEW user message, rewrite the "
        "new message into a SINGLE, SELF-CONTAINED question that can be answered "
        "on its own, carrying over the relevant time period, entity, or metric "
        "from the context.\n"
        "\n"
        "STRICT RULES:\n"
        "- Do NOT answer the question. Output only the rewritten question.\n"
        "- Use the previous result rows only to resolve references such as 'the "
        "second one' or 'that product' (e.g. replace 'the second one' with the "
        "actual name from row 2). You are NOT stating that value is the answer; "
        "you are just naming the entity so the database can be queried again.\n"
        "- POSITIONAL and SUPERLATIVE references are NOT ambiguous: resolve them "
        "directly. 'the second one' -> the item in row 2; 'the first one' -> row 1; "
        "'the highest'/'the top one' -> the single top row; 'the lowest' -> the "
        "bottom row. Name that item in the rewritten question.\n"
        "- A BARE PRONOUN ('it', 'that one', 'that', 'them') is ambiguous ONLY when "
        "the previous result contains more than one candidate item and the user "
        "did not indicate which. In that case you MUST NOT guess or combine items; "
        f"respond with '{CLARIFY_PREFIX} <question listing the candidate options>'. "
        "Example: previous result had Laptop and Monitor, user says 'how much did "
        f"it sell?' -> '{CLARIFY_PREFIX} Which product do you mean - Laptop or Monitor?'\n"
        "  If the previous result has exactly one item, a pronoun resolves to it.\n"
        "- If the new message is already self-contained, return it unchanged.\n"
        "\n"
        f"{_context_block(context)}\n"
        "\n"
        f"NEW USER MESSAGE: {question}\n"
        "\nREWRITTEN STANDALONE QUESTION (or CLARIFY: ...):"
    )


def resolve_followup(question, context, chat):
    """Resolve a follow-up into a standalone question or a clarification.

    Returns a dict:
      {"kind": "standalone", "question": <str>}   -> feed to the normal pipeline
      {"kind": "clarify",    "message": <str>}     -> ask the user, do not query
      {"kind": "passthrough","question": <str>}    -> not a follow-up / no context

    `chat` is a callable(prompt) -> text (the agent's _chat), injected for
    testability. The resolver NEVER answers or touches the database.
    """
    if context is None or context.is_empty() or not looks_like_followup(question):
        return {"kind": "passthrough", "question": question}

    try:
        raw = chat(resolve_prompt(question, context)).strip()
    except Exception:
        # If resolution fails, fall back to treating it as a standalone question
        # (still goes through full verification downstream).
        return {"kind": "passthrough", "question": question}

    # Strip stray fences/quotes.
    raw = raw.strip().strip('"').strip()
    if raw.upper().startswith(CLARIFY_PREFIX):
        message = raw[len(CLARIFY_PREFIX):].strip()
        return {"kind": "clarify", "message": message or
                "Could you clarify which item you mean?"}

    # Keep only the first line/sentence as the rewritten question.
    rewritten = raw.splitlines()[0].strip() if raw else question
    if not rewritten:
        rewritten = question
    return {"kind": "standalone", "question": rewritten}
