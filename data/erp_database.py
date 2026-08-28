"""Build a small but meaningful, fully reproducible ERP SQLite database.

Design goals
------------
* Deterministic: a fixed RNG seed means the generated database is identical on
  every machine, so ground-truth answers stay valid and judges can reproduce
  the exact numbers.
* Fixed calendar window: data spans 2026-01-01 .. 2026-08-31 regardless of when
  the script runs. "Last month" in the evaluation always means the fixed month
  we designed the ground truth around, not a moving target.
* ERP-style star schema: branches, categories, products, customers, invoices and
  invoice_lines so multi-table joins, rankings and month-over-month comparisons
  are all answerable.
* One engineered challenge case: product 'Docking Station' has sales that decline
  across three consecutive months (May -> Jun -> Jul 2026) while its stock rises,
  so the hardest evaluation question has a real, checkable answer.

Run:  python erp_database.py
Creates/overwrites: erp.db
"""

import os
import sqlite3
import random
from datetime import date

from paths import ERP_DB as DB_PATH
SEED = 42

# Fixed data window so results are stable and reproducible.
DATA_START = date(2026, 1, 1)
DATA_END = date(2026, 8, 31)

BRANCHES = [
    (1, "Dubai Main", "Dubai"),
    (2, "Abu Dhabi", "Abu Dhabi"),
    (3, "Sharjah", "Sharjah"),
]

CATEGORIES = [
    (1, "Laptops"),
    (2, "Accessories"),
    (3, "Displays"),
    (4, "Audio"),
]

# (id, name, category_id, unit_price)
PRODUCTS = [
    (1, "ProBook Laptop", 1, 3200.00),
    (2, "UltraSlim Laptop", 1, 4500.00),
    (3, "Wireless Mouse", 2, 90.00),
    (4, "Mechanical Keyboard", 2, 320.00),
    (5, "Docking Station", 2, 550.00),   # engineered declining-sales case
    (6, "27in Monitor", 3, 780.00),
    (7, "34in Ultrawide", 3, 1650.00),
    (8, "Noise-Cancel Headphones", 4, 620.00),
    (9, "USB Speaker", 4, 140.00),
]

# (id, name, city, segment)
CUSTOMERS = [
    (1, "Al Noor Trading", "Dubai", "Corporate"),
    (2, "Gulf Retail LLC", "Abu Dhabi", "Retail"),
    (3, "Emirates Tech", "Dubai", "Corporate"),
    (4, "Sharjah Stores", "Sharjah", "Retail"),
    (5, "Desert Systems", "Abu Dhabi", "Corporate"),
    (6, "Marina Gadgets", "Dubai", "Retail"),
]

PRODUCT_PRICE = {pid: price for pid, _, _, price in PRODUCTS}


def _reset_db(conn):
    conn.executescript(
        """
        DROP TABLE IF EXISTS invoice_lines;
        DROP TABLE IF EXISTS invoices;
        DROP TABLE IF EXISTS products;
        DROP TABLE IF EXISTS categories;
        DROP TABLE IF EXISTS customers;
        DROP TABLE IF EXISTS branches;
        DROP TABLE IF EXISTS stock;

        CREATE TABLE branches (
            branch_id   INTEGER PRIMARY KEY,
            branch_name TEXT NOT NULL,
            city        TEXT NOT NULL
        );
        CREATE TABLE categories (
            category_id   INTEGER PRIMARY KEY,
            category_name TEXT NOT NULL
        );
        CREATE TABLE products (
            product_id   INTEGER PRIMARY KEY,
            product_name TEXT NOT NULL,
            category_id  INTEGER NOT NULL REFERENCES categories(category_id),
            unit_price   REAL NOT NULL
        );
        CREATE TABLE customers (
            customer_id   INTEGER PRIMARY KEY,
            customer_name TEXT NOT NULL,
            city          TEXT NOT NULL,
            segment       TEXT NOT NULL
        );
        CREATE TABLE invoices (
            invoice_id   INTEGER PRIMARY KEY,
            invoice_date TEXT NOT NULL,
            customer_id  INTEGER NOT NULL REFERENCES customers(customer_id),
            branch_id    INTEGER NOT NULL REFERENCES branches(branch_id)
        );
        CREATE TABLE invoice_lines (
            line_id     INTEGER PRIMARY KEY,
            invoice_id  INTEGER NOT NULL REFERENCES invoices(invoice_id),
            product_id  INTEGER NOT NULL REFERENCES products(product_id),
            quantity    INTEGER NOT NULL,
            unit_price  REAL NOT NULL,
            line_total  REAL NOT NULL
        );
        CREATE TABLE stock (
            stock_id      INTEGER PRIMARY KEY,
            product_id    INTEGER NOT NULL REFERENCES products(product_id),
            month         TEXT NOT NULL,
            units_on_hand INTEGER NOT NULL
        );
        """
    )


def _months_in_window():
    """Return list of (year, month) tuples inside the fixed window."""
    months = []
    y, m = DATA_START.year, DATA_START.month
    while (y, m) <= (DATA_END.year, DATA_END.month):
        months.append((y, m))
        m += 1
        if m > 12:
            m = 1
            y += 1
    return months


def _random_day(rng, year, month):
    # All our months are within Jan-Aug so 28 is always a safe upper bound.
    return date(year, month, rng.randint(1, 28))


def create_erp_database(db_path=DB_PATH):
    if os.path.exists(db_path):
        os.remove(db_path)

    rng = random.Random(SEED)
    conn = sqlite3.connect(db_path)
    _reset_db(conn)

    conn.executemany("INSERT INTO branches VALUES (?, ?, ?)", BRANCHES)
    conn.executemany("INSERT INTO categories VALUES (?, ?)", CATEGORIES)
    conn.executemany("INSERT INTO products VALUES (?, ?, ?, ?)", PRODUCTS)
    conn.executemany("INSERT INTO customers VALUES (?, ?, ?, ?)", CUSTOMERS)

    months = _months_in_window()
    docking_id = 5

    # Engineered challenge case: Docking Station monthly UNIT sales.
    # Declining for three consecutive months May -> Jun -> Jul, while stock rises.
    docking_units = {
        (2026, 1): 40,
        (2026, 2): 45,
        (2026, 3): 60,
        (2026, 4): 70,
        (2026, 5): 55,   # decline starts
        (2026, 6): 38,   # decline
        (2026, 7): 25,   # decline (3 consecutive)
        (2026, 8): 30,
    }
    docking_stock = {
        (2026, 1): 120,
        (2026, 2): 130,
        (2026, 3): 140,
        (2026, 4): 150,
        (2026, 5): 170,  # stock rising while sales fall
        (2026, 6): 190,
        (2026, 7): 210,
        (2026, 8): 205,
    }

    invoice_id = 0
    line_id = 0
    invoices = []
    lines = []

    for (y, m) in months:
        # Regular products: a set number of invoices per month with random lines.
        n_invoices = rng.randint(18, 26)
        for _ in range(n_invoices):
            invoice_id += 1
            cust = rng.choice(CUSTOMERS)[0]
            branch = rng.choice(BRANCHES)[0]
            d = _random_day(rng, y, m)
            invoices.append((invoice_id, d.isoformat(), cust, branch))

            n_lines = rng.randint(1, 4)
            # Products other than the docking station are chosen randomly here;
            # the docking station is injected separately below to hit exact totals.
            candidate_products = [p for p in PRODUCTS if p[0] != docking_id]
            for _ in range(n_lines):
                prod = rng.choice(candidate_products)
                pid = prod[0]
                price = PRODUCT_PRICE[pid]
                qty = rng.randint(1, 6)
                line_id += 1
                lines.append((line_id, invoice_id, pid, qty, price, round(qty * price, 2)))

        # Inject the docking-station units for the month as its own invoice,
        # so the monthly unit total exactly matches the engineered figure.
        invoice_id += 1
        cust = rng.choice(CUSTOMERS)[0]
        branch = rng.choice(BRANCHES)[0]
        d = _random_day(rng, y, m)
        invoices.append((invoice_id, d.isoformat(), cust, branch))
        line_id += 1
        dprice = PRODUCT_PRICE[docking_id]
        dunits = docking_units[(y, m)]
        lines.append((line_id, invoice_id, docking_id, dunits, dprice, round(dunits * dprice, 2)))

    conn.executemany("INSERT INTO invoices VALUES (?, ?, ?, ?)", invoices)
    conn.executemany("INSERT INTO invoice_lines VALUES (?, ?, ?, ?, ?, ?)", lines)

    # Stock snapshot per product per month. Docking station follows the
    # engineered rising curve; other products get stable-ish random levels.
    stock_rows = []
    stock_id = 0
    for pid, _, _, _ in PRODUCTS:
        base = rng.randint(60, 160)
        for (y, m) in months:
            stock_id += 1
            month_key = f"{y:04d}-{m:02d}"
            if pid == docking_id:
                units = docking_stock[(y, m)]
            else:
                units = base + rng.randint(-15, 15)
            stock_rows.append((stock_id, pid, month_key, units))
    conn.executemany("INSERT INTO stock VALUES (?, ?, ?, ?)", stock_rows)

    conn.commit()
    conn.close()


if __name__ == "__main__":
    create_erp_database()
    print(f"ERP database created at {DB_PATH} (seed={SEED}, window {DATA_START}..{DATA_END}).")
