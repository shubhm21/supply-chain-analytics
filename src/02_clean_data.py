"""
02_clean_data.py
Cleans the raw extracts and writes analysis-ready tables to data/processed/.
Every fix is counted and written to outputs/cleaning_report.csv so the
cleaning decisions are auditable.
"""
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW, PROC, OUT = ROOT / "data/raw", ROOT / "data/processed", ROOT / "outputs"
PROC.mkdir(parents=True, exist_ok=True)
OUT.mkdir(parents=True, exist_ok=True)
log = []

def note(table, issue, rows, action):
    log.append({"table": table, "issue": issue, "rows_affected": int(rows), "action": action})

# ---------------------------------------------------------------- products
products = pd.read_csv(RAW / "products.csv")
bad_cat = (products.category != products.category.str.strip().str.title()).sum()
products["category"] = products.category.str.strip().str.title().str.replace("And", "&")
note("products", "Inconsistent category casing / trailing spaces", bad_cat, "Trimmed and title-cased")
products["margin_pct"] = (products.unit_price - products.unit_cost) / products.unit_price

# ---------------------------------------------------------------- sales
sales = pd.read_csv(RAW / "sales.csv")
n0 = len(sales)

dups = sales.duplicated().sum()
sales = sales.drop_duplicates()
note("sales", "Exact duplicate rows", dups, "Removed")

iso = pd.to_datetime(sales.order_date, format="%Y-%m-%d", errors="coerce")
dmy = pd.to_datetime(sales.order_date, format="%d/%m/%Y", errors="coerce")
note("sales", "Non-ISO date format (DD/MM/YYYY)", iso.isna().sum(), "Parsed to ISO date")
sales["order_date"] = iso.fillna(dmy)

neg = (sales.quantity <= 0).sum()
sales = sales[sales.quantity > 0]
note("sales", "Zero/negative quantity (entry errors, not tagged as returns)", neg, "Removed")

# Outliers: quantity far above the product's normal line size (robust z on log scale)
med = sales.groupby("product_id").quantity.transform("median")
q99 = sales.groupby("product_id").quantity.transform(lambda s: s.quantile(0.99))
outlier = sales.quantity > np.maximum(q99 * 5, med * 20)
note("sales", "Extreme quantity outliers (>5x product's 99th pct)", outlier.sum(), "Removed")
sales = sales[~outlier]

missing_price = sales.unit_price.isna().sum()
list_price = sales.product_id.map(products.set_index("product_id").unit_price)
sales["unit_price"] = sales.unit_price.fillna(list_price)
note("sales", "Missing unit_price", missing_price, "Imputed with product list price")

sales = sales.merge(products[["product_id", "category", "unit_cost"]], on="product_id", how="left")
sales["revenue"] = (sales.quantity * sales.unit_price).round(2)
sales["cogs"] = (sales.quantity * sales.unit_cost).round(2)
sales["gross_profit"] = sales.revenue - sales.cogs
sales = sales.drop(columns="unit_cost").sort_values(["order_date", "transaction_id"])
note("sales", "Rows in -> rows out", n0 - len(sales), f"{n0:,} -> {len(sales):,}")

# ---------------------------------------------------------------- purchase orders
po = pd.read_csv(RAW / "purchase_orders.csv",
                 parse_dates=["order_date", "promised_date", "received_date"])
open_po = po.received_date.isna().sum()
note("purchase_orders", "Open POs (not yet received at period end)", open_po,
     "Kept, excluded from delivery KPIs")
po["actual_lead_time_days"] = (po.received_date - po.order_date).dt.days
po["days_late"] = (po.received_date - po.promised_date).dt.days.clip(lower=0)
po["on_time"] = np.where(po.received_date.isna(), np.nan, (po.received_date <= po.promised_date).astype(float))
po["in_full"] = np.where(po.received_date.isna(), np.nan, (po.qty_received >= po.qty_ordered).astype(float))
po["otif"] = po.on_time * po.in_full
po["po_value"] = po.qty_ordered * po.unit_cost

# ---------------------------------------------------------------- inventory
inv = pd.read_csv(RAW / "inventory_daily.csv", parse_dates=["snapshot_date"])
inv = inv.merge(products[["product_id", "unit_cost"]], on="product_id")
inv["inventory_value"] = inv.on_hand_qty * inv.unit_cost
inv["stockout_flag"] = (inv.on_hand_qty == 0).astype(int)
# demand_qty includes unmet demand; lost units = demand - units actually sold that day
daily_sold = sales.groupby(["order_date", "product_id"]).quantity.sum().rename("sold_qty")
inv = inv.merge(daily_sold, left_on=["snapshot_date", "product_id"],
                right_index=True, how="left").fillna({"sold_qty": 0})
inv["lost_units"] = (inv.demand_qty - inv.sold_qty).clip(lower=0)
inv = inv.drop(columns="unit_cost")

# ---------------------------------------------------------------- write
suppliers = pd.read_csv(RAW / "suppliers.csv")
products.to_csv(PROC / "dim_products.csv", index=False)
suppliers.to_csv(PROC / "dim_suppliers.csv", index=False)
sales.to_csv(PROC / "fact_sales.csv", index=False, date_format="%Y-%m-%d")
po.to_csv(PROC / "fact_purchase_orders.csv", index=False, date_format="%Y-%m-%d")
inv.to_csv(PROC / "fact_inventory_daily.csv", index=False, date_format="%Y-%m-%d")
pd.DataFrame(log).to_csv(OUT / "cleaning_report.csv", index=False)
print(pd.DataFrame(log).to_string(index=False))
