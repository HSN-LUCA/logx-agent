"""Streamlit UI for the AI Data Analyst Agent for Business Databases.

Wraps the schema-agnostic AnalystAgent. The UI surfaces the features that make
this more than a text-to-SQL chatbot: the schema it discovered, whether the
result was verified, how many self-corrections it took, the SQL it ran, and the
result data as evidence.
"""

import os

import streamlit as st

from src.analyst_agent import AnalystAgent
from paths import ERP_DB, POS_DB

# Available demo schemas -> (database path, business-context id, builder module).
SCHEMAS = {
    "ERP (invoices / branches / customers)": {
        "db": ERP_DB,
        "schema_id": "erp",
        "builder": "data.erp_database",
    },
    "POS (receipts / outlets / shoppers)": {
        "db": POS_DB,
        "schema_id": "pos",
        "builder": "data.pos_database",
    },
}

SAMPLE_QUESTIONS = [
    "What was the total sales revenue in July 2026?",
    "What are the top 3 products by total revenue?",
    "Which branch had the highest revenue growth from June to July 2026?",
    "How much revenue came from Corporate versus Retail customers?",
    "Which product had declining sales for three months while stock rose?",
]

st.set_page_config(page_title="AI Data Analyst Agent", page_icon="📊", layout="wide")

# ---- session state ---------------------------------------------------------- #
if "agent" not in st.session_state:
    st.session_state.agent = None
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []


def ensure_database(builder_module, db_path):
    """Build the demo database if it does not exist yet."""
    if os.path.exists(db_path):
        return
    import importlib

    mod = importlib.import_module(builder_module)
    # Both builders expose create_<name>_database().
    for fn_name in ("create_erp_database", "create_pos_database"):
        if hasattr(mod, fn_name):
            getattr(mod, fn_name)()
            return


def build_agent(schema_choice, flags):
    cfg = SCHEMAS[schema_choice]
    ensure_database(cfg["builder"], cfg["db"])
    return AnalystAgent(db_uri=cfg["db"], schema_id=cfg["schema_id"], **flags)


def render_response(question, resp):
    """Render one agent response with its verification evidence."""
    if resp.get("success"):
        if resp.get("verified"):
            st.success("Verified — the result was checked against the question.")
        else:
            st.warning(f"Not fully verified: {resp.get('reason')}")

        st.markdown(f"**Q:** {question}")
        st.markdown(f"**A:** {resp.get('answer')}")

        cols = st.columns(3)
        cols[0].metric("Verified", "Yes" if resp.get("verified") else "No")
        cols[1].metric("Attempts", resp.get("attempts", 1))
        cols[2].metric("Self-corrections", resp.get("self_corrections", 0))

        if resp.get("sql_query"):
            with st.expander("SQL executed (evidence)", expanded=False):
                st.code(resp["sql_query"], language="sql")
        df = resp.get("chart_data")
        if df is not None and len(df) > 0:
            with st.expander("Result data", expanded=False):
                st.dataframe(df, use_container_width=True)
    else:
        st.error(f"**Q:** {question}")
        st.error(resp.get("answer") or resp.get("error") or "Failed to answer.")


def process_question(question):
    with st.spinner("Analyzing, generating SQL, verifying result..."):
        resp = st.session_state.agent.query(question)
        st.session_state.chat_history.append((question, resp))


def main():
    col1, col2 = st.columns([1, 5])
    with col1:
        if os.path.exists("logo.png"):
            st.image("logo.png", width=90)
        else:
            st.write("📊")
    with col2:
        st.title("AI Data Analyst Agent")
        st.caption("Ask business questions in plain language. The agent discovers "
                   "the schema, writes SQL, verifies the result, and shows its evidence.")

    tab_chat, tab_history = st.tabs(["Ask", "History"])

    with st.sidebar:
        st.header("Configuration")

        schema_choice = st.selectbox("Database", list(SCHEMAS.keys()))

        # Resolve a default key from env (.env locally) or Streamlit secrets
        # (Streamlit Community Cloud). The user can still override it here.
        default_key = os.getenv("OPENAI_API_KEY", "")
        if not default_key:
            try:
                default_key = st.secrets.get("OPENAI_API_KEY", "")
            except Exception:
                default_key = ""

        api_key = st.text_input(
            "OpenAI API Key", type="password",
            value=default_key,
            help="Needed for SQL generation, verification and analysis. "
                 "On Streamlit Cloud, set it in the app's Secrets instead.",
        )
        if api_key:
            os.environ["OPENAI_API_KEY"] = api_key

        st.subheader("Agent capabilities")
        use_schema_context = st.checkbox("Schema discovery + business context", value=True)
        use_validation = st.checkbox("Read-only SQL validation", value=True)
        use_verification = st.checkbox("Result verification", value=True)
        use_self_correction = st.checkbox("Self-correction", value=True)
        use_business_analysis = st.checkbox("Business-analysis output", value=True)

        flags = dict(
            use_schema_context=use_schema_context,
            use_validation=use_validation,
            use_verification=use_verification,
            use_self_correction=use_self_correction,
            use_business_analysis=use_business_analysis,
        )

        if st.button("Initialize / Update Agent"):
            if not api_key:
                st.warning("Enter an API key to run queries (schema preview works without one).")
            try:
                st.session_state.agent = build_agent(schema_choice, flags)
                st.success("Agent ready.")
            except Exception as e:
                st.error(f"Could not initialize agent: {e}")

        if st.session_state.agent is not None:
            with st.expander("Discovered schema"):
                st.text(st.session_state.agent.get_table_info())

    with tab_chat:
        if st.session_state.agent is None:
            st.info("Choose a database and click 'Initialize / Update Agent' in the sidebar.")
        else:
            st.subheader("Sample questions")
            cols = st.columns(len(SAMPLE_QUESTIONS))
            for i, q in enumerate(SAMPLE_QUESTIONS):
                if cols[i].button(q, key=f"sample_{i}"):
                    process_question(q)

            st.subheader("Ask your own question")
            user_q = st.text_input("Type a question about the data", key="user_input")
            if st.button("Ask", type="primary") and user_q:
                process_question(user_q)

            if st.session_state.chat_history:
                st.divider()
                question, resp = st.session_state.chat_history[-1]
                render_response(question, resp)

    with tab_history:
        if not st.session_state.chat_history:
            st.info("No questions asked yet.")
        else:
            st.subheader(f"History ({len(st.session_state.chat_history)})")
            if st.button("Clear history"):
                st.session_state.chat_history = []
                st.rerun()
            for i, (question, resp) in enumerate(reversed(st.session_state.chat_history)):
                label = question[:60] + ("..." if len(question) > 60 else "")
                with st.expander(f"#{len(st.session_state.chat_history) - i}: {label}"):
                    render_response(question, resp)


if __name__ == "__main__":
    main()
