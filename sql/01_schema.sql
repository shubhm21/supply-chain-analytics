-- 01_schema.sql
-- Star schema for the supply chain analytics database (SQLite syntax;
-- portable to PostgreSQL / SQL Server with minor type changes).

DROP TABLE IF EXISTS fact_inventory_daily;
DROP TABLE IF EXISTS fact_purchase_orders;
DROP TABLE IF EXISTS fact_sales;
DROP TABLE IF EXISTS dim_products;
DROP TABLE IF EXISTS dim_suppliers;

CREATE TABLE dim_suppliers (
    supplier_id              TEXT PRIMARY KEY,
    supplier_name            TEXT NOT NULL,
    country                  TEXT,
    promised_lead_time_days  INTEGER,
    min_order_qty            INTEGER
);

CREATE TABLE dim_products (
    product_id    TEXT PRIMARY KEY,
    product_name  TEXT NOT NULL,
    category      TEXT NOT NULL,
    supplier_id   TEXT REFERENCES dim_suppliers(supplier_id),
    unit_cost     REAL,
    unit_price    REAL,
    margin_pct    REAL
);

CREATE TABLE fact_sales (
    transaction_id TEXT PRIMARY KEY,
    order_date     DATE NOT NULL,
    product_id     TEXT REFERENCES dim_products(product_id),
    quantity       INTEGER CHECK (quantity > 0),
    unit_price     REAL,
    region         TEXT,
    category       TEXT,
    revenue        REAL,
    cogs           REAL,
    gross_profit   REAL
);

CREATE TABLE fact_purchase_orders (
    po_id                  TEXT PRIMARY KEY,
    product_id             TEXT REFERENCES dim_products(product_id),
    supplier_id            TEXT REFERENCES dim_suppliers(supplier_id),
    order_date             DATE,
    promised_date          DATE,
    received_date          DATE,          -- NULL = still open
    qty_ordered            INTEGER,
    qty_received           REAL,
    unit_cost              REAL,
    actual_lead_time_days  REAL,
    days_late              REAL,
    on_time                REAL,
    in_full                REAL,
    otif                   REAL,
    po_value               REAL
);

CREATE TABLE fact_inventory_daily (
    snapshot_date    DATE,
    product_id       TEXT REFERENCES dim_products(product_id),
    on_hand_qty      INTEGER,
    demand_qty       INTEGER,
    inventory_value  REAL,
    stockout_flag    INTEGER,
    sold_qty         REAL,
    lost_units       REAL,
    PRIMARY KEY (snapshot_date, product_id)
);

CREATE INDEX idx_sales_date    ON fact_sales(order_date);
CREATE INDEX idx_sales_product ON fact_sales(product_id);
CREATE INDEX idx_inv_product   ON fact_inventory_daily(product_id);
CREATE INDEX idx_po_supplier   ON fact_purchase_orders(supplier_id);
