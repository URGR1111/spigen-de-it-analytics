-- RFM 분석
-- R: 기준일(마지막 주문일 +1) 대비 최근 구매 경과일  → 5분위 (최근일수록 5점)
-- F: 주문 횟수. 1회 구매 고객이 절반 이상이라 NTILE을 쓰면 동점이 여러 분위로 쪼개진다.
--    그래서 규칙 기반 구간을 쓴다: 1회=1, 2회=2, 3회=3, 4–5회=4, 6회 이상=5
-- M: 반품 제외 순매출 → 5분위

-- @ddl: v_rfm
DROP VIEW IF EXISTS v_rfm;
CREATE VIEW v_rfm AS
WITH ref AS (SELECT julianday(DATE(MAX(order_ts), '+1 day')) AS ref_jd FROM orders),
cust AS (
  SELECT o.user_id,
         u.country,
         u.acquisition_channel,
         CAST((SELECT ref_jd FROM ref) - julianday(MAX(o.order_ts)) AS INTEGER) AS recency_days,
         COUNT(*)                                                               AS frequency,
         ROUND(SUM(CASE WHEN o.is_returned = 1 THEN 0 ELSE o.net_amount_eur END), 2) AS monetary_eur
  FROM orders o
  JOIN users u USING (user_id)
  GROUP BY o.user_id, u.country, u.acquisition_channel
),
scored AS (
  SELECT *,
         6 - NTILE(5) OVER (ORDER BY recency_days ASC) AS r_score,
         CASE WHEN frequency >= 6 THEN 5 WHEN frequency >= 4 THEN 4 ELSE frequency END AS f_score,
         NTILE(5) OVER (ORDER BY monetary_eur ASC) AS m_score
  FROM cust
)
SELECT *,
       CASE
         WHEN r_score >= 4 AND f_score >= 4 AND m_score >= 4 THEN '1_Champions'
         WHEN r_score >= 3 AND f_score >= 3                  THEN '2_Loyal'
         WHEN r_score >= 4 AND f_score = 2                   THEN '3_Potential Loyalist'
         WHEN r_score >= 4 AND f_score = 1                   THEN '4_New Customers'
         WHEN r_score <= 2 AND f_score >= 3                  THEN '5_At Risk'
         WHEN r_score = 3                                    THEN '6_Need Attention'
         WHEN r_score <= 2 AND f_score = 2                   THEN '7_Hibernating'
         ELSE                                                     '8_Lost'
       END AS rfm_segment
FROM scored;

-- @name: rfm_segment_summary
SELECT rfm_segment,
       COUNT(*)                                                    AS customers,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1)          AS customer_share_pct,
       ROUND(SUM(monetary_eur), 0)                                 AS revenue_eur,
       ROUND(100.0 * SUM(monetary_eur) / SUM(SUM(monetary_eur)) OVER (), 1) AS revenue_share_pct,
       ROUND(AVG(recency_days), 0)                                 AS avg_recency_days,
       ROUND(AVG(frequency), 2)                                    AS avg_frequency,
       ROUND(AVG(monetary_eur), 1)                                 AS avg_monetary_eur
FROM v_rfm
GROUP BY rfm_segment
ORDER BY rfm_segment;

-- @name: rfm_by_channel
-- 유입 채널별 고객 가치: Champions+Loyal 비중과 1인당 누적 매출
SELECT acquisition_channel,
       COUNT(*)                                                         AS customers,
       ROUND(100.0 * AVG(rfm_segment IN ('1_Champions', '2_Loyal')), 1) AS champions_loyal_pct,
       ROUND(AVG(monetary_eur), 1)                                      AS avg_ltv_eur,
       ROUND(AVG(frequency), 2)                                         AS avg_orders
FROM v_rfm
GROUP BY acquisition_channel
ORDER BY avg_ltv_eur DESC;

-- @name: pareto_top_customers
-- 상위 5%·20% 고객의 매출 비중
WITH r AS (SELECT monetary_eur, PERCENT_RANK() OVER (ORDER BY monetary_eur DESC) AS pr FROM v_rfm)
SELECT ROUND(100.0 * SUM(CASE WHEN pr < 0.05 THEN monetary_eur END) / SUM(monetary_eur), 1) AS top5pct_revenue_share,
       ROUND(100.0 * SUM(CASE WHEN pr < 0.20 THEN monetary_eur END) / SUM(monetary_eur), 1) AS top20pct_revenue_share
FROM r;

-- @name: validation_rfm_vs_truth
-- [검증 전용] 합성 데이터의 숨은 세그먼트와 RFM 결과 비교. 실무 데이터에는 이 표가 없다.
SELECT r.rfm_segment,
       SUM(t.latent_segment = 'vip')     AS vip,
       SUM(t.latent_segment = 'loyal')   AS loyal,
       SUM(t.latent_segment = 'regular') AS regular,
       SUM(t.latent_segment = 'one_off') AS one_off
FROM v_rfm r JOIN _truth_users t USING (user_id)
GROUP BY r.rfm_segment
ORDER BY r.rfm_segment;
