"""
비즈니스 택소노미와 시뮬레이션 파라미터.

모든 "숨은 규칙"(계절성, VIP 클러스터, 이탈, A/B 실제 효과)이 이 파일 한 곳에 있다.
분석 단계에서는 이 값을 모른다고 가정하고, 분석 결과가 이 값을 다시 찾아내는지로
분석 방법을 검증한다.

실측 기반 값 (출처 표기):
  - DEVICE_BRAND_SHARE : Statcounter 모바일 제조사 점유율 12개월 평균 (2025.9–2026.8)
  - data_seed/google_trends_weekly.csv : Google Trends 주간 지수 (2024.9–2026.9)
그 외 값은 모두 가정(assumption)이다.
"""
from datetime import date

SEED = 42
START_DATE = date(2024, 9, 1)
END_DATE = date(2026, 8, 31)

# ---------------------------------------------------------------------------
# 국가
# ---------------------------------------------------------------------------
COUNTRIES = {
    "DE": {"user_share": 0.58, "faker_locale": "de_DE", "shipping_fee": 3.99,
           "free_shipping_over": 29.0, "gender_p": {"m": 0.60, "f": 0.38, "u": 0.02}},
    "IT": {"user_share": 0.42, "faker_locale": "it_IT", "shipping_fee": 4.49,
           "free_shipping_over": 29.0, "gender_p": {"m": 0.55, "f": 0.43, "u": 0.02}},
}

# Google Trends 키워드를 하나의 일간 수요지수로 합치는 가중치.
# 이탈리아는 일반 키워드('cover cellulare')가 거의 검색되지 않아 제외한다.
DEMAND_KEYWORD_WEIGHTS = {
    "DE": {"kw_generic": 0.50, "kw_iphone": 0.35, "kw_samsung": 0.15},
    "IT": {"kw_generic": 0.00, "kw_iphone": 0.75, "kw_samsung": 0.25},
}
# 요일 효과 (월=0 … 일=6)
WEEKDAY_MULT = [1.04, 1.00, 0.98, 0.97, 0.94, 0.95, 1.12]
# 시간대 분포 (0–23시, 저녁 피크)
HOUR_WEIGHTS = [2, 1, 1, 1, 1, 1, 2, 3, 4, 5, 6, 6, 7, 7, 6, 6, 6, 7, 8, 10, 11, 10, 8, 4]
# 연간 사업 성장률 (슈피겐 5개년 CAGR 11%를 참고한 가정)
ANNUAL_GROWTH = 0.11

# ---------------------------------------------------------------------------
# 기기
# ---------------------------------------------------------------------------
DEVICE_BRAND_SHARE = {  # Statcounter 12개월 평균, 모델링 대상 브랜드만 재정규화해서 사용
    "DE": {"Apple": 38.3, "Samsung": 31.5, "Xiaomi": 10.3, "Google": 5.7, "Motorola": 1.1},
    "IT": {"Apple": 34.1, "Samsung": 26.9, "Xiaomi": 10.3, "Google": 5.5, "Motorola": 5.0, "Oppo": 3.9},
}

# (brand, model, release_date, tier) — 출시일은 시뮬레이션용 가정
DEVICE_MODELS = [
    ("Apple", "iPhone 13", date(2021, 9, 24), "legacy"),
    ("Apple", "iPhone 14", date(2022, 9, 16), "legacy"),
    ("Apple", "iPhone 15", date(2023, 9, 22), "legacy"),
    ("Apple", "iPhone 16", date(2024, 9, 20), "flagship"),
    ("Apple", "iPhone 16 Pro", date(2024, 9, 20), "flagship"),
    ("Apple", "iPhone 16 Pro Max", date(2024, 9, 20), "flagship"),
    ("Apple", "iPhone 16e", date(2025, 2, 28), "mid"),
    ("Apple", "iPhone 17", date(2025, 9, 19), "flagship"),
    ("Apple", "iPhone 17 Pro", date(2025, 9, 19), "flagship"),
    ("Apple", "iPhone 17 Pro Max", date(2025, 9, 19), "flagship"),
    ("Samsung", "Galaxy A55", date(2024, 3, 20), "mid"),
    ("Samsung", "Galaxy S24", date(2024, 1, 31), "flagship"),
    ("Samsung", "Galaxy S24 Ultra", date(2024, 1, 31), "flagship"),
    ("Samsung", "Galaxy S25", date(2025, 2, 7), "flagship"),
    ("Samsung", "Galaxy S25 Ultra", date(2025, 2, 7), "flagship"),
    ("Samsung", "Galaxy A56", date(2025, 3, 10), "mid"),
    ("Samsung", "Galaxy A17", date(2025, 9, 1), "budget"),
    ("Samsung", "Galaxy S26", date(2026, 3, 6), "flagship"),
    ("Samsung", "Galaxy S26 Ultra", date(2026, 3, 6), "flagship"),
    ("Samsung", "Galaxy A57", date(2026, 3, 16), "mid"),
    ("Google", "Pixel 9", date(2024, 8, 22), "flagship"),
    ("Google", "Pixel 9a", date(2025, 4, 10), "mid"),
    ("Google", "Pixel 10", date(2025, 8, 28), "flagship"),
    ("Google", "Pixel 10a", date(2026, 4, 9), "mid"),
    ("Xiaomi", "Redmi Note 13", date(2024, 1, 15), "budget"),
    ("Xiaomi", "Redmi Note 14", date(2025, 1, 15), "budget"),
    ("Xiaomi", "Xiaomi 15", date(2025, 3, 2), "flagship"),
    ("Xiaomi", "Redmi Note 15", date(2026, 1, 15), "budget"),
    ("Motorola", "moto g85", date(2024, 7, 10), "budget"),
    ("Motorola", "moto g86", date(2025, 6, 12), "budget"),
    ("Oppo", "Oppo A80", date(2024, 7, 1), "budget"),
    ("Oppo", "Oppo A6", date(2025, 10, 1), "budget"),
]
# 신규 기기 선택 시 최신 모델 선호: weight = exp(-모델 나이(일) / RECENCY_DAYS)
DEVICE_RECENCY_DAYS = 420

# ---------------------------------------------------------------------------
# 상품 택소노미 (가격 EUR, 원가율)
# ---------------------------------------------------------------------------
CASE_SERIES = {
    # name: (list_price, cost_ratio, style, n_colors)
    "Ultra Hybrid": (19.99, 0.30, "clear", 2),
    "Liquid Air": (15.99, 0.28, "slim", 3),
    "Rugged Armor": (17.99, 0.29, "rugged", 2),
    "Tough Armor": (27.99, 0.33, "rugged", 2),
    "Thin Fit": (14.99, 0.27, "slim", 3),
    "Optik Armor": (24.99, 0.32, "camera", 2),
    "Wallet S": (26.99, 0.34, "wallet", 2),
}
CASE_STYLE_PREF_BY_AGE = {  # 연령대별 케이스 스타일 선호 (가정)
    "18-24": {"clear": 0.30, "slim": 0.35, "rugged": 0.10, "camera": 0.15, "wallet": 0.10},
    "25-34": {"clear": 0.32, "slim": 0.25, "rugged": 0.18, "camera": 0.15, "wallet": 0.10},
    "35-44": {"clear": 0.25, "slim": 0.18, "rugged": 0.30, "camera": 0.12, "wallet": 0.15},
    "45-54": {"clear": 0.20, "slim": 0.12, "rugged": 0.35, "camera": 0.10, "wallet": 0.23},
    "55-64": {"clear": 0.15, "slim": 0.10, "rugged": 0.35, "camera": 0.08, "wallet": 0.32},
    "65+":   {"clear": 0.12, "slim": 0.08, "rugged": 0.35, "camera": 0.05, "wallet": 0.40},
}
PROTECTOR_TYPES = {
    "Glas.tR EZ Fit (2-pack)": (19.99, 0.22),
    "Glas.tR Slim (2-pack)": (14.99, 0.20),
}
UNIVERSAL_ACCESSORIES = [
    # (category, name, list_price, cost_ratio)
    ("charger", "ArcStation 30W USB-C", 24.99, 0.38),
    ("charger", "ArcStation 45W GaN", 39.99, 0.40),
    ("charger", "MagFit Wireless Pad", 34.99, 0.39),
    ("charger", "3-in-1 MagFit Stand", 59.99, 0.42),
    ("power_bank", "MagFit Power Bank 5000", 44.99, 0.41),
    ("car_mount", "OneTap MagFit Car Mount", 39.99, 0.36),
    ("car_mount", "Vent Car Mount", 24.99, 0.33),
    ("watch_band", "Rugged Band 45mm", 29.99, 0.30),
    ("watch_band", "Lite Fit Band 41mm", 19.99, 0.28),
    ("life", "Lock Fit Sunglasses Case", 19.99, 0.30),
    ("life", "Carabiner Phone Strap", 14.99, 0.26),
    ("life", "AirPods Pro Rugged Case", 21.99, 0.30),
    ("life", "Waterproof Phone Pouch", 12.99, 0.25),
    ("cable", "USB-C to C Braided 1m", 12.99, 0.30),
]
REPEAT_CATEGORY_MIX = {"case": 0.45, "protector": 0.20, "accessory": 0.35}

# ---------------------------------------------------------------------------
# 고객 세그먼트 (숨은 정답 — 분석 단계에서는 사용 금지, 검증용으로만 사용)
# ---------------------------------------------------------------------------
SEGMENTS = {
    #          비중,  평균 활동기간(일), 재구매율(/일), 장바구니 평균 품목수, 방문율(/일),
    #          신모델 업그레이드 구매확률, 할인 민감도, 액세서리 선호
    "vip":     dict(share=0.05, lifetime_mean_days=700, repeat_rate=1 / 55,   items_mean=2.4,
                    browse_rate=1 / 4,  upgrade_prob=0.60, discount_sensitivity=0.35, accessory_affinity=0.55),
    "loyal":   dict(share=0.15, lifetime_mean_days=380, repeat_rate=1 / 110,  items_mean=1.8,
                    browse_rate=1 / 8,  upgrade_prob=0.32, discount_sensitivity=0.60, accessory_affinity=0.30),
    "regular": dict(share=0.40, lifetime_mean_days=180, repeat_rate=1 / 240,  items_mean=1.35,
                    browse_rate=1 / 16, upgrade_prob=0.12, discount_sensitivity=0.85, accessory_affinity=0.15),
    "one_off": dict(share=0.40, lifetime_mean_days=25,  repeat_rate=1 / 3000, items_mean=1.12,
                    browse_rate=1 / 28, upgrade_prob=0.02, discount_sensitivity=1.00, accessory_affinity=0.05),
}
# 이탈 이후에도 가끔 방문만 하는 '잔존 방문' (구매 없음)
LAPSED_VISIT_RATE = 1 / 150
LAPSED_VISIT_DAYS = 120

AGE_BANDS = ["18-24", "25-34", "35-44", "45-54", "55-64", "65+"]
AGE_DIST = {  # Meta EU 도달 분포 관측(대시보드)에서 방향만 차용한 가정
    "DE": [0.07, 0.22, 0.26, 0.21, 0.15, 0.09],
    "IT": [0.14, 0.34, 0.24, 0.14, 0.08, 0.06],
}

# ---------------------------------------------------------------------------
# 유입 채널
# ---------------------------------------------------------------------------
CHANNELS = {
    "meta_ads": dict(paid=True, acq_share={"DE": 0.28, "IT": 0.32},
                     segment_tilt={"vip": 0.8, "loyal": 0.9, "regular": 1.0, "one_off": 1.15},
                     lifetime_mult=0.90, return_mult=1.10, cac_target={"DE": 16.0, "IT": 12.0}),
    "google_search": dict(paid=True, acq_share={"DE": 0.25, "IT": 0.22},
                          segment_tilt={"vip": 1.1, "loyal": 1.1, "regular": 1.0, "one_off": 0.9},
                          lifetime_mult=1.05, return_mult=0.90, cac_target={"DE": 13.0, "IT": 10.0}),
    "tiktok_ads": dict(paid=True, acq_share={"DE": 0.10, "IT": 0.03},
                       segment_tilt={"vip": 0.5, "loyal": 0.7, "regular": 0.9, "one_off": 1.5},
                       lifetime_mult=0.60, return_mult=1.60, cac_target={"DE": 11.0, "IT": 9.0},
                       age_dist=[0.36, 0.38, 0.15, 0.07, 0.03, 0.01]),
    "influencer": dict(paid=True, acq_share={"DE": 0.05, "IT": 0.08},
                       segment_tilt={"vip": 0.9, "loyal": 1.0, "regular": 1.0, "one_off": 1.1},
                       lifetime_mult=0.85, return_mult=1.20, cac_target={"DE": 14.0, "IT": 11.0},
                       age_dist=[0.25, 0.40, 0.20, 0.10, 0.04, 0.01]),
    "organic": dict(paid=False, acq_share={"DE": 0.24, "IT": 0.25},
                    segment_tilt={"vip": 1.3, "loyal": 1.2, "regular": 1.0, "one_off": 0.8},
                    lifetime_mult=1.20, return_mult=0.90),
    "referral": dict(paid=False, acq_share={"DE": 0.08, "IT": 0.10},
                     segment_tilt={"vip": 1.5, "loyal": 1.3, "regular": 1.0, "one_off": 0.7},
                     lifetime_mult=1.30, return_mult=0.80),
}
# 재방문·재구매 세션의 유입경로 (세그먼트별)
REPEAT_SOURCE_MIX = {
    "vip":     {"email": 0.35, "direct": 0.30, "organic": 0.15, "meta_ads": 0.10, "google_search": 0.10},
    "loyal":   {"email": 0.30, "direct": 0.25, "organic": 0.20, "meta_ads": 0.15, "google_search": 0.10},
    "regular": {"email": 0.20, "direct": 0.20, "organic": 0.25, "meta_ads": 0.20, "google_search": 0.15},
    "one_off": {"email": 0.10, "direct": 0.15, "organic": 0.30, "meta_ads": 0.30, "google_search": 0.15},
}
PLATFORM_P = {"mobile": 0.72, "desktop": 0.28}
BASE_RETURN_RATE = 0.04

# 브라우징 세션 퍼널 전환확률 (구매 없는 세션)
BROWSE_FUNNEL = {"product_view": 0.82, "add_to_cart": 0.24, "begin_checkout": 0.38}

# ---------------------------------------------------------------------------
# 프로모션 캘린더
# ---------------------------------------------------------------------------
PROMOS = [
    # (code, start, end, discount_pct, usage_prob_at_sensitivity_1)
    ("BF24", date(2024, 11, 25), date(2024, 12, 2), 0.25, 0.80),
    ("XMAS24", date(2024, 12, 9), date(2024, 12, 22), 0.10, 0.55),
    ("SUMMER25", date(2025, 7, 7), date(2025, 7, 20), 0.15, 0.50),
    ("BF25", date(2025, 11, 24), date(2025, 12, 1), 0.25, 0.80),
    ("XMAS25", date(2025, 12, 8), date(2025, 12, 21), 0.10, 0.55),
    ("SUMMER26", date(2026, 7, 6), date(2026, 7, 19), 0.15, 0.50),
]
WELCOME_COUPON = ("WELCOME10", 0.10, 0.35)   # 첫 주문 쿠폰, 사용확률
ALWAYS_ON_COUPON = ("SAVE10", 0.10, 0.06)    # 상시 쿠폰, 사용확률

# ---------------------------------------------------------------------------
# A/B 테스트 (실제 효과 = 정답)
# ---------------------------------------------------------------------------
EXPERIMENT = dict(
    exp_id="EXP_2026_04_CART_BUNDLE",
    name="장바구니 번들 업셀 (케이스+강화유리 15% 할인 제안)",
    start=date(2026, 4, 13),
    end=date(2026, 5, 31),
    treatment_share=0.50,
    # 정답 효과
    purchase_loss_prob=0.03,        # 처치군 구매의 3%가 이탈 (선택지 증가로 인한 마찰)
    bundle_prob_novelty=0.34,       # 노출 후 첫 7일 번들 수락률
    bundle_prob=0.22,               # 이후 번들 수락률
    novelty_days=7,
    bundle_discount=0.15,
    bundle_return_mult=1.35,        # 가드레일: 번들 주문 반품률 상승
)

# ---------------------------------------------------------------------------
# 마케팅 비용 (현재 방식 = 월 예산을 일별로 균등 배분 → 주제 1의 문제 상황)
# ---------------------------------------------------------------------------
SPEND_DAILY_NOISE = 0.08
CPM = {"meta_ads": {"DE": 7.5, "IT": 5.8}, "tiktok_ads": {"DE": 5.2, "IT": 4.1},
       "google_search": {"DE": 22.0, "IT": 16.0}, "influencer": {"DE": 9.0, "IT": 7.0}}
BASE_CTR = {"meta_ads": 0.009, "tiktok_ads": 0.007, "google_search": 0.045, "influencer": 0.012}
