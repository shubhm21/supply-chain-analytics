# Power BI Build Guide

This walks you through building the four-page dashboard from the pipeline's
output files. Budget about 3 to 4 hours the first time. Power BI Desktop is
free and Windows-only; on a Mac, use a Windows VM or a lab machine.

Build it yourself rather than skipping ahead: in interviews you will be asked
how a measure works or why a relationship points a certain way, and having
clicked through it is what lets you answer confidently.

---

## Step 1. Run the pipeline

```bash
pip install -r requirements.txt
python run_all.py
```

## Step 2. Import data (Home > Get data > Text/CSV)

| Load this file | Name the table |
|---|---|
| `outputs/abc_xyz_classification.csv` | `dim_products` (this version already has ABC/XYZ, revenue and `revenue_rank`) |
| `data/processed/dim_suppliers.csv` | `dim_suppliers` |
| `data/processed/fact_sales.csv` | `fact_sales` |
| `data/processed/fact_inventory_daily.csv` | `fact_inventory_daily` |
| `data/processed/fact_purchase_orders.csv` | `fact_purchase_orders` |
| `outputs/replenishment_plan.csv` | `replenishment_plan` |
| `outputs/demand_forecast_next_13_weeks.csv` | `demand_forecast` |
| `outputs/policy_backtest_comparison.csv` | `policy_backtest` |

In **Power Query** (Transform data), check types before loading:
date columns as *Date*, `quantity`/`on_hand_qty` as *Whole number*, money as
*Fixed decimal*, and `on_time`, `in_full`, `otif` as *Decimal* (blanks must stay
null, not 0, or open POs will drag OTIF down). In `fact_sales`, remove the
`category` column: category should come from `dim_products` so there is one
source of truth.

## Step 3. Date table and model

1. **Modeling > New table**, paste the `dim_date` block from `measures.dax`.
   Mark it as a date table, and sort `Month` by `Month Num`.
2. In **Model view**, create these relationships (all single direction, one to many):

```
dim_date[Date]            1 ──► *  fact_sales[order_date]
dim_date[Date]            1 ──► *  fact_inventory_daily[snapshot_date]
dim_date[Date]            1 ──► *  fact_purchase_orders[order_date]
dim_date[Date]            1 ──► *  demand_forecast[week_ending]
dim_products[product_id]  1 ──► *  fact_sales[product_id]
dim_products[product_id]  1 ──► *  fact_inventory_daily[product_id]
dim_products[product_id]  1 ──► *  fact_purchase_orders[product_id]
dim_products[product_id]  1 ──► *  replenishment_plan[product_id]
dim_products[product_id]  1 ──► *  demand_forecast[product_id]
dim_suppliers[supplier_id] 1 ──► * dim_products[supplier_id]
```

Do **not** also connect `dim_suppliers` directly to `fact_purchase_orders`.
That creates two filter paths and Power BI will make one inactive. Supplier
filters reach POs through `dim_products`, which is a clean snowflake.

3. Create an empty `_Measures` table, then add every measure from `measures.dax`.
4. **Modeling > New parameter > Numeric range**: name `Holding Rate`,
   0.10 to 0.40, step 0.01, default 0.25. This drives `Annual Carrying Cost`
   and lets a viewer test assumptions with a slider.
5. Hide the raw ID and key columns from report view (right-click > Hide).

## Step 4. Theme

**View > Themes > Browse for themes** and load `northstar_theme.json`.
Canvas size: 1280 x 720.

---

## Step 5. Pages

### Page 1: Executive Overview
Answers: *how is the business doing and what are stockouts costing us?*

- **Slicers** across the top: `dim_date[Year]`, `dim_products[category]`, `fact_sales[region]`.
- **8 KPI cards**: Total Revenue, Gross Margin %, Revenue YoY %, Inventory
  Turnover, Fill Rate %, Stockout Rate %, Lost Revenue, OTIF %.
  Use the new card visual and add `Revenue PY` as a reference label on the revenue card.
- **Line chart**: X `dim_date[Year-Month]`, Y `Total Revenue` and `Revenue PY`.
- **Clustered bar**: `dim_products[category]` by `Total Revenue`, tooltip `Gross Margin %`.
- **Text box headline**: *"Demand grew 1.7% in 2025 but units sold fell 1.4%:
  stockouts rose from 5.0% to 6.3% of SKU-days."* A headline that states the
  insight is what separates an analyst's dashboard from a chart gallery.

### Page 2: Inventory Health
Answers: *which products are we losing money on, and why?*

- **ABC Pareto** (Line and clustered column chart): X `dim_products[product_id]`
  sorted by `revenue_rank`, columns `Total Revenue` coloured by `abc_class`,
  line `Cumulative Revenue %`. Add constant lines at 80% and 95%.
- **Matrix**: rows `abc_class`, columns `xyz_class`, values count of `product_id`.
- **Bar**: Top 15 products by `Lost Revenue` (Filters pane > Top N = 15).
- **Scatter**: X `Inventory Turnover`, Y `Stockout Rate %`, size `Total Revenue`,
  legend `abc_class`, details `product_name`. Top-left quadrant = understocked
  winners; bottom-right = overstocked slow movers.
- **Insight callout**: A items have the *highest* stockout rate (8.7%) despite
  being the most important. Safety stock was not prioritised by value.

### Page 3: Supplier Performance
Answers: *which suppliers are causing the stockouts?*

- **Bar**: `dim_suppliers[supplier_name]` by `OTIF %`, colour via
  Format > Bars > fx > Field value > `OTIF Color`. Add `OTIF Target` as a constant line.
- **Clustered bar**: supplier by `Avg Promised Lead Time` vs `Avg Actual Lead Time`.
- **Scatter**: X `PO Spend`, Y `OTIF %`, details supplier. High spend + low
  OTIF (Summit Packaging) is the renegotiation priority.
- **Line**: `OTIF %` by `dim_date[Quarter]` and `Year`, to show whether it is improving.
- **Table**: supplier, POs, On-Time %, In-Full %, OTIF %, Lead Time Gap, PO Spend.

### Page 4: Forecast & Replenishment
Answers: *what should the buyer do on Monday morning?*

- **Cards**: SKUs to Reorder, Suggested Order Value, Excess SKUs, Excess Inventory Value.
- **Line chart**: X `dim_date[Week Ending]`, values `Weekly Demand (actual)`
  and `Forecast Units`. History and forecast meet at the start of 2026.
- **Table**: from `replenishment_plan`: product_name, abc_class, on_hand,
  reorder_point, safety_stock, order_qty, days_of_cover, action. Background
  colour on `action` via fx > Field value > `Action Color`. Default sort: action.
- **Table**: `policy_backtest` (metric, current, optimized, change_pct) with the
  title *"Back-test: optimized policy on 2025 demand"*.
- **Slicer**: `replenishment_plan[action]` as tiles.

---

## Step 6. Polish (the part most portfolio dashboards skip)

- Every visual gets a title that is a *finding*, not a label.
  "Two suppliers deliver fewer than half of POs on time and in full" beats "OTIF by supplier".
- Add a **drill-through page** on `product_id` showing that product's daily
  on-hand vs demand line and its PO history.
- Turn on **tooltips** with product category, ABC class and supplier.
- Use **bookmarks** for a "Reset filters" button.
- Add a small footer on each page: *Data: synthetic, generated for portfolio use.*

## Step 7. Publish and share

1. **File > Publish to web** needs a work/school account. If you don't have one,
   export the report to PDF (**File > Export > PDF**) and take PNG screenshots
   of each page for the GitHub README.
2. Commit the `.pbix` to the repo (it's usually under 10 MB with this data).
3. Put the screenshots at the top of your README so a recruiter sees the
   dashboard without downloading anything.
