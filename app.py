"""Streamlit UI for the AI Data Analyst Agent for Business Databases.

A business-facing console that surfaces what makes this more than a text-to-SQL
chatbot: the schema it discovered, whether the result was verified, how it
planned complex questions, and the SQL + data as evidence.

The OpenAI key is read from the environment (.env locally) or Streamlit secrets
(on Community Cloud). There is deliberately no API-key input in the UI.
"""

import os
import re

import pandas as pd
import streamlit as st

from src.analyst_agent import AnalystAgent
from src.gap_analysis import (
    GapAnalyzer, SUPPORTED, PARTIALLY, NOT_SUPPORTED, UNCERTAIN,
)
from paths import ERP_DB, POS_DB

# --- schema registry -------------------------------------------------------- #
SCHEMAS = {
    "ERP Database": {"db": ERP_DB, "schema_id": "erp", "builder": "data.erp_database"},
    "POS Database": {"db": POS_DB, "schema_id": "pos", "builder": "data.pos_database"},
}

SAMPLE_QUESTIONS = [
    {"q": "What was the total sales revenue in July 2026?", "complex": False},
    {"q": "What are the top 3 products by total revenue?", "complex": False},
    {"q": "Which branch had the highest revenue growth from June to July 2026?", "complex": False},
    {"q": "How much revenue came from Corporate versus Retail customers?", "complex": False},
    {"q": "Which product had declining sales for three months while stock rose?", "complex": True},
]

CAPABILITIES = [
    "Schema Discovery",
    "Read-only SQL",
    "Result Verification",
    "Self-Correction",
    "Query Planning",
]

GAP_EXAMPLES = [
    "Can our ERP measure customer churn?",
    "Can we identify customers who have become inactive?",
    "Can we measure supplier delivery performance?",
    "Can we calculate customer lifetime value?",
    "Can we measure inventory turnover?",
]

# Phrases that suggest a capability question (for a non-blocking hint only;
# never used to auto-route). Purely a deterministic string check, no LLM.
CAPABILITY_HINT_PHRASES = (
    "can our", "can the system", "can the erp", "can we measure",
    "can we track", "can we calculate", "does the database support",
    "does the system support", "can we support", "is it possible to measure",
    "can this database", "can it measure",
)


def looks_like_capability_question(text):
    t = (text or "").lower()
    return any(p in t for p in CAPABILITY_HINT_PHRASES)

STATUS_STYLE = {
    SUPPORTED: ("#ecfdf5", "#a7f3d0", "#065f46"),
    PARTIALLY: ("#fffbeb", "#fde68a", "#92400e"),
    NOT_SUPPORTED: ("#fef2f2", "#fecaca", "#991b1b"),
    UNCERTAIN: ("#f3f4f6", "#e5e7eb", "#374151"),
}

# Column-name tokens that indicate a monetary value (AED). We only format as
# currency when the column name clearly means money; otherwise we leave numbers
# unformatted rather than risk mislabeling a non-currency figure.
MONEY_TOKENS = ("revenue", "amount", "line_total", "sales", "value")
# Tokens that look monetary but are not (avoid false positives).
NON_MONEY_EXACT = {"units", "quantity", "count", "n", "stock", "units_on_hand", "pct_change"}

st.set_page_config(page_title="AI Data Analyst Agent", page_icon="📊", layout="wide")


# --- styling (Part C) ------------------------------------------------------- #
def inject_css():
    st.markdown(
        """
        <style>
        .block-container { padding-top: 2rem; }
        .cap-row { display:flex; align-items:center; gap:8px; margin:4px 0; font-size:0.92rem; }
        .cap-dot { color:#16a34a; font-weight:700; }
        .status-dot { color:#16a34a; font-weight:700; }
        .verified-banner {
            background:#ecfdf5; border:1px solid #a7f3d0; border-radius:10px;
            padding:14px 16px; margin-bottom:14px;
        }
        .verified-banner .title { font-weight:700; color:#065f46; font-size:1.05rem; }
        .verified-banner .sub { color:#047857; font-size:0.86rem; }
        .unverified-banner {
            background:#fffbeb; border:1px solid #fde68a; border-radius:10px;
            padding:14px 16px; margin-bottom:14px;
        }
        .badge-complex {
            display:inline-block; background:#eef2ff; color:#4338ca;
            font-size:0.66rem; font-weight:700; letter-spacing:0.04em;
            padding:2px 8px; border-radius:6px; margin-top:6px;
        }
        .metric-card {
            border:1px solid #e5e7eb; border-radius:10px; padding:10px 12px; text-align:center;
            background:#ffffff;
        }
        .metric-card .label { font-size:0.66rem; letter-spacing:0.05em; color:#6b7280; text-transform:uppercase; }
        .metric-card .value { font-size:1.15rem; font-weight:700; color:#111827; margin-top:2px; }
        .workflow-step { font-size:0.9rem; margin:3px 0; color:#374151; }
        .workflow-step .ok { color:#16a34a; font-weight:700; }
        .trust-pill {
            display:inline-block; background:#f3f4f6; border:1px solid #e5e7eb;
            border-radius:999px; padding:3px 10px; font-size:0.78rem; margin-right:6px;
        }
        /* Mode selector styled as an obvious segmented control. */
        div[role="radiogroup"] {
            display:flex; gap:0; border:1px solid #d1d5db; border-radius:10px;
            overflow:hidden; width:fit-content; margin-bottom:12px;
        }
        div[role="radiogroup"] label {
            margin:0 !important; padding:8px 22px; cursor:pointer;
            background:#f9fafb; border-right:1px solid #e5e7eb;
            font-weight:600; color:#6b7280;
        }
        div[role="radiogroup"] label:last-child { border-right:none; }
        /* Hide the little radio circle; the whole segment is the control. */
        div[role="radiogroup"] label > div:first-child { display:none; }
        /* Highlight the checked segment. */
        div[role="radiogroup"] label:has(input:checked) {
            background:#2563eb; color:#ffffff;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


# --- helpers ---------------------------------------------------------------- #
def resolve_api_key():
    key = os.getenv("OPENAI_API_KEY", "")
    if not key:
        try:
            key = st.secrets.get("OPENAI_API_KEY", "")
        except Exception:
            key = ""
    return key


def ensure_database(builder_module, db_path):
    if os.path.exists(db_path):
        return
    import importlib

    mod = importlib.import_module(builder_module)
    for fn_name in ("create_erp_database", "create_pos_database"):
        if hasattr(mod, fn_name):
            getattr(mod, fn_name)()
            return


def get_agent(schema_label):
    """Build (and cache) the agent for the selected schema. Full pipeline on."""
    cfg = SCHEMAS[schema_label]
    ensure_database(cfg["builder"], cfg["db"])
    return AnalystAgent(
        db_uri=cfg["db"], schema_id=cfg["schema_id"],
        use_schema_context=True, use_validation=True, use_verification=True,
        use_self_correction=True, use_business_analysis=True, use_query_planning=True,
    )


def prettify_col(name):
    special = {
        "product_name": "Product", "customer_name": "Customer",
        "category_name": "Category", "branch_name": "Branch",
        "store_name": "Store", "shopper_name": "Customer",
        "total_revenue": "Total Revenue (AED)", "revenue": "Revenue (AED)",
        "pct_change": "Change (%)", "units": "Units", "dept": "Category",
        "segment": "Segment", "title": "Product",
    }
    if name in special:
        return special[name]
    return name.replace("_", " ").title()


def is_money_col(name):
    n = name.lower()
    if n in NON_MONEY_EXACT:
        return False
    return any(tok in n for tok in MONEY_TOKENS)


def fmt_value(col, v):
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        if is_money_col(col):
            if float(v) == int(v):
                return f"AED {int(v):,}"
            return f"AED {v:,.2f}"
        # Plain number, exact.
        if float(v) == int(v):
            return f"{int(v):,}"
        return f"{v:,}"
    return v


def render_table(df):
    """Render a result dataframe as a prettified, value-preserving table."""
    display = df.copy()
    # Format cells then rename columns for display.
    for col in display.columns:
        display[col] = display[col].map(lambda v, c=col: fmt_value(c, v))
    display.columns = [prettify_col(c) for c in display.columns]
    # Add a Rank column for multi-row ranking-style results.
    if len(display) > 1:
        display.insert(0, "Rank", range(1, len(display) + 1))
    st.dataframe(display, use_container_width=True, hide_index=True)


# --- deterministic visualization ------------------------------------------- #
TEMPORAL_TOKENS = ("month", "date", "period", "year", "day", "week", "quarter")
TEMPORAL_INTENT = ("over time", "trend", "monthly", "by month", "each month",
                   "per month", "timeline", "time series", "growth over")
RANKING_INTENT = ("top", "ranking", "rank", "by product", "by branch", "by store",
                  "by category", "highest", "lowest", "most", "least", "compare")
COMPOSITION_INTENT = ("share", "composition", "distribution", "breakdown",
                      "proportion", "percentage of", "split")


def _numeric_cols(df):
    return [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]


def _looks_temporal(colname, series):
    n = colname.lower()
    if any(tok in n for tok in TEMPORAL_TOKENS):
        return True
    # Values like '2026-01' or '2026-01-15'.
    try:
        sample = str(series.iloc[0])
        return bool(re.match(r"^\d{4}-\d{2}", sample))
    except Exception:
        return False


def select_chart_type(df, question):
    """Deterministically choose a chart type from data shape + question intent.

    Returns one of: 'line', 'bar', 'pie', 'scatter', or None (table only).
    No LLM involved; purely a function of the verified dataframe and the text.
    """
    if df is None or len(df) < 2:
        return None  # a single value is not a chart

    q = (question or "").lower()
    num_cols = _numeric_cols(df)
    non_num = [c for c in df.columns if c not in num_cols]

    # Need at least one numeric series to plot.
    if not num_cols:
        return None

    # Two numeric columns and correlation-style intent -> scatter.
    if len(num_cols) >= 2 and ("correlation" in q or "relationship" in q or "vs" in q):
        return "scatter"

    # Temporal x-axis (by column name/values or intent) -> line.
    label_col = non_num[0] if non_num else df.columns[0]
    if _looks_temporal(label_col, df[label_col]) or any(t in q for t in TEMPORAL_INTENT):
        return "line"

    # Composition intent with a small number of categories -> pie.
    if any(t in q for t in COMPOSITION_INTENT) and 2 <= len(df) <= 8 and len(num_cols) == 1:
        return "pie"

    # Ranking / category comparison -> bar.
    if non_num and (any(t in q for t in RANKING_INTENT) or len(df) <= 15):
        return "bar"

    return None


def _insight_lines(df, label_col, value_col):
    """Deterministic high/low summary of a numeric series (exact values)."""
    try:
        top = df.loc[df[value_col].idxmax()]
        bottom = df.loc[df[value_col].idxmin()]
        money = is_money_col(value_col)
        def fmt(v):
            if money:
                return f"AED {int(v):,}" if float(v) == int(v) else f"AED {v:,.2f}"
            return f"{int(v):,}" if float(v) == int(v) else f"{v:,}"
        st.markdown(
            f"- **Highest:** {top[label_col]} — {fmt(top[value_col])}\n"
            f"- **Lowest:** {bottom[label_col]} — {fmt(bottom[value_col])}"
        )
    except Exception:
        pass


def render_chart(df, question, chart_type):
    """Visualize the VERIFIED dataframe. The chart is a view of the data the
    agent already computed -- never re-queried or LLM-generated."""
    num_cols = _numeric_cols(df)
    non_num = [c for c in df.columns if c not in num_cols]
    label_col = non_num[0] if non_num else df.columns[0]
    value_col = num_cols[0]

    st.markdown(f"### {answer_heading(question)}")

    plot_df = df[[label_col, value_col]].copy()
    y_title = prettify_col(value_col)
    x_title = prettify_col(label_col)

    try:
        import altair as alt

        # Y scale fitted to the data and never negative (revenue-friendly).
        y_min = min(0, float(plot_df[value_col].min()))
        y_scale = alt.Scale(domainMin=y_min)

        if chart_type == "line":
            chart = (
                alt.Chart(plot_df)
                .mark_line(point=True)
                .encode(
                    x=alt.X(label_col, sort=None, title=x_title),
                    y=alt.Y(value_col, title=y_title, scale=y_scale),
                )
            )
            st.altair_chart(chart, use_container_width=True)
        elif chart_type == "bar":
            chart = (
                alt.Chart(plot_df)
                .mark_bar()
                .encode(
                    x=alt.X(label_col, sort="-y", title=x_title),
                    y=alt.Y(value_col, title=y_title, scale=y_scale),
                )
            )
            st.altair_chart(chart, use_container_width=True)
        elif chart_type == "scatter":
            chart = (
                alt.Chart(df)
                .mark_circle(size=80)
                .encode(x=num_cols[0], y=num_cols[1])
            )
            st.altair_chart(chart, use_container_width=True)
        elif chart_type == "pie":
            chart = (
                alt.Chart(df)
                .mark_arc()
                .encode(theta=alt.Theta(value_col, type="quantitative"),
                        color=alt.Color(label_col, type="nominal"))
            )
            st.altair_chart(chart, use_container_width=True)
    except Exception:
        # Fallback to native charts if Altair is unavailable.
        indexed = plot_df.set_index(label_col)
        if chart_type == "bar":
            st.bar_chart(indexed)
        else:
            st.line_chart(indexed)

    # Deterministic high/low insight beneath the chart.
    if chart_type in ("line", "bar", "pie"):
        _insight_lines(df, label_col, value_col)


def answer_heading(question):
    q = question.lower()
    is_revenue = "revenue" in q or "sales" in q
    if any(t in q for t in ("month", "monthly", "over time", "trend")):
        return "Monthly Sales Revenue" if is_revenue else "Monthly Trend"
    if "top" in q and "product" in q:
        return "Top Products by Revenue"
    if "revenue" in q and ("corporate" in q or "retail" in q or "segment" in q):
        return "Revenue by Customer Segment"
    if "branch" in q or "store" in q:
        return "Branch Performance"
    if "category" in q:
        return "Revenue by Category"
    return "Answer"


def render_workflow(workflow):
    st.markdown("**Agent Execution Workflow**")
    for step in workflow:
        st.markdown(f"<div class='workflow-step'><span class='ok'>✓</span> {step}</div>",
                    unsafe_allow_html=True)


def metric_card(label, value):
    st.markdown(
        f"<div class='metric-card'><div class='label'>{label}</div>"
        f"<div class='value'>{value}</div></div>",
        unsafe_allow_html=True,
    )


# --- response rendering ----------------------------------------------------- #
def render_response(question, resp, schema_label):
    if not resp.get("success"):
        st.markdown("<div class='unverified-banner'><span class='title'>Could not "
                    "answer reliably</span></div>", unsafe_allow_html=True)
        st.error(resp.get("error") or resp.get("reason") or "Unknown error.")
        return

    is_complex = resp.get("query_type") == "complex"
    verified = resp.get("verified")

    # Verified banner.
    if verified:
        st.markdown(
            "<div class='verified-banner'><span class='title'>✓ Verified Answer</span>"
            "<br><span class='sub'>The result was checked against the question.</span></div>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f"<div class='unverified-banner'><span class='title'>Answer (not fully "
            f"verified)</span><br><span class='sub'>{resp.get('reason')}</span></div>",
            unsafe_allow_html=True,
        )

    left, right = st.columns([2, 1])

    with left:
        df = resp.get("chart_data")
        chart_type = None if is_complex else select_chart_type(df, question)

        if is_complex:
            # Complex: highlight the answer + business explanation.
            st.markdown(f"### {resp.get('answer').split(' had ')[0] if ' had ' in str(resp.get('answer')) else 'Result'}")
            st.write(resp.get("answer"))
        elif chart_type:
            # Auto-visualize the verified dataframe; keep the table below.
            render_chart(df, question, chart_type)
            with st.expander("View exact data"):
                render_table(df)
        elif df is not None and len(df) > 0 and not (df.shape == (1, 1)):
            st.markdown(f"### {answer_heading(question)}")
            render_table(df)
        else:
            # Single scalar / short answer.
            st.markdown("### Result")
            st.write(resp.get("answer"))

    with right:
        render_workflow(resp.get("workflow", []))
        qt = "Complex Query" if is_complex else "Simple Query"
        st.markdown(f"<div class='trust-pill'>Query type: {qt}</div>", unsafe_allow_html=True)

    # Metric cards.
    st.write("")
    cards = [
        ("Database", schema_label.replace(" Database", "")),
        ("Query Type", "Complex" if is_complex else "Simple"),
        ("Steps", resp.get("steps", 1)),
        ("Attempts", resp.get("attempts", 1)),
        ("Self-Corrections", resp.get("self_corrections", 0)),
        ("Execution Time", f"{resp.get('response_time_s', 0)}s"),
    ]
    cols = st.columns(len(cards))
    for c, (label, value) in zip(cols, cards):
        with c:
            metric_card(label, value)

    # Trust pills.
    st.write("")
    st.markdown(
        "<span class='trust-pill'>🔒 Read-only</span>"
        + ("<span class='trust-pill'>✓ Results verified</span>" if verified else ""),
        unsafe_allow_html=True,
    )

    # Evidence (collapsible).
    if is_complex and resp.get("intermediate_frames"):
        with st.expander("Query Plan (sub-queries + deterministic analysis)"):
            st.write(f"This complex question was decomposed into {resp.get('steps')} "
                     "sub-queries; the final answer was computed deterministically "
                     "from the verified data (no LLM rewriting).")
            for name, frame in resp["intermediate_frames"].items():
                st.markdown(f"**Sub-query: {name}**")
                st.dataframe(frame.head(20), use_container_width=True, hide_index=True)

    if resp.get("sql_query"):
        with st.expander("SQL Executed (evidence)"):
            st.code(resp["sql_query"], language="sql")

    df = resp.get("chart_data")
    if df is not None and len(df) > 0:
        with st.expander("Result Data"):
            st.dataframe(df, use_container_width=True, hide_index=True)


# --- gap analysis (Iteration 8) --------------------------------------------- #
def get_gap_analyzer(schema_label):
    cfg = SCHEMAS[schema_label]
    ensure_database(cfg["builder"], cfg["db"])
    from src.schema_tools import make_engine

    return GapAnalyzer(make_engine(cfg["db"]), schema_id=cfg["schema_id"])


def render_gap_report(report):
    bg, border, fg = STATUS_STYLE.get(report.status, STATUS_STYLE[UNCERTAIN])
    st.markdown(
        f"<div style='background:{bg};border:1px solid {border};border-radius:10px;"
        f"padding:14px 16px;margin-bottom:14px;'>"
        f"<span style='font-weight:700;color:{fg};font-size:1.05rem;'>"
        f"{report.capability}</span><br>"
        f"<span style='font-weight:700;color:{fg};'>Status: {report.status}</span>"
        f"</div>",
        unsafe_allow_html=True,
    )

    left, right = st.columns(2)
    with left:
        st.markdown("**Available information**")
        if report.available:
            for a in report.available:
                ev = ", ".join(a["evidence"][:4])
                st.markdown(f"<div class='cap-row'><span class='cap-dot'>✓</span> "
                            f"{a['name']}</div>", unsafe_allow_html=True)
                if ev:
                    st.caption(f"evidence: {ev}")
        else:
            st.caption("None of the required concepts were found.")
    with right:
        st.markdown("**Missing / insufficient**")
        if report.missing:
            for m in report.missing:
                st.markdown(f"<div class='cap-row'><span style='color:#dc2626;"
                            f"font-weight:700;'>✗</span> {m['name']}</div>",
                            unsafe_allow_html=True)
        else:
            st.caption("Nothing essential is missing.")

    st.markdown(f"**Evidence:** {report.evidence_summary}")
    if report.business_impact:
        st.markdown(f"**Business impact:** {report.business_impact}")
    if report.recommendation:
        st.markdown(f"**Recommendation:** {report.recommendation}")

    st.write("")
    st.markdown(
        f"<span class='trust-pill'>Confidence: {report.confidence}</span>"
        f"<span class='trust-pill'>🔒 Read-only (analysis only)</span>",
        unsafe_allow_html=True,
    )

    with st.expander("Schema evidence (facts)"):
        for f in report.facts:
            st.markdown(f"- {f}")


def process_gap(capability):
    with st.spinner("Inspecting schema, comparing required vs available data..."):
        analyzer = get_gap_analyzer(st.session_state.schema_label)
        report = analyzer.analyze(capability)
        st.session_state.gap_history.append((capability, report, st.session_state.schema_label))


# --- app -------------------------------------------------------------------- #
def process_question(question):
    with st.spinner("Analyzing, planning, generating SQL, verifying result..."):
        resp = st.session_state.agent.query(question)
        st.session_state.chat_history.append(
            (question, resp, st.session_state.schema_label)
        )


def main():
    inject_css()

    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []
    if "gap_history" not in st.session_state:
        st.session_state.gap_history = []
    if "agent" not in st.session_state:
        st.session_state.agent = None
    if "schema_label" not in st.session_state:
        st.session_state.schema_label = None

    api_key = resolve_api_key()
    if api_key:
        os.environ["OPENAI_API_KEY"] = api_key

    # ---- sidebar ----------------------------------------------------------- #
    with st.sidebar:
        st.markdown("### ✦ AI Data Analyst")

        st.markdown("**DATABASE**")
        schema_label = st.selectbox("Database", list(SCHEMAS.keys()),
                                    label_visibility="collapsed")

        # (Re)build the agent when the schema changes.
        if st.session_state.schema_label != schema_label:
            try:
                st.session_state.agent = get_agent(schema_label)
                st.session_state.schema_label = schema_label
            except Exception as e:
                st.session_state.agent = None
                st.error(f"Could not initialize agent: {e}")

        ready = st.session_state.agent is not None
        st.markdown("**AGENT STATUS**")
        st.markdown(
            f"<span class='status-dot'>●</span> {'Agent Ready' if ready else 'Not ready'}",
            unsafe_allow_html=True,
        )

        st.divider()
        st.markdown("**CAPABILITIES**")
        for cap in CAPABILITIES:
            st.markdown(f"<div class='cap-row'><span class='cap-dot'>✓</span> {cap}</div>",
                        unsafe_allow_html=True)

        st.divider()
        st.markdown("**TRUST & SAFETY**")
        st.markdown("<div class='cap-row'>🔒 Read-only mode</div>", unsafe_allow_html=True)
        st.markdown("<div class='cap-row'><span class='cap-dot'>✓</span> Results verified</div>",
                    unsafe_allow_html=True)

        st.divider()
        with st.expander("Technical Details"):
            if not api_key:
                st.warning("No API key found. Set OPENAI_API_KEY in the environment "
                           "or Streamlit secrets to run queries.")
            if ready:
                st.text(st.session_state.agent.get_table_info())

    # ---- header ------------------------------------------------------------ #
    st.title("AI Data Analyst Agent")
    st.caption("Ask business questions in plain language. Get verified, "
               "evidence-backed answers from your business database.")
    st.markdown(
        f"<span class='trust-pill'>{schema_label}</span>"
        f"<span class='trust-pill'><span class='status-dot'>●</span> Agent Ready</span>",
        unsafe_allow_html=True,
    )

    tab_ask, tab_history = st.tabs(["Ask", "History"])

    with tab_ask:
        if st.session_state.agent is None:
            st.info("Select a database in the sidebar to begin.")
            return

        mode = st.radio("Mode", ["Data Analysis", "Gap Analysis"],
                        horizontal=True, label_visibility="collapsed",
                        key="mode")

        if mode == "Data Analysis":
            st.markdown("#### Try a sample question")
            cols = st.columns(len(SAMPLE_QUESTIONS))
            for i, item in enumerate(SAMPLE_QUESTIONS):
                with cols[i]:
                    if st.button(item["q"], key=f"sample_{i}"):
                        process_question(item["q"])
                    if item["complex"]:
                        st.markdown("<span class='badge-complex'>COMPLEX QUERY</span>",
                                    unsafe_allow_html=True)

            st.markdown("#### Ask your own question")
            user_q = st.text_input("Question", key="user_input",
                                   label_visibility="collapsed",
                                   placeholder="e.g. What are the top 3 products by revenue?")
            # Non-blocking hint: never reroutes, just suggests the other mode.
            if user_q and looks_like_capability_question(user_q):
                st.info("This looks like a business capability question. "
                        "Consider switching to **Gap Analysis** for a schema-grounded "
                        "capability assessment.")
            if st.button("Analyze", type="primary") and user_q:
                process_question(user_q)

            if st.session_state.chat_history:
                st.divider()
                question, resp, schema = st.session_state.chat_history[-1]
                render_response(question, resp, schema)

        else:  # Gap Analysis (Iteration 8)
            st.caption("Ask whether this database can support a business capability. "
                       "The agent inspects the actual schema and reports what is "
                       "available, what is missing, and what to add — read-only.")
            st.markdown("#### Try a capability question")
            gcols = st.columns(len(GAP_EXAMPLES))
            for i, gq in enumerate(GAP_EXAMPLES):
                with gcols[i]:
                    if st.button(gq, key=f"gap_{i}"):
                        process_gap(gq)

            st.markdown("#### Ask your own capability question")
            gap_q = st.text_input("Capability", key="gap_input",
                                  label_visibility="collapsed",
                                  placeholder="e.g. Can we measure customer lifetime value?")
            if st.button("Analyze Capability", type="primary") and gap_q:
                process_gap(gap_q)

            if st.session_state.gap_history:
                st.divider()
                capability, report, schema = st.session_state.gap_history[-1]
                render_gap_report(report)

    with tab_history:
        if not st.session_state.chat_history:
            st.info("No questions asked yet.")
        else:
            if st.button("Clear history"):
                st.session_state.chat_history = []
                st.rerun()
            for i, (question, resp, schema) in enumerate(reversed(st.session_state.chat_history)):
                label = question[:60] + ("..." if len(question) > 60 else "")
                with st.expander(f"#{len(st.session_state.chat_history) - i}: {label}"):
                    render_response(question, resp, schema)


if __name__ == "__main__":
    main()
