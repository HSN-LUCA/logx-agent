import os
import datetime
from datetime import timedelta

import pandas as pd
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_experimental.sql import SQLDatabaseChain
from langchain.sql_database import SQLDatabase
from sqlalchemy import create_engine, text

load_dotenv()


class DatabaseAIAgent:
    """Natural-language-to-SQL agent over an ERP-style database.

    Baseline behaviour: a single LangChain SQLDatabaseChain on GPT-3.5-turbo
    converts a question to SQL, runs it, and returns the answer plus the
    generated SQL and (when possible) a dataframe for charting.
    """

    def __init__(self, db_path="business.db", use_sql_server=False):
        if use_sql_server:
            server = os.getenv("DB_SERVER")
            database = os.getenv("DB_DATABASE")
            username = os.getenv("DB_USERNAME")
            password = os.getenv("DB_PASSWORD")
            driver = os.getenv("DB_DRIVER", "ODBC Driver 17 for SQL Server")
            connection_string = (
                f"mssql+pyodbc://{username}:{password}@{server}/{database}"
                f"?driver={driver}&TrustServerCertificate=yes"
            )
            self.engine = create_engine(connection_string)
        else:
            self.engine = create_engine(f"sqlite:///{db_path}")

        self.db = SQLDatabase(self.engine)

        # Resolve API key from environment, falling back to Streamlit secrets.
        api_key = os.getenv("OPENAI_API_KEY")
        try:
            import streamlit as st

            try:
                api_key = api_key or st.secrets.get("OPENAI_API_KEY", "")
            except Exception:
                pass
        except Exception:
            pass

        self.llm = ChatOpenAI(
            temperature=0,
            model="gpt-3.5-turbo",
            openai_api_key=api_key,
        )
        self.db_chain = SQLDatabaseChain.from_llm(
            llm=self.llm,
            db=self.db,
            verbose=True,
            return_intermediate_steps=True,
        )

    def query(self, question):
        """Process a natural-language question and return a structured result."""
        try:
            result = self.db_chain(question)

            intermediate = result.get("intermediate_steps") or []
            sql_query = intermediate[0] if intermediate else None

            chart_data = None
            if sql_query:
                try:
                    chart_data = pd.read_sql(str(sql_query), self.engine)
                except Exception:
                    chart_data = None

            return {
                "success": True,
                "answer": result.get("result"),
                "sql_query": sql_query,
                "chart_data": chart_data,
                "has_chart": chart_data is not None and len(chart_data) > 0,
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "answer": "Sorry, I couldn't process your question. Please try rephrasing it.",
                "sql_query": None,
                "chart_data": None,
                "has_chart": False,
            }

    def get_table_info(self):
        """Return the database schema information."""
        return self.db.get_table_info()
