"""POS mapping of the SAME business questions as eval_questions.py.

Same question text, same ids, same check types -- but the reference SQL is
written against the POS schema (sales_receipts / basket_items / outlets /
shoppers / items / inventory_snapshots). This is what proves generalization:
the agent is asked identical business questions and must adapt to a different
schema to answer them.

Q07 uses "in 2026" -> all POS sales are in 2026, matching the ERP intent.
"""

from paths import POS_DB as DB_PATH

EVAL_CASES = [
    {
        "id": "Q01",
        "category": "simple",
        "question": "How many customers do we have?",
        "reference_sql": "SELECT COUNT(*) AS n FROM shoppers;",
        "check": "scalar",
    },
    {
        "id": "Q02",
        "category": "simple",
        "question": "What was the total sales revenue in July 2026?",
        "reference_sql": (
            "SELECT ROUND(SUM(bi.amount), 2) AS revenue "
            "FROM basket_items bi JOIN sales_receipts r ON r.receipt_id = bi.receipt_id "
            "WHERE strftime('%Y-%m', r.sold_at) = '2026-07';"
        ),
        "check": "scalar",
    },
    {
        "id": "Q03",
        "category": "aggregation",
        "question": "What is the total sales revenue across all time?",
        "reference_sql": "SELECT ROUND(SUM(amount), 2) AS revenue FROM basket_items;",
        "check": "scalar",
    },
    {
        "id": "Q04",
        "category": "aggregation",
        "question": "What is the average invoice value (total amount per invoice)?",
        "reference_sql": (
            "SELECT ROUND(AVG(rec_total), 2) AS avg_receipt FROM ("
            "  SELECT receipt_id, SUM(amount) AS rec_total "
            "  FROM basket_items GROUP BY receipt_id"
            ");"
        ),
        "check": "scalar",
    },
    {
        "id": "Q05",
        "category": "ranking",
        "question": "What are the top 3 products by total revenue, all time?",
        "reference_sql": (
            "SELECT it.title, ROUND(SUM(bi.amount), 2) AS revenue "
            "FROM basket_items bi JOIN items it ON it.item_id = bi.item_id "
            "GROUP BY it.title ORDER BY revenue DESC LIMIT 3;"
        ),
        "check": "ordered_labels",
    },
    {
        "id": "Q06",
        "category": "ranking",
        "question": "Which product category generated the most revenue overall?",
        "reference_sql": (
            "SELECT it.dept, ROUND(SUM(bi.amount), 2) AS revenue "
            "FROM basket_items bi JOIN items it ON it.item_id = bi.item_id "
            "GROUP BY it.dept ORDER BY revenue DESC LIMIT 1;"
        ),
        "check": "top_label",
    },
    {
        "id": "Q07",
        "category": "multi_table",
        "question": "Which branch had the highest total revenue in 2026?",
        "reference_sql": (
            "SELECT o.store_name, ROUND(SUM(bi.amount), 2) AS revenue "
            "FROM basket_items bi "
            "JOIN sales_receipts r ON r.receipt_id = bi.receipt_id "
            "JOIN outlets o ON o.outlet_id = r.outlet_id "
            "GROUP BY o.store_name ORDER BY revenue DESC LIMIT 1;"
        ),
        "check": "top_label",
    },
    {
        "id": "Q08",
        "category": "multi_table",
        "question": "How much revenue came from Corporate customers versus Retail customers?",
        # member_type: Business == Corporate, Consumer == Retail.
        "reference_sql": (
            "SELECT CASE s.member_type WHEN 'Business' THEN 'Corporate' "
            "  WHEN 'Consumer' THEN 'Retail' ELSE s.member_type END AS segment, "
            "  ROUND(SUM(bi.amount), 2) AS revenue "
            "FROM basket_items bi "
            "JOIN sales_receipts r ON r.receipt_id = bi.receipt_id "
            "JOIN shoppers s ON s.shopper_id = r.shopper_id "
            "GROUP BY segment ORDER BY revenue DESC;"
        ),
        "check": "label_value_pairs",
    },
    {
        "id": "Q09",
        "category": "multi_table",
        "question": "Which customers bought products in the Displays category?",
        "reference_sql": (
            "SELECT DISTINCT s.shopper_name "
            "FROM basket_items bi "
            "JOIN sales_receipts r ON r.receipt_id = bi.receipt_id "
            "JOIN shoppers s ON s.shopper_id = r.shopper_id "
            "JOIN items it ON it.item_id = bi.item_id "
            "WHERE it.dept = 'Displays' ORDER BY s.shopper_name;"
        ),
        "check": "label_set",
    },
    {
        "id": "Q10",
        "category": "comparison",
        "question": "How did total revenue in July 2026 compare with June 2026? Give the percentage change.",
        "reference_sql": (
            "WITH m AS ("
            "  SELECT strftime('%Y-%m', r.sold_at) AS mon, SUM(bi.amount) AS rev "
            "  FROM basket_items bi JOIN sales_receipts r ON r.receipt_id = bi.receipt_id "
            "  WHERE strftime('%Y-%m', r.sold_at) IN ('2026-06','2026-07') "
            "  GROUP BY mon) "
            "SELECT ROUND("
            "  (MAX(CASE WHEN mon='2026-07' THEN rev END) - MAX(CASE WHEN mon='2026-06' THEN rev END)) "
            "  * 100.0 / MAX(CASE WHEN mon='2026-06' THEN rev END), 1) AS pct_change "
            "FROM m;"
        ),
        "check": "scalar_pct",
    },
    {
        "id": "Q11",
        "category": "comparison",
        "question": "Which branch had the highest revenue growth from June 2026 to July 2026?",
        "reference_sql": (
            "WITH b AS ("
            "  SELECT o.store_name, strftime('%Y-%m', r.sold_at) AS mon, "
            "         SUM(bi.amount) AS rev "
            "  FROM basket_items bi "
            "  JOIN sales_receipts r ON r.receipt_id = bi.receipt_id "
            "  JOIN outlets o ON o.outlet_id = r.outlet_id "
            "  WHERE strftime('%Y-%m', r.sold_at) IN ('2026-06','2026-07') "
            "  GROUP BY o.store_name, mon) "
            "SELECT store_name, ROUND("
            "  SUM(CASE WHEN mon='2026-07' THEN rev ELSE 0 END) - "
            "  SUM(CASE WHEN mon='2026-06' THEN rev ELSE 0 END), 2) AS growth "
            "FROM b GROUP BY store_name ORDER BY growth DESC LIMIT 1;"
        ),
        "check": "top_label",
    },
    {
        "id": "Q12",
        "category": "challenge",
        "question": (
            "Which product had declining unit sales for three consecutive months "
            "while its stock on hand was increasing?"
        ),
        "reference_sql": "SELECT 'Docking Station' AS title;",
        "check": "top_label",
        "note": (
            "Same engineered case as ERP. Docking Station units fall Apr->May->Jun->Jul "
            "(70,55,38,25) while inventory_snapshots.qty_available rises (150,170,190,210)."
        ),
    },
]
