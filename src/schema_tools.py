"""Schema discovery for arbitrary relational databases (no LLM required).

This is the foundation for the agent's ability to adapt to different schemas.
Given any SQLAlchemy engine, it introspects tables, columns, primary keys and
foreign-key relationships, and renders a compact, model-friendly summary plus a
few sample rows per table.

Because it relies only on SQLAlchemy reflection, the same code works across
SQLite, PostgreSQL, MySQL and SQL Server -- which is what lets one agent operate
over ERP, POS or CRM schemas without hard-coded table names.
"""

from sqlalchemy import create_engine, inspect, text


def make_engine(db_uri):
    """Create a SQLAlchemy engine from a URI or a bare SQLite file path."""
    if "://" not in db_uri:
        db_uri = f"sqlite:///{db_uri}"
    return create_engine(db_uri)


def discover_schema(engine, sample_rows=2):
    """Introspect the database and return a structured schema description.

    Returns a dict:
      {
        "tables": {
            table_name: {
                "columns": [{"name", "type"}],
                "primary_key": [col, ...],
                "foreign_keys": [{"column", "ref_table", "ref_column"}],
                "sample_rows": [ {col: value, ...}, ... ],
            }, ...
        }
      }
    """
    inspector = inspect(engine)
    tables = {}

    for table_name in sorted(inspector.get_table_names()):
        columns = [
            {"name": c["name"], "type": str(c["type"])}
            for c in inspector.get_columns(table_name)
        ]
        pk = inspector.get_pk_constraint(table_name).get("constrained_columns", []) or []
        fks = []
        for fk in inspector.get_foreign_keys(table_name):
            ref_table = fk.get("referred_table")
            local_cols = fk.get("constrained_columns", []) or []
            ref_cols = fk.get("referred_columns", []) or []
            for lc, rc in zip(local_cols, ref_cols):
                fks.append({"column": lc, "ref_table": ref_table, "ref_column": rc})

        sample = []
        if sample_rows:
            try:
                with engine.connect() as conn:
                    rows = conn.execute(
                        text(f'SELECT * FROM "{table_name}" LIMIT {int(sample_rows)}')
                    ).mappings().all()
                    sample = [dict(r) for r in rows]
            except Exception:
                sample = []

        tables[table_name] = {
            "columns": columns,
            "primary_key": pk,
            "foreign_keys": fks,
            "sample_rows": sample,
        }

    return {"tables": tables}


def render_schema_summary(schema, include_samples=True):
    """Render the discovered schema as compact text for a prompt."""
    lines = []
    for table, info in schema["tables"].items():
        col_str = ", ".join(f'{c["name"]} ({c["type"]})' for c in info["columns"])
        lines.append(f"TABLE {table}: {col_str}")
        if info["primary_key"]:
            lines.append(f"  PK: {', '.join(info['primary_key'])}")
        for fk in info["foreign_keys"]:
            lines.append(
                f"  FK: {fk['column']} -> {fk['ref_table']}.{fk['ref_column']}"
            )
        if include_samples and info["sample_rows"]:
            first = info["sample_rows"][0]
            preview = ", ".join(f"{k}={v}" for k, v in list(first.items())[:6])
            lines.append(f"  sample: {preview}")
    return "\n".join(lines)


def relationship_edges(schema):
    """Return FK relationships as (from_table, to_table) edges (for planning)."""
    edges = []
    for table, info in schema["tables"].items():
        for fk in info["foreign_keys"]:
            edges.append((table, fk["ref_table"]))
    return edges


if __name__ == "__main__":
    import sys
    from paths import ERP_DB

    target = sys.argv[1] if len(sys.argv) > 1 else ERP_DB
    eng = make_engine(target)
    sch = discover_schema(eng)
    print(render_schema_summary(sch))
    print("\nRelationship edges:")
    for a, b in relationship_edges(sch):
        print(f"  {a} -> {b}")
