"""Business context for target databases.

Schema discovery tells the agent WHAT columns exist. Business context tells it
what they MEAN in business terms (what "revenue" is, what a "month" looks like,
which segments exist). Keeping this separate from the code means a new schema is
onboarded by adding a context entry, not by editing the agent.

Each entry is optional guidance. The agent still works without it, but accuracy
on domain-specific questions improves when it is present.
"""

# Keyed by a short schema id. The agent looks up context by the id it is given;
# if none is found it proceeds with schema discovery alone.
BUSINESS_CONTEXT = {
    "erp": {
        "description": (
            "An ERP sales database. Invoices are issued to customers at branches. "
            "Each invoice has one or more invoice_lines, one per product sold."
        ),
        "glossary": [
            "revenue / sales = SUM(invoice_lines.line_total)",
            "an invoice's total value = SUM(line_total) for that invoice_id",
            "units sold = SUM(invoice_lines.quantity)",
            "a month is derived from invoices.invoice_date (format YYYY-MM-DD); "
            "group by strftime('%Y-%m', invoice_date)",
            "stock / inventory on hand = stock.units_on_hand, snapshot per "
            "product per month (stock.month is 'YYYY-MM')",
            "customer segment is customers.segment ('Corporate' or 'Retail')",
            "a branch is a physical location (branches.branch_name / city)",
        ],
        "notes": [
            "The data window is fixed to 2026-01 through 2026-08.",
            "Money values are in AED.",
            "Always answer read-only questions; never modify data.",
        ],
    },
    # Placeholder for the generalization schema (Iteration 6). Filled when
    # pos_database.py is added.
    "pos": {
        "description": (
            "A point-of-sale (POS) database. Each sale is a sales_receipts row at an "
            "outlet (store) for a shopper. Each receipt has one or more basket_items, "
            "one per product (item) sold."
        ),
        "glossary": [
            "revenue / sales = SUM(basket_items.amount)",
            "a receipt's total value = SUM(amount) for that receipt_id",
            "units sold = SUM(basket_items.units)",
            "a customer is a shopper (shoppers table); customer name = shopper_name",
            "a branch / store is an outlet (outlets.store_name)",
            "product name = items.title; product category = items.dept "
            "(the category is denormalized onto items; there is no category table)",
            "customer segment = shoppers.member_type, where 'Business' means "
            "Corporate and 'Consumer' means Retail",
            "a month is derived from sales_receipts.sold_at (a datetime like "
            "'2026-07-14 13:22:00'); group by strftime('%Y-%m', sold_at)",
            "stock / inventory on hand = inventory_snapshots.qty_available, "
            "a snapshot per item per month (inventory_snapshots.period is 'YYYY-MM')",
        ],
        "notes": [
            "The data window is fixed to 2026-01 through 2026-08.",
            "Money values are in AED.",
            "Same business questions as the ERP schema, different table/column names.",
            "Always answer read-only questions; never modify data.",
        ],
    },
}


def render_business_context(schema_id):
    """Render the business context for a schema id as prompt text (or empty)."""
    ctx = BUSINESS_CONTEXT.get(schema_id)
    if not ctx:
        return ""
    lines = [f"BUSINESS CONTEXT: {ctx['description']}"]
    if ctx.get("glossary"):
        lines.append("Definitions:")
        lines.extend(f"  - {g}" for g in ctx["glossary"])
    if ctx.get("notes"):
        lines.append("Notes:")
        lines.extend(f"  - {n}" for n in ctx["notes"])
    return "\n".join(lines)
