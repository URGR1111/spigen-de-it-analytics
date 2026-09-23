-- 주제 1: 수요 캘린더 기반 광고 예산 배분
-- 현재 방식(월 예산 균등 배분)에서 수요가 높은 주와 낮은 주의 광고 효율이 얼마나 다른지 본다.
-- 수요지수 = 실측 Google Trends 주간 지수 (dim_calendar.demand_index)

-- @ddl: v_weekly_efficiency
DROP VIEW IF EXISTS v_weekly_efficiency;
CREATE VIEW v_weekly_efficiency AS
WITH spend AS (
  SELECT c.week_start, s.country,
         SUM(s.spend_eur) AS spend_eur, SUM(s.impressions) AS impressions, SUM(s.clicks) AS clicks
  FROM marketing_spend s
  JOIN dim_calendar c ON c.date = s.date AND c.country = s.country
  GROUP BY 1, 2
),
dem AS (
  SELECT week_start, country, AVG(demand_index) AS demand_index, COUNT(*) AS days
  FROM dim_calendar GROUP BY 1, 2
),
acq AS (
  SELECT c.week_start, o.country,
         COUNT(*)              AS new_paid_customers,
         SUM(o.net_amount_eur) AS first_order_revenue_eur
  FROM orders o
  JOIN dim_calendar c ON c.date = DATE(o.order_ts) AND c.country = o.country
  WHERE o.order_type = 'first'
    AND o.traffic_source IN ('meta_ads', 'google_search', 'tiktok_ads', 'influencer')
  GROUP BY 1, 2
)
SELECT d.week_start, d.country, d.days,
       ROUND(d.demand_index, 3)                                        AS demand_index,
       ROUND(s.spend_eur, 2)                                           AS spend_eur,
       COALESCE(a.new_paid_customers, 0)                               AS new_paid_customers,
       ROUND(COALESCE(a.first_order_revenue_eur, 0), 2)                AS first_order_revenue_eur,
       ROUND(s.spend_eur / NULLIF(a.new_paid_customers, 0), 2)         AS cac_eur,
       ROUND(COALESCE(a.first_order_revenue_eur, 0) / s.spend_eur, 3)  AS first_order_roas,
       ROUND(1.0 * s.clicks / s.impressions, 5)                        AS ctr
FROM dem d
JOIN spend s USING (week_start, country)
LEFT JOIN acq a USING (week_start, country);

-- @name: weekly_efficiency
SELECT * FROM v_weekly_efficiency WHERE days = 7 ORDER BY country, week_start;

-- @name: efficiency_by_demand_quintile
-- 수요 5분위별 효율 (국가별로 분위 산정). 균등 배분이면 광고비 비중은 분위마다 ~20%로 비슷하다.
WITH q AS (
  SELECT *, NTILE(5) OVER (PARTITION BY country ORDER BY demand_index) AS demand_q
  FROM v_weekly_efficiency WHERE days = 7
)
SELECT country, demand_q,
       ROUND(AVG(demand_index), 2)                                               AS avg_demand_index,
       ROUND(100.0 * SUM(spend_eur) / SUM(SUM(spend_eur)) OVER (PARTITION BY country), 1) AS spend_share_pct,
       ROUND(100.0 * SUM(new_paid_customers) / SUM(SUM(new_paid_customers)) OVER (PARTITION BY country), 1) AS acquisition_share_pct,
       ROUND(SUM(spend_eur) / SUM(new_paid_customers), 2)                        AS cac_eur,
       ROUND(SUM(first_order_revenue_eur) / SUM(spend_eur), 3)                   AS first_order_roas
FROM q
GROUP BY country, demand_q
ORDER BY country, demand_q;

-- @name: top8_weeks_gap
-- 최근 52주 중 수요 상위 8주: 수요 비중 vs 현재 광고비 비중
WITH last52 AS (
  SELECT * FROM v_weekly_efficiency
  WHERE days = 7
    AND week_start > (SELECT DATE(MAX(week_start), '-364 day') FROM v_weekly_efficiency WHERE days = 7)
),
r AS (SELECT *, ROW_NUMBER() OVER (PARTITION BY country ORDER BY demand_index DESC) AS rk FROM last52)
SELECT country,
       ROUND(100.0 * SUM(CASE WHEN rk <= 8 THEN demand_index END) / SUM(demand_index), 1) AS top8_demand_share_pct,
       ROUND(100.0 * SUM(CASE WHEN rk <= 8 THEN spend_eur END) / SUM(spend_eur), 1)       AS top8_spend_share_pct,
       ROUND(100.0 * SUM(CASE WHEN rk <= 8 THEN new_paid_customers END) / SUM(new_paid_customers), 1) AS top8_acquisition_share_pct
FROM r
GROUP BY country;
