-- =====================================================================
-- AARRR 퍼널 (MySQL 8.0+) — 주문 테이블만으로 만드는 대리(proxy) 지표 버전
-- 테이블: orders(user_id, order_date, amount)
--
-- 주문 데이터만 있으므로 단계를 구매 행동으로 정의한다.
-- 퍼널이 되려면 각 단계가 앞 단계의 부분집합이어야 한다 (A1 ⊇ A2 ⊇ R1).
--   A1 Acquisition : 첫 구매 고객 (방문·가입 데이터가 있으면 '가입'으로 교체)
--   A2 Activation  : 첫 구매 후 90일 이내 두 번째 구매 (액세서리는 구매 주기가 길어 30일보다 90일이 적합)
--   R1 Retention   : Activation 고객 중 91~180일 사이에도 구매 (재구매가 이어짐)
--   R2 Revenue     : 단계가 아니라 각 단계 고객의 180일 누적 매출·1인당 매출로 표시
--   R3 Referral    : 주문 테이블에 추천 정보가 없어 계산 불가 (NULL)
-- 180일을 다 관찰할 수 있는 코호트만 집계한다.
-- =====================================================================

-- [쿼리 A] 월별 코호트 퍼널
WITH ranked AS (                                                   -- ① 주문마다 순번·첫 구매일 붙이기
    SELECT
        user_id,                                                   -- 고객 ID
        order_date,                                                -- 주문일
        amount,                                                    -- 주문 금액
        ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY order_date)
            AS order_seq,                                          -- 윈도우: 고객별 몇 번째 주문인지
        MIN(order_date) OVER (PARTITION BY user_id)
            AS first_date                                          -- 윈도우: 고객별 첫 구매일
    FROM orders                                                    -- 주문 테이블에서
),
user_funnel AS (                                                   -- ② 고객별 행동 플래그
    SELECT
        user_id,                                                   -- 고객 ID
        first_date,                                                -- 첫 구매일
        MAX(CASE WHEN order_seq = 2
                  AND DATEDIFF(order_date, first_date) <= 90
                 THEN 1 ELSE 0 END) AS activated,                  -- A2: 90일 내 2회차 구매
        MAX(CASE WHEN DATEDIFF(order_date, first_date) BETWEEN 91 AND 180
                 THEN 1 ELSE 0 END) AS late_purchase,              -- 91~180일 사이 구매 여부
        SUM(CASE WHEN DATEDIFF(order_date, first_date) <= 180
                 THEN amount ELSE 0 END) AS revenue_180d           -- 첫 180일 누적 매출
    FROM ranked                                                    -- ①의 결과에서
    GROUP BY user_id, first_date                                   -- 고객 단위로 집계
),
user_stage AS (                                                    -- ③ 포함 관계가 되도록 단계 확정
    SELECT
        user_id,                                                   -- 고객 ID
        DATE_FORMAT(first_date, '%Y-%m') AS cohort_month,          -- 첫 구매 월(코호트)
        activated,                                                 -- A2 도달 여부
        activated * late_purchase AS retained,                     -- R1: A2를 통과한 고객만 인정
        revenue_180d                                               -- 180일 매출
    FROM user_funnel                                               -- ②의 결과에서
    WHERE first_date <= (SELECT DATE_SUB(MAX(order_date), INTERVAL 180 DAY)
                         FROM orders)                              -- 180일 관찰 가능한 코호트만
)
SELECT
    cohort_month,                                                  -- 코호트 월
    COUNT(*)                          AS acquisition,              -- A1: 신규 구매 고객 수
    SUM(activated)                    AS activation,               -- A2: 활성화 고객 수
    ROUND(100 * AVG(activated), 1)    AS activation_rate_pct,      -- A1 → A2 전환율(%)
    SUM(retained)                     AS retention,                -- R1: 유지 고객 수
    ROUND(100 * SUM(retained) / NULLIF(SUM(activated), 0), 1)
                                      AS retention_rate_pct,       -- A2 → R1 전환율(%)
    ROUND(SUM(revenue_180d), 0)       AS revenue_180d,             -- R2: 코호트 180일 매출
    ROUND(AVG(revenue_180d), 2)       AS arpu_180d,                -- R2: 1인당 180일 매출
    NULL                              AS referral                  -- R3: 데이터 없음
FROM user_stage                                                    -- ③의 결과에서
GROUP BY cohort_month                                              -- 코호트 월별 집계
ORDER BY cohort_month;                                             -- 월 순서로 정렬


-- [쿼리 B] 전체 퍼널을 세로로 펼치고 단계 간 전환율 계산
WITH ranked AS (                                                   -- ① 쿼리 A와 동일
    SELECT
        user_id,                                                   -- 고객 ID
        order_date,                                                -- 주문일
        amount,                                                    -- 주문 금액
        ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY order_date) AS order_seq,  -- 고객별 주문 순번
        MIN(order_date) OVER (PARTITION BY user_id) AS first_date  -- 고객별 첫 구매일
    FROM orders                                                    -- 주문 테이블에서
),
user_stage AS (                                                    -- ② 고객별 단계 도달 여부 + 매출
    SELECT
        user_id,                                                   -- 고객 ID
        MAX(CASE WHEN order_seq = 2 AND DATEDIFF(order_date, first_date) <= 90
                 THEN 1 ELSE 0 END) AS activated,                  -- A2: 90일 내 2회차 구매
        MAX(CASE WHEN order_seq = 2 AND DATEDIFF(order_date, first_date) <= 90
                 THEN 1 ELSE 0 END)
      * MAX(CASE WHEN DATEDIFF(order_date, first_date) BETWEEN 91 AND 180
                 THEN 1 ELSE 0 END) AS retained,                   -- R1: A2 통과 + 91~180일 구매
        SUM(CASE WHEN DATEDIFF(order_date, first_date) <= 180
                 THEN amount ELSE 0 END) AS revenue_180d           -- 180일 누적 매출
    FROM ranked                                                    -- ①의 결과에서
    WHERE first_date <= (SELECT DATE_SUB(MAX(order_date), INTERVAL 180 DAY) FROM orders)  -- 관찰 가능 코호트만
    GROUP BY user_id                                               -- 고객 단위로 집계
),
stages AS (                                                        -- ③ 단계별 고객 수·매출을 세로로 쌓기
    SELECT 1 AS step, 'A1 Acquisition' AS stage,
           COUNT(*) AS users, SUM(revenue_180d) AS revenue_180d
    FROM user_stage                                                -- 전체 신규 고객
    UNION ALL
    SELECT 2, 'A2 Activation',
           SUM(activated), SUM(activated * revenue_180d)
    FROM user_stage                                                -- 90일 내 재구매 고객
    UNION ALL
    SELECT 3, 'R1 Retention',
           SUM(retained), SUM(retained * revenue_180d)
    FROM user_stage                                                -- 재구매가 이어진 고객
)
SELECT
    step,                                                          -- 단계 순서
    stage,                                                         -- 단계명
    users,                                                         -- 도달 고객 수
    ROUND(100 * users / FIRST_VALUE(users) OVER (ORDER BY step), 1)
        AS pct_of_acquisition,                                     -- 윈도우: 첫 단계 대비 도달률
    ROUND(100 * users / LAG(users) OVER (ORDER BY step), 1)
        AS pct_of_prev_step,                                       -- 윈도우: 직전 단계 대비 전환율
    ROUND(revenue_180d / users, 2) AS arpu_180d,                   -- R2: 단계별 1인당 180일 매출
    ROUND(100 * revenue_180d / FIRST_VALUE(revenue_180d) OVER (ORDER BY step), 1)
        AS revenue_share_pct                                       -- 윈도우: 전체 매출 중 이 단계 고객 비중
FROM stages                                                        -- ③의 결과에서
ORDER BY step;                                                     -- 단계 순서로 정렬
