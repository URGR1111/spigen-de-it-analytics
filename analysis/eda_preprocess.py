# %% [markdown]
# # 결측·이상치 진단 → 날짜 전처리·내보내기 → 기술 통계(APA 표) → 일변량·다변량 EDA
# - 데이터: spigen-synthetic-data (합성 데이터) data/raw/*.csv
# - 분석 기준 테이블: orders (주문 1건 = 1행) + users(고객 속성) 조인
# - 산출물: outputs/eda/ (진단 리포트, APA 표, 그림), data/processed/ (전처리 파일)

# %% [0] 설정
import math
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.ticker import FuncFormatter, PercentFormatter

sys.path.insert(0, str(Path(__file__).resolve().parent))
from style import CATEGORICAL, COUNTRY, DIVERGING, INK, MUTED, OI, eur, finish, headline, insight, setup  # noqa: E402

setup()
ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
PROC = ROOT / "data" / "processed"
EDA = ROOT / "outputs" / "eda"
for d in (PROC, EDA):
    d.mkdir(parents=True, exist_ok=True)
WEEKDAY_KO = ["월", "화", "수", "목", "금", "토", "일"]
KO = {  # 변수 한글명 (표·그림용)
    "gross_amount_eur": "총 주문금액(€)", "discount_amount_eur": "할인금액(€)", "net_amount_eur": "순 주문금액(€)",
    "shipping_fee_eur": "배송비(€)", "items_count": "주문 품목 수", "frequency": "구매 횟수",
    "monetary": "누적 순매출(€)", "recency_days": "최근 구매 경과일", "tenure_days": "첫 구매 후 경과일",
    "aov": "평균 객단가(€)", "sessions_total": "총 방문 수", "orders": "주문 수", "buyers": "구매 고객 수",
    "revenue_eur": "매출(€)", "aov_eur": "객단가(€)", "return_rate": "반품률", "new_customers": "신규 고객 수",
}
CH_KO = {"meta_ads": "Meta 광고", "google_search": "구글 검색", "tiktok_ads": "TikTok 광고",
         "influencer": "인플루언서", "organic": "오가닉", "referral": "추천"}
OT_KO = {"first": "첫 구매", "repeat": "재구매", "upgrade": "기기 교체 구매"}

# %% [1] 결측치·이상치 진단 -------------------------------------------------------
print("\n[1] 결측치·이상치 진단")
tables = {n: pd.read_csv(RAW / f"{n}.csv", low_memory=False)
          for n in ["orders", "order_items", "products", "sessions", "events", "marketing_spend"]}
# 고객 테이블은 기본 설정으로 읽으면 두 가지 오류가 생긴다 → 원인을 기록하고 올바르게 다시 읽는다
_naive = pd.read_csv(RAW / "users.csv")                                      # pandas 기본 설정
PARSE_ISSUES = {
    "지명 'None'을 결측으로 오인": int(_naive.city.isna().sum()),              # 이탈리아 실제 지명 None(피에몬테)
    "우편번호 앞자리 0 손실(숫자형 변환)": int((_naive.postcode.astype(str).str.len() < 5).sum()),
}
tables["users"] = pd.read_csv(RAW / "users.csv", dtype={"postcode": str},     # 우편번호는 문자열
                              keep_default_na=False, na_values=[""])           # 빈칸만 결측으로 인정

# 1-1. 결측치: 모든 테이블·컬럼. 결측의 '의미'를 함께 분류한다 (값이 없는 것 자체가 정보인 경우가 많음)
STRUCTURAL = {  # (테이블, 컬럼): 결측의 의미 → 오류가 아니라 '해당 없음'
    ("orders", "promo_code"): "할인코드 미사용",
    ("orders", "returned_ts"): "반품되지 않은 주문",
    ("orders", "ab_variant"): "A/B 실험 대상이 아닌 주문",
    ("sessions", "exp_variant"): "A/B 실험 대상이 아닌 세션",
    ("events", "product_id"): "상품과 무관한 이벤트(세션 시작·결제 등)",
    ("events", "order_id"): "구매가 아닌 이벤트",
}
miss = []
for t, df in tables.items():
    for c in df.columns:
        n = int(df[c].isna().sum())
        if n:
            miss.append(dict(table=t, column=c, n_missing=n, pct_missing=round(100 * n / len(df), 2),
                             type="구조적 결측(의미 있음)" if (t, c) in STRUCTURAL else "확인 필요",
                             meaning=STRUCTURAL.get((t, c), "")))
miss = pd.DataFrame(miss)
miss.to_csv(EDA / "01_missing_report.csv", index=False, encoding="utf-8-sig")
print(miss.to_string(index=False))

# 1-2. 무결성·도메인 규칙 위반 (이상치의 한 종류: 값이 '불가능'한 경우)
o, u = tables["orders"].copy(), tables["users"].copy()
o["order_ts"] = pd.to_datetime(o.order_ts)
u["signup_ts"] = pd.to_datetime(u.signup_ts)
rules = {
    "중복 주문 ID": int(o.order_id.duplicated().sum()),
    "중복 고객 ID": int(u.user_id.duplicated().sum()),
    "음수 금액": int((o[["gross_amount_eur", "discount_amount_eur", "net_amount_eur"]] < 0).any(axis=1).sum()),
    "할인 > 총액": int((o.discount_amount_eur > o.gross_amount_eur).sum()),
    "순액 ≠ 총액 − 할인": int((abs(o.net_amount_eur - (o.gross_amount_eur - o.discount_amount_eur)) > 0.011).sum()),
    "품목 수 0 이하": int((o.items_count <= 0).sum()),
    "가입 전 주문": int((o.merge(u[["user_id", "signup_ts"]], on="user_id").pipe(lambda d: d.order_ts < d.signup_ts)).sum()),
    "미래 날짜 주문": int((o.order_ts > pd.Timestamp("2026-09-23")).sum()),
    "주문 없는 고객": int((~u.user_id.isin(o.user_id)).sum()),
    **{f"[읽기 오류] {k}": v for k, v in PARSE_ISSUES.items()},
}
rules = pd.DataFrame(rules.items(), columns=["rule", "violations"])
rules.to_csv(EDA / "01_integrity_rules.csv", index=False, encoding="utf-8-sig")
print(rules.to_string(index=False))

# 1-3. 통계적 이상치: IQR(1.5배)와 로버스트 z(MAD 기반, |z|>3.5) 두 방법으로 비교
cust = o.groupby("user_id").agg(frequency=("order_id", "count"), monetary=("net_amount_eur", "sum"))
sess_per_user = tables["sessions"].groupby("user_id").size().rename("sessions_total")
checks = {
    ("orders", "net_amount_eur"): o.net_amount_eur, ("orders", "gross_amount_eur"): o.gross_amount_eur,
    ("orders", "discount_amount_eur"): o.discount_amount_eur, ("orders", "items_count"): o.items_count,
    ("order_items", "unit_price_eur"): tables["order_items"].unit_price_eur,
    ("customers", "frequency"): cust.frequency, ("customers", "monetary"): cust.monetary,
    ("customers", "sessions_total"): sess_per_user,
    ("marketing_spend", "spend_eur"): tables["marketing_spend"].spend_eur,
}
out_rows = []
for (t, c), s in checks.items():
    s = s.dropna().astype(float)
    q1, q3 = s.quantile([.25, .75])
    iqr = q3 - q1
    lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    mad = (s - s.median()).abs().median()
    rz = 0.6745 * (s - s.median()) / mad if mad > 0 else pd.Series(0, index=s.index)
    out_rows.append(dict(table=t, column=c, n=len(s), median=s.median(), q1=q1, q3=q3, max=s.max(),
                         iqr_upper=hi, n_iqr_outliers=int(((s < lo) | (s > hi)).sum()),
                         pct_iqr=round(100 * ((s < lo) | (s > hi)).mean(), 2),
                         n_robust_z_outliers=int((rz.abs() > 3.5).sum()), skew=s.skew()))
outliers = pd.DataFrame(out_rows).round(3)
outliers.to_csv(EDA / "01_outlier_report.csv", index=False, encoding="utf-8-sig")
print(outliers[["table", "column", "median", "max", "iqr_upper", "n_iqr_outliers", "pct_iqr",
                "n_robust_z_outliers", "skew"]].to_string(index=False))

# 1-4. 시계열 구조 점검: 월별 재구매 주문 비중 (데이터가 고객 0명에서 시작하는지 확인)
m = o.assign(ym=o.order_ts.dt.to_period("M")).groupby("ym").agg(
    orders=("order_id", "count"), repeat_share=("order_type", lambda s: (s != "first").mean()))
steady = m.repeat_share.iloc[-12:].median()
rampup = m[m.repeat_share < steady * 0.5].index
print(f"재구매 비중 정상 수준(최근 12개월 중앙값) {steady:.1%}, 그 절반 미만인 초기 구간: "
      f"{', '.join(str(p) for p in rampup)}")

# %% [2] 날짜 전처리 + 전처리 파일 내보내기 ----------------------------------------
print("\n[2] 날짜 전처리·내보내기")


def ym_label(x) -> str:
    """연월 코드(202301, '202301', '2023-01', Timestamp 모두 가능) → '2023년 01월'."""
    if isinstance(x, (pd.Timestamp, pd.Period)):
        return f"{x.year}년 {x.month:02d}월"
    s = str(x).replace("-", "").replace(".", "").strip()[:6]
    return f"{s[:4]}년 {s[4:6]}월"


assert ym_label(202301) == "2023년 01월" and ym_label("2023-01") == "2023년 01월"   # 예시 형식 검증

# 2-1. 주문 분석 데이터셋: 주문 + 고객 속성 + 날짜 파생 컬럼
df = o.merge(u[["user_id", "signup_ts", "acquisition_channel", "age_band", "gender", "device_brand"]],
             on="user_id", how="left")
df["order_date"] = df.order_ts.dt.strftime("%Y-%m-%d")                        # 날짜 (YYYY-MM-DD)
df["order_ym_code"] = (df.order_ts.dt.year * 100 + df.order_ts.dt.month)       # 연월 코드 (202409)
df["주문연월"] = df.order_ym_code.map(ym_label)                                 # 연월 라벨 (2024년 09월)
df["주문분기"] = df.order_ts.dt.year.astype(str) + "년 " + df.order_ts.dt.quarter.astype(str) + "분기"
df["주문요일"] = df.order_ts.dt.dayofweek.map(dict(enumerate(WEEKDAY_KO)))
df["주문시각"] = df.order_ts.dt.hour
df["가입연월"] = df.signup_ts.map(ym_label)
first_ts = df.groupby("user_id").order_ts.transform("min")
df["코호트(첫구매연월)"] = first_ts.map(ym_label)
df["코호트경과월"] = ((df.order_ts.dt.year - first_ts.dt.year) * 12 + (df.order_ts.dt.month - first_ts.dt.month))

# 2-2. 1번 진단에 따른 처리 (삭제 대신 '표시(flag)'로 남겨 분석 목적에 따라 선택)
df["promo_code"] = df.promo_code.fillna("없음")                                # 구조적 결측 → 명시적 범주
df["ab_variant"] = df.ab_variant.fillna("비대상")
df["returned_date"] = pd.to_datetime(df.returned_ts).dt.strftime("%Y-%m-%d")   # 반품 안 된 주문은 빈칸 유지
upper = outliers.set_index(["table", "column"]).loc[("orders", "net_amount_eur"), "iqr_upper"]
df["flag_고액주문"] = df.net_amount_eur > upper                                  # 이상치는 제거하지 않고 표시
df["flag_초기구간"] = df.order_ts.dt.to_period("M").isin(rampup)                # 재구매 고객층 형성 전 구간
df["net_amount_log"] = np.log1p(df.net_amount_eur)                             # 왜도 큰 금액의 로그 변환

cols = ["order_id", "user_id", "order_date", "order_ym_code", "주문연월", "주문분기", "주문요일", "주문시각",
        "가입연월", "코호트(첫구매연월)", "코호트경과월", "country", "acquisition_channel", "traffic_source",
        "age_band", "gender", "device_brand", "device_model_at_order", "order_type", "items_count",
        "gross_amount_eur", "discount_amount_eur", "net_amount_eur", "net_amount_log", "shipping_fee_eur",
        "promo_code", "is_returned", "returned_date", "ab_variant", "has_bundle_upsell",
        "flag_고액주문", "flag_초기구간"]
orders_proc = df[cols].sort_values(["order_date", "order_id"]).reset_index(drop=True)

# 2-3. 월별 국가 KPI (연월 단위 분석·대시보드용)
first_order = df.groupby("user_id").order_ts.min().dt.to_period("M")
monthly = (df.assign(ym=df.order_ts.dt.to_period("M"))
           .groupby(["ym", "country"])
           .agg(orders=("order_id", "count"), buyers=("user_id", "nunique"), revenue_eur=("net_amount_eur", "sum"),
                aov_eur=("net_amount_eur", "mean"), return_rate=("is_returned", "mean"),
                promo_share=("promo_code", lambda s: (s != "없음").mean()),
                new_customers=("order_type", lambda s: (s == "first").sum()))
           .reset_index())
monthly.insert(0, "연월", monthly.ym.map(ym_label))
monthly.insert(0, "ym_code", monthly.ym.dt.year * 100 + monthly.ym.dt.month)
monthly["flag_초기구간"] = monthly.ym.isin(rampup)
monthly = monthly.drop(columns="ym").round({"revenue_eur": 2, "aov_eur": 2, "return_rate": 4, "promo_share": 4})

# 2-4. 내보내기: CSV는 엑셀에서 한글이 깨지지 않도록 UTF-8 BOM, 엑셀 파일도 함께
orders_proc.to_csv(PROC / "orders_processed.csv", index=False, encoding="utf-8-sig")
monthly.to_csv(PROC / "monthly_kpi_processed.csv", index=False, encoding="utf-8-sig")
with pd.ExcelWriter(PROC / "spigen_processed.xlsx") as xw:
    monthly.to_excel(xw, sheet_name="월별KPI", index=False)
    orders_proc.to_excel(xw, sheet_name="주문", index=False)
print(f"  orders_processed.csv      {len(orders_proc):,}행 × {orders_proc.shape[1]}열")
print(f"  monthly_kpi_processed.csv {len(monthly):,}행 × {monthly.shape[1]}열")
print(orders_proc[["order_date", "order_ym_code", "주문연월", "주문분기", "주문요일", "코호트(첫구매연월)"]].head(3))

# %% [3] 기술 통계 (APA 형식 표) -----------------------------------------------------
print("\n[3] 기술 통계")


def fmt(x, d=2):
    return "—" if pd.isna(x) else f"{x:,.{d}f}"


def desc_table(frame: pd.DataFrame, cols_: list[str], dec: dict | None = None) -> pd.DataFrame:
    rows = []
    for c in cols_:
        s = frame[c].dropna().astype(float)
        d = (dec or {}).get(c, 2)
        q1, q3 = s.quantile([.25, .75])
        rows.append({"변수": KO.get(c, c), "n": f"{len(s):,}", "M": fmt(s.mean(), d), "SD": fmt(s.std(), d),
                     "Mdn": fmt(s.median(), d), "IQR": f"{fmt(q1, d)}–{fmt(q3, d)}", "Min": fmt(s.min(), d),
                     "Max": fmt(s.max(), d), "왜도": fmt(s.skew()), "첨도": fmt(s.kurt())})
    return pd.DataFrame(rows)


def welch_row(frame, col, g="country", a="DE", b="IT", d=2):
    x, y = frame.loc[frame[g] == a, col].astype(float), frame.loc[frame[g] == b, col].astype(float)
    se = np.sqrt(x.var() / len(x) + y.var() / len(y))
    t = (x.mean() - y.mean()) / se
    df_ = se ** 4 / ((x.var() / len(x)) ** 2 / (len(x) - 1) + (y.var() / len(y)) ** 2 / (len(y) - 1))
    p = math.erfc(abs(t) / math.sqrt(2))                                        # 정규근사 양측 p (자유도 매우 큼)
    sp = np.sqrt(((len(x) - 1) * x.var() + (len(y) - 1) * y.var()) / (len(x) + len(y) - 2))
    ptxt = "< .001" if p < .001 else f"{p:.3f}".lstrip("0")
    return {"변수": KO.get(col, col), f"{a} M (SD)": f"{fmt(x.mean(), d)} ({fmt(x.std(), d)})",
            f"{b} M (SD)": f"{fmt(y.mean(), d)} ({fmt(y.std(), d)})", "t": fmt(t), "df": f"{df_:,.0f}",
            "p": ptxt, "d": fmt((x.mean() - y.mean()) / sp)}


cust2 = df.groupby("user_id").agg(country=("country", "first"), frequency=("order_id", "count"),
                                  monetary=("net_amount_eur", "sum"), aov=("net_amount_eur", "mean"),
                                  last=("order_ts", "max"), first=("order_ts", "min"))
snap = df.order_ts.max().normalize() + pd.Timedelta(days=1)
cust2["recency_days"] = (snap - cust2["last"]).dt.days
cust2["tenure_days"] = (snap - cust2["first"]).dt.days
cust2 = cust2.join(sess_per_user).fillna({"sessions_total": 0})

T1 = desc_table(df, ["gross_amount_eur", "discount_amount_eur", "net_amount_eur", "shipping_fee_eur", "items_count"])
T2 = desc_table(cust2, ["frequency", "monetary", "aov", "recency_days", "tenure_days", "sessions_total"],
                {"frequency": 2, "recency_days": 1, "tenure_days": 1, "sessions_total": 2})
mk = monthly[~monthly.flag_초기구간]
T3 = desc_table(mk, ["orders", "buyers", "new_customers", "revenue_eur", "aov_eur", "return_rate"],
                {"orders": 1, "buyers": 1, "new_customers": 1, "return_rate": 3})
cat_rows = []
for col, name in [("country", "국가"), ("acquisition_channel", "유입 채널"), ("age_band", "연령대"),
                  ("device_brand", "기기 브랜드"), ("order_type", "주문 유형"), ("promo_code", "할인코드"),
                  ("is_returned", "반품 여부")]:
    vc = (df[col].astype(str).replace({"True": "반품", "False": "반품 아님", **CH_KO, **OT_KO})
          .value_counts())
    if col == "promo_code":
        vc = pd.Series({"사용": int((df.promo_code != "없음").sum()), "미사용": int((df.promo_code == "없음").sum())})
    cat_rows.append({"변수": f"**{name}**", "범주": "", "n": "", "%": ""})
    for k, v in vc.items():
        cat_rows.append({"변수": "", "범주": k, "n": f"{v:,}", "%": f"{100 * v / len(df):.1f}"})
T4 = pd.DataFrame(cat_rows)
T5 = pd.DataFrame([welch_row(df, "net_amount_eur"), welch_row(df, "items_count"),
                   welch_row(cust2, "frequency"), welch_row(cust2, "monetary"), welch_row(cust2, "recency_days", d=1)])

n_orders, n_cust, n_mk = len(df), len(cust2), len(mk)
APA = [
    ("표 1", f"주문 단위 연속형 변수의 기술 통계 (N = {n_orders:,})", T1,
     "주. 금액 단위는 유로(€). 순 주문금액 = 총 주문금액 − 할인금액이며 배송비는 제외했다. IQR은 제1사분위수–제3사분위수, "
     "첨도는 초과 첨도(정규분포 = 0)이다. 합성 데이터."),
    ("표 2", f"고객 단위 구매·방문 행동의 기술 통계 (N = {n_cust:,})", T2,
     f"주. 기준일은 {snap:%Y-%m-%d}이다. 누적 순매출은 반품 주문을 포함한 합계이다. 총 방문 수는 로그인 세션 기준이다. 합성 데이터."),
    ("표 3", f"국가별 월간 KPI의 기술 통계 (N = {n_mk} 국가·월)", T3,
     f"주. 재구매 고객층이 형성되기 전인 초기 {len(rampup)}개월({', '.join(ym_label(p) for p in rampup)})은 제외했다. "
     "반품률은 비율(0–1)이다. 합성 데이터."),
    ("표 4", f"주문 단위 범주형 변수의 빈도와 비율 (N = {n_orders:,})", T4,
     "주. 비율(%)은 전체 주문 대비이다. 유입 채널·연령대·기기 브랜드는 고객의 가입 시점 속성이다. 합성 데이터."),
    ("표 5", "국가별(독일 vs 이탈리아) 주요 변수 비교", T5,
     "주. t = Welch의 t 검정(등분산 가정 없음), df = Welch–Satterthwaite 자유도, d = Cohen의 d(합동 표준편차 기준). "
     "자유도가 매우 커 p값은 정규분포로 근사했다. 주문 금액·품목 수는 주문 단위, 나머지는 고객 단위이다. 합성 데이터."),
]


def md_table(t: pd.DataFrame) -> str:
    h = "| " + " | ".join(t.columns) + " |\n|" + "|".join(":---" if i == 0 else "---:" for i in range(len(t.columns))) + "|\n"
    return h + "\n".join("| " + " | ".join(str(v) for v in r) + " |" for r in t.itertuples(index=False))


md = ["# 기술 통계 분석 결과 (APA 7판 형식)\n", "> 데이터: spigen-synthetic-data (합성 데이터). 수치는 실제 기업 성과가 아니다.\n"]
html = ["<html><head><meta charset='utf-8'><style>body{font-family:'Times New Roman','Batang',serif;font-size:12pt;"
        "max-width:900px;margin:40px auto;line-height:2}table{border-collapse:collapse;width:100%;margin:6px 0}"
        "th{border-top:1.5px solid #000;border-bottom:1px solid #000;font-weight:normal;padding:2px 8px;text-align:center}"
        "td{padding:2px 8px;text-align:right}td:first-child,td:nth-child(2){text-align:left}"
        "tbody tr:last-child td{border-bottom:1.5px solid #000}.num{font-weight:bold}.ttl{font-style:italic}"
        ".note{font-size:11pt;line-height:1.5}</style></head><body>"]
for num, title, t, note in APA:
    md += [f"**{num}**\n", f"*{title}*\n", md_table(t), "", note, ""]
    t_html = t.copy()
    t_html["변수"] = t_html["변수"].str.replace(r"\*\*(.+)\*\*", r"<i>\1</i>", regex=True)
    html += [f"<p class='num'>{num}</p><p class='ttl'>{title}</p>",
             t_html.to_html(index=False, escape=False, border=0).replace(' class="dataframe"', ""),
             f"<p class='note'><i>주.</i>{note[2:]}</p><br>"]
(EDA / "03_descriptive_apa.md").write_text("\n".join(md), encoding="utf-8")
(EDA / "03_descriptive_apa.html").write_text("".join(html) + "</body></html>", encoding="utf-8")
for num, title, t, _ in APA:
    t.to_csv(EDA / f"03_{num.replace(' ', '')}.csv", index=False, encoding="utf-8-sig")
print("\n".join(md[:12]))

# %% [4] 일변량·다변량 EDA --------------------------------------------------------------
print("\n[4] EDA")
dm = df.copy()
dm["ym"] = dm.order_ts.dt.to_period("M").dt.to_timestamp()

# 4-1. 일변량
fig, ax = plt.subplots(2, 3, figsize=(18, 9.2))
med, mean = dm.net_amount_eur.median(), dm.net_amount_eur.mean()
headline(fig, f"주문 금액은 오른쪽으로 긴 분포: 중앙값 €{med:.0f}, 평균 €{mean:.0f}, 상위 주문이 평균을 끌어올린다",
         f"일변량 EDA · 주문 {len(dm):,}건 · 고객 {dm.user_id.nunique():,}명 · 2024.09–2026.08 · 합성 데이터")
a = ax[0, 0]                                                           # 순 주문금액 분포 (로그 구간)
bins = np.logspace(np.log10(max(dm.net_amount_eur.min(), 1)), np.log10(dm.net_amount_eur.max()), 45)
a.hist(dm.net_amount_eur, bins=bins, color=OI["sky"], edgecolor="white", lw=0.3)
a.set_xscale("log")
a.axvline(med, color=INK, ls="--", lw=1.5, label=f"중앙값 €{med:.0f}")
a.axvline(mean, color=OI["vermillion"], lw=1.5, label=f"평균 €{mean:.0f}")
a.axvline(upper, color=MUTED, ls=":", lw=1.5, label=f"IQR 상한 €{upper:.0f}")
a.set_title("순 주문금액 분포 (가로축 로그)")
a.set_xlabel("순 주문금액 (€, 로그 눈금)")
a.set_ylabel("주문 수 (건)")
a.xaxis.set_major_formatter(FuncFormatter(lambda x, p: f"€{x:,.0f}"))
a.legend()
insight(a, f"왜도 {dm.net_amount_eur.skew():.2f} → 평균보다 중앙값·로그 변환 사용\n"
           f"IQR 상한 초과 {dm.flag_고액주문.mean():.1%}: 제거 대신 표시", xy=(0.98, 0.60), ha="right")

a = ax[0, 1]                                                           # 품목 수
vc = dm.items_count.clip(upper=6).value_counts().sort_index()
a.bar([str(i) if i < 6 else "6+" for i in vc.index], vc.values / len(dm) * 100, color=OI["blue"], width=0.6)
for i, v in enumerate(vc.values / len(dm) * 100):
    a.text(i, v + 1, f"{v:.0f}%", ha="center", fontsize=9)
a.set_title("주문당 품목 수")
a.set_xlabel("품목 수 (개)")
a.set_ylabel("주문 비중 (%)")
a.yaxis.set_major_formatter(PercentFormatter(decimals=0))
a.grid(axis="x", visible=False)

a = ax[0, 2]                                                           # 월별 주문 수
mo = dm.groupby("ym").order_id.count()
a.plot(mo.index, mo.values, color=INK, lw=2)
a.axvspan(mo.index.min(), (rampup.max().to_timestamp() + pd.offsets.MonthEnd(0)) if len(rampup) else mo.index.min(),
          color="#bbbbbb", alpha=0.3, lw=0)
a.text(mo.index.min(), mo.max() * 0.95, " 초기 구간\n (재구매층 형성 전)", fontsize=8, color=MUTED, va="top")
a.set_title("월별 주문 수")
a.set_xlabel("연월")
a.set_ylabel("주문 수 (건)")
a.xaxis.set_major_formatter(plt.matplotlib.dates.DateFormatter("%y.%m"))

a = ax[1, 0]                                                           # 유입 채널 (고객 기준)
ch = u.acquisition_channel.map(CH_KO).value_counts(normalize=True).sort_values() * 100
a.barh(ch.index, ch.values, color=OI["blue"])
for i, v in enumerate(ch.values):
    a.text(v + 0.4, i, f"{v:.1f}%", va="center", fontsize=9)
a.set_title("고객 유입 채널 (가입 기준)")
a.set_xlabel("고객 비중 (%)")
a.xaxis.set_major_formatter(PercentFormatter(decimals=0))
a.grid(axis="y", visible=False)

a = ax[1, 1]                                                           # 연령대 × 국가 (국가 내 비중)
ag = pd.crosstab(u.age_band, u.country, normalize="columns") * 100
x = np.arange(len(ag))
for j, c in enumerate(["DE", "IT"]):
    a.bar(x + (j - 0.5) * 0.38, ag[c], width=0.38, color=COUNTRY[c], label=c, hatch="" if c == "DE" else "//",
          edgecolor="white")
a.set_xticks(x, ag.index)
a.set_title("고객 연령대 (국가 내 비중)")
a.set_xlabel("연령대")
a.set_ylabel("고객 비중 (%)")
a.yaxis.set_major_formatter(PercentFormatter(decimals=0))
a.legend()
a.grid(axis="x", visible=False)

a = ax[1, 2]                                                           # 주문 유형
ot = dm.order_type.map(OT_KO).value_counts(normalize=True) * 100
rev = dm.groupby(dm.order_type.map(OT_KO)).net_amount_eur.sum() / dm.net_amount_eur.sum() * 100
xx = np.arange(len(ot))
a.bar(xx - 0.19, ot.values, width=0.38, color="white", edgecolor=OI["blue"], hatch="///", label="주문 비중")
a.bar(xx + 0.19, rev[ot.index].values, width=0.38, color=OI["blue"], label="매출 비중")
for i, (v1, v2) in enumerate(zip(ot.values, rev[ot.index].values)):
    a.text(i - 0.19, v1 + 1, f"{v1:.0f}%", ha="center", fontsize=8.5, color=MUTED)
    a.text(i + 0.19, v2 + 1, f"{v2:.0f}%", ha="center", fontsize=8.5, fontweight="bold")
a.set_xticks(xx, ot.index)
a.set_title("주문 유형별 주문·매출 비중")
a.set_ylabel("비중 (%)")
a.yaxis.set_major_formatter(PercentFormatter(decimals=0))
a.legend()
a.grid(axis="x", visible=False)
finish(fig, EDA / "04_univariate.png")

# 4-2. 다변량
fig, ax = plt.subplots(2, 3, figsize=(18, 9.6))
num = cust2[["frequency", "monetary", "aov", "recency_days", "tenure_days", "sessions_total"]]
corr = num.corr(method="spearman")                                    # 치우친 분포라 순위 상관(스피어만)
r_fm = corr.loc["frequency", "sessions_total"]
rep = num[num.frequency >= 2]                                           # 재구매 고객만 (1회 구매자는 누적매출 = 객단가)
corr_rep = rep.corr(method="spearman")
headline(fig, f"방문이 많은 고객이 더 자주 산다 (구매 횟수–방문 수 ρ = {r_fm:.2f}): 방문 데이터를 이탈 예측 피처로 검토할 만하다",
         f"다변량 EDA · 고객 {len(cust2):,}명 · 주문 {len(dm):,}건 · 스피어만 순위 상관 · 합성 데이터")
a = ax[0, 0]
im = a.imshow(corr.values, cmap=DIVERGING, vmin=-1, vmax=1)
labs = [KO[c] for c in corr.columns]
a.set_xticks(range(len(labs)), labs, rotation=40, ha="right", fontsize=8.5)
a.set_yticks(range(len(labs)), labs, fontsize=8.5)
for i in range(len(labs)):
    for j in range(len(labs)):
        v = corr.values[i, j]
        a.text(j, i, f"{v:.2f}", ha="center", va="center", fontsize=8, color="white" if abs(v) > 0.6 else INK)
a.grid(False)
fig.colorbar(im, ax=a, fraction=0.046, pad=0.03).set_label("스피어만 ρ")
a.set_title("고객 행동 변수 간 순위 상관")

a = ax[0, 1]                                                           # 구매 횟수 × 누적 매출
sm = cust2.sample(min(6000, len(cust2)), random_state=1)
for c in ["DE", "IT"]:
    s = sm[sm.country == c]
    a.scatter(s.frequency + np.random.default_rng(1).uniform(-0.25, 0.25, len(s)), s.monetary, s=6, alpha=0.3,
              color=COUNTRY[c], marker="o" if c == "DE" else "^", label=c, linewidths=0)
a.set_yscale("log")
a.set_title("구매 횟수와 누적 매출 (표본 6,000명)")
a.set_xlabel("구매 횟수 (회, 겹침 방지 흔들기)")
a.set_ylabel("누적 순매출 (€, 로그)")
a.yaxis.set_major_formatter(FuncFormatter(lambda x, p: f"€{x:,.0f}"))
a.legend(markerscale=3)
insight(a, f"전체 ρ = {corr.loc['frequency', 'monetary']:.2f}, 재구매 고객만 ρ = {corr_rep.loc['frequency', 'monetary']:.2f}\n"
           f"(1회 구매자 {1 - len(rep) / len(num):.0%}는 누적매출 = 객단가)", xy=(0.98, 0.03), ha="right", va="bottom")

a = ax[0, 2]                                                           # 월별 매출 × 국가
mr = dm.groupby(["ym", "country"]).net_amount_eur.sum().unstack()
for c in ["DE", "IT"]:
    a.plot(mr.index, mr[c], color=COUNTRY[c], lw=2, ls="-" if c == "DE" else "--", label=c)
    a.annotate(f"{c} €{mr[c].iloc[-1] / 1000:.0f}k", (mr.index[-1], mr[c].iloc[-1]), xytext=(4, 0),
               textcoords="offset points", fontsize=9, color=COUNTRY[c], va="center")
a.set_title("국가별 월 매출")
a.set_xlabel("연월")
a.set_ylabel("월 매출 (€)")
a.yaxis.set_major_formatter(FuncFormatter(eur))
a.xaxis.set_major_formatter(plt.matplotlib.dates.DateFormatter("%y.%m"))
a.legend(loc="upper left")

a = ax[1, 0]                                                           # 유입 채널 × 국가: 1인당 누적 매출
cc = cust2.join(u.set_index("user_id").acquisition_channel).groupby(["acquisition_channel", "country"]).monetary
ltv = cc.mean().unstack()
se = (cc.std() / np.sqrt(cc.count())).unstack()
ltv = ltv.loc[ltv.mean(axis=1).sort_values().index]
y = np.arange(len(ltv))
for j, c in enumerate(["DE", "IT"]):
    a.barh(y + (j - 0.5) * 0.38, ltv[c], xerr=1.96 * se.loc[ltv.index, c], height=0.38, color=COUNTRY[c],
           label=c, hatch="" if c == "DE" else "//", edgecolor="white", error_kw=dict(lw=0.8, ecolor=MUTED))
a.set_yticks(y, [CH_KO[i] for i in ltv.index])
a.set_title("유입 채널별 고객 1인당 누적 매출 (95% CI)")
a.set_xlabel("1인당 누적 순매출 (€)")
a.legend(loc="lower right")
a.grid(axis="y", visible=False)
best, worst = ltv.mean(axis=1).idxmax(), ltv.mean(axis=1).idxmin()
insight(a, f"{CH_KO[best]} 유입 고객이 {CH_KO[worst]}의 {ltv.loc[best].mean() / ltv.loc[worst].mean():.1f}배",
        xy=(0.98, 0.25), ha="right", va="bottom")

a = ax[1, 1]                                                           # 할인코드 × 주문 유형: 객단가
pv = dm.assign(할인=np.where(dm.promo_code == "없음", "할인 없음", "할인 사용"))
g = pv.groupby([pv.order_type.map(OT_KO), "할인"]).net_amount_eur.agg(["mean", "count", "std"])
xs = np.arange(len(g.index.levels[0]))
for j, (k, col_, h) in enumerate([("할인 없음", OI["blue"], ""), ("할인 사용", OI["orange"], "//")]):
    sub = g.xs(k, level=1).reindex(g.index.levels[0])
    a.bar(xs + (j - 0.5) * 0.38, sub["mean"], width=0.38, color=col_, hatch=h, edgecolor="white", label=k,
          yerr=1.96 * sub["std"] / np.sqrt(sub["count"]), error_kw=dict(lw=0.8, ecolor=MUTED))
a.set_xticks(xs, g.index.levels[0])
a.set_title("주문 유형 × 할인 사용별 평균 순 주문금액 (95% CI)")
a.set_ylabel("평균 순 주문금액 (€)")
a.legend()
a.grid(axis="x", visible=False)

a = ax[1, 2]                                                           # 요일 × 시간대 주문 히트맵
hm = pd.crosstab(dm.주문요일, dm.주문시각).reindex(WEEKDAY_KO)
hm = hm / hm.values.sum() * 100
im = a.imshow(hm.values, aspect="auto", cmap="Blues")
a.set_yticks(range(7), WEEKDAY_KO)
a.set_xticks(range(0, 24, 3), [f"{h}시" for h in range(0, 24, 3)])
a.set_title("요일 × 시간대별 주문 분포")
a.set_xlabel("주문 시각")
a.grid(False)
fig.colorbar(im, ax=a, fraction=0.046, pad=0.03).set_label("전체 주문 대비 (%)")
pk = hm.stack().idxmax()
insight(a, f"피크: {pk[0]}요일 {pk[1]}시 → 광고 예산 시간대 가중에 활용", xy=(0.02, 0.03), va="bottom")
finish(fig, EDA / "04_multivariate.png")

# 4-3. EDA 요약 (수치 자동 기입)
summary = f"""# EDA 요약 (합성 데이터)

## 일변량
- 순 주문금액: 중앙값 €{med:.2f}, 평균 €{mean:.2f}, 왜도 {dm.net_amount_eur.skew():.2f} → 오른쪽 꼬리가 긴 분포. 요약은 중앙값, 모델링은 로그 변환을 쓴다.
- IQR 상한(€{upper:.2f}) 초과 주문 {dm.flag_고액주문.mean():.1%}: 여러 품목을 함께 산 정상 주문이라 삭제하지 않고 `flag_고액주문`으로 표시했다.
- 주문 유형: 첫 구매 {ot.get('첫 구매', 0):.1f}%, 재구매 {ot.get('재구매', 0):.1f}%, 기기 교체 구매 {ot.get('기기 교체 구매', 0):.1f}%.
- 초기 구간({', '.join(ym_label(p) for p in rampup)})은 재구매 고객층이 형성되기 전이라 월별 추세·전년 대비 비교에서 제외하거나 따로 표시한다.

## 다변량
- 누적 매출과의 상관: 전체 고객에서는 객단가 ρ = {corr.loc['aov', 'monetary']:.2f}, 구매 횟수 ρ = {corr.loc['frequency', 'monetary']:.2f}.
  전체의 {1 - len(rep) / len(num):.0%}인 1회 구매자는 누적 매출이 곧 객단가라서 객단가 상관이 커 보인다.
  재구매 고객({len(rep):,}명)만 보면 구매 횟수 ρ = {corr_rep.loc['frequency', 'monetary']:.2f}, 객단가 ρ = {corr_rep.loc['aov', 'monetary']:.2f}로
  {'구매 횟수가 더 크다' if corr_rep.loc['frequency', 'monetary'] > corr_rep.loc['aov', 'monetary'] else '객단가가 더 크다'}. → 재구매 전환과 객단가 모두 관리 대상이다.
- 구매 횟수–방문 수 ρ = {r_fm:.2f}로 강한 양의 상관. 반면 최근 구매 경과일–방문 수는 ρ = {corr.loc["recency_days", "sessions_total"]:.2f}에 그쳐 약하다.
  방문 데이터는 이탈 예측 피처 후보지만, '방문 감소가 이탈보다 먼저 온다'는 선행성은 시점별(스냅샷) 분석으로 따로 확인해야 한다.
- 유입 채널별 1인당 누적 매출: 가장 높은 채널 {CH_KO[best]} €{ltv.loc[best].mean():.1f}, 가장 낮은 채널 {CH_KO[worst]} €{ltv.loc[worst].mean():.1f} ({ltv.loc[best].mean() / ltv.loc[worst].mean():.1f}배).
- 주문 피크 시간대: {pk[0]}요일 {pk[1]}시.
"""
(EDA / "04_eda_summary.md").write_text(summary, encoding="utf-8")
print(summary)
