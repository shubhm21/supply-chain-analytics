"""
06_inventory_policy.py
Builds a data-driven replenishment policy and back-tests it against what
actually happened in 2025.

Policy (continuous review, reorder point / order quantity):
    d        expected daily demand = trailing 8-week demand x last year's
             seasonal ratio for the coming month (seasonal naive won the
             forecast backtest, so the policy uses the same logic)
    sigma_d  std dev of daily demand (trailing 8 weeks)
    LT, sLT  supplier's *actual* lead time mean / std dev (not the promised one)
    z        service-level factor by ABC class: A 98%, B 95%, C 90%
    SS       safety stock = z * sqrt(LT * sigma_d^2 + d^2 * sLT^2)
    ROP      reorder point = d * LT + SS
    EOQ      economic order qty = sqrt(2 * annual demand * order cost / holding cost)
    Q        max(EOQ, supplier minimum order qty)
Parameters are refreshed on the 1st of every month using only data
available at that date (no look-ahead).
"""
from pathlib import Path
import json
import numpy as np
import pandas as pd
from scipy.stats import norm
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
PROC, OUT = ROOT / "data/processed", ROOT / "outputs"
rng = np.random.default_rng(7)

ORDER_COST = 75.0          # $ per purchase order (admin, receiving, freight fixed part)
HOLDING_RATE = 0.25        # annual carrying cost as % of unit cost
SERVICE = {"A": 0.98, "B": 0.95, "C": 0.90}

products = pd.read_csv(PROC / "dim_products.csv").set_index("product_id")
suppliers = pd.read_csv(PROC / "dim_suppliers.csv").set_index("supplier_id")
inv = pd.read_csv(PROC / "fact_inventory_daily.csv", parse_dates=["snapshot_date"])
po = pd.read_csv(PROC / "fact_purchase_orders.csv", parse_dates=["order_date", "promised_date", "received_date"])
abc = pd.read_csv(OUT / "abc_xyz_classification.csv").set_index("product_id")

D = inv.pivot(index="snapshot_date", columns="product_id", values="demand_qty")   # days x products
OH = inv.pivot(index="snapshot_date", columns="product_id", values="on_hand_qty")
pids = D.columns
dates = D.index
prod = products.loc[pids]
abc = abc.loc[pids]
z = abc.abc_class.map(lambda c: norm.ppf(SERVICE[c])).values
moq = suppliers.loc[prod.supplier_id, "min_order_qty"].values
unit_cost = prod.unit_cost.values
unit_price = prod.unit_price.values
sup_of = prod.supplier_id.values


def supplier_lead_times(asof):
    rec = po[po.received_date < asof]
    g = rec.groupby("supplier_id").actual_lead_time_days
    lt = g.mean().reindex(suppliers.index).fillna(suppliers.promised_lead_time_days)
    sd = g.std().reindex(suppliers.index).fillna(1.0)
    return lt, sd


def policy(asof):
    """compute policy parameters using data strictly before `asof`."""
    hist = D[D.index < asof]
    recent = hist.iloc[-56:]
    d_recent = recent.mean().values
    sd_d = recent.std().values
    # seasonal adjustment from last year: next 30 days vs the 56 days before, one year ago
    ly = asof - pd.Timedelta(days=364)
    ly_next = D[(D.index >= ly) & (D.index < ly + pd.Timedelta(days=30))].mean().values
    ly_prev = D[(D.index >= ly - pd.Timedelta(days=56)) & (D.index < ly)].mean().values
    ratio = np.clip(ly_next / np.maximum(ly_prev, 0.05), 0.5, 2.0) if len(D[D.index < ly]) else 1.0
    d = d_recent * ratio
    lt_s, sdlt_s = supplier_lead_times(asof)
    lt = lt_s.loc[sup_of].values
    sdlt = sdlt_s.loc[sup_of].values
    ss = z * np.sqrt(lt * sd_d ** 2 + d ** 2 * sdlt ** 2)
    rop = d * lt + ss
    annual = d * 365
    eoq = np.sqrt(2 * annual * ORDER_COST / (HOLDING_RATE * unit_cost))
    q = np.maximum(np.ceil(eoq), moq)
    return pd.DataFrame({"daily_demand": d, "demand_std": sd_d, "lead_time": lt, "lead_time_std": sdlt,
                         "z": z, "safety_stock": np.ceil(ss), "reorder_point": np.ceil(rop),
                         "eoq": np.ceil(eoq), "order_qty": q}, index=pids)


# ======================================================== back-test on 2025
# Supplier behaviour is replayed from history: each simulated PO draws a
# real (actual - promised) lead-time deviation and fill ratio from that supplier.
rec = po.dropna(subset=["received_date"]).copy()
rec["lt_dev"] = (rec.received_date - rec.promised_date).dt.days
rec["fill"] = rec.qty_received / rec.qty_ordered
dev_pool = {s: g[["lt_dev", "fill"]].values for s, g in rec.groupby("supplier_id")}
promised = suppliers.loc[sup_of, "promised_lead_time_days"].values

bt_days = dates[dates >= "2025-01-01"]
start = dates.get_loc(bt_days[0])
on_hand = OH.iloc[start - 1].values.astype(float)          # same starting stock as reality
# carry over real POs that were open on 2024-12-31 so the start is fair
pipeline = [[] for _ in pids]
open_at_start = po[(po.order_date < "2025-01-01") & ((po.received_date >= "2025-01-01") | po.received_date.isna())]
pid_index = {p: i for i, p in enumerate(pids)}
for r in open_at_start.itertuples():
    arr = (r.received_date - bt_days[0]).days if pd.notna(r.received_date) else 9999
    pipeline[pid_index[r.product_id]].append([arr, r.qty_received if pd.notna(r.qty_received) else r.qty_ordered])

sim = {"on_hand": [], "sold": [], "lost": [], "stockout": []}
n_po, pol = 0, None
for t, day in enumerate(bt_days):
    if pol is None or day.day == 1:
        pol = policy(day)
    rop, q = pol.reorder_point.values, pol.order_qty.values
    dem = D.loc[day].values
    for i in range(len(pids)):
        arrived = sum(x[1] for x in pipeline[i] if x[0] == t)
        if arrived:
            on_hand[i] += arrived
            pipeline[i] = [x for x in pipeline[i] if x[0] != t]
    sold = np.minimum(dem, on_hand)
    on_hand -= sold
    sim["on_hand"].append(on_hand.copy()); sim["sold"].append(sold)
    sim["lost"].append(dem - sold); sim["stockout"].append(on_hand == 0)
    for i in range(len(pids)):
        position = on_hand[i] + sum(x[1] for x in pipeline[i])
        if position <= rop[i]:
            pool = dev_pool[sup_of[i]]
            dev, fill = pool[rng.integers(len(pool))]
            pipeline[i].append([t + max(1, int(promised[i] + dev)), np.floor(q[i] * fill)])
            n_po += 1

S = {k: np.array(v) for k, v in sim.items()}
base = inv[inv.snapshot_date >= "2025-01-01"]
base_po = po[(po.order_date >= "2025-01-01")]
inv_val_sim = (S["on_hand"] * unit_cost).sum(axis=1).mean()
inv_val_base = base.groupby("snapshot_date").inventory_value.sum().mean()
lost_base = (base.lost_units * base.product_id.map(products.unit_price)).sum()
lost_sim = (S["lost"] * unit_price).sum()
gm = (prod.unit_price - prod.unit_cost).values

comparison = pd.DataFrame({
    "metric": ["Stockout rate (% of SKU-days)", "Fill rate (% of demand met)", "Lost units",
               "Est. lost revenue ($)", "Est. lost gross profit ($)", "Avg inventory value ($)",
               "Annual carrying cost @25% ($)", "Purchase orders placed", "Ordering cost @$75/PO ($)"],
    "current_policy_2025": [base.stockout_flag.mean(), base.sold_qty.sum() / base.demand_qty.sum(),
                            base.lost_units.sum(), lost_base,
                            (base.lost_units * base.product_id.map(products.unit_price - products.unit_cost)).sum(),
                            inv_val_base, inv_val_base * HOLDING_RATE, len(base_po), len(base_po) * ORDER_COST],
    "optimized_policy_2025": [S["stockout"].mean(), S["sold"].sum() / D.loc[bt_days].values.sum(),
                              S["lost"].sum(), lost_sim, (S["lost"] * gm).sum(),
                              inv_val_sim, inv_val_sim * HOLDING_RATE, n_po, n_po * ORDER_COST],
})
comparison["change"] = comparison.optimized_policy_2025 - comparison.current_policy_2025
comparison["change_pct"] = comparison.change / comparison.current_policy_2025
comparison.to_csv(OUT / "policy_backtest_comparison.csv", index=False)
print(comparison.round(4).to_string(index=False))

# per-class view
cls = abc.abc_class.values
by_class = []
for c in "ABC":
    m = cls == c
    b = base[base.product_id.isin(pids[m])]
    by_class.append({"abc_class": c, "stockout_rate_current": b.stockout_flag.mean(),
                     "stockout_rate_optimized": S["stockout"][:, m].mean(),
                     "inv_value_current": b.groupby("snapshot_date").inventory_value.sum().mean(),
                     "inv_value_optimized": (S["on_hand"][:, m] * unit_cost[m]).sum(axis=1).mean()})
by_class = pd.DataFrame(by_class)
by_class.to_csv(OUT / "policy_backtest_by_class.csv", index=False)
print("\n", by_class.round(3).to_string(index=False))

# chart
fig, axes = plt.subplots(1, 2, figsize=(9, 3.4))
x = np.arange(3)
for ax, (cur, opt, title, fmt) in zip(axes, [
        ("stockout_rate_current", "stockout_rate_optimized", "Stockout rate by ABC class", "{:.1%}"),
        ("inv_value_current", "inv_value_optimized", "Avg inventory value by ABC class", "${:,.0f}")]):
    ax.bar(x - 0.2, by_class[cur], 0.4, color="#9aa5b1", label="Current policy")
    ax.bar(x + 0.2, by_class[opt], 0.4, color="#2a9d8f", label="Optimized policy")
    ax.set_xticks(x, ["A", "B", "C"]); ax.set_title(title, fontweight="bold")
    ax.spines[["top", "right"]].set_visible(False)
    if "rate" in cur:
        ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.0%}"))
    else:
        ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"${v/1e3:.0f}K"))
axes[0].legend(frameon=False, fontsize=8)
fig.suptitle("2025 back-test: current vs optimized replenishment policy", fontweight="bold")
fig.tight_layout(); fig.savefig(OUT / "charts/08_policy_backtest.png", dpi=130); plt.close(fig)

# ======================================================== recommendations as of today (end of data)
asof = dates[-1] + pd.Timedelta(days=1)
rec_pol = policy(asof)
open_po = po[po.received_date.isna()].groupby("product_id").qty_ordered.sum()
plan = prod[["product_name", "category", "supplier_id", "unit_cost", "unit_price"]].join(
    abc[["abc_class", "xyz_class"]]).join(rec_pol)
plan["service_level"] = plan.abc_class.map(SERVICE)
plan["moq"] = moq
plan["on_hand"] = OH.iloc[-1].values
plan["on_order"] = open_po.reindex(pids).fillna(0).values
plan["inventory_position"] = plan.on_hand + plan.on_order
plan["days_of_cover"] = plan.on_hand / plan.daily_demand.clip(lower=0.01)
EXCESS_DAYS = 120   # same rule as the Excel workbook
max_stock = np.maximum(plan.reorder_point + plan.order_qty, plan.daily_demand * EXCESS_DAYS)
plan["excess_units"] = (plan.inventory_position - max_stock).clip(lower=0)
plan["excess_value"] = plan.excess_units * plan.unit_cost
plan["action"] = np.select(
    [plan.inventory_position <= plan.reorder_point, plan.excess_units > 0],
    ["REORDER NOW", "EXCESS - pause orders / promote"], "OK")
plan["suggested_order_qty"] = np.where(plan.action == "REORDER NOW", plan.order_qty, 0)
plan = plan.reset_index().rename(columns={"index": "product_id"})
plan.to_csv(OUT / "replenishment_plan.csv", index=False)
print("\nAction counts:\n", plan.action.value_counts())
print("Excess value: $", round(plan.excess_value.sum()))

summary = {r.metric: {"current": r.current_policy_2025, "optimized": r.optimized_policy_2025,
                      "change_pct": r.change_pct} for r in comparison.itertuples()}
(OUT / "policy_summary.json").write_text(json.dumps(summary, indent=2, default=float))
