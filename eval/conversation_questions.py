"""Separate evaluation set for Iteration 9 conversational follow-ups.

Independent of the 12-question Data Analysis set and the Gap Analysis set; it
does not modify or import their logic.

Each scenario is a sequence of turns. Turn 1 is a standalone question; later
turns are follow-ups that depend on the previous verified result. After each
turn the harness builds a ConversationContext from the VERIFIED result and feeds
it to the next turn. `expect_contains` lists strings the final turn's answer must
contain to count as correct (grounded in the seeded ERP data).

Expected values are grounded in erp.db (seed=42, fixed 2026 window):
  monthly sales: Jan 286,260 Feb 424,050 Mar 308,330 Apr 255,640 May 265,990
                 Jun 435,290 Jul 244,870 Aug 357,450  -> highest Jun, lowest Jul
  top products by revenue: UltraSlim Laptop, ProBook Laptop, 34in Ultrawide, ...
"""

CONVERSATION_SCENARIOS = [
    {
        "id": "C1",
        "schema_id": "erp",
        "turns": [
            "What were our monthly sales in 2026?",
            "Which month was highest?",
        ],
        "expect_contains": ["2026-06"],  # June
        "tests": "carry period context; superlative over previous result",
    },
    {
        "id": "C2",
        "schema_id": "erp",
        "turns": [
            "What were our monthly sales in 2026?",
            "Which month was highest?",
            "What about the lowest?",
        ],
        "expect_contains": ["2026-07"],  # July
        "tests": "multi-turn context preserved across three turns",
    },
    {
        "id": "C3",
        "schema_id": "erp",
        "turns": [
            "What are the top 5 products by revenue?",
            "What about the second one?",
        ],
        # 2nd product by revenue is ProBook Laptop.
        "expect_contains": ["ProBook Laptop"],
        "tests": "positional reference into previous result rows",
    },
    {
        "id": "C4",
        "schema_id": "erp",
        "turns": [
            "Show the top customers by total revenue.",
            "How much did the first one spend?",
        ],
        # First customer by revenue (grounded; harness verifies against DB).
        "expect_contains": [],  # value-checked dynamically in the harness
        "tests": "positional reference + re-query for a metric",
    },
    {
        "id": "C5",
        "schema_id": "pos",
        "turns": [
            "What were monthly sales in 2026?",
            "Which month was highest?",
        ],
        # POS has its own seeded distribution: the highest month is 2026-02
        # (verified against pos.db), NOT June. This confirms the follow-up
        # re-queries the actual database rather than reusing ERP assumptions.
        "expect_contains": ["2026-02"],
        "tests": "conversational follow-up generalizes to the POS schema",
    },
]
