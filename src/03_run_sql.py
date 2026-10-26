"""
03_run_sql.py
Loads the cleaned tables into a SQLite database (data/supply_chain.db),
then runs every query in sql/02_analysis_queries.sql and saves each result
to outputs/sql_results/<name>.csv.
"""
from pathlib import Path
import re
import sqlite3
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PROC, SQL = ROOT / "data/processed", ROOT / "sql"
RES = ROOT / "outputs/sql_results"
RES.mkdir(parents=True, exist_ok=True)
DB = ROOT / "data/supply_chain.db"

con = sqlite3.connect(DB)
con.executescript((SQL / "01_schema.sql").read_text())
for table in ["dim_suppliers", "dim_products", "fact_sales",
              "fact_purchase_orders", "fact_inventory_daily"]:
    df = pd.read_csv(PROC / f"{table}.csv")
    df.to_sql(table, con, if_exists="append", index=False)
    print(f"loaded {table:<22} {len(df):>8,} rows")

queries = re.split(r"^-- name:\s*", (SQL / "02_analysis_queries.sql").read_text(), flags=re.M)[1:]
for block in queries:
    name, sql = block.split("\n", 1)
    result = pd.read_sql_query(sql, con)
    result.to_csv(RES / f"{name.strip()}.csv", index=False)
    print(f"ran {name.strip():<32} -> {len(result):>4} rows")
con.close()
