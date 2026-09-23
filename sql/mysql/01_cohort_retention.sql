-- =====================================================================
-- 월별 코호트 리텐션 (MySQL 8.0+)
-- 테이블: orders(user_id, order_date, amount)
-- 코호트 = 첫 구매 월, 리텐션 = 코호트 고객 중 N개월 후에도 구매한 고객 비율
-- =====================================================================
WITH first_order AS (                                              -- ① 고객별 첫 구매 월(코호트)
    SELECT
        user_id,                                                   -- 고객 ID
        CAST(DATE_FORMAT(MIN(order_date), '%Y-%m-01') AS DATE)     -- 첫 구매일을 그 달 1일로 맞춤
            AS cohort_month                                        -- → 코호트 월
    FROM orders                                                    -- 주문 테이블에서
    GROUP BY user_id                                               -- 고객 단위로 묶음
),
monthly_activity AS (                                              -- ② 고객이 구매한 월 목록
    SELECT DISTINCT                                                -- 한 달에 여러 번 사도 1번만 셈
        user_id,                                                   -- 고객 ID
        CAST(DATE_FORMAT(order_date, '%Y-%m-01') AS DATE)          -- 주문일을 그 달 1일로 맞춤
            AS order_month                                         -- → 구매 월
    FROM orders                                                    -- 주문 테이블에서
),
cohort_activity AS (                                               -- ③ 코호트 기준 경과 개월 수 계산
    SELECT
        f.cohort_month,                                            -- 코호트 월
        TIMESTAMPDIFF(MONTH, f.cohort_month, a.order_month)        -- 코호트 월로부터 몇 개월째 구매인지
            AS month_index,                                        -- → 0 = 첫 구매 월, 1 = 다음 달 …
        a.user_id                                                  -- 고객 ID
    FROM first_order AS f                                          -- 코호트 정보에
    JOIN monthly_activity AS a                                     -- 월별 구매 기록을
      ON a.user_id = f.user_id                                     -- 같은 고객끼리 연결
),
cohort_counts AS (                                                 -- ④ 코호트 × 경과월별 활성 고객 수
    SELECT
        cohort_month,                                              -- 코호트 월
        month_index,                                               -- 경과 개월 수
        COUNT(DISTINCT user_id) AS active_users                    -- 그 달에 구매한 코호트 고객 수
    FROM cohort_activity                                           -- ③의 결과에서
    GROUP BY cohort_month, month_index                             -- 코호트·경과월 단위로 집계
)
SELECT
    cohort_month,                                                  -- 코호트 월
    month_index,                                                   -- 경과 개월 수
    FIRST_VALUE(active_users) OVER w AS cohort_size,               -- 윈도우: M0 인원 = 코호트 크기
    active_users,                                                  -- 해당 월 활성 고객 수
    ROUND(100 * active_users / FIRST_VALUE(active_users) OVER w, 1)
        AS retention_pct,                                          -- 리텐션(%) = 활성 ÷ 코호트 크기
    CASE WHEN month_index >= 2                                     -- M0→M1 급락은 당연하므로 M2부터 표시
         THEN ROUND(100 * (active_users - LAG(active_users) OVER w)
                    / FIRST_VALUE(active_users) OVER w, 1)
    END AS change_vs_prev_pp                                       -- 윈도우: 직전 경과월 대비 리텐션 변화(%p)
FROM cohort_counts                                                 -- ④의 결과에서
WHERE month_index <= 6                                             -- M0~M6까지만 표시
WINDOW w AS (PARTITION BY cohort_month ORDER BY month_index)       -- 코호트별로 경과월 순서 정렬
ORDER BY cohort_month, month_index;                                -- 코호트 → 경과월 순으로 출력
