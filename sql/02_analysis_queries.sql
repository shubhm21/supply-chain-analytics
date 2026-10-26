-- 02_analysis_queries.sql
-- Core business questions answered in SQL. Each query is tagged with
-- "-- name:" so src/03_run_sql.py can execute it and export the result.
-- Uses CTEs and window functions (SQLite 3.25+, PostgreSQL, SQL Server).


-- name: q01_monthly_revenue_trend
-- How are revenue and profit trending month over month?
WITH monthly AS (
    SELECT strftime('%Y-%m', order_date) AS month,
           ROUND(SUM(revenue), 2)        AS revenue,
           ROUND(SUM(gross_profit), 2)   AS gross_profit,
           SUM(quantity)                 AS units
    FROM fact_sales
    GROUP BY 1
)
SELECT month, revenue, gross_profit, units,
       ROUND(100.0 * (revenue - LAG(revenue) OVER (ORDER BY month))
             / LAG(revenue) OVER (ORDER BY month), 1)            AS mom_growth_pct,
       ROUND(100.0 * (revenue - LAG(revenue, 12) OVER (ORDER BY month))
             / LAG(revenue, 12) OVER (ORDER BY month), 1)        AS yoy_growth_pct
FROM monthly
ORDER BY month;


-- name: q02_category_performance
-- Which categories drive revenue and margin?
SELECT category,
       ROUND(SUM(revenue), 0)                              AS revenue,
       ROUND(SUM(gross_profit), 0)                         AS gross_profit,
       ROUND(100.0 * SUM(gross_profit) / SUM(revenue), 1)  AS gross_margin_pct,
       ROUND(100.0 * SUM(revenue) / SUM(SUM(revenue)) OVER (), 1) AS revenue_share_pct
FROM fact_sales
GROUP BY category
ORDER BY revenue DESC;


-- name: q03_abc_classification
-- ABC analysis: A = top 80% of revenue, B = next 15%, C = last 5%.
WITH prod_rev AS (
    SELECT product_id, SUM(revenue) AS revenue
    FROM fact_sales GROUP BY product_id
),
ranked AS (
    SELECT product_id, revenue,
           SUM(revenue) OVER (ORDER BY revenue DESC ROWS UNBOUNDED PRECEDING)
             / SUM(revenue) OVER ()  AS cum_share
    FROM prod_rev
)
SELECT product_id, ROUND(revenue, 2) AS revenue,
       ROUND(100 * cum_share, 2) AS cum_revenue_pct,
       CASE WHEN cum_share <= 0.80 THEN 'A'
            WHEN cum_share <= 0.95 THEN 'B'
            ELSE 'C' END AS abc_class
FROM ranked
ORDER BY revenue DESC;


-- name: q04_supplier_scorecard
-- Which suppliers deliver late, short, or with unpredictable lead times?
SELECT s.supplier_id, s.supplier_name, s.country,
       COUNT(*)                                          AS pos_received,
       s.promised_lead_time_days                         AS promised_lt,
       ROUND(AVG(po.actual_lead_time_days), 1)           AS avg_actual_lt,
       ROUND(SQRT(AVG(po.actual_lead_time_days * po.actual_lead_time_days)
                  - AVG(po.actual_lead_time_days) * AVG(po.actual_lead_time_days)), 1) AS lt_std_dev,
       ROUND(100.0 * AVG(po.on_time), 1)                 AS on_time_pct,
       ROUND(100.0 * AVG(po.in_full), 1)                 AS in_full_pct,
       ROUND(100.0 * AVG(po.otif), 1)                    AS otif_pct,
       ROUND(AVG(CASE WHEN po.days_late > 0 THEN po.days_late END), 1) AS avg_days_late_when_late,
       ROUND(SUM(po.po_value), 0)                        AS spend
FROM fact_purchase_orders po
JOIN dim_suppliers s USING (supplier_id)
WHERE po.received_date IS NOT NULL
GROUP BY s.supplier_id
ORDER BY otif_pct ASC;


-- name: q05_stockouts_and_lost_revenue
-- Which products run out most often, and what does it cost?
SELECT i.product_id, p.product_name, p.category, p.supplier_id,
       SUM(i.stockout_flag)                                   AS stockout_days,
       ROUND(100.0 * AVG(i.stockout_flag), 1)                 AS stockout_rate_pct,
       SUM(i.lost_units)                                      AS lost_units,
       ROUND(SUM(i.lost_units) * p.unit_price, 0)             AS est_lost_revenue
FROM fact_inventory_daily i
JOIN dim_products p USING (product_id)
GROUP BY i.product_id
HAVING SUM(i.stockout_flag) > 0
ORDER BY est_lost_revenue DESC;


-- name: q06_inventory_turnover
-- Turnover = annual COGS / average inventory value; DOI = 365 / turnover.
WITH cogs AS (
    SELECT product_id, SUM(cogs) / 2.0 AS annual_cogs   -- 2 years of data
    FROM fact_sales GROUP BY product_id
),
inv AS (
    SELECT product_id, AVG(inventory_value) AS avg_inv_value,
           AVG(on_hand_qty) AS avg_on_hand
    FROM fact_inventory_daily GROUP BY product_id
)
SELECT p.product_id, p.product_name, p.category,
       ROUND(inv.avg_inv_value, 0)                            AS avg_inventory_value,
       ROUND(cogs.annual_cogs, 0)                             AS annual_cogs,
       ROUND(cogs.annual_cogs / NULLIF(inv.avg_inv_value, 0), 2) AS turnover,
       ROUND(365.0 * inv.avg_inv_value / NULLIF(cogs.annual_cogs, 0), 0) AS days_of_inventory
FROM dim_products p
JOIN inv  USING (product_id)
LEFT JOIN cogs USING (product_id)
ORDER BY days_of_inventory DESC;


-- name: q07_slow_moving_excess
-- Excess stock: current on-hand covers more than 120 days of recent demand.
WITH last90 AS (
    SELECT product_id, SUM(quantity) / 90.0 AS avg_daily_units
    FROM fact_sales
    WHERE order_date > date((SELECT MAX(order_date) FROM fact_sales), '-90 day')
    GROUP BY product_id
),
current_inv AS (
    SELECT product_id, on_hand_qty, inventory_value
    FROM fact_inventory_daily
    WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM fact_inventory_daily)
)
SELECT c.product_id, p.product_name, p.category, c.on_hand_qty,
       ROUND(l.avg_daily_units, 2) AS avg_daily_units_90d,
       ROUND(c.on_hand_qty / NULLIF(l.avg_daily_units, 0), 0) AS days_of_cover,
       ROUND(c.inventory_value, 0) AS inventory_value,
       ROUND(c.inventory_value - 60 * l.avg_daily_units * p.unit_cost, 0) AS excess_value_over_60d
FROM current_inv c
JOIN dim_products p USING (product_id)
LEFT JOIN last90 l USING (product_id)
WHERE c.on_hand_qty / NULLIF(l.avg_daily_units, 0) > 120
ORDER BY excess_value_over_60d DESC;


-- name: q08_seasonality_by_category
-- Average daily units by calendar month: reveals each category's peak season.
SELECT category,
       CAST(strftime('%m', order_date) AS INTEGER) AS month_num,
       ROUND(SUM(quantity) * 1.0 / COUNT(DISTINCT order_date), 1) AS avg_daily_units
FROM fact_sales
GROUP BY category, month_num
ORDER BY category, month_num;


-- name: q09_regional_sales
SELECT region,
       ROUND(SUM(revenue), 0) AS revenue,
       ROUND(100.0 * SUM(revenue) / SUM(SUM(revenue)) OVER (), 1) AS share_pct,
       COUNT(*) AS order_lines
FROM fact_sales
GROUP BY region
ORDER BY revenue DESC;
