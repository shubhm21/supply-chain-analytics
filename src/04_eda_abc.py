"""
04_eda_abc.py
Exploratory analysis, KPI calculation, ABC-XYZ classification and charts.

ABC = revenue contribution (how important is the product?)
XYZ = demand variability, coefficient of variation of weekly demand
      (how predictable is it?)
Together they decide how much safety stock each product deserves.
"""
from pathlib import Path
import json
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mtick

ROOT = Path(__file__).resolve().parents[1]
PROC, OUT = ROOT / "data/processed", ROOT / "outputs"
CH = OUT / "charts"
CH.mkdir(parents=True, exist_ok=True)

plt.rcParams.update({"figure.dpi": 130, "font.size": 9, "axes.spines.top": False,
                     "axes.spines.right": False, "axes.titleweight": "bold"})
NAVY, TEAL, AMBER, RED, GREY = "#1f3a5f", "#2a9d8f", "#e9a23b", "#d1495b", "#9aa5b1"

products = pd.read_csv(PROC / "dim_products.csv")
suppliers = pd.read_csv(PROC / "dim_suppliers.csv")
sales = pd.read_csv(PROC / "fact_sales.csv", parse_dates=["order_date"])
inv = pd.read_csv(PROC / "fact_inventory_daily.csv", parse_dates=["snapshot_date"])
po = pd.read_csv(PROC / "fact_purchase_orders.csv", parse_dates=["order_date", "received_date"])

# ======================================================== headline KPIs
received = po.dropna(subset=["received_date"])
annual_cogs = sales.cogs.sum() / 2
avg_inv_value = inv.groupby("snapshot_date").inventory_value.sum().mean()
lost_rev = (inv.lost_units * inv.product_id.map(products.set_index("product_id").unit_price)).sum()
kpis = {
    "total_revenue": round(sales.revenue.sum(), 0),
    "gross_margin_pct": round(sales.gross_profit.sum() / sales.revenue.sum(), 4),
    "yoy_revenue_growth_pct": round(sales[sales.order_date.dt.year == 2025].revenue.sum()
                                    / sales[sales.order_date.dt.year == 2024].revenue.sum() - 1, 4),
    "avg_inventory_value": round(avg_inv_value, 0),
    "inventory_turnover": round(annual_cogs / avg_inv_value, 2),
    "days_of_inventory": round(365 * avg_inv_value / annual_cogs, 1),
    "stockout_rate_pct": round(inv.stockout_flag.mean(), 4),
    "fill_rate_pct": round(inv.sold_qty.sum() / inv.demand_qty.sum(), 4),
    "lost_units": int(inv.lost_units.sum()),
    "est_lost_revenue": round(lost_rev, 0),
    "supplier_on_time_pct": round(received.on_time.mean(), 4),
    "supplier_otif_pct": round(received.otif.mean(), 4),
    "annual_carrying_cost_at_25pct": round(avg_inv_value * 0.25, 0),
}
(OUT / "kpis.json").write_text(json.dumps(kpis, indent=2))

# ======================================================== ABC-XYZ
prod_rev = sales.groupby("product_id").agg(revenue=("revenue", "sum"),
                                           units=("quantity", "sum"),
                                           gross_profit=("gross_profit", "sum"))
prod_rev = prod_rev.reindex(products.product_id, fill_value=0).sort_values("revenue", ascending=False)
prod_rev["cum_share"] = prod_rev.revenue.cumsum() / prod_rev.revenue.sum()
prod_rev["abc_class"] = np.select([prod_rev.cum_share <= 0.80, prod_rev.cum_share <= 0.95], ["A", "B"], "C")

# XYZ on *unconstrained* weekly demand (sales are capped by stockouts, demand isn't)
weekly = (inv.set_index("snapshot_date").groupby("product_id").demand_qty
             .resample("W-SUN").sum().unstack(0))
weekly = weekly.iloc[1:-1]                      # drop partial first/last weeks
cv = (weekly.std() / weekly.mean()).rename("demand_cv")
prod_rev = prod_rev.join(cv)
prod_rev["xyz_class"] = pd.cut(prod_rev.demand_cv, [-np.inf, 0.5, 1.0, np.inf], labels=["X", "Y", "Z"]).astype(str)
prod_rev["abc_xyz"] = prod_rev.abc_class + prod_rev.xyz_class
prod_rev["revenue_rank"] = np.arange(1, len(prod_rev) + 1)
abc = products.merge(prod_rev.reset_index(), on="product_id")
abc.to_csv(OUT / "abc_xyz_classification.csv", index=False)

abc_summary = abc.groupby("abc_class").agg(products=("product_id", "count"),
                                           revenue=("revenue", "sum")).assign(
    pct_products=lambda d: d.products / d.products.sum(),
    pct_revenue=lambda d: d.revenue / d.revenue.sum())
matrix = pd.crosstab(abc.abc_class, abc.xyz_class)

# ======================================================== product-level inventory health
inv_prod = inv.groupby("product_id").agg(stockout_days=("stockout_flag", "sum"),
                                         stockout_rate=("stockout_flag", "mean"),
                                         lost_units=("lost_units", "sum"),
                                         avg_inventory_value=("inventory_value", "mean"))
cogs_p = sales.groupby("product_id").cogs.sum() / 2
inv_prod["turnover"] = cogs_p / inv_prod.avg_inventory_value
inv_prod["days_of_inventory"] = 365 / inv_prod.turnover
inv_prod = inv_prod.join(products.set_index("product_id")[["product_name", "category", "supplier_id", "unit_price"]])
inv_prod["est_lost_revenue"] = inv_prod.lost_units * inv_prod.unit_price
inv_prod = inv_prod.join(abc.set_index("product_id")[["abc_class", "xyz_class"]])
inv_prod.reset_index().to_csv(OUT / "product_inventory_health.csv", index=False)

# ======================================================== charts
def save(fig, name):
    fig.tight_layout()
    fig.savefig(CH / name, bbox_inches="tight")
    plt.close(fig)

# 1. monthly revenue
m = sales.set_index("order_date").resample("MS")[["revenue", "gross_profit"]].sum()
fig, ax = plt.subplots(figsize=(9, 3.6))
ax.plot(m.index, m.revenue / 1e6, color=NAVY, lw=2, marker="o", ms=3, label="Revenue")
ax.plot(m.index, m.gross_profit / 1e6, color=TEAL, lw=2, marker="o", ms=3, label="Gross profit")
ax.set_title("Monthly revenue and gross profit ($M)")
ax.yaxis.set_major_formatter(mtick.FormatStrFormatter("$%.1fM"))
ax.legend(frameon=False)
save(fig, "01_monthly_revenue.png")

# 2. seasonality heatmap
seas = sales.assign(m=sales.order_date.dt.month).groupby(["category", "m"]).quantity.sum().unstack()
seas = seas.div(seas.mean(axis=1), axis=0)
fig, ax = plt.subplots(figsize=(9, 3.4))
im = ax.imshow(seas.values, cmap="RdYlGn", aspect="auto", vmin=0.4, vmax=1.6)
ax.set_xticks(range(12), ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])
ax.set_yticks(range(len(seas)), seas.index)
for i in range(seas.shape[0]):
    for j in range(12):
        ax.text(j, i, f"{seas.values[i, j]:.2f}", ha="center", va="center", fontsize=7)
ax.set_title("Seasonality index by category (1.00 = average month)")
fig.colorbar(im, ax=ax, fraction=0.025)
save(fig, "02_seasonality_heatmap.png")

# 3. Pareto
fig, ax = plt.subplots(figsize=(9, 3.6))
colors = prod_rev.abc_class.map({"A": NAVY, "B": TEAL, "C": GREY})
ax.bar(range(len(prod_rev)), prod_rev.revenue / 1e3, color=colors, width=1.0)
ax2 = ax.twinx()
ax2.plot(range(len(prod_rev)), prod_rev.cum_share * 100, color=RED, lw=2)
ax2.axhline(80, ls="--", color=GREY, lw=1); ax2.axhline(95, ls="--", color=GREY, lw=1)
ax2.set_ylim(0, 102); ax2.yaxis.set_major_formatter(mtick.PercentFormatter())
ax2.spines["right"].set_visible(True)
ax.set_xlabel("Products ranked by revenue"); ax.set_ylabel("Revenue ($K)")
nA = (prod_rev.abc_class == "A").sum()
ax.set_title(f"ABC Pareto: {nA} 'A' products ({nA/len(prod_rev):.0%} of SKUs) generate 80% of revenue")
save(fig, "03_abc_pareto.png")

# 4. supplier OTIF
sc = received.groupby("supplier_id").agg(otif=("otif", "mean"), on_time=("on_time", "mean")).join(
    suppliers.set_index("supplier_id").supplier_name).sort_values("otif")
fig, ax = plt.subplots(figsize=(9, 3.6))
cols = [RED if v < 0.5 else AMBER if v < 0.6 else TEAL for v in sc.otif]
ax.barh(sc.supplier_name, sc.otif * 100, color=cols)
for y, v in enumerate(sc.otif):
    ax.text(v * 100 + 0.8, y, f"{v:.0%}", va="center", fontsize=8)
ax.xaxis.set_major_formatter(mtick.PercentFormatter()); ax.set_xlim(0, 80)
ax.set_title("Supplier OTIF (on-time, in-full) rate")
save(fig, "04_supplier_otif.png")

# 5. top lost revenue
top = inv_prod.sort_values("est_lost_revenue", ascending=False).head(15)[::-1]
fig, ax = plt.subplots(figsize=(9, 4))
ax.barh(top.product_name + " (" + top.abc_class + ")", top.est_lost_revenue / 1e3,
        color=[NAVY if c == "A" else TEAL if c == "B" else GREY for c in top.abc_class])
ax.set_xlabel("Estimated lost revenue from stockouts ($K)")
ax.set_title("Top 15 products by revenue lost to stockouts")
save(fig, "05_top_lost_revenue.png")

# 6. stock vs demand example for worst product
worst = top.index[-1]
d = inv[inv.product_id == worst].set_index("snapshot_date")
fig, ax = plt.subplots(figsize=(9, 3.4))
ax.plot(d.index, d.on_hand_qty, color=NAVY, lw=1.2, label="On-hand units")
ax.plot(d.index, d.demand_qty.rolling(7).mean() * 7, color=AMBER, lw=1.2, label="Weekly demand (7-day sum)")
so = d[d.stockout_flag == 1]
ax.scatter(so.index, np.zeros(len(so)), color=RED, s=6, label="Stockout day", zorder=3)
ax.set_title(f"{products.set_index('product_id').product_name[worst]}: inventory vs demand")
ax.legend(frameon=False, ncol=3, loc="upper left")
save(fig, "06_worst_product_stock_profile.png")

# ======================================================== print summary
print(json.dumps(kpis, indent=2))
print("\nABC summary\n", abc_summary.round(3))
print("\nABC x XYZ\n", matrix)
print("\nInventory health quartiles\n", inv_prod[["stockout_rate", "turnover", "days_of_inventory"]].describe().round(2))
