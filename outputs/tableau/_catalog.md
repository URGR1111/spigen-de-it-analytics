| 파일 | 행 수 | 열 | 설명 |
|---|---|---|---|
| prophet_weekly.csv | 242 | week_start, country, series, revenue_eur, lower_80, upper_80 | 국가별 주간 실적(actual)과 2026.9–12 예측(forecast, 80% 구간) |
| prophet_backtest_weekly.csv | 80 | week_start, country, window, actual_eur, model_a_eur, model_b_eur | 검증 구간별 실제 vs 모델 A/B 주간 매출 |
| prophet_backtest_mape.csv | 12 | country, window, model, mape_pct | 국가 × 검증 구간 × 모델별 주간 MAPE(%) |
| prophet_event_effects.csv | 8 | event, country, lift_pct | 이벤트 주 매출 ÷ 직전 4주 평균 − 1 (%) |
| ab_summary.csv | 5 | metric, control, treatment, lift_pct, ci_low_pct, ci_high_pct, p_value, significant | 지표별 대조군·처치군 값, 상승률(%), 95% CI, p-value |
| ab_user_level.csv | 5,739 | user_id, variant, country, first_exposure_ts, orders, converted, revenue_eur, bundle_orders, returned | 노출 사용자 1명 = 1행. 대시보드에서 필터·재집계용 |
| ab_bootstrap.csv | 3,000 | iteration, rpu_lift_pct | RPU 상승률 부트스트랩 3,000회 (히스토그램용) |
| ab_novelty.csv | 5 | days_since_exposure, orders, bundle_rate_pct | 처치군 경과일 구간별 주문 수·번들 수락률(%) |
| ab_by_country.csv | 4 | country, variant, users, rpu_eur, cvr | 국가 × 그룹별 사용자 수·RPU·전환율 (긴 형식) |
| kmeans_customers.csv | 29,982 | user_id, cluster, recency_days, frequency, monetary, aov, discount_share, accessory_share, sessions_90d, tenure_days, cluster_role, pc1, pc2 | 고객 1명 = 1행: 군집, 역할, 피처 원값, PCA 좌표(산점도용) |
| kmeans_cluster_profile.csv | 3 | cluster, customers, recency_days, frequency, monetary, aov, discount_share, accessory_share, sessions_90d, tenure_days, top_features, role, customer_share_pct, revenue_share_pct | 군집별 고객 수·비중·매출 비중·피처 평균 |
| kmeans_cluster_centers_long.csv | 24 | cluster, feature, z_value, feature_ko, cluster_role | 군집 × 피처 표준화 중심값 (긴 형식, 히트맵용) |
| kmeans_k_selection.csv | 7 | k, inertia, silhouette | k별 관성·실루엣 (군집 수 선택 근거) |
