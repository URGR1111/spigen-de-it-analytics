-- =====================================================================
-- RFM 분석 (MySQL 8.0+)
-- 테이블: orders(user_id, order_date, amount)
-- R = 최근 구매 경과일, F = 구매 횟수, M = 누적 구매금액 → 각 1~5점 → 세그먼트
-- =====================================================================
WITH ref AS (                                                      -- ① 분석 기준일
    SELECT DATE_ADD(MAX(order_date), INTERVAL 1 DAY) AS ref_date   -- 마지막 주문일 다음 날
    FROM orders                                                    -- 주문 테이블에서
),
customer AS (                                                      -- ② 고객별 R·F·M 원값
    SELECT
        o.user_id,                                                 -- 고객 ID
        DATEDIFF(r.ref_date, MAX(o.order_date)) AS recency_days,   -- R: 기준일 − 마지막 구매일
        COUNT(*)                                AS frequency,      -- F: 주문 건수
        SUM(o.amount)                           AS monetary        -- M: 누적 구매금액
    FROM orders AS o                                               -- 주문 테이블에
    CROSS JOIN ref AS r                                            -- 기준일(1행)을 모든 행에 붙임
    GROUP BY o.user_id, r.ref_date                                 -- 고객 단위로 집계
),
scored AS (                                                        -- ③ R·F·M 점수화
    SELECT
        user_id,                                                   -- 고객 ID
        recency_days,                                              -- R 원값
        frequency,                                                 -- F 원값
        monetary,                                                  -- M 원값
        NTILE(5) OVER (ORDER BY recency_days DESC) AS r_score,     -- 윈도우: 오래될수록 1점, 최근일수록 5점
        CASE                                                       -- F는 1회 구매 동점이 많아 NTILE 대신 구간 사용
            WHEN frequency >= 6 THEN 5                             -- 6회 이상 → 5점
            WHEN frequency >= 4 THEN 4                             -- 4~5회 → 4점
            ELSE frequency                                         -- 1·2·3회 → 1·2·3점
        END AS f_score,
        NTILE(5) OVER (ORDER BY monetary ASC) AS m_score           -- 윈도우: 금액 하위 20% = 1점 … 상위 20% = 5점
    FROM customer                                                  -- ②의 결과에서
),
segmented AS (                                                     -- ④ 점수 조합 → 세그먼트
    SELECT
        *,                                                         -- ③의 모든 컬럼
        CONCAT(r_score, f_score, m_score) AS rfm_code,             -- 예: '545'
        CASE
            WHEN r_score >= 4 AND f_score >= 4 AND m_score >= 4 THEN '1_Champions'          -- 최근·자주·많이
            WHEN r_score >= 3 AND f_score >= 3                  THEN '2_Loyal'              -- 꾸준한 재구매
            WHEN r_score >= 4 AND f_score = 2                   THEN '3_Potential Loyalist' -- 최근 2회차 구매
            WHEN r_score >= 4 AND f_score = 1                   THEN '4_New Customers'      -- 최근 첫 구매
            WHEN r_score <= 2 AND f_score >= 3                  THEN '5_At Risk'            -- 단골이었는데 뜸함
            WHEN r_score = 3                                    THEN '6_Need Attention'     -- 중간, 관심 필요
            WHEN r_score <= 2 AND f_score = 2                   THEN '7_Hibernating'        -- 2회 구매 후 휴면
            ELSE                                                     '8_Lost'               -- 1회 구매 후 장기 미구매
        END AS segment
    FROM scored                                                    -- ③의 결과에서
)
SELECT                                                             -- ⑤ 세그먼트 요약 (고객 단위가 필요하면 SELECT * FROM segmented)
    segment,                                                       -- 세그먼트명
    COUNT(*) AS customers,                                         -- 고객 수
    ROUND(100 * COUNT(*) / SUM(COUNT(*)) OVER (), 1)
        AS customer_share_pct,                                     -- 윈도우: 전체 고객 대비 비중
    ROUND(SUM(monetary), 0) AS revenue,                            -- 세그먼트 매출
    ROUND(100 * SUM(monetary) / SUM(SUM(monetary)) OVER (), 1)
        AS revenue_share_pct,                                      -- 윈도우: 전체 매출 대비 비중
    ROUND(AVG(recency_days), 0) AS avg_recency_days,               -- 평균 경과일
    ROUND(AVG(frequency), 2)    AS avg_frequency,                  -- 평균 구매 횟수
    ROUND(AVG(monetary), 1)     AS avg_monetary                    -- 평균 누적 금액
FROM segmented                                                     -- ④의 결과에서
GROUP BY segment                                                   -- 세그먼트별 집계
ORDER BY segment;                                                  -- 세그먼트 번호 순 정렬
