-- 데이터 품질 점검
-- 블록 규칙: "-- @name: x" = 결과를 outputs/에 저장하는 조회, "-- @ddl: x" = 뷰 생성 등 실행만

-- @name: row_counts
SELECT 'users' AS tbl, COUNT(*) AS n FROM users
UNION ALL SELECT 'orders', COUNT(*) FROM orders
UNION ALL SELECT 'order_items', COUNT(*) FROM order_items
UNION ALL SELECT 'products', COUNT(*) FROM products
UNION ALL SELECT 'sessions', COUNT(*) FROM sessions
UNION ALL SELECT 'events', COUNT(*) FROM events
UNION ALL SELECT 'ab_assignments', COUNT(*) FROM ab_assignments
UNION ALL SELECT 'marketing_spend', COUNT(*) FROM marketing_spend;

-- @name: integrity_checks
-- 모든 값이 0이어야 정상
SELECT
  (SELECT COUNT(*) FROM order_items oi LEFT JOIN orders o USING (order_id) WHERE o.order_id IS NULL) AS orphan_items,
  (SELECT COUNT(*) FROM orders o LEFT JOIN users u USING (user_id) WHERE u.user_id IS NULL)          AS orphan_orders,
  (SELECT COUNT(*) FROM orders WHERE ABS(net_amount_eur - (gross_amount_eur - discount_amount_eur)) > 0.011) AS amount_mismatch,
  (SELECT COUNT(*) FROM (
      SELECT o.order_id FROM orders o JOIN order_items oi USING (order_id)
      GROUP BY o.order_id, o.net_amount_eur
      HAVING ABS(o.net_amount_eur - SUM(oi.line_amount_eur)) > 0.05))                             AS item_sum_mismatch,
  (SELECT COUNT(*) FROM orders o JOIN users u USING (user_id) WHERE o.order_ts < u.signup_ts)       AS order_before_signup,
  (SELECT COUNT(*) FROM events WHERE event_name = 'purchase' AND order_id IS NULL)                  AS purchase_without_order,
  (SELECT COUNT(*) FROM orders o LEFT JOIN events e
      ON e.order_id = o.order_id AND e.event_name = 'purchase' WHERE e.event_id IS NULL)            AS order_without_event;

-- @name: monthly_kpi
SELECT strftime('%Y-%m', order_ts)          AS month,
       country,
       COUNT(*)                             AS orders,
       COUNT(DISTINCT user_id)              AS buyers,
       ROUND(SUM(net_amount_eur), 0)        AS revenue_eur,
       ROUND(AVG(net_amount_eur), 2)        AS aov_eur,
       ROUND(100.0 * AVG(is_returned), 1)   AS return_rate_pct,
       ROUND(100.0 * AVG(promo_code IS NOT NULL), 1) AS promo_share_pct
FROM orders
GROUP BY 1, 2
ORDER BY 1, 2;

-- @name: funnel_by_source
-- 세션 단위 퍼널: 세션 → 상품조회 → 장바구니 → 결제시작 → 구매
WITH s AS (
  SELECT e.session_id,
         MAX(e.event_name = 'product_view')   AS pv,
         MAX(e.event_name = 'add_to_cart')    AS atc,
         MAX(e.event_name = 'begin_checkout') AS co,
         MAX(e.event_name = 'purchase')       AS pur
  FROM events e
  GROUP BY e.session_id
)
SELECT se.traffic_source,
       COUNT(*)                                  AS sessions,
       ROUND(100.0 * AVG(s.pv), 1)               AS product_view_pct,
       ROUND(100.0 * AVG(s.atc), 1)              AS add_to_cart_pct,
       ROUND(100.0 * AVG(s.co), 1)               AS checkout_pct,
       ROUND(100.0 * AVG(s.pur), 2)              AS session_cvr_pct
FROM s JOIN sessions se USING (session_id)
GROUP BY se.traffic_source
ORDER BY sessions DESC;
