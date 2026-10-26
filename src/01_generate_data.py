"""
01_generate_data.py
Generates a realistic synthetic dataset for a fictional Canadian distributor
("NorthStar Supply Co.") covering 2 years of daily operations.

The simulation runs an actual inventory policy day by day, so stockouts,
excess stock and late supplier deliveries emerge naturally from the data
rather than being hard-coded. A small amount of "dirty" data is injected
at the end so the cleaning step has real work to do.

Outputs (data/raw/):
    products.csv, suppliers.csv, sales.csv, inventory_daily.csv, purchase_orders.csv
"""
from pathlib import Path
import numpy as np
import pandas as pd

SEED = 42
rng = np.random.default_rng(SEED)
ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
RAW.mkdir(parents=True, exist_ok=True)

START, END = "2024-01-01", "2025-12-31"
dates = pd.date_range(START, END, freq="D")
N_DAYS = len(dates)

# ---------------------------------------------------------------- suppliers
suppliers = pd.DataFrame({
    "supplier_id": [f"S{i:02d}" for i in range(1, 11)],
    "supplier_name": ["Maple Industrial", "Great Lakes Supply", "Rideau Wholesale",
                      "Pacific Rim Trading", "Laurentian Goods", "Prairie Distributors",
                      "Atlantic Imports", "Northern Parts Co.", "Summit Packaging",
                      "Capital Sourcing"],
    "country": ["Canada", "Canada", "Canada", "China", "Canada", "Canada",
                "USA", "Canada", "USA", "Mexico"],
    "promised_lead_time_days": [7, 10, 5, 35, 8, 12, 14, 9, 11, 21],
    "min_order_qty": [24, 50, 12, 200, 24, 48, 100, 12, 150, 120],
})
# hidden "true" reliability used only by the simulation
true_late_prob = np.array([0.05, 0.12, 0.04, 0.38, 0.08, 0.22, 0.15, 0.06, 0.30, 0.18])
true_late_days = np.array([2, 3, 1, 12, 2, 5, 4, 2, 6, 7])

# ---------------------------------------------------------------- products
categories = {
    #  name               n   price range     seasonality profile
    "Electronics":        (25, (40, 400),  "holiday"),
    "Home & Kitchen":     (30, (10, 120),  "holiday"),
    "Outdoor & Garden":   (25, (15, 250),  "summer"),
    "Office Supplies":    (30, (3, 60),    "back_to_school"),
    "Health & Safety":    (20, (8, 90),    "winter"),
    "Packaging":          (20, (2, 35),    "flat"),
}
rows, pid = [], 1
for cat, (n, (lo, hi), season) in categories.items():
    for _ in range(n):
        price = round(float(np.exp(rng.uniform(np.log(lo), np.log(hi)))), 2)
        margin = rng.uniform(0.25, 0.55)
        # Pareto-ish demand so ABC analysis finds a real long tail
        base = float(rng.pareto(1.6) * 3 + 0.3)
        rows.append({
            "product_id": f"P{pid:04d}",
            "product_name": f"{cat.split()[0]} Item {pid:03d}",
            "category": cat,
            "supplier_id": rng.choice(suppliers.supplier_id),
            "unit_cost": round(price * (1 - margin), 2),
            "unit_price": price,
            "_base_demand": min(base, 40.0),
            "_season": season,
        })
        pid += 1
products = pd.DataFrame(rows)
N_P = len(products)

# ---------------------------------------------------------------- demand
doy = dates.dayofyear.values
month = dates.month.values
seasonal_profiles = {
    "holiday":        1 + 0.9 * np.exp(-((doy - 340) ** 2) / (2 * 18 ** 2)) + 0.15 * (month == 11),
    "summer":         1 + 0.85 * np.sin(np.pi * np.clip((doy - 90) / 150, 0, 1)) - 0.45 * np.isin(month, [12, 1, 2]),
    "back_to_school": 1 + 0.8 * np.exp(-((doy - 240) ** 2) / (2 * 15 ** 2)) + 0.2 * (month == 1),
    "winter":         1 + 0.45 * np.cos(2 * np.pi * (doy - 15) / 365),
    "flat":           np.ones(N_DAYS),
}
weekday_factor = np.array([1.05, 1.08, 1.06, 1.04, 1.12, 0.85, 0.80])[dates.dayofweek.values]
trend = np.linspace(1.0, 1.12, N_DAYS)  # ~12% growth over the 2 years

# Lifecycle: ~10% of SKUs fade out in year 2 (customers switching away),
# ~8% take off. The planner never updates the policy, which is realistic
# and produces both excess stock and stockouts.
lifecycle = np.ones((N_P, N_DAYS))
t_norm = np.clip((np.arange(N_DAYS) - 300) / 300, 0, 1)
fading = rng.choice(N_P, size=15, replace=False)
growing = rng.choice(np.setdiff1d(np.arange(N_P), fading), size=12, replace=False)
lifecycle[fading] = 1 - 0.85 * t_norm
lifecycle[growing] = 1 + 0.9 * t_norm

demand = np.zeros((N_P, N_DAYS), dtype=int)
for i, p in products.iterrows():
    lam = p._base_demand * seasonal_profiles[p._season] * weekday_factor * trend * lifecycle[i]
    demand[i] = rng.poisson(np.clip(lam, 0.01, None))

# ---------------------------------------------------------------- inventory simulation
# Deliberately imperfect (s, Q) policy: the "current" business sets reorder
# points by gut feel, so some SKUs are under-protected and some over-stocked.
sup_idx = products.supplier_id.str[1:].astype(int).values - 1
promised_lt = suppliers.promised_lead_time_days.values[sup_idx]
avg_d = demand[:, :90].mean(axis=1) + 0.05   # planner's estimate from Q1 2024, never refreshed
policy_noise = rng.choice([0.45, 0.7, 1.0, 1.6, 2.6], size=N_P, p=[0.15, 0.25, 0.3, 0.2, 0.1])
reorder_point = np.ceil(avg_d * promised_lt * policy_noise).astype(int) + 1
cover_days = rng.choice([20, 30, 45, 90, 150], size=N_P, p=[0.2, 0.3, 0.25, 0.15, 0.1])
moq = suppliers.min_order_qty.values[sup_idx]
order_qty = np.maximum(np.ceil(avg_d * cover_days).astype(int) + 5, moq)

on_hand = (reorder_point + order_qty).astype(int)
pipeline = [[] for _ in range(N_P)]  # (arrival_day, qty, po_id)
sales_qty = np.zeros_like(demand)
inv_end = np.zeros_like(demand)
po_rows, po_counter = [], 1

for t in range(N_DAYS):
    for i in range(N_P):
        # receive arrivals
        arrived = [x for x in pipeline[i] if x[0] == t]
        if arrived:
            on_hand[i] += sum(x[1] for x in arrived)
            pipeline[i] = [x for x in pipeline[i] if x[0] != t]
        # sell (lost sales if short)
        s = min(demand[i, t], on_hand[i])
        sales_qty[i, t] = s
        on_hand[i] -= s
        inv_end[i, t] = on_hand[i]
        # reorder check (inventory position)
        position = on_hand[i] + sum(x[1] for x in pipeline[i])
        if position <= reorder_point[i]:
            j = sup_idx[i]
            late = rng.random() < true_late_prob[j]
            delay = int(rng.integers(1, true_late_days[j] * 2 + 1)) if late else int(rng.integers(-1, 2))
            actual = max(1, promised_lt[i] + delay)
            # supplier occasionally short-ships
            short = rng.random() < true_late_prob[j] * 0.4
            received = int(order_qty[i] * rng.uniform(0.7, 0.95)) if short else int(order_qty[i])
            pipeline[i].append((t + actual, received, po_counter))
            po_rows.append({
                "po_id": f"PO{po_counter:06d}",
                "product_id": products.product_id[i],
                "supplier_id": suppliers.supplier_id[j],
                "order_date": dates[t],
                "promised_date": dates[t] + pd.Timedelta(days=int(promised_lt[i])),
                "received_date": dates[t] + pd.Timedelta(days=actual) if t + actual < N_DAYS else pd.NaT,
                "qty_ordered": int(order_qty[i]),
                "qty_received": received if t + actual < N_DAYS else np.nan,
                "unit_cost": products.unit_cost[i],
            })
            po_counter += 1

# ---------------------------------------------------------------- assemble tables
pi, di = np.nonzero(sales_qty)
sales = pd.DataFrame({
    "order_date": dates[di],
    "product_id": products.product_id.values[pi],
    "quantity": sales_qty[pi, di],
})
# spread a day's quantity across 1-3 order lines so it looks like transactions
sales["n_lines"] = np.minimum(sales.quantity, rng.integers(1, 4, len(sales)))
sales = sales.loc[sales.index.repeat(sales.n_lines)].reset_index(drop=True)
split = sales.groupby(level=0).cumcount()
sales["quantity"] = (sales.quantity // sales.n_lines) + (split < sales.quantity % sales.n_lines).astype(int)
sales = sales[sales.quantity > 0].drop(columns="n_lines")
price_map = products.set_index("product_id").unit_price
discount = rng.choice([0, 0, 0, 0.05, 0.10], len(sales))
sales["unit_price"] = (sales.product_id.map(price_map) * (1 - discount)).round(2)
sales["region"] = rng.choice(["Ontario", "Quebec", "Western Canada", "Atlantic Canada"],
                             len(sales), p=[0.42, 0.24, 0.24, 0.10])
sales = sales.sample(frac=1, random_state=SEED).sort_values("order_date").reset_index(drop=True)
sales.insert(0, "transaction_id", [f"T{i:07d}" for i in range(1, len(sales) + 1)])

inventory = pd.DataFrame({
    "snapshot_date": np.tile(dates, N_P),
    "product_id": np.repeat(products.product_id.values, N_DAYS),
    "on_hand_qty": inv_end.ravel(),
    "demand_qty": demand.ravel(),   # includes unmet demand (lost sales)
})

purchase_orders = pd.DataFrame(po_rows)

# ---------------------------------------------------------------- inject dirty data
dirty = sales.copy()
dup = dirty.sample(frac=0.004, random_state=1)                       # duplicate rows
dirty = pd.concat([dirty, dup])
dirty.loc[dirty.sample(frac=0.003, random_state=2).index, "unit_price"] = np.nan   # missing prices
neg = dirty.sample(n=60, random_state=3).index                       # data-entry negatives
dirty.loc[neg, "quantity"] = -dirty.loc[neg, "quantity"]
out = dirty.sample(n=8, random_state=4).index                        # fat-finger outliers
dirty.loc[out, "quantity"] = dirty.loc[out, "quantity"] * 100
dirty["order_date"] = dirty.order_date.dt.strftime("%Y-%m-%d")
mixed = dirty.sample(frac=0.02, random_state=5).index                # mixed date formats
dirty.loc[mixed, "order_date"] = pd.to_datetime(dirty.loc[mixed, "order_date"]).dt.strftime("%d/%m/%Y")
dirty = dirty.sample(frac=1, random_state=6)

prod_out = products.drop(columns=["_base_demand", "_season"]).copy()
messy = prod_out.sample(n=15, random_state=7).index                  # inconsistent text
prod_out.loc[messy, "category"] = prod_out.loc[messy, "category"].str.upper() + " "

# ---------------------------------------------------------------- write
prod_out.to_csv(RAW / "products.csv", index=False)
suppliers.to_csv(RAW / "suppliers.csv", index=False)
dirty.to_csv(RAW / "sales.csv", index=False)
inventory.to_csv(RAW / "inventory_daily.csv", index=False)
purchase_orders.to_csv(RAW / "purchase_orders.csv", index=False, date_format="%Y-%m-%d")

print(f"products: {len(prod_out)}, suppliers: {len(suppliers)}, sales lines: {len(dirty):,}, "
      f"inventory rows: {len(inventory):,}, POs: {len(purchase_orders):,}")
print(f"Lost sales units: {(demand - sales_qty).sum():,} of {demand.sum():,} demanded")
