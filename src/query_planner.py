"""Iteration 7: query planning and decomposition.

Some business questions cannot be answered reliably by a single SQL query. The
classic example: "which product had declining sales for three consecutive months
while its stock was rising?" A model asked for one query reaches for window
functions inside HAVING and produces SQL the database rejects.

The planner routes each question:

    question
      -> classify
           SIMPLE  -> the existing single-query pipeline (unchanged)
           COMPLEX -> a known pattern with:
                        * a set of simple sub-queries (each a plain SELECT)
                        * a DETERMINISTIC pandas computation over the results

Crucially, the final answer for a COMPLEX question is computed in Python from
verified data frames -- never synthesized by the LLM. This is the same
value-preserving rule used by the presentation layer: reason over verified data
deterministically; do not let the model invent or restate the result.

The planner recognizes a small, explicit set of patterns rather than generating
arbitrary code. Recognizing a *class* of question and applying a hand-verified
computation is reliable and auditable; improvising pandas from an LLM is not.
"""

import pandas as pd


# --------------------------------------------------------------------------- #
# Pattern definitions
#
# Each pattern provides:
#   detect(question)  -> bool          (cheap keyword heuristic; the LLM planner
#                                        can also select it explicitly)
#   subqueries(schema_id) -> dict[name -> NL sub-question]
#   compute(frames)   -> (answer_label, detail)   deterministic, over frames
# --------------------------------------------------------------------------- #

def _consecutive_decline_with_rising_other(units_df, stock_df, n=3):
    """Deterministic core for the Q12 pattern.

    units_df: columns [entity, period, units]   (monthly units sold per product)
    stock_df: columns [entity, period, stock]    (monthly stock on hand per product)

    Returns the entity whose `units` fell for `n` consecutive month-transitions
    while, over the same window, `stock` rose each step. Returns None if no
    entity qualifies.
    """
    units_df = units_df.copy()
    stock_df = stock_df.copy()
    units_df.columns = ["entity", "period", "units"]
    stock_df.columns = ["entity", "period", "stock"]

    merged = pd.merge(units_df, stock_df, on=["entity", "period"], how="inner")
    merged = merged.sort_values(["entity", "period"])

    for entity, g in merged.groupby("entity"):
        u = g["units"].tolist()
        s = g["stock"].tolist()
        # Look for any window of n consecutive transitions (n+1 points) where
        # units strictly decrease and stock strictly increases each step.
        for i in range(len(u) - n):
            window_u = u[i:i + n + 1]
            window_s = s[i:i + n + 1]
            units_falling = all(window_u[k] > window_u[k + 1] for k in range(n))
            stock_rising = all(window_s[k] < window_s[k + 1] for k in range(n))
            if units_falling and stock_rising:
                return entity
    return None


class DecliningSalesRisingStockPattern:
    """Q12-shaped: consecutive monthly sales decline while stock rises."""

    name = "declining_sales_rising_stock"

    KEYWORDS = ("consecutive", "three", "declin", "stock")

    @classmethod
    def detect(cls, question):
        q = question.lower()
        has_trend = ("declin" in q or "decreas" in q or "falling" in q)
        has_stock = ("stock" in q or "inventory" in q)
        has_consecutive = ("consecutive" in q or "three" in q or "3" in q or "months" in q)
        return has_trend and has_stock and has_consecutive

    @staticmethod
    def subqueries(schema_id):
        """Return {frame_name: natural-language sub-question}.

        The sub-questions are simple aggregations that the existing single-query
        pipeline handles reliably on any schema.
        """
        return {
            "units": "For every product, the total units sold in each month. "
                     "Return three columns: product name, month (YYYY-MM), total units.",
            "stock": "For every product, the stock on hand in each month. "
                     "Return three columns: product name, month (YYYY-MM), units on hand.",
        }

    @staticmethod
    def compute(frames):
        units_df = frames["units"]
        stock_df = frames["stock"]
        entity = _consecutive_decline_with_rising_other(units_df, stock_df, n=3)
        if entity is None:
            return None, "No product matched the pattern."
        return entity, (
            f"{entity} had three consecutive months of declining unit sales "
            f"while its stock on hand rose over the same period."
        )


# Registry of known complex patterns, checked in order.
PATTERNS = [DecliningSalesRisingStockPattern]


def detect_pattern(question):
    """Return the first pattern whose heuristic matches, else None."""
    for p in PATTERNS:
        if p.detect(question):
            return p
    return None
