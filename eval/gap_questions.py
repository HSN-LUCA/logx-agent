"""Separate evaluation set for Iteration 8 Gap & Capability Analysis.

This is completely independent of the 12-question Data Analysis evaluation and
does not touch it in any way.

Each case gives a business capability question and the EXPECTED status. The
expected status is grounded in the actual ERP and POS demo schemas (verified
against the discovered schema, not tuned to flatter the agent):

  ERP tables : branches, categories, customers, invoice_lines, invoices,
               products, stock
  POS tables : basket_items, inventory_snapshots, items, outlets,
               sales_receipts, shoppers

Reasoning for each expected status (same for both schemas, since both carry the
same business facts under different names):

  churn                -> PARTIALLY: customer identity + purchase history exist,
                          but there is no customer status/lifecycle or churn flag.
  inactive customers   -> PARTIALLY: identity + transaction dates exist (recency
                          can be inferred), but there is no explicit activity/
                          status field to mark a customer inactive.
  supplier delivery    -> NOT SUPPORTED: no supplier/vendor or delivery/PO data.
  customer lifetime val-> SUPPORTED: customer identity + linked revenue history
                          are present (CLV = sum of a customer's purchases).
  inventory turnover   -> SUPPORTED: stock levels + sales history are present.

For scoring we also record which required concepts are ESSENTIAL, so the
deterministic matcher's status can be checked against the expectation.
"""

# capability, expected_status, and the essential/optional concepts with keyword
# hints (so the eval is deterministic and independent of LLM concept phrasing).
GAP_CASES = [
    {
        "id": "G1",
        "capability": "Can the ERP measure customer churn?",
        "expected_status": "PARTIALLY SUPPORTED",
        "concepts": [
            {"name": "Customer identity", "keywords": ["customer", "shopper", "client"], "essential": True},
            {"name": "Customer status / lifecycle history", "keywords": ["status", "activity", "lifecycle", "state"], "essential": True},
            {"name": "Churn / cancellation flag", "keywords": ["churn", "cancelled", "inactive", "closed"], "essential": True},
        ],
    },
    {
        "id": "G2",
        "capability": "Can we identify customers who have become inactive?",
        "expected_status": "PARTIALLY SUPPORTED",
        "concepts": [
            {"name": "Customer identity", "keywords": ["customer", "shopper", "client"], "essential": True},
            {"name": "Transaction dates", "keywords": ["date", "sold_at", "invoice_date", "period"], "essential": True},
            {"name": "Explicit activity / status field", "keywords": ["status", "active", "inactive", "lastactive"], "essential": True},
        ],
    },
    {
        "id": "G3",
        "capability": "Can we measure supplier delivery performance?",
        "expected_status": "NOT SUPPORTED",
        "concepts": [
            {"name": "Supplier / vendor records", "keywords": ["supplier", "vendor"], "essential": True},
            {"name": "Delivery / purchase orders", "keywords": ["delivery", "purchase_order", "shipment", "receipt_date"], "essential": True},
        ],
    },
    {
        "id": "G4",
        "capability": "Can we calculate customer lifetime value?",
        "expected_status": "SUPPORTED",
        "concepts": [
            {"name": "Customer identity", "keywords": ["customer", "shopper", "client"], "essential": True},
            {"name": "Revenue / transaction history", "keywords": ["invoice", "line_total", "amount", "basket", "sales", "revenue"], "essential": True},
        ],
    },
    {
        "id": "G5",
        "capability": "Can we measure inventory turnover?",
        "expected_status": "SUPPORTED",
        "concepts": [
            {"name": "Inventory / stock levels", "keywords": ["stock", "inventory", "units_on_hand", "qty_available"], "essential": True},
            {"name": "Sales history", "keywords": ["invoice", "line_total", "basket", "sales", "amount"], "essential": True},
        ],
    },
]
