"""Build a reproducible POS (point-of-sale) SQLite database.

This is the GENERALIZATION schema for Iteration 6. It stores the SAME business
facts as the ERP database (erp_database.py) but with deliberately DIFFERENT
table and column names and a slightly different structure:

    business fact     ERP schema                 POS schema
    -------------     -------------------------  --------------------------
    a sale            invoices                   sales_receipts
    line item         invoice_lines              basket_items
    revenue field     line_total                 amount
    sale date         invoice_date (TEXT date)   sold_at (datetime text)
    location          branches.branch_name       outlets.store_name
    buyer             customers                  shoppers
    segment           customers.segment          shoppers.member_type
    product           products.product_name      items.title
    category          categories.category_name   items.dept (denormalized)
    stock             stock.units_on_hand        inventory_snapshots.qty_available

Because the facts are identical but the schema is not, a baseline tuned to ERP
column names fails here, while a schema-aware agent that reads the schema and
business context should still answer the same business questions correctly.
That contrast is the generalization evidence.

Deterministic: fixed seed and fixed window 2026-01..2026-08.

Run:  python pos_database.py   ->  creates pos.db
"""

import os
import sqlite3
import random
from datetime import date

from paths import POS_DB as DB_PATH
SEED = 7  # different seed from ERP; facts are pinned explicitly below anyway.

DATA_START = date(2026, 1, 1)
DATA_END = date(2026, 8, 31)

# member_type maps to ERP 'segment'. 'Business' == Corporate, 'Consumer' == Retail.
SHOPPERS = [
    (1, "Al Noor Trading", "Dubai", "Business"),
    (2, "Gulf Retail LLC", "Abu Dhabi", "Consumer"),
    (3, "Emirates Tech", "Dubai", "Business"),
    (4, "Sharjah Stores", "Sharjah", "Consumer"),
    (5, "Desert Systems", "Abu Dhabi", "Business"),
    (6, "Marina Gadgets", "Dubai", "Consumer"),
]

OUTLETS = [
    (1, "Dubai Main", "Dubai"),
    (2, "Abu Dhabi", "Abu Dhabi"),
    (3, "Sharjah", "Sharjah"),
]

# items: dept is denormalized (no separate category table). price == ERP unit_price.
ITEMS = [
    (1, "ProBook Laptop", "Laptops", 3200.00),
    (2, "UltraSlim Laptop", "Laptops", 4500.00),
    (3, "Wireless Mouse", "Accessories", 90.00),
    (4, "Mechanical Keyboard", "Accessories", 320.00),
    (5, "Docking Station", "Accessories", 550.00),   # challenge case
    (6, "27in Monitor", "Displays", 780.00),
    (7, "34in Ultrawide", "Displays", 1650.00),
    (8, "Noise-Cancel Headphones", "Audio", 620.00),
    (9, "USB Speaker", "Audio", 140.00),
]

ITEM_PRICE = {iid: price for iid, _, _, price in ITEMS}


def _reset(conn):
    conn.executescript(
        """
        DROP TABLE IF EXISTS basket_items;
        DROP TABLE IF EXISTS sales_receipts;
        DROP TABLE IF EXISTS items;
        DROP TABLE IF EXISTS shoppers;
        DROP TABLE IF EXISTS outlets;
        DROP TABLE IF EXISTS inventory_snapshots;

        CREATE TABLE outlets (
            outlet_id  INTEGER PRIMARY KEY,
            store_name TEXT NOT NULL,
            city       TEXT NOT NULL
        );
        CREATE TABLE shoppers (
            shopper_id  INTEGER PRIMARY KEY,
            shopper_name TEXT NOT NULL,
            city        TEXT NOT NULL,
            member_type TEXT NOT NULL
        );
        CREATE TABLE items (
            item_id   INTEGER PRIMARY KEY,
            title     TEXT NOT NULL,
            dept      TEXT NOT NULL,
            price     REAL NOT NULL
        );
        CREATE TABLE sales_receipts (
            receipt_id INTEGER PRIMARY KEY,
            sold_at    TEXT NOT NULL,        -- datetime, e.g. '2026-07-14 13:22:00'
            shopper_id INTEGER NOT NULL REFERENCES shoppers(shopper_id),
            outlet_id  INTEGER NOT NULL REFERENCES outlets(outlet_id)
        );
        CREATE TABLE basket_items (
            basket_id  INTEGER PRIMARY KEY,
            receipt_id INTEGER NOT NULL REFERENCES sales_receipts(receipt_id),
            item_id    INTEGER NOT NULL REFERENCES items(item_id),
            units      INTEGER NOT NULL,
            unit_price REAL NOT NULL,
            amount     REAL NOT NULL          -- revenue for the line
        );
        CREATE TABLE inventory_snapshots (
            snap_id       INTEGER PRIMARY KEY,
            item_id       INTEGER NOT NULL REFERENCES items(item_id),
            period        TEXT NOT NULL,       -- 'YYYY-MM'
            qty_available INTEGER NOT NULL
        );
        """
    )


def _months():
    out = []
    y, m = DATA_START.year, DATA_START.month
    while (y, m) <= (DATA_END.year, DATA_END.month):
        out.append((y, m))
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return out


def create_pos_database(db_path=DB_PATH):
    if os.path.exists(db_path):
        os.remove(db_path)

    rng = random.Random(SEED)
    conn = sqlite3.connect(db_path)
    _reset(conn)

    conn.executemany("INSERT INTO outlets VALUES (?, ?, ?)", OUTLETS)
    conn.executemany("INSERT INTO shoppers VALUES (?, ?, ?, ?)", SHOPPERS)
    conn.executemany("INSERT INTO items VALUES (?, ?, ?, ?)", ITEMS)

    months = _months()
    docking_id = 5

    # Same engineered challenge-case figures as the ERP schema.
    docking_units = {
        (2026, 1): 40, (2026, 2): 45, (2026, 3): 60, (2026, 4): 70,
        (2026, 5): 55, (2026, 6): 38, (2026, 7): 25, (2026, 8): 30,
    }
    docking_stock = {
        (2026, 1): 120, (2026, 2): 130, (2026, 3): 140, (2026, 4): 150,
        (2026, 5): 170, (2026, 6): 190, (2026, 7): 210, (2026, 8): 205,
    }

    receipt_id = 0
    basket_id = 0
    receipts = []
    baskets = []

    for (y, m) in months:
        n = rng.randint(18, 26)
        for _ in range(n):
            receipt_id += 1
            shopper = rng.choice(SHOPPERS)[0]
            outlet = rng.choice(OUTLETS)[0]
            day = rng.randint(1, 28)
            hh, mm = rng.randint(9, 20), rng.randint(0, 59)
            sold_at = f"{y:04d}-{m:02d}-{day:02d} {hh:02d}:{mm:02d}:00"
            receipts.append((receipt_id, sold_at, shopper, outlet))

            for _ in range(rng.randint(1, 4)):
                item = rng.choice([i for i in ITEMS if i[0] != docking_id])
                iid = item[0]
                price = ITEM_PRICE[iid]
                units = rng.randint(1, 6)
                basket_id += 1
                baskets.append((basket_id, receipt_id, iid, units, price, round(units * price, 2)))

        # Inject docking-station units so the monthly total matches exactly.
        receipt_id += 1
        shopper = rng.choice(SHOPPERS)[0]
        outlet = rng.choice(OUTLETS)[0]
        day = rng.randint(1, 28)
        sold_at = f"{y:04d}-{m:02d}-{day:02d} 15:00:00"
        receipts.append((receipt_id, sold_at, shopper, outlet))
        basket_id += 1
        dprice = ITEM_PRICE[docking_id]
        dunits = docking_units[(y, m)]
        baskets.append((basket_id, receipt_id, docking_id, dunits, dprice, round(dunits * dprice, 2)))

    conn.executemany("INSERT INTO sales_receipts VALUES (?, ?, ?, ?)", receipts)
    conn.executemany("INSERT INTO basket_items VALUES (?, ?, ?, ?, ?, ?)", baskets)

    snap_id = 0
    snaps = []
    for iid, _, _, _ in ITEMS:
        base = rng.randint(60, 160)
        for (y, m) in months:
            snap_id += 1
            period = f"{y:04d}-{m:02d}"
            qty = docking_stock[(y, m)] if iid == docking_id else base + rng.randint(-15, 15)
            snaps.append((snap_id, iid, period, qty))
    conn.executemany("INSERT INTO inventory_snapshots VALUES (?, ?, ?, ?)", snaps)

    conn.commit()
    conn.close()


if __name__ == "__main__":
    create_pos_database()
    print(f"POS database created at {DB_PATH} (seed={SEED}, window {DATA_START}..{DATA_END}).")
