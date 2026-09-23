# %% [markdown]
# # Prophet 시계열 분석: 국가별 일매출 예측과 4분기 피크 주간
# - 데이터: spigen-synthetic-data (합성 데이터) — orders.csv, dim_calendar.csv(실측 Google Trends 수요지수)
# - 목적: 2026년 9–12월 매출을 예측해 광고 예산을 집중할 피크 주간을 찾는다 (주제 1: 수요 캘린더 기반 예산 배분)
# - 검증: 세 구간을 떼어 두고 두 모델을 비교한다 — 4분기(2025.9–12), 봄(2026.2–4, 갤럭시 출시), 여름(2026.6–8)
#     모델 A = 추세 + 주간·연간 계절성 + 이벤트(블프·크리스마스·아이폰·갤럭시 S/A 출시·여름 세일)
#     모델 B = 모델 A + 외부 변수(Google Trends 수요지수)

# %% [0] 설정
import logging
import sys
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.ticker import FuncFormatter
from prophet import Prophet

sys.path.insert(0, str(Path(__file__).resolve().parent))
from style import (COUNTRY, FIG, INK, MUTED, OI, eur, export_tableau, finish, headline, insight,  # noqa: E402
                   reset_catalog, setup)

setup()                                                                  # 색맹 친화 팔레트·한글 폰트·기본 스타일
logging.getLogger("cmdstanpy").setLevel(logging.WARNING)                 # Stan 학습 로그 숨김
ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
BACKTESTS = {"4분기 2025.9–12": ("2025-09-01", "2025-12-31"),            # 검증 구간: (시작, 끝)
             "봄 2026.2–4": ("2026-02-01", "2026-04-30"),               # 갤럭시 S26·A57 출시 구간
             "여름 2026.6–8": ("2026-06-01", "2026-08-31")}
FORECAST_END = pd.Timestamp("2026-12-31")                                # 예측 끝
COUNTRIES = ["DE", "IT"]

# %% [1] 데이터 로드
orders = pd.read_csv(RAW / "orders.csv", parse_dates=["order_ts"], dtype={"ab_variant": "string"})
cal = pd.read_csv(RAW / "dim_calendar.csv", parse_dates=["date"])
print(f"주문 {len(orders):,}건, 기간 {orders.order_ts.min():%Y-%m-%d} ~ {orders.order_ts.max():%Y-%m-%d}")

# %% [2] 전처리
# 2-1. 국가·일 단위 매출 집계 (주문이 없는 날은 0으로 채움)
orders["ds"] = orders.order_ts.dt.normalize()
daily = (orders.groupby(["country", "ds"]).net_amount_eur.sum()
         .unstack("country").asfreq("D").fillna(0).stack().rename("y").reset_index())

# 2-2. 외부 변수: 수요지수 붙이기 (모델 B용)
daily = daily.merge(cal.rename(columns={"date": "ds"})[["ds", "country", "demand_index"]], on=["ds", "country"])

# 2-3. 이벤트 캘린더 (Prophet holidays 형식). 2026년 날짜는 예측을 위한 가정
events = pd.DataFrame([
    # 블랙프라이데이: 전 4일 ~ 사이버먼데이까지
    *[dict(holiday="black_friday", ds=d, lower_window=-4, upper_window=3)
      for d in ["2024-11-29", "2025-11-28", "2026-11-27"]],
    # 크리스마스 선물 시즌: 2주 전부터
    *[dict(holiday="christmas", ds=d, lower_window=-14, upper_window=0)
      for d in ["2024-12-24", "2025-12-24", "2026-12-24"]],
    # 신형 아이폰 출시: 출시 후 2주 (2026-09-18은 가정)
    *[dict(holiday="iphone_launch", ds=d, lower_window=-3, upper_window=14)
      for d in ["2024-09-20", "2025-09-19", "2026-09-18"]],
    # 여름 세일 (과거만 존재)
    *[dict(holiday="summer_sale", ds=d, lower_window=0, upper_window=13)
      for d in ["2025-07-07", "2026-07-06"]],
    # 갤럭시 출시: 출시일이 해마다 바뀌어(S25 2/7 → S26 3/6) 연간 계절성으로는 시점을 못 맞춘다 → 이벤트로 명시.
    # S(플래그십)와 A(중급) 시리즈는 효과 크기가 달라 별도 이벤트로 둔다. 하나로 묶으면 두 효과가 평균나고,
    # 2026년처럼 두 출시 기간이 겹칠 때 예측이 왜곡된다 (검증 결과 독일 봄 MAPE 15.9% → 25.0%로 악화).
    *[dict(holiday="galaxy_s_launch", ds=d, lower_window=-2, upper_window=14)
      for d in ["2025-02-07", "2026-03-06"]],
    *[dict(holiday="galaxy_a_launch", ds=d, lower_window=-2, upper_window=14)
      for d in ["2025-03-10", "2026-03-16"]],
])
events["ds"] = pd.to_datetime(events.ds)
print(daily.groupby("country").y.describe().round(1))


def make_model(with_regressor: bool) -> Prophet:
    """모델 A/B 공통 설정. 데이터가 2년뿐이라 연간 계절성은 푸리에 차수를 낮게 둔다."""
    m = Prophet(holidays=events, weekly_seasonality=True, yearly_seasonality=6, daily_seasonality=False,
                seasonality_mode="multiplicative", changepoint_prior_scale=0.05, interval_width=0.8)
    if with_regressor:
        m.add_regressor("demand_index", mode="multiplicative")
    return m


def to_weekly(s: pd.Series | pd.DataFrame):
    """일 → 주(일요일 시작) 합계. 7일이 다 차지 않은 주는 합계가 작게 나와 급락처럼 보이므로 제외한다."""
    r = s.resample("W-SUN", label="left", closed="left")
    n = r.size()                                                         # 주별 일수
    return r.sum()[n == 7]


def weekly_mape(actual: pd.Series, pred: pd.Series) -> float:
    """일 단위는 변동이 커서 주 단위로 합친 뒤 평균절대백분율오차(MAPE)를 계산."""
    a, p = to_weekly(actual), to_weekly(pred)
    return float((np.abs(a - p) / a).mean())


# %% [3] 분석
backtest, forecasts, models = {}, {}, {}
for c in COUNTRIES:
    df = daily[daily.country == c][["ds", "y", "demand_index"]]
    backtest[c] = {}
    # 3-1. 검증: 구간 시작 전 데이터로만 학습 → 구간 예측 → 실제와 비교. 모델 A(이벤트) vs 모델 B(이벤트 + 수요지수)
    for win, (start, end) in BACKTESTS.items():
        train, test = df[df.ds < start], df[(df.ds >= start) & (df.ds <= end)]
        res = {}
        for name, reg in [("A", False), ("B", True)]:
            m = make_model(reg).fit(train)
            fc = m.predict(test.drop(columns="y")).set_index("ds").yhat
            res[name] = dict(pred=fc, mape=weekly_mape(test.set_index("ds").y, fc))
        backtest[c][win] = dict(actual=test.set_index("ds").y, **res)
        print(f"[{c}] {win} 주간 MAPE — 모델 A {res['A']['mape']:.1%} / 모델 B {res['B']['mape']:.1%}")

    # 3-2. 미래 예측: 수요지수의 미래 값은 알 수 없으므로 모델 A를 전체 데이터로 다시 학습
    m = make_model(False).fit(df[["ds", "y"]])
    future = m.make_future_dataframe(periods=(FORECAST_END - df.ds.max()).days)
    forecasts[c] = m.predict(future)
    models[c] = m

# 3-3. 4분기(10–12월) 주간 예측과 피크 주간
weekly = {}
for c, fc in forecasts.items():
    f = fc[(fc.ds >= "2026-09-01") & (fc.ds <= FORECAST_END)].set_index("ds")
    w = to_weekly(f[["yhat", "yhat_lower", "yhat_upper"]])
    w = w[w.index >= "2026-08-30"]
    w["share_pct"] = w.yhat / w.yhat.sum() * 100
    weekly[c] = w
    print(f"\n[{c}] 2026.9–12 주간 예측 상위 5주")
    print(w.sort_values("yhat", ascending=False).head(5).round(0))

# 3-4. 이벤트 효과는 Prophet 계수 대신 실제 매출로 계산한다.
#      데이터가 2년뿐이면 연간 계절성과 이벤트가 같은 시기에 겹쳐 모델이 둘을 구분하지 못한다(식별 불가).
#      실제로 블랙프라이데이 계수가 음수로 나오는데, 실제 매출은 평소보다 높다 → 계수를 효과로 해석하면 안 된다.
EVENT_WEEKS = {"블랙프라이데이": "2025-11-23", "크리스마스 직전": "2025-12-21", "아이폰 출시": "2025-09-21",
               "갤럭시 S26 출시": "2026-03-08"}                                   # 이벤트 주 시작일(일)
effects = {}
for c in COUNTRIES:
    wk = to_weekly(daily[daily.country == c].set_index("ds").y)
    effects[c] = {}
    for ev, d in EVENT_WEEKS.items():
        d = pd.Timestamp(d)
        base = wk[d - pd.Timedelta(weeks=5): d - pd.Timedelta(weeks=1)].mean()   # 직전 4주 평균 (이벤트 영향 전)
        effects[c][ev] = wk[d] / base - 1
    fc = forecasts[c]
    effects[c]["(참고) Prophet 블프 계수"] = fc.loc[fc.black_friday != 0, "black_friday"].mean()
effects = pd.DataFrame(effects)
print(effects.round(3))

# %% [4] 시각화 — 제목은 결론 한 문장, 차트 안에 인사이트를 직접 표시
EV_KO = {"black_friday": "블프", "christmas": "크리스마스", "iphone_launch": "아이폰 출시",
         "galaxy_s_launch": "갤럭시 S", "galaxy_a_launch": "갤럭시 A", "summer_sale": "여름 세일"}
peaks = {c: weekly[c].yhat.idxmax() for c in COUNTRIES}
same_peak = len(set(peaks.values())) == 1
fig, ax = plt.subplots(2, 2, figsize=(17, 9.6), gridspec_kw={"width_ratios": [1, 1.25]})
headline(fig,
         (f"두 나라 모두 {peaks['DE']:%m월 %d일} 주가 연말 매출 정점: 광고 예산을 피크 주간에 앞당겨 배정해야 한다"
          if same_peak else
          f"연말 매출 정점은 DE {peaks['DE']:%m/%d}주, IT {peaks['IT']:%m/%d}주: 국가별로 예산 집중 시점이 다르다"),
         "국가별 일매출을 주간 합계로 표시 · Prophet(추세 + 주간·연간 계절성 + 이벤트) · "
         "검증은 학습에 쓰지 않은 구간으로 평가 · 합성 데이터")

win = "4분기 2025.9–12"
for i, c in enumerate(COUNTRIES):
    col = COUNTRY[c]
    # 4-1. 검증: 실제(검정 실선) vs 모델 A(국가색 파선) vs 모델 B(보라 점선+마커) — 색과 선 모양으로 이중 구분
    bt = backtest[c][win]
    act = to_weekly(bt["actual"])
    ax[i, 0].plot(act.index, act, color=INK, lw=2.4, label="실제 매출")
    ax[i, 0].plot(act.index, to_weekly(bt["A"]["pred"]), color=col, lw=2, ls="--",
                  label=f"모델 A: 이벤트 (오차 {bt['A']['mape']:.1%})")
    ax[i, 0].plot(act.index, to_weekly(bt["B"]["pred"]), color=OI["purple"], lw=1.8, ls=":", marker="o", ms=3.5,
                  label=f"모델 B: +검색 수요지수 (오차 {bt['B']['mape']:.1%})")
    ax[i, 0].set_title(f"{c} 예측 검증: {win} (학습에 쓰지 않은 구간)")
    ax[i, 0].set_ylabel("주간 매출 (EUR)")
    ax[i, 0].set_xlabel("주 시작일")
    ax[i, 0].yaxis.set_major_formatter(FuncFormatter(eur))
    ax[i, 0].xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
    ax[i, 0].legend(loc="upper left")
    mape_all = "  ".join(f"{w.split()[0]} {backtest[c][w]['A']['mape'] * 100:.1f}→{backtest[c][w]['B']['mape'] * 100:.1f}%"
                         for w in BACKTESTS)
    insight(ax[i, 0], f"주간 오차(MAPE) A→B\n{mape_all}", xy=(0.98, 0.03), ha="right", va="bottom")

    # 4-2. 최근 실적 + 2026.9–12 예측 (80% 구간), 이벤트 기간 음영, 상위 3주 값 직접 표시
    hist = to_weekly(daily[daily.country == c].set_index("ds").y)
    hist = hist[hist.index >= "2025-07-01"]                         # 작년 같은 시즌과 비교할 수 있게 작년 7월부터
    fc = forecasts[c].set_index("ds")
    fw = to_weekly(fc[["yhat", "yhat_lower", "yhat_upper"]])        # 주간 구간 = 일별 구간 단순 합산(근사, 실제보다 넓음)
    fw = fw[fw.index > hist.index.max()]
    a = ax[i, 1]
    spans = []                                                      # 이벤트 기간 (가까운 이벤트는 이름을 합침)
    for _, e in events[events.ds >= "2025-07-01"].sort_values("ds").iterrows():
        s, t = e.ds + pd.Timedelta(days=e.lower_window), e.ds + pd.Timedelta(days=e.upper_window)
        a.axvspan(s, t, color="#bbbbbb", alpha=0.25, lw=0)
        if spans and (s - spans[-1][0]).days <= 14:
            spans[-1][2].append(EV_KO[e.holiday])
        else:
            spans.append([s, t, [EV_KO[e.holiday]]])
    for s, t, names in spans:                                       # 이름은 음영 안쪽 아래, 세로로 (겹침 방지)
        a.text(s + (t - s) / 2, 0.02, "·".join(dict.fromkeys(names)), transform=a.get_xaxis_transform(),
               rotation=90, ha="center", va="bottom", fontsize=8, color=MUTED)
    a.plot(hist.index, hist, color=INK, lw=1.6, label="실제 매출")
    a.fill_between(fw.index, fw.yhat_lower, fw.yhat_upper, color=col, alpha=0.18, lw=0, label="예측 80% 구간")
    a.plot(fw.index, fw.yhat, color=col, lw=2.4, label="예측 (모델 A)")
    for d, v in weekly[c].yhat.nlargest(3).items():
        a.plot(d, v, "o", ms=7, color=col, mec="white", mew=1.5, zorder=5)
        a.annotate(f"{d:%m/%d}주\n{eur(v)}", (d, v), xytext=(0, 10), textcoords="offset points", ha="center",
                   fontsize=8.5, fontweight="bold", color=INK)
    a.set_title(f"{c} 주간 매출: 최근 실적과 2026년 9–12월 예측")
    a.set_ylabel("주간 매출 (EUR)")
    a.set_xlabel("주 시작일")
    a.yaxis.set_major_formatter(FuncFormatter(eur))
    a.xaxis.set_major_formatter(mdates.DateFormatter("%y.%m"))
    a.set_ylim(0, max(fw.yhat_upper.max(), hist.max()) * 1.22)
    a.legend(loc="upper left")
    w = weekly[c]
    insight(a, f"예측 상위 8주 = 기간 매출의 {w.yhat.nlargest(8).sum() / w.yhat.sum():.0%} (균등 배분이면 {8 / len(w):.0%})\n"
               f"피크 주 매출은 비수기 최저 주의 {w.yhat.max() / w.yhat.min():.1f}배",
            xy=(0.60, 0.97), ha="center", va="top")
finish(fig, FIG / "prophet_forecast.png")

# 4-3. Prophet 구성요소 (추세·이벤트·주간·연간 계절성) — 독일 모델, Prophet 기본 그림
comp = models["DE"].plot_components(forecasts["DE"])
comp.savefig(FIG / "prophet_components_DE.png", dpi=120)
print(f"그래프 저장: {FIG / 'prophet_forecast.png'}, {FIG / 'prophet_components_DE.png'}")

# %% [5] 인사이트 도출 (수치는 모두 위 결과에서 자동으로 채움)
lines = []
for c in COUNTRIES:
    w = weekly[c]
    top3 = w.yhat.nlargest(3)
    top8_share = w.yhat.nlargest(8).sum() / w.yhat.sum()
    lines.append(
        f"- **{c}**: 예측 기간 {len(w)}주 중 매출 상위 3주는 "
        f"{', '.join(f'{d:%m/%d}주({v:,.0f}€)' for d, v in top3.items())}. "
        f"상위 8주가 기간 매출의 {top8_share:.0%}를 차지한다 (균등 배분이면 {8 / len(w):.0%}).")
bt_lines = [f"| {c} | {win} | {backtest[c][win]['A']['mape']:.1%} | {backtest[c][win]['B']['mape']:.1%} |"
            for c in COUNTRIES for win in BACKTESTS]
eff = effects
eff_lines = [f"- {ev}: DE {eff.loc[ev, 'DE']:+.0%}, IT {eff.loc[ev, 'IT']:+.0%}" for ev in EVENT_WEEKS]
# 모델 B가 나았던 구간 수 → 문장 자동 선택
b_wins = [(c, w) for c in COUNTRIES for w in BACKTESTS if backtest[c][w]["B"]["mape"] < backtest[c][w]["A"]["mape"]]
b_loses = [f"{c} {w}" for c in COUNTRIES for w in BACKTESTS if (c, w) not in b_wins]
reg_note = (f"수요지수를 넣은 모델 B가 {len(b_wins)}/{len(COUNTRIES) * len(BACKTESTS)}개 구간에서 오차가 더 작았다"
            + (f" (예외: {', '.join(b_loses)})." if b_loses else "."))
# 이벤트 비교 문장: 국가 간 비교 + 국가별 최대 이벤트
cmp = [f"{ev} 효과는 {'독일이' if eff.loc[ev, 'DE'] > eff.loc[ev, 'IT'] else '이탈리아가'} 더 크다"
       for ev in ["블랙프라이데이", "크리스마스 직전"]]
biggest = {c: eff.loc[list(EVENT_WEEKS), c].idxmax() for c in COUNTRIES}
big_note = (f"두 나라 모두 가장 큰 이벤트는 {biggest['DE']} 주다" if biggest["DE"] == biggest["IT"]
            else f"가장 큰 이벤트는 DE {biggest['DE']}, IT {biggest['IT']}")
insights = f"""# Prophet 시계열 인사이트 (합성 데이터)

## 1. 예측 정확도 (주간 MAPE, 구간 시작 전 데이터로만 학습)
| 국가 | 검증 구간 | 모델 A (이벤트) | 모델 B (+수요지수) |
|---|---|---|---|
{chr(10).join(bt_lines)}

{reg_note} 단, 이 합성 데이터는 수요지수로 계절성을 만들었기 때문에 모델 B가 유리한 건 당연하다.
실무에서는 검색지수가 매출보다 **먼저** 움직이는지(선행성)를 확인한 뒤 변수로 쓴다. 또 미래 수요지수는 알 수 없으므로 실제 예측에는 모델 A를 쓰고,
Google Trends를 매주 새로 받아 단기(1–2주) 예측만 모델 B로 보정하는 방식이 현실적이다.

## 2. 2026년 9–12월 피크 주간 (모델 A)
{chr(10).join(lines)}

→ **광고 예산을 월별로 균등하게 나누지 말고, 예측 상위 주간에 앞당겨 배정**한다 (주제 1 예산 재배분 시뮬레이션과 연결).

## 3. 이벤트 효과 (2025년 실제 매출, 이벤트 주 ÷ 직전 4주 평균 − 1)
{chr(10).join(eff_lines)}

{cmp[0]}, {cmp[1]}. 실측 Google Trends에서 본 국가별 차이(독일 블프 정점, 이탈리아 크리스마스 정점)와 같은 방향이다.
{big_note}. 다만 아이폰 출시 주의 비교 기준(직전 4주)이 비수기인 8월이라 상승률이 크게 나온다.

**Prophet 이벤트 계수를 쓰지 않은 이유**: 블랙프라이데이 계수가 DE {eff.loc['(참고) Prophet 블프 계수', 'DE']:+.0%}, IT {eff.loc['(참고) Prophet 블프 계수', 'IT']:+.0%}로 음수가 나왔다.
실제 매출은 평소보다 높았으므로, 이 값은 "연말 계절성으로 이미 설명된 뒤 남은 부분"일 뿐 이벤트 효과가 아니다.
학습 데이터가 2년이면 연간 계절성과 연말 이벤트를 분리할 수 없어서 생기는 현상이다. 그래서 예측은 Prophet으로 하고, 효과 크기는 실제 매출로 계산했다.

## 4. 한계
- 학습 데이터가 2년(연간 주기 2회)뿐이라 연간 계절성 추정이 불안정하다. 예측구간(80%)을 함께 보고 판단한다.
- 합성 데이터는 2024년 9월에 고객 0명에서 시작한다. 첫해에는 재구매 고객층이 거의 없어 매출이 낮으므로 **전년 대비 증가율은 과대평가**된다. 추세 예측도 이 영향을 받는다.
- 2026년 아이폰 출시일(9/18)은 가정이다. 실제 발표일로 바꾸면 9월 예측이 달라진다.
- 갤럭시 S·A 출시 이벤트는 이벤트마다 학습 사례가 한 번(2025년)뿐이라 효과 추정이 불안정하다.
  추가 효과가 국가별로 엇갈렸으므로(독일은 봄 구간 개선, 이탈리아는 4분기·봄 구간 악화), 출시 사례가 쌓일 때마다 다시 검증한다.
"""
(ROOT / "outputs" / "insights_prophet.md").write_text(insights, encoding="utf-8")
print(insights)

# %% [6] Tableau Public용 CSV 내보내기 (주간·긴 형식, 영문 열 이름)
reset_catalog("prophet")
rows = []
for c in COUNTRIES:
    hist = to_weekly(daily[daily.country == c].set_index("ds").y)
    fw = to_weekly(forecasts[c].set_index("ds")[["yhat", "yhat_lower", "yhat_upper"]])
    fw = fw[fw.index > hist.index.max()]
    rows.append(pd.DataFrame(dict(week_start=hist.index, country=c, series="actual", revenue_eur=hist.values)))
    rows.append(pd.DataFrame(dict(week_start=fw.index, country=c, series="forecast", revenue_eur=fw.yhat.values,
                                  lower_80=fw.yhat_lower.values, upper_80=fw.yhat_upper.values)))
export_tableau(pd.concat(rows, ignore_index=True), "prophet_weekly",
               "국가별 주간 실적(actual)과 2026.9–12 예측(forecast, 80% 구간)")
export_tableau(pd.concat([pd.DataFrame(dict(week_start=to_weekly(bt["actual"]).index, country=c, window=w,
                                            actual_eur=to_weekly(bt["actual"]).values,
                                            model_a_eur=to_weekly(bt["A"]["pred"]).values,
                                            model_b_eur=to_weekly(bt["B"]["pred"]).values))
                          for c in COUNTRIES for w, bt in backtest[c].items()], ignore_index=True),
               "prophet_backtest_weekly", "검증 구간별 실제 vs 모델 A/B 주간 매출")
export_tableau(pd.DataFrame([dict(country=c, window=w, model=m, mape_pct=backtest[c][w][m]["mape"] * 100)
                             for c in COUNTRIES for w in BACKTESTS for m in ("A", "B")]),
               "prophet_backtest_mape", "국가 × 검증 구간 × 모델별 주간 MAPE(%)")
export_tableau(effects.drop(index="(참고) Prophet 블프 계수").rename_axis("event").reset_index()
               .melt(id_vars="event", var_name="country", value_name="lift")
               .assign(lift_pct=lambda d: d.lift * 100).drop(columns="lift"),
               "prophet_event_effects", "이벤트 주 매출 ÷ 직전 4주 평균 − 1 (%)")
