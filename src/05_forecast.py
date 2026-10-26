"""
05_forecast.py
Weekly demand forecasting for all 150 products, 13 weeks (one quarter) ahead.

Key design choice: we forecast *unconstrained demand* (from the inventory
table, which includes demand lost to stockouts), not sales. Sales are capped
whenever a product is out of stock, so a model trained on sales would learn
to under-forecast exactly the products that already run out.

Models compared on a holdout of the last 13 weeks of 2025 (includes the
holiday peak, the hardest period to forecast):
  1. Naive          - average of the last 8 weeks
  2. Seasonal naive - same weeks last year, scaled by year-over-year level change
  3. Gradient boosting (global model across all products, direct multi-horizon,
     trained to correct the seasonal-naive signal)
  4. Ensemble       - average of 2 and 3

Metric: WAPE = sum(|actual - forecast|) / sum(actual). Preferred over MAPE
because MAPE blows up on low-volume weeks with near-zero demand.
"""
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
PROC, OUT = ROOT / "data/processed", ROOT / "outputs"
H = 13          # forecast horizon (weeks)
SEED = 42

inv = pd.read_csv(PROC / "fact_inventory_daily.csv", parse_dates=["snapshot_date"])
abc = pd.read_csv(OUT / "abc_xyz_classification.csv")
weekly = (inv.set_index("snapshot_date").groupby("product_id").demand_qty
             .resample("W-SUN").sum().unstack(0))
weekly = weekly.iloc[1:-1]            # full weeks only
Y = weekly.values.T.astype(float)     # products x weeks
P, W = Y.shape
week_dates = weekly.index
woy = week_dates.isocalendar().week.values.astype(int)
cat_code = abc.set_index("product_id").loc[weekly.columns, "category"].astype("category").cat.codes.values


def level(y, end, n):
    """mean of the n weeks ending just before index `end` (exclusive)."""
    return y[:, max(0, end - n):end].mean(axis=1)


def seasonal_naive(y, origin, h):
    lvl_now = level(y, origin, 13)
    lvl_ly = level(y, origin - 52, 13)
    ratio = np.clip(lvl_now / np.maximum(lvl_ly, 0.1), 0.3, 3.0)
    return y[:, origin + h - 1 - 52] * ratio


def features(y, origin, h):
    """features known at forecast origin for the week origin+h-1."""
    target_wk = origin + h - 1
    lvl4, lvl8, lvl13 = level(y, origin, 4), level(y, origin, 8), level(y, origin, 13)
    ly_same = y[:, target_wk - 52]
    ly_lvl13 = level(y, origin - 52, 13)
    ly_ratio = ly_same / np.maximum(ly_lvl13, 0.1)        # last year's seasonal shape
    return np.column_stack([
        np.full(P, h), np.full(P, woy[min(target_wk, W - 1)] if target_wk < W else woy[target_wk - 52]),
        cat_code, lvl4, lvl8, lvl13, ly_same, ly_lvl13, ly_ratio,
        lvl13 * ly_ratio,                                  # seasonal-naive-like signal
        lvl4 / np.maximum(lvl13, 0.1),                     # recent momentum
    ])


def build_training(y, last_origin):
    X, t, wts = [], [], []
    for origin in range(56, last_origin - H + 1, 2):
        for h in range(1, H + 1):
            X.append(features(y, origin, h))
            t.append(y[:, origin + h - 1])
    X, t = np.vstack(X), np.concatenate(t)
    return X, t


def fit_gbm(y, last_origin):
    X, t = build_training(y, last_origin)
    # model the ratio to the seasonal-naive signal: the GBM learns *corrections*
    # (momentum, category effects) rather than re-learning seasonality from scratch
    base = np.maximum(X[:, 9], 0.5)
    m = HistGradientBoostingRegressor(max_iter=400, learning_rate=0.05, max_leaf_nodes=31,
                                      min_samples_leaf=40, l2_regularization=1.0, random_state=SEED)
    m.fit(X, t / base, sample_weight=base)
    return m


def predict_gbm(m, y, origin, h):
    X = features(y, origin, h)
    return np.clip(m.predict(X) * np.maximum(X[:, 9], 0.5), 0, None)


def wape(a, f):
    return np.abs(a - f).sum() / a.sum()


# ======================================================== backtest
origin = W - H
actual = Y[:, origin:origin + H]
fc = {
    "Naive (8-wk avg)": np.column_stack([level(Y, origin, 8)] * H),
    "Seasonal naive": np.column_stack([seasonal_naive(Y, origin, h) for h in range(1, H + 1)]),
}
gbm = fit_gbm(Y, origin)
fc["Gradient boosting"] = np.column_stack([predict_gbm(gbm, Y, origin, h) for h in range(1, H + 1)])
fc["Ensemble (SN + GBM)"] = (fc["Seasonal naive"] + fc["Gradient boosting"]) / 2

abc_cls = abc.set_index("product_id").loc[weekly.columns, "abc_class"].values
rows = []
for name, f in fc.items():
    r = {"model": name, "WAPE_all": wape(actual, f),
         "bias_pct": (f.sum() - actual.sum()) / actual.sum()}
    for c in "ABC":
        r[f"WAPE_{c}"] = wape(actual[abc_cls == c], f[abc_cls == c])
    r["WAPE_total_quarter"] = wape(actual.sum(axis=1), f.sum(axis=1))  # product-quarter level
    rows.append(r)
metrics = pd.DataFrame(rows)
metrics.to_csv(OUT / "forecast_backtest_metrics.csv", index=False)
print("Backtest: forecast origin", week_dates[origin - 1].date(), "-> 13 weeks\n")
print(metrics.round(3).to_string(index=False))
best = metrics.sort_values("WAPE_all").iloc[0].model
print("\nBest model:", best)

# backtest chart: total demand
fig, ax = plt.subplots(figsize=(9, 3.6))
hist = slice(origin - 40, origin + H)
ax.plot(week_dates[hist], Y[:, hist].sum(axis=0), color="#1f3a5f", lw=2, label="Actual demand")
styles = {"Naive (8-wk avg)": ("#9aa5b1", ":"), "Seasonal naive": ("#e9a23b", "--"),
          "Gradient boosting": ("#2a9d8f", "-."), "Ensemble (SN + GBM)": ("#d1495b", "-")}
for name, f in fc.items():
    c, ls = styles[name]
    ax.plot(week_dates[origin:origin + H], f.sum(axis=0), color=c, ls=ls, lw=2,
            label=f"{name} (WAPE {metrics.set_index('model').WAPE_all[name]:.0%})")
ax.axvline(week_dates[origin], color="grey", lw=0.8)
ax.set_title("Forecast backtest: total weekly demand, Q4 2025 holdout")
ax.legend(frameon=False, fontsize=8)
ax.spines[["top", "right"]].set_visible(False)
fig.tight_layout(); fig.savefig(OUT / "charts/07_forecast_backtest.png", dpi=130); plt.close(fig)

# ======================================================== production forecast: next 13 weeks
# Extend the arrays with empty future weeks so feature code can index them
future_dates = pd.date_range(week_dates[-1] + pd.Timedelta(weeks=1), periods=H, freq="W-SUN")
Y_ext = np.hstack([Y, np.zeros((P, H))])
woy = np.concatenate([woy, future_dates.isocalendar().week.values.astype(int)])
W = Y_ext.shape[1]
final = fit_gbm(Y, Y.shape[1]) if "Gradient" in best or "Ensemble" in best else None
out = []
for h in range(1, H + 1):
    sn = seasonal_naive(Y_ext, Y.shape[1], h)
    if best == "Ensemble (SN + GBM)":
        f = (sn + predict_gbm(final, Y_ext, Y.shape[1], h)) / 2
    elif best == "Gradient boosting":
        f = predict_gbm(final, Y_ext, Y.shape[1], h)
    elif best == "Seasonal naive":
        f = sn
    else:
        f = level(Y, Y.shape[1], 8)
    out.append(pd.DataFrame({"product_id": weekly.columns, "week_ending": future_dates[h - 1],
                             "forecast_units": f.round(1)}))
forecast = pd.concat(out).merge(abc[["product_id", "product_name", "category", "abc_class"]], on="product_id")
forecast["model"] = best
forecast.to_csv(OUT / "demand_forecast_next_13_weeks.csv", index=False, date_format="%Y-%m-%d")
print(f"\nForecast for {future_dates[0].date()} .. {future_dates[-1].date()}: "
      f"{forecast.forecast_units.sum():,.0f} units")
