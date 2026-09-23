-- 리텐션 코호트
-- 코호트 = 첫 구매 월. 구매 리텐션과 방문(세션) 리텐션을 함께 본다.
-- 액세서리는 구매 주기가 길어 월별 구매 리텐션이 낮으므로, 방문 리텐션이 이탈 신호를 더 빨리 보여준다.

-- @ddl: v_cohort
DROP VIEW IF EXISTS v_cohort;
CREATE VIEW v_cohort AS
SELECT user_id,
       strftime('%Y-%m', MIN(order_ts)) AS cohort_month,
       CAST(strftime('%Y', MIN(order_ts)) AS INTEGER) * 12 + CAST(strftime('%m', MIN(order_ts)) AS INTEGER) AS cohort_mi
FROM orders
GROUP BY user_id;

-- @name: purchase_retention_matrix
WITH act AS (
  SELECT DISTINCT o.user_id,
         CAST(strftime('%Y', o.order_ts) AS INTEGER) * 12 + CAST(strftime('%m', o.order_ts) AS INTEGER) AS mi
  FROM orders o
),
m AS (
  SELECT c.cohort_month, a.mi - c.cohort_mi AS month_index, COUNT(DISTINCT a.user_id) AS active_users
  FROM act a JOIN v_cohort c USING (user_id)
  GROUP BY 1, 2
),
size AS (SELECT cohort_month, COUNT(*) AS cohort_size FROM v_cohort GROUP BY 1)
SELECT m.cohort_month, s.cohort_size, m.month_index, m.active_users,
       ROUND(100.0 * m.active_users / s.cohort_size, 1) AS retention_pct
FROM m JOIN size s USING (cohort_month)
WHERE m.month_index BETWEEN 0 AND 12
ORDER BY 1, 3;

-- @name: visit_retention_matrix
WITH act AS (
  SELECT DISTINCT se.user_id,
         CAST(strftime('%Y', se.session_start_ts) AS INTEGER) * 12 + CAST(strftime('%m', se.session_start_ts) AS INTEGER) AS mi
  FROM sessions se
),
m AS (
  SELECT c.cohort_month, a.mi - c.cohort_mi AS month_index, COUNT(DISTINCT a.user_id) AS active_users
  FROM act a JOIN v_cohort c USING (user_id)
  WHERE a.mi >= c.cohort_mi
  GROUP BY 1, 2
),
size AS (SELECT cohort_month, COUNT(*) AS cohort_size FROM v_cohort GROUP BY 1)
SELECT m.cohort_month, s.cohort_size, m.month_index, m.active_users,
       ROUND(100.0 * m.active_users / s.cohort_size, 1) AS retention_pct
FROM m JOIN size s USING (cohort_month)
WHERE m.month_index BETWEEN 0 AND 12
ORDER BY 1, 3;

-- @name: retention_by_channel
-- 채널별 M1·M3·M6 구매 리텐션(누적 재구매율). 관측기간이 6개월 이상인 코호트만 사용.
WITH last AS (SELECT CAST(strftime('%Y', MAX(order_ts)) AS INTEGER) * 12 + CAST(strftime('%m', MAX(order_ts)) AS INTEGER) AS mi FROM orders),
ranked AS (
  SELECT user_id, order_ts, ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY order_ts) AS rn
  FROM orders
),
rep AS (
  SELECT c.user_id, c.cohort_mi,
         MIN(CASE WHEN r.rn >= 2 THEN CAST(strftime('%Y', r.order_ts) AS INTEGER) * 12
                                     + CAST(strftime('%m', r.order_ts) AS INTEGER) - c.cohort_mi END) AS first_repeat_month
  FROM v_cohort c JOIN ranked r USING (user_id)
  GROUP BY c.user_id, c.cohort_mi
)
SELECT u.acquisition_channel,
       COUNT(*)                                                    AS customers,
       ROUND(100.0 * AVG(COALESCE(r.first_repeat_month, 99) <= 1), 1) AS repeat_by_m1_pct,
       ROUND(100.0 * AVG(COALESCE(r.first_repeat_month, 99) <= 3), 1) AS repeat_by_m3_pct,
       ROUND(100.0 * AVG(COALESCE(r.first_repeat_month, 99) <= 6), 1) AS repeat_by_m6_pct
FROM rep r JOIN users u USING (user_id)
WHERE r.cohort_mi <= (SELECT mi FROM last) - 6
GROUP BY u.acquisition_channel
ORDER BY repeat_by_m6_pct DESC;

-- @name: churn_status_by_channel
-- 이탈 정의: 마지막 구매 후 180일 이상 경과 (가입 180일 이상 고객만)
WITH ref AS (SELECT julianday(MAX(order_ts)) AS jd FROM orders),
lastbuy AS (SELECT user_id, julianday(MAX(order_ts)) AS last_jd, julianday(MIN(order_ts)) AS first_jd FROM orders GROUP BY user_id)
SELECT u.acquisition_channel,
       COUNT(*)                                                            AS eligible_customers,
       ROUND(100.0 * AVG((SELECT jd FROM ref) - l.last_jd >= 180), 1)      AS churned_pct
FROM lastbuy l JOIN users u USING (user_id)
WHERE (SELECT jd FROM ref) - l.first_jd >= 180
GROUP BY u.acquisition_channel
ORDER BY churned_pct;
