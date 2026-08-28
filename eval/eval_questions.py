"""Fixed evaluation set for the AI ERP Data Analyst Agent.

Each case has:
  id           stable identifier
  category     type of question (simple / aggregation / ranking / multi_table /
               comparison / challenge)
  question     the natural-language question given to the agent AND the baseline
  reference_sql a hand-written, verified SQL query that produces the ground truth
  expected     the ground-truth answer, expressed as the value(s) that a correct
               answer MUST contain. `check` describes how to compare.

The `reference_sql` is the source of truth: ground_truth.py runs it against erp.db
to produce the expected values, so the answers can never drift from the data.

`answer_key` gives the primary fact(s) the agent's natural-language answer must
contain to be counted correct (used for automated answer-accuracy scoring).
"""

# The same fixed database (erp.db, seed=42, window 2026-01..2026-08) is used for
# both the baseline and the final agent.
from paths import ERP_DB as DB_PATH

EVAL_CASES = [
    {
        "id": "Q01",
        "category": "simple",
        "question": "How many customers do we have?",
        "reference_sql": "SELECT COUNT(*) AS n FROM customers;",
        "check": "scalar",
    },
    {
        "id": "Q02",
        "category": "simple",
        "question": "What was the total sales revenue in July 2026?",
        "reference_sql": (
            "SELECT ROUND(SUM(il.line_total), 2) AS revenue "
            "FROM invoice_lines il JOIN invoices i ON i.invoice_id = il.invoice_id "
            "WHERE strftime('%Y-%m', i.invoice_date) = '2026-07';"
        ),
        "check": "scalar",
    },
    {
        "id": "Q03",
        "category": "aggregation",
        "question": "What is the total sales revenue across all time?",
        "reference_sql": "SELECT ROUND(SUM(line_total), 2) AS revenue FROM invoice_lines;",
        "check": "scalar",
    },
    {
        "id": "Q04",
        "category": "aggregation",
        "question": "What is the average invoice value (total amount per invoice)?",
        "reference_sql": (
            "SELECT ROUND(AVG(inv_total), 2) AS avg_invoice FROM ("
            "  SELECT invoice_id, SUM(line_total) AS inv_total "
            "  FROM invoice_lines GROUP BY invoice_id"
            ");"
        ),
        "check": "scalar",
    },
    {
        "id": "Q05",
        "category": "ranking",
        "question": "What are the top 3 products by total revenue, all time?",
        "reference_sql": (
            "SELECT p.product_name, ROUND(SUM(il.line_total), 2) AS revenue "
            "FROM invoice_lines il JOIN products p ON p.product_id = il.product_id "
            "GROUP BY p.product_name ORDER BY revenue DESC LIMIT 3;"
        ),
        "check": "ordered_labels",
    },
    {
        "id": "Q06",
        "category": "ranking",
        "question": "Which product category generated the most revenue overall?",
        "reference_sql": (
            "SELECT c.category_name, ROUND(SUM(il.line_total), 2) AS revenue "
            "FROM invoice_lines il "
            "JOIN products p ON p.product_id = il.product_id "
            "JOIN categories c ON c.category_id = p.category_id "
            "GROUP BY c.category_name ORDER BY revenue DESC LIMIT 1;"
        ),
        "check": "top_label",
    },
    {
        "id": "Q07",
        "category": "multi_table",
        "question": "Which branch had the highest total revenue in 2026?",
        "reference_sql": (
            "SELECT b.branch_name, ROUND(SUM(il.line_total), 2) AS revenue "
            "FROM invoice_lines il "
            "JOIN invoices i ON i.invoice_id = il.invoice_id "
            "JOIN branches b ON b.branch_id = i.branch_id "
            "GROUP BY b.branch_name ORDER BY revenue DESC LIMIT 1;"
        ),
        "check": "top_label",
    },
    {
        "id": "Q08",
        "category": "multi_table",
        "question": "How much revenue came from Corporate customers versus Retail customers?",
        "reference_sql": (
            "SELECT cu.segment, ROUND(SUM(il.line_total), 2) AS revenue "
            "FROM invoice_lines il "
            "JOIN invoices i ON i.invoice_id = il.invoice_id "
            "JOIN customers cu ON cu.customer_id = i.customer_id "
            "GROUP BY cu.segment ORDER BY revenue DESC;"
        ),
        "check": "label_value_pairs",
    },
    {
        "id": "Q09",
        "category": "multi_table",
        "question": "Which customers bought products in the Displays category?",
        "reference_sql": (
            "SELECT DISTINCT cu.customer_name "
            "FROM invoice_lines il "
            "JOIN invoices i ON i.invoice_id = il.invoice_id "
            "JOIN customers cu ON cu.customer_id = i.customer_id "
            "JOIN products p ON p.product_id = il.product_id "
            "JOIN categories c ON c.category_id = p.category_id "
            "WHERE c.category_name = 'Displays' ORDER BY cu.customer_name;"
        ),
        "check": "label_set",
    },
    {
        "id": "Q10",
        "category": "comparison",
        "question": "How did total revenue in July 2026 compare with June 2026? Give the percentage change.",
        "reference_sql": (
            "WITH m AS ("
            "  SELECT strftime('%Y-%m', i.invoice_date) AS mon, SUM(il.line_total) AS rev "
            "  FROM invoice_lines il JOIN invoices i ON i.invoice_id = il.invoice_id "
            "  WHERE strftime('%Y-%m', i.invoice_date) IN ('2026-06','2026-07') "
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
            "  SELECT br.branch_name, strftime('%Y-%m', i.invoice_date) AS mon, "
            "         SUM(il.line_total) AS rev "
            "  FROM invoice_lines il "
            "  JOIN invoices i ON i.invoice_id = il.invoice_id "
            "  JOIN branches br ON br.branch_id = i.branch_id "
            "  WHERE strftime('%Y-%m', i.invoice_date) IN ('2026-06','2026-07') "
            "  GROUP BY br.branch_name, mon) "
            "SELECT branch_name, ROUND("
            "  SUM(CASE WHEN mon='2026-07' THEN rev ELSE 0 END) - "
            "  SUM(CASE WHEN mon='2026-06' THEN rev ELSE 0 END), 2) AS growth "
            "FROM b GROUP BY branch_name ORDER BY growth DESC LIMIT 1;"
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
        "reference_sql": (
            # Documented answer: Docking Station (units Apr70 -> May55 -> Jun38 -> Jul25,
            # stock 150 -> 170 -> 190 -> 210). Returned directly for ground-truth clarity.
            "SELECT 'Docking Station' AS product_name;"
        ),
        "check": "top_label",
        "note": (
            "Engineered case. Docking Station unit sales fall for 3 consecutive "
            "months (Apr->May->Jun->Jul: 70,55,38,25) while monthly stock rises "
            "(150,170,190,210). This is the single correct answer."
        ),
    },
]
