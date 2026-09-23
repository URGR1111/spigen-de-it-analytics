-- A/B 테스트: 장바구니 번들 업셀 (EXP_2026_04_CART_BUNDLE)
-- 분석 단위: 노출 사용자 (장바구니 페이지 첫 도달 시점에 배정)
-- 주요 지표: 사용자당 매출(RPU). 보조: 구매전환율, 객단가. 가드레일: 반품률
-- 통계 검정은 src/analyze.py에서 수행한다.

-- @name: srm_check
SELECT variant, COUNT(*) AS users FROM ab_assignments GROUP BY variant;

-- @ddl: v_ab_user
DROP VIEW IF EXISTS v_ab_user;
CREATE VIEW v_ab_user AS
SELECT a.user_id,
       a.variant,
       a.country,
       COUNT(o.order_id)                          AS orders,
       CASE WHEN COUNT(o.order_id) > 0 THEN 1 ELSE 0 END AS converted,
       COALESCE(SUM(o.net_amount_eur), 0)         AS revenue_eur,
       COALESCE(SUM(o.has_bundle_upsell), 0)      AS bundle_orders,
       COALESCE(SUM(o.is_returned), 0)            AS returned_orders
FROM ab_assignments a
LEFT JOIN orders o
       ON o.user_id = a.user_id
      AND o.ab_variant IS NOT NULL
GROUP BY a.user_id, a.variant, a.country;

-- @name: ab_user_summary
SELECT variant,
       COUNT(*)                                      AS users,
       SUM(converted)                                AS converters,
       ROUND(AVG(converted), 5)                      AS cvr,
       SUM(orders)                                   AS orders,
       ROUND(SUM(revenue_eur), 2)                    AS revenue_eur,
       ROUND(AVG(revenue_eur), 4)                    AS rpu_eur,
       ROUND(AVG(revenue_eur * revenue_eur) - AVG(revenue_eur) * AVG(revenue_eur), 4) AS rpu_var,
       ROUND(1.0 * SUM(bundle_orders) / SUM(orders), 4)   AS bundle_attach_rate,
       ROUND(1.0 * SUM(returned_orders) / SUM(orders), 4) AS return_rate
FROM v_ab_user
GROUP BY variant
ORDER BY variant;

-- @name: ab_order_summary
SELECT ab_variant AS variant,
       COUNT(*)                         AS orders,
       ROUND(AVG(net_amount_eur), 4)    AS aov_eur,
       ROUND(AVG(net_amount_eur * net_amount_eur) - AVG(net_amount_eur) * AVG(net_amount_eur), 4) AS aov_var,
       ROUND(AVG(items_count), 3)       AS items_per_order
FROM orders
WHERE ab_variant IS NOT NULL
GROUP BY ab_variant
ORDER BY ab_variant;

-- @name: ab_by_country
SELECT country, variant,
       COUNT(*)                     AS users,
       ROUND(AVG(converted), 4)     AS cvr,
       ROUND(AVG(revenue_eur), 3)   AS rpu_eur
FROM v_ab_user
GROUP BY country, variant
ORDER BY country, variant;

-- @name: ab_novelty
-- 노출 후 경과일별 번들 수락률: 초기 신기효과(novelty)가 있는지 확인
SELECT o.ab_variant AS variant,
       CASE WHEN julianday(o.order_ts) - julianday(a.first_exposure_ts) < 7 THEN 'd0-6' ELSE 'd7+' END AS since_exposure,
       COUNT(*)                                    AS orders,
       ROUND(AVG(o.has_bundle_upsell), 4)          AS bundle_attach_rate,
       ROUND(AVG(o.net_amount_eur), 2)             AS aov_eur
FROM orders o
JOIN ab_assignments a USING (user_id)
WHERE o.ab_variant IS NOT NULL
GROUP BY 1, 2
ORDER BY 1, 2;

-- @name: ab_user_level
-- 부트스트랩·추가 분석용 사용자 단위 원자료
SELECT user_id, variant, country, orders, converted, ROUND(revenue_eur, 2) AS revenue_eur, bundle_orders, returned_orders
FROM v_ab_user;
