"""
07_build_excel.py
Builds outputs/Inventory_Optimization_Workbook.xlsx: a working planning tool
for a buyer, not just a data dump. The Replenishment Plan and ABC sheets use
live Excel formulas driven by the Assumptions sheet, so changing a service
level or the order cost recalculates safety stock, reorder points and actions.
"""
from pathlib import Path
import json
import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.formatting.rule import CellIsRule, FormulaRule
from openpyxl.utils import get_column_letter
from openpyxl.comments import Comment

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"

F = "Arial"
H_FILL = PatternFill("solid", fgColor="1F3A5F")
H_FONT = Font(name=F, bold=True, color="FFFFFF", size=10)
BODY = Font(name=F, size=10)
INPUT = Font(name=F, size=10, color="0000FF")
LINK = Font(name=F, size=10, color="008000")
BOLD = Font(name=F, size=10, bold=True)
TITLE = Font(name=F, size=16, bold=True, color="1F3A5F")
SUB = Font(name=F, size=10, italic=True, color="5F6B7A")
YELLOW = PatternFill("solid", fgColor="FFF2CC")
THIN = Border(bottom=Side(style="thin", color="D9DEE5"))
CUR, CUR2, PCT, NUM, NUM1 = '$#,##0;($#,##0);"-"', '$#,##0.00', '0.0%;(0.0%);"-"', '#,##0;(#,##0);"-"', '#,##0.0'

wb = Workbook()


def header(ws, row, cols, widths=None):
    for j, c in enumerate(cols, 1):
        cell = ws.cell(row=row, column=j, value=c)
        cell.font, cell.fill = H_FONT, H_FILL
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[row].height = 32
    if widths:
        for j, w in enumerate(widths, 1):
            ws.column_dimensions[get_column_letter(j)].width = w
    ws.freeze_panes = ws.cell(row=row + 1, column=1)


def title(ws, text, subtitle):
    ws["A1"], ws["A2"] = text, subtitle
    ws["A1"].font, ws["A2"].font = TITLE, SUB
    ws.sheet_view.showGridLines = False


def write_df(ws, df, start_row, formats, fonts=None):
    for i, row in enumerate(df.itertuples(index=False), start_row):
        for j, v in enumerate(row, 1):
            c = ws.cell(row=i, column=j, value=None if pd.isna(v) else v)
            c.font = (fonts or {}).get(j, BODY)
            c.border = THIN
            if j in formats:
                c.number_format = formats[j]


# ------------------------------------------------------------------ data
kpis = json.loads((OUT / "kpis.json").read_text())
plan = pd.read_csv(OUT / "replenishment_plan.csv")
abc = pd.read_csv(OUT / "abc_xyz_classification.csv").sort_values("revenue", ascending=False)
sup = pd.read_csv(OUT / "sql_results/q04_supplier_scorecard.csv")
health = pd.read_csv(OUT / "product_inventory_health.csv").sort_values("est_lost_revenue", ascending=False)
fc = pd.read_csv(OUT / "demand_forecast_next_13_weeks.csv")
fcm = pd.read_csv(OUT / "forecast_backtest_metrics.csv")
bt = pd.read_csv(OUT / "policy_backtest_comparison.csv")
clean = pd.read_csv(OUT / "cleaning_report.csv")
cat = pd.read_csv(OUT / "sql_results/q02_category_performance.csv")

# ================================================================== Assumptions
wa = wb.active
wa.title = "Assumptions"
title(wa, "Assumptions", "Blue text on yellow = inputs you can change. Every formula in the workbook reads from here.")
rows = [("Order cost per PO ($)", 75, CUR2, "Admin, receiving and fixed freight per purchase order. Industry rule of thumb; replace with your actual figure."),
        ("Annual holding cost (% of unit cost)", 0.25, PCT, "Capital, storage, insurance, obsolescence. 20-30% is the common range."),
        ("Service level: A items", 0.98, PCT, "Probability of not stocking out during a replenishment cycle."),
        ("Service level: B items", 0.95, PCT, ""),
        ("Service level: C items", 0.90, PCT, ""),
        ("Excess threshold (days of cover)", 120, NUM, "On-hand above this many days of forecast demand is flagged as excess.")]
header(wa, 4, ["Assumption", "Value", "Note"], [40, 14, 90])
wa.freeze_panes = None
for i, (k, v, fmt, note) in enumerate(rows, 5):
    wa.cell(row=i, column=1, value=k).font = BODY
    c = wa.cell(row=i, column=2, value=v)
    c.font, c.fill, c.number_format = INPUT, YELLOW, fmt
    wa.cell(row=i, column=3, value=note).font = SUB
wa["A12"], wa["A13"] = "Class", "A"
wa["A12"].font = BOLD
for r, (cls, ref) in enumerate([("A", "B7"), ("B", "B8"), ("C", "B9")], 13):
    wa.cell(row=r, column=1, value=cls).font = BODY
    wa.cell(row=r, column=2, value=f"={ref}").font = BODY
    wa.cell(row=r, column=2).number_format = PCT
wa["B12"] = "Service level"; wa["B12"].font = BOLD
wa["C12"] = "Lookup table used by the Replenishment Plan (do not edit; change B7:B9 instead)."
wa["C12"].font = SUB
ORDER_COST, HOLD, EXCESS_DAYS = "Assumptions!$B$5", "Assumptions!$B$6", "Assumptions!$B$10"

# ================================================================== Replenishment Plan
wp = wb.create_sheet("Replenishment Plan")
title(wp, "Replenishment Plan (as of 2026-01-01)",
      "Blue = data inputs from the Python pipeline. Black = live formulas. Change Assumptions to re-plan.")
cols = ["Product ID", "Product", "Category", "Supplier", "ABC", "XYZ", "Unit cost ($)",
        "Daily demand (units)", "Demand std dev", "Lead time (days)", "Lead time std dev", "MOQ",
        "On hand", "On order",
        "Service level", "Z score", "Safety stock", "Reorder point", "EOQ", "Order qty",
        "Inventory position", "Days of cover", "Excess units", "Excess value ($)", "Action", "Suggested order"]
header(wp, 4, cols, [10, 20, 16, 9, 6, 6, 10, 11, 10, 10, 10, 8, 9, 9, 10, 8, 10, 10, 9, 9, 11, 9, 10, 12, 30, 11])
pdata = plan[["product_id", "product_name", "category", "supplier_id", "abc_class", "xyz_class", "unit_cost",
              "daily_demand", "demand_std", "lead_time", "lead_time_std", "moq", "on_hand", "on_order"]].copy()
pdata = pdata.sort_values(["abc_class", "product_id"])
for c in ["daily_demand", "demand_std", "lead_time", "lead_time_std"]:
    pdata[c] = pdata[c].round(3)
write_df(wp, pdata, 5, {7: CUR2, 8: '0.00', 9: '0.00', 10: '0.0', 11: '0.0', 12: NUM, 13: NUM, 14: NUM},
         {j: INPUT for j in range(7, 15)})
n = len(pdata)
last = 4 + n
for r in range(5, last + 1):
    f = {
        15: f"=INDEX(Assumptions!$B$13:$B$15,MATCH(E{r},Assumptions!$A$13:$A$15,0))",
        16: f"=NORMSINV(O{r})",
        17: f"=ROUNDUP(P{r}*SQRT(J{r}*I{r}^2+H{r}^2*K{r}^2),0)",
        18: f"=ROUNDUP(H{r}*J{r}+Q{r},0)",
        19: f"=IF(H{r}>0,ROUNDUP(SQRT(2*H{r}*365*{ORDER_COST}/({HOLD}*G{r})),0),0)",
        20: f"=MAX(S{r},L{r})",
        21: f"=M{r}+N{r}",
        22: f"=IF(H{r}>0,M{r}/H{r},999)",
        23: f"=MAX(0,U{r}-MAX(R{r}+T{r},H{r}*{EXCESS_DAYS}))",
        24: f"=W{r}*G{r}",
        25: f'=IF(U{r}<=R{r},"REORDER NOW",IF(W{r}>0,"EXCESS - pause orders / promote","OK"))',
        26: f'=IF(Y{r}="REORDER NOW",T{r},0)',
    }
    for j, formula in f.items():
        c = wp.cell(row=r, column=j, value=formula)
        c.font, c.border = BODY, THIN
        c.number_format = {15: PCT, 16: '0.00', 22: NUM, 24: CUR}.get(j, NUM)
wp.conditional_formatting.add(f"Y5:Y{last}", FormulaRule(formula=[f'$Y5="REORDER NOW"'],
                              fill=PatternFill("solid", fgColor="F8D7DA"), font=Font(name=F, bold=True, color="9B1C2E")))
wp.conditional_formatting.add(f"Y5:Y{last}", FormulaRule(formula=[f'LEFT($Y5,6)="EXCESS"'],
                              fill=PatternFill("solid", fgColor="FFF3CD"), font=Font(name=F, bold=True, color="8A5A00")))
wp.auto_filter.ref = f"A4:Z{last}"
wp["Q4"].comment = Comment("Safety stock = Z x sqrt(LT x demand_std^2 + demand^2 x LT_std^2). "
                           "Covers both demand and supplier lead-time uncertainty.", "Model")
wp["S4"].comment = Comment("Economic order quantity = sqrt(2 x annual demand x order cost / annual holding cost per unit).", "Model")
wp["W4"].comment = Comment("Units above the larger of (reorder point + order qty) and the excess-days threshold.", "Model")
wp["H4"].comment = Comment("Expected daily demand: trailing 8-week unconstrained demand x last year's seasonal ratio.", "Model")
wp["J4"].comment = Comment("Supplier's ACTUAL average lead time from received POs, not the promised one.", "Model")
PLAN_LAST = last

# ================================================================== ABC Analysis
wc = wb.create_sheet("ABC Analysis")
title(wc, "ABC-XYZ Classification", "A = top 80% of revenue, B = next 15%, C = last 5%.  X/Y/Z = demand CV <0.5 / 0.5-1.0 / >1.0.")
header(wc, 4, ["Product ID", "Product", "Category", "Revenue ($)", "Share of revenue", "Cumulative share",
               "ABC (formula)", "Demand CV", "XYZ", "ABC-XYZ"], [10, 20, 16, 14, 12, 12, 12, 10, 8, 10])
a = abc[["product_id", "product_name", "category", "revenue", "demand_cv", "xyz_class"]].reset_index(drop=True)
alast = 4 + len(a)
for i, r in enumerate(a.itertuples(index=False), 5):
    vals = [r.product_id, r.product_name, r.category, round(r.revenue, 2)]
    for j, v in enumerate(vals, 1):
        c = wc.cell(row=i, column=j, value=v); c.font, c.border = (INPUT if j == 4 else BODY), THIN
    wc.cell(row=i, column=4).number_format = CUR
    wc.cell(row=i, column=5, value=f"=D{i}/SUM($D$5:$D${alast})").number_format = PCT
    wc.cell(row=i, column=6, value=f"=SUM($D$5:D{i})/SUM($D$5:$D${alast})").number_format = PCT
    wc.cell(row=i, column=7, value=f'=IF(F{i}<=0.8,"A",IF(F{i}<=0.95,"B","C"))')
    wc.cell(row=i, column=8, value=round(r.demand_cv, 3)).number_format = '0.00'
    wc.cell(row=i, column=9, value=r.xyz_class)
    wc.cell(row=i, column=10, value=f"=G{i}&I{i}")
    for j in range(5, 11):
        wc.cell(row=i, column=j).font, wc.cell(row=i, column=j).border = BODY, THIN
    wc.cell(row=i, column=8).font = INPUT
# summary block
wc["L4"], wc["M4"], wc["N4"], wc["O4"] = "Class", "Products", "% of SKUs", "% of revenue"
for c in ["L4", "M4", "N4", "O4"]:
    wc[c].font, wc[c].fill = H_FONT, H_FILL
for r, cls in enumerate("ABC", 5):
    wc[f"L{r}"] = cls
    wc[f"M{r}"] = f'=COUNTIF($G$5:$G${alast},L{r})'
    wc[f"N{r}"] = f"=M{r}/COUNTA($A$5:$A${alast})"; wc[f"N{r}"].number_format = PCT
    wc[f"O{r}"] = f'=SUMIF($G$5:$G${alast},L{r},$D$5:$D${alast})/SUM($D$5:$D${alast})'; wc[f"O{r}"].number_format = PCT
    for c in "LMNO":
        wc[f"{c}{r}"].font = BODY
for c, w in zip("LMNO", [8, 10, 11, 12]):
    wc.column_dimensions[c].width = w

# ================================================================== Supplier Scorecard
ws = wb.create_sheet("Supplier Scorecard")
title(ws, "Supplier Scorecard (2024-2025, received POs)", "Sorted worst OTIF first. Lead-time gap = actual minus promised.")
header(ws, 4, ["Supplier ID", "Supplier", "Country", "POs received", "Promised LT (days)", "Actual LT (days)",
               "LT gap (days)", "LT std dev", "On-time %", "In-full %", "OTIF %", "Avg days late (when late)", "Spend ($)", "Rating"],
       [10, 22, 10, 10, 11, 11, 10, 10, 10, 10, 10, 12, 13, 12])
sd = sup[["supplier_id", "supplier_name", "country", "pos_received", "promised_lt", "avg_actual_lt",
          "lt_std_dev", "on_time_pct", "in_full_pct", "otif_pct", "avg_days_late_when_late", "spend"]].copy()
for c in ["on_time_pct", "in_full_pct", "otif_pct"]:
    sd[c] = sd[c] / 100
for i, r in enumerate(sd.itertuples(index=False), 5):
    vals = list(r)
    vals.insert(6, None)
    for j, v in enumerate(vals, 1):
        c = ws.cell(row=i, column=j, value=v); c.font, c.border = (INPUT if j >= 4 else BODY), THIN
    ws.cell(row=i, column=7, value=f"=F{i}-E{i}").font = BODY
    ws.cell(row=i, column=14, value=f'=IF(K{i}<0.45,"Critical",IF(K{i}<0.55,"Needs review","Acceptable"))').font = BOLD
    for j, fmt in {5: NUM, 6: '0.0', 7: '0.0', 8: '0.0', 9: PCT, 10: PCT, 11: PCT, 12: '0.0', 13: CUR}.items():
        ws.cell(row=i, column=j).number_format = fmt
slast = 4 + len(sd)
ws.conditional_formatting.add(f"N5:N{slast}", CellIsRule(operator="equal", formula=['"Critical"'],
                              fill=PatternFill("solid", fgColor="F8D7DA")))
ws.conditional_formatting.add(f"N5:N{slast}", CellIsRule(operator="equal", formula=['"Needs review"'],
                              fill=PatternFill("solid", fgColor="FFF3CD")))

# ================================================================== Stockout Impact
wsi = wb.create_sheet("Stockout Impact")
title(wsi, "Stockout Impact by Product (2024-2025)", "Lost units = demand that arrived while the product was out of stock.")
header(wsi, 4, ["Product ID", "Product", "Category", "ABC", "Supplier", "Stockout days", "Stockout rate",
                "Lost units", "Unit price ($)", "Est. lost revenue ($)", "Turnover", "Days of inventory"],
       [10, 20, 16, 6, 9, 10, 10, 10, 10, 14, 9, 10])
h = health[["product_id", "product_name", "category", "abc_class", "supplier_id", "stockout_days", "stockout_rate",
            "lost_units", "unit_price", "turnover", "days_of_inventory"]].round(3)
for i, r in enumerate(h.itertuples(index=False), 5):
    vals = list(r)
    for j, v in enumerate(vals[:9], 1):
        c = wsi.cell(row=i, column=j, value=v); c.font, c.border = (INPUT if j >= 6 else BODY), THIN
    wsi.cell(row=i, column=10, value=f"=H{i}*I{i}").number_format = CUR
    wsi.cell(row=i, column=11, value=vals[9]).number_format = '0.0'
    wsi.cell(row=i, column=12, value=vals[10]).number_format = NUM
    for j in (10, 11, 12):
        wsi.cell(row=i, column=j).font, wsi.cell(row=i, column=j).border = BODY, THIN
    for j, fmt in {6: NUM, 7: PCT, 8: NUM, 9: CUR2}.items():
        wsi.cell(row=i, column=j).number_format = fmt
hlast = 4 + len(h)
wsi.auto_filter.ref = f"A4:L{hlast}"

# ================================================================== Demand Forecast
wf = wb.create_sheet("Demand Forecast")
title(wf, "13-Week Demand Forecast (Q1 2026, units)", f"Model: {fc.model.iloc[0]}. Forecasts unconstrained demand, not sales.")
piv = fc.pivot_table(index=["product_id", "product_name", "abc_class"], columns="week_ending",
                     values="forecast_units").reset_index()
weeks = [c for c in piv.columns if c not in ("product_id", "product_name", "abc_class")]
header(wf, 4, ["Product ID", "Product", "ABC"] + [f"Wk {w[5:]}" for w in weeks] + ["Q1 total"],
       [10, 20, 6] + [8] * len(weeks) + [10])
for i, r in enumerate(piv.itertuples(index=False), 5):
    for j, v in enumerate(r, 1):
        c = wf.cell(row=i, column=j, value=round(v, 1) if isinstance(v, float) else v)
        c.font, c.border = (INPUT if j > 3 else BODY), THIN
        if j > 3:
            c.number_format = NUM
    tc = wf.cell(row=i, column=4 + len(weeks), value=f"=SUM({get_column_letter(4)}{i}:{get_column_letter(3 + len(weeks))}{i})")
    tc.font, tc.number_format = BOLD, NUM
flast = 4 + len(piv)
wf.cell(row=flast + 1, column=1, value="Total").font = BOLD
for j in range(4, 5 + len(weeks)):
    col = get_column_letter(j)
    c = wf.cell(row=flast + 1, column=j, value=f"=SUM({col}5:{col}{flast})")
    c.font, c.number_format = BOLD, NUM
# backtest metrics
r0 = flast + 4
wf.cell(row=r0 - 1, column=1, value="Backtest accuracy (Q4 2025 holdout, lower WAPE is better)").font = BOLD
header_cells = ["Model", "WAPE all", "Bias", "WAPE A", "WAPE B", "WAPE C"]
for j, t in enumerate(header_cells, 1):
    c = wf.cell(row=r0, column=j, value=t); c.font, c.fill = H_FONT, H_FILL
for i, r in enumerate(fcm.itertuples(index=False), r0 + 1):
    for j, v in enumerate([r.model, r.WAPE_all, r.bias_pct, r.WAPE_A, r.WAPE_B, r.WAPE_C], 1):
        c = wf.cell(row=i, column=j, value=v); c.font = BODY
        if j > 1:
            c.number_format = PCT
wf.freeze_panes = "D5"

# ================================================================== Policy Backtest
wb_ = wb.create_sheet("Policy Backtest")
title(wb_, "2025 Back-test: Current vs Optimized Policy",
      "Optimized policy simulated on actual 2025 demand with replayed supplier lead times. Parameters refreshed monthly, no look-ahead.")
header(wb_, 4, ["Metric", "Current policy", "Optimized policy", "Change", "Change %"], [34, 16, 16, 16, 12])
for i, r in enumerate(bt.itertuples(index=False), 5):
    is_pct = "rate" in r.metric
    fmt = PCT if is_pct else (CUR if "$" in r.metric else NUM)
    wb_.cell(row=i, column=1, value=r.metric).font = BODY
    for j, v in [(2, r.current_policy_2025), (3, r.optimized_policy_2025)]:
        c = wb_.cell(row=i, column=j, value=round(v, 4)); c.font, c.number_format = INPUT, fmt
    c = wb_.cell(row=i, column=4, value=f"=C{i}-B{i}"); c.font, c.number_format = BODY, fmt
    c = wb_.cell(row=i, column=5, value=f"=IF(B{i}=0,0,D{i}/B{i})"); c.font, c.number_format = BOLD, PCT
    for j in range(1, 6):
        wb_.cell(row=i, column=j).border = THIN
blast = 4 + len(bt)

# ================================================================== Data Cleaning Log
wl = wb.create_sheet("Data Cleaning Log")
title(wl, "Data Cleaning Log", "Every correction applied by src/02_clean_data.py.")
header(wl, 4, ["Table", "Issue", "Rows affected", "Action"], [16, 60, 14, 36])
write_df(wl, clean, 5, {3: NUM})

# ================================================================== Summary (first sheet)
wsum = wb.create_sheet("Summary", 0)
title(wsum, "NorthStar Supply Co. — Inventory & Supply Chain Summary",
      "2024-2025, 150 SKUs, 10 suppliers. Synthetic data generated for a portfolio project.")
wsum.column_dimensions["A"].width = 38
wsum.column_dimensions["B"].width = 18
wsum.column_dimensions["C"].width = 70
items = [
    ("CURRENT PERFORMANCE (2024-2025)", None, None, None),
    ("Total revenue", kpis["total_revenue"], CUR, "Source: fact_sales"),
    ("Gross margin", kpis["gross_margin_pct"], PCT, ""),
    ("Revenue growth 2025 vs 2024", kpis["yoy_revenue_growth_pct"], PCT, "Demand grew ~2% but sales fell: stockouts rose in 2025"),
    ("Inventory turnover (annual)", kpis["inventory_turnover"], '0.0"x"', "Annual COGS / average inventory value"),
    ("Days of inventory", kpis["days_of_inventory"], NUM1, ""),
    ("Stockout rate (% of SKU-days)", kpis["stockout_rate_pct"], PCT, ""),
    ("Fill rate (% of demand met)", kpis["fill_rate_pct"], PCT, ""),
    ("Est. revenue lost to stockouts", kpis["est_lost_revenue"], CUR, "Lost units x list price"),
    ("Supplier OTIF", kpis["supplier_otif_pct"], PCT, "On-time AND in-full"),
    ("RECOMMENDED POLICY (2025 back-test)", None, None, None),
    ("Stockout rate: optimized (current at right)", "='Policy Backtest'!C5", PCT, "='Policy Backtest'!B5"),
    ("Revenue recovered vs current policy", "=-'Policy Backtest'!D8", CUR, "Lost revenue avoided in 2025"),
    ("Change in avg inventory value", "='Policy Backtest'!E10", PCT, "Fewer stockouts AND less capital tied up"),
    ("Purchase orders: change", "='Policy Backtest'!E12", PCT, ""),
    ("ACTION LIST TODAY", None, None, None),
    ("SKUs to reorder now", f"=COUNTIF('Replenishment Plan'!Y5:Y{PLAN_LAST},\"REORDER NOW\")", NUM, "See Replenishment Plan, filter column Y"),
    ("Suggested order value ($)", f"=SUMPRODUCT('Replenishment Plan'!Z5:Z{PLAN_LAST},'Replenishment Plan'!G5:G{PLAN_LAST})", CUR, ""),
    ("SKUs flagged as excess", f"=COUNTIF('Replenishment Plan'!Y5:Y{PLAN_LAST},\"EXCESS*\")", NUM, ""),
    ("Excess inventory value ($)", f"=SUM('Replenishment Plan'!X5:X{PLAN_LAST})", CUR, "Candidates for promotion, transfer or return-to-vendor"),
    ("Critical suppliers (OTIF < 45%)", f"=COUNTIF('Supplier Scorecard'!N5:N{slast},\"Critical\")", NUM, ""),
]
r = 4
for label, val, fmt, note in items:
    if val is None:
        r += 1
        c = wsum.cell(row=r, column=1, value=label); c.font = Font(name=F, bold=True, color="FFFFFF")
        for j in range(1, 4):
            wsum.cell(row=r, column=j).fill = H_FILL
    else:
        wsum.cell(row=r, column=1, value=label).font = BODY
        c = wsum.cell(row=r, column=2, value=val); c.number_format = fmt
        c.font = LINK if isinstance(val, str) and "!" in val else (BOLD if isinstance(val, str) else INPUT)
        n_ = wsum.cell(row=r, column=3, value=note)
        n_.font = LINK if note.startswith("=") else SUB
        if note.startswith("="):
            n_.number_format = PCT
            wsum.cell(row=r, column=3).alignment = Alignment(horizontal="left")
        for j in range(1, 4):
            wsum.cell(row=r, column=j).border = THIN
    r += 1
wsum.cell(row=r + 1, column=1, value="Colour key: blue = data from the pipeline, black = formula, green = link to another sheet.").font = SUB

path = OUT / "Inventory_Optimization_Workbook.xlsx"
wb.save(path)
print("saved", path)
