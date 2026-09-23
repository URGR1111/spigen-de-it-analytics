# %% [markdown]
# # A/B 테스트 분석: 장바구니 번들 업셀
# - 데이터: spigen-synthetic-data (합성 데이터) — ab_assignments.csv, orders.csv
# - 가설: 장바구니에서 "케이스+강화유리 15% 번들"을 제안하면 사용자당 매출(RPU)이 오른다
# - 주요 지표 RPU / 보조 지표 구매전환율(CVR)·객단가(AOV) / 가드레일 반품률
# - 통계 검정은 scipy 없이 정규근사 + 부트스트랩으로 계산한다 (이 PC는 보안 정책으로 scipy DLL이 차단됨)

# %% [0] 설정
import math
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.ticker import FuncFormatter, PercentFormatter

sys.path.insert(0, str(Path(__file__).resolve().parent))
from style import (FIG, HIGHLIGHT, INK, MUTED, OI, VARIANT, export_tableau, finish, headline, insight,  # noqa: E402
                   reset_catalog, setup)

setup()                                                  # 색맹 친화 팔레트·한글 폰트·기본 스타일
ROOT = Path(__file__).resolve().parents[1]              # 프로젝트 루트
RAW = ROOT / "data" / "raw"                              # 생성된 CSV 위치
RNG = np.random.default_rng(42)                          # 부트스트랩 재현성
ALPHA = 0.05                                             # 유의수준


def p_two_sided(z: float) -> float:
    """표준정규분포 양측 p-value."""
    return math.erfc(abs(z) / math.sqrt(2))


# %% [1] 데이터 로드
assign = pd.read_csv(RAW / "ab_assignments.csv", parse_dates=["first_exposure_ts"])   # 실험 노출·배정
orders = pd.read_csv(RAW / "orders.csv", parse_dates=["order_ts"], dtype={"ab_variant": "string"})  # 전체 주문
print(f"배정 {len(assign):,}명 / 주문 {len(orders):,}건")
print(assign.head(3))

# %% [2] 전처리
# 2-1. 한 사용자가 두 그룹에 중복 배정되지 않았는지 확인
assert assign.user_id.is_unique, "중복 배정된 사용자가 있습니다"

# 2-2. 실험 기간 중 노출 이후 발생한 주문만 사용 (ab_variant가 기록된 주문)
exp_orders = orders[orders.ab_variant.notna()].copy()

# 2-3. 오염 점검: 주문에 찍힌 그룹과 배정 그룹이 다르면 실험 설계 오류
chk = exp_orders.merge(assign[["user_id", "variant"]], on="user_id", how="left")
contaminated = int((chk.ab_variant != chk.variant).sum())
print(f"그룹 불일치 주문: {contaminated}건")

# 2-4. 노출 후 경과일 계산 (신기효과 분석용)
exp_orders = exp_orders.merge(assign[["user_id", "first_exposure_ts"]], on="user_id")
exp_orders["days_since_exposure"] = (exp_orders.order_ts - exp_orders.first_exposure_ts).dt.days

# 2-5. 사용자 단위로 집계: 노출됐지만 구매하지 않은 사용자도 0으로 포함해야 RPU가 왜곡되지 않는다
per_user = (exp_orders.groupby("user_id")
            .agg(orders=("order_id", "count"), revenue=("net_amount_eur", "sum"),
                 bundle_orders=("has_bundle_upsell", "sum"), returned=("is_returned", "sum"))
            .reset_index())
user = assign.merge(per_user, on="user_id", how="left").fillna({"orders": 0, "revenue": 0.0,
                                                                "bundle_orders": 0, "returned": 0})
user["converted"] = (user.orders > 0).astype(int)
C, T = user[user.variant == "control"], user[user.variant == "treatment"]
oC, oT = exp_orders[exp_orders.ab_variant == "control"], exp_orders[exp_orders.ab_variant == "treatment"]

# %% [3] 분석
results = {}

# 3-1. SRM(Sample Ratio Mismatch): 50:50 배정이 실제로 지켜졌는지 카이제곱 검정
n_c, n_t = len(C), len(T)
exp_n = (n_c + n_t) / 2
chi2 = (n_c - exp_n) ** 2 / exp_n + (n_t - exp_n) ** 2 / exp_n
results["SRM"] = dict(control=n_c, treatment=n_t, p_value=math.erfc(math.sqrt(chi2 / 2)))

# 3-2. 구매전환율(CVR): 두 비율 z-검정
p1, p2 = C.converted.mean(), T.converted.mean()
pp = (C.converted.sum() + T.converted.sum()) / (n_c + n_t)
z = (p2 - p1) / math.sqrt(pp * (1 - pp) * (1 / n_c + 1 / n_t))
se = math.sqrt(p1 * (1 - p1) / n_c + p2 * (1 - p2) / n_t)
results["CVR"] = dict(control=p1, treatment=p2, lift=(p2 - p1) / p1,
                      ci=((p2 - p1 - 1.96 * se) / p1, (p2 - p1 + 1.96 * se) / p1), p_value=p_two_sided(z))


# 3-3. 평균 비교(Welch) 함수: 표본이 커서 t분포 ≈ 정규분포로 근사
def welch(a: pd.Series, b: pd.Series) -> dict:
    d = b.mean() - a.mean()
    se = math.sqrt(a.var(ddof=1) / len(a) + b.var(ddof=1) / len(b))
    return dict(control=a.mean(), treatment=b.mean(), lift=d / a.mean(),
                ci=((d - 1.96 * se) / a.mean(), (d + 1.96 * se) / a.mean()),
                p_value=p_two_sided(d / se), mde=2.8 * se / a.mean())  # mde: 검정력 80%로 잡을 수 있는 최소 효과


results["RPU"] = welch(C.revenue, T.revenue)          # 주요 지표: 사용자당 매출
results["AOV"] = welch(oC.net_amount_eur, oT.net_amount_eur)  # 보조 지표: 객단가

# 3-4. RPU 상대 상승률의 부트스트랩 95% 신뢰구간 (매출은 한쪽으로 치우친 분포라 정규근사를 교차 검증)
rc, rt = C.revenue.to_numpy(), T.revenue.to_numpy()
boot = np.array([RNG.choice(rt, len(rt)).mean() / RNG.choice(rc, len(rc)).mean() - 1 for _ in range(3000)])
results["RPU"]["boot_ci"] = tuple(np.percentile(boot, [2.5, 97.5]))

# 3-5. 가드레일: 주문 반품률이 나빠지지 않았는지 (두 비율 z-검정)
r1, r2 = oC.is_returned.mean(), oT.is_returned.mean()
rp = (oC.is_returned.sum() + oT.is_returned.sum()) / (len(oC) + len(oT))
zr = (r2 - r1) / math.sqrt(rp * (1 - rp) * (1 / len(oC) + 1 / len(oT)))
ser = math.sqrt(r1 * (1 - r1) / len(oC) + r2 * (1 - r2) / len(oT))
results["Return"] = dict(control=r1, treatment=r2, lift=(r2 - r1) / r1,
                         ci=((r2 - r1 - 1.96 * ser) / r1, (r2 - r1 + 1.96 * ser) / r1), p_value=p_two_sided(zr))

# 3-6. 신기효과: 처치군 번들 수락률을 노출 후 경과일 구간별로 비교
bins = [-1, 2, 6, 13, 27, 999]
labels = ["0–2일", "3–6일", "7–13일", "14–27일", "28일+"]
oT = oT.assign(period=pd.cut(oT.days_since_exposure, bins=bins, labels=labels))
novelty = oT.groupby("period", observed=True).agg(orders=("order_id", "count"),
                                                  bundle_rate=("has_bundle_upsell", "mean"))

# 3-7. 국가별 효과 (이질성 확인)
by_country = user.groupby(["country", "variant"]).agg(users=("user_id", "count"), rpu=("revenue", "mean"),
                                                      cvr=("converted", "mean")).unstack("variant")
by_country["rpu_lift"] = by_country[("rpu", "treatment")] / by_country[("rpu", "control")] - 1

summary = pd.DataFrame({k: {m: v[m] for m in ("control", "treatment", "lift", "p_value") if m in v}
                        for k, v in results.items()}).T
print(summary.round(4))
print(novelty.round(3))
print(by_country.round(3))

# %% [4] 시각화 — 제목은 결론 한 문장, 차트 안에 인사이트를 직접 표시
fmt_p = lambda p: "p<0.001" if p < 0.001 else f"p={p:.3f}"
R = results
fig, ax = plt.subplots(1, 3, figsize=(17, 5.2), gridspec_kw={"width_ratios": [1.15, 1, 1]})
cvr_part = ("구매자 수는 그대로, 객단가가 올랐다" if R["CVR"]["p_value"] >= ALPHA
            else f"구매전환율 {R['CVR']['lift']:+.0%}, 객단가 {R['AOV']['lift']:+.0%}")
headline(fig,
         f"번들 제안으로 사용자당 매출 {R['RPU']['lift']:+.0%}: {cvr_part}",
         f"{assign.exp_id.iloc[0]} · 노출 {assign.first_exposure_ts.min():%Y.%m.%d}–{assign.first_exposure_ts.max():%m.%d} · "
         f"노출 사용자 {n_c + n_t:,}명 (대조 {n_c:,} / 처치 {n_t:,}) · 합성 데이터")

# 4-1. 지표별 상승률과 95% 신뢰구간: 유의한 지표는 파랑 채운 원, 유의하지 않은 지표는 회색 빈 원
metrics = [("RPU", "사용자당 매출 (주요)"), ("AOV", "객단가"), ("CVR", "구매전환율"), ("Return", "반품률 (가드레일)")]
for y, (k, label) in enumerate(metrics[::-1]):
    r = R[k]
    sig_k = r["p_value"] < ALPHA
    col = OI["blue"] if sig_k else "#999999"
    lo, hi = r["ci"]
    ax[0].plot([lo * 100, hi * 100], [y, y], color=col, lw=2.2, solid_capstyle="round")
    ax[0].plot(r["lift"] * 100, y, "o", ms=9, color=col, mfc=col if sig_k else "white", mew=2)
    ax[0].annotate(f"{r['lift']:+.1%}  ({fmt_p(r['p_value'])})", (hi * 100, y), xytext=(8, 0),
                   textcoords="offset points", va="center", fontsize=9, color=INK if sig_k else MUTED)
ax[0].axvline(0, color=INK, lw=1)
ax[0].set_yticks(range(len(metrics)), [m[1] for m in metrics[::-1]])
ax[0].set_xlabel("대조군 대비 처치군 상승률 (%, 95% 신뢰구간)")
ax[0].set_title("지표별 효과: 채운 원 = 유의함 (α=0.05)")
ax[0].xaxis.set_major_formatter(PercentFormatter(decimals=0))
ax[0].set_xlim(min(R[k]["ci"][0] for k, _ in metrics) * 100 - 5, max(R[k]["ci"][1] for k, _ in metrics) * 100 + 28)
ax[0].grid(axis="y", visible=False)

# 4-2. RPU 상승률 부트스트랩 분포: 0%(효과 없음)가 신뢰구간 밖이면 효과가 있다는 뜻
lo, hi = R["RPU"]["boot_ci"]
ax[1].hist(boot * 100, bins=50, color=OI["sky"], edgecolor="white", linewidth=0.3)
ax[1].axvspan(lo * 100, hi * 100, color=OI["blue"], alpha=0.10, label="95% 신뢰구간")
ax[1].axvline(0, color=HIGHLIGHT, lw=1.8, ls="--", label="효과 없음 (0%)")
ax[1].axvline(R["RPU"]["lift"] * 100, color=OI["blue"], lw=1.8, label=f"관측 상승률 {R['RPU']['lift']:+.1%}")
ax[1].set_xlabel("사용자당 매출(RPU) 상승률 (%)")
ax[1].set_ylabel("부트스트랩 반복 횟수")
ax[1].set_title("RPU 상승률 부트스트랩 분포 (3,000회 재표본)")
ax[1].xaxis.set_major_formatter(PercentFormatter(decimals=0))
ax[1].set_ylim(0, ax[1].get_ylim()[1] * 1.45)                      # 위쪽 여백: 인사이트 박스·범례가 막대를 가리지 않게
ax[1].legend(loc="upper right")
insight(ax[1], f"95% CI {lo:+.1%} ~ {hi:+.1%}\n"
               + ("0%가 구간 밖 → 우연으로 보기 어렵다" if lo > 0 or hi < 0 else "0% 포함 → 효과 불확실"))

# 4-3. 경과일별 번들 수락률: 막대 = 주문 수(신뢰도), 선 = 수락률
x = np.arange(len(novelty))
ax2b = ax[2].twinx()
ax2b.bar(x, novelty.orders, color="#dddddd", width=0.55, zorder=0)
ax2b.set_ylabel("처치군 주문 수 (건)", color=MUTED)
ax2b.grid(False)
ax2b.spines["right"].set_visible(True)
ax[2].set_zorder(ax2b.get_zorder() + 1)
ax[2].patch.set_visible(False)
ax[2].plot(x, novelty.bundle_rate * 100, marker="o", ms=7, color=OI["orange"], lw=2.2)
for xi, v in zip(x, novelty.bundle_rate * 100):
    ax[2].annotate(f"{v:.0f}%", (xi, v), xytext=(0, 9), textcoords="offset points", ha="center",
                   fontsize=9, fontweight="bold", color=INK)
ax[2].set_xticks(x, novelty.index.astype(str))
ax[2].set_xlabel("첫 노출 후 경과일")
ax[2].set_ylabel("번들 수락률 (%)", color=OI["orange"])
ax[2].set_ylim(0, novelty.bundle_rate.max() * 100 * 1.45)
ax[2].yaxis.set_major_formatter(PercentFormatter(decimals=0))
ax[2].set_title("처치군 번들 수락률: 노출 직후가 가장 높다")
wavg = lambda d: (d.bundle_rate * d.orders).sum() / d.orders.sum()      # 주문 수 가중평균 (구간별 표본 크기 차이 반영)
early, late = wavg(novelty.iloc[:2]), wavg(novelty.iloc[2:])
insight(ax[2], f"첫 7일 {early:.0%} → 7일 이후 {late:.0%} (주문 수 가중)\n신기효과: 장기 효과는 실험값보다 작을 수 있다",
        xy=(0.98, 0.97), ha="right")
finish(fig, FIG / "ab_test.png")
print(f"그래프 저장: {FIG / 'ab_test.png'}")

# %% [5] 인사이트 도출 (수치는 모두 위 분석 결과에서 자동으로 채움)
R = results
sig = lambda p: "유의함" if p < ALPHA else "유의하지 않음"
rpu_win = R["RPU"]["p_value"] < ALPHA and R["RPU"]["lift"] > 0
guard_ok = not (R["Return"]["p_value"] < ALPHA and R["Return"]["lift"] > 0)
first, last = novelty.bundle_rate.iloc[0], novelty.bundle_rate.iloc[-1]
decision = ("출시 권장" if rpu_win and guard_ok and R["SRM"]["p_value"] >= 0.01 and contaminated == 0
            else "추가 검증 필요")
lifts = by_country["rpu_lift"]
country_note = (f"두 시장 모두 상승했지만 {lifts.idxmin()}는 {lifts.idxmax()}의 절반 이하라 국가별 표본으로 유의성을 다시 확인해야 한다"
                if (lifts > 0).all() and lifts.min() < lifts.max() / 2
                else "두 시장 모두 비슷하게 상승해 전체 출시가 가능하다" if (lifts > 0).all()
                else "시장별 방향이 달라 효과가 있는 국가만 출시하는 것을 검토한다")

insights = f"""# A/B 테스트 인사이트: 장바구니 번들 업셀 (합성 데이터)

**결론: {decision}**

1. **데이터 신뢰성**: 배정 {R['SRM']['control']:,} : {R['SRM']['treatment']:,} (SRM p={R['SRM']['p_value']:.3f}), 그룹 불일치 주문 {contaminated}건 → 배정 {'정상' if R['SRM']['p_value'] >= 0.01 else '이상, 원인 확인 필요'}.
2. **주요 지표 RPU**: €{R['RPU']['control']:.2f} → €{R['RPU']['treatment']:.2f} ({R['RPU']['lift']:+.1%}, p={R['RPU']['p_value']:.4f}, {sig(R['RPU']['p_value'])}).
   부트스트랩 95% CI {R['RPU']['boot_ci'][0]:+.1%} ~ {R['RPU']['boot_ci'][1]:+.1%}. 이 표본으로 잡을 수 있는 최소 효과(MDE)는 약 {R['RPU']['mde']:.1%}.
3. **상승 원인은 객단가**: AOV {R['AOV']['lift']:+.1%} (p={R['AOV']['p_value']:.4f}), 구매전환율은 {R['CVR']['lift']:+.1%} (p={R['CVR']['p_value']:.3f}, {sig(R['CVR']['p_value'])}).
   번들 제안이 구매를 늘리기보다, 사는 사람의 장바구니를 키웠다.
4. **신기효과 주의**: 번들 수락률이 노출 직후 {first:.0%} → {novelty.index[-1]} {last:.0%}로 떨어진다. 실험 기간 평균 효과는 장기 효과보다 과대평가됐을 수 있으므로, 출시 후 4주 이상 효과를 추적해야 한다.
5. **가드레일 반품률**: {R['Return']['control']:.1%} → {R['Return']['treatment']:.1%} (p={R['Return']['p_value']:.3f}, {sig(R['Return']['p_value'])}). 방향은 나빠졌으므로 출시 후에도 모니터링한다.
6. **국가별**: {', '.join(f"{c} RPU {v:+.1%}" for c, v in lifts.items())}. {country_note}.
"""
(ROOT / "outputs" / "insights_ab_test.md").write_text(insights, encoding="utf-8")
print(insights)

# %% [6] Tableau Public용 CSV 내보내기 (outputs/tableau/, 영문 열 이름·ISO 날짜·긴 형식)
reset_catalog("ab")
export_tableau(pd.DataFrame([dict(metric=k, control=v["control"], treatment=v["treatment"],
                                  lift_pct=v.get("lift", np.nan) * 100 if v.get("lift") is not None else np.nan,
                                  ci_low_pct=v["ci"][0] * 100 if "ci" in v else np.nan,
                                  ci_high_pct=v["ci"][1] * 100 if "ci" in v else np.nan,
                                  p_value=v["p_value"], significant=v["p_value"] < ALPHA)
                             for k, v in results.items()]),
               "ab_summary", "지표별 대조군·처치군 값, 상승률(%), 95% CI, p-value")
export_tableau(user[["user_id", "variant", "country", "first_exposure_ts", "orders", "converted",
                     "revenue", "bundle_orders", "returned"]].rename(columns={"revenue": "revenue_eur"}),
               "ab_user_level", "노출 사용자 1명 = 1행. 대시보드에서 필터·재집계용")
export_tableau(pd.DataFrame({"iteration": np.arange(1, len(boot) + 1), "rpu_lift_pct": boot * 100}),
               "ab_bootstrap", "RPU 상승률 부트스트랩 3,000회 (히스토그램용)")
export_tableau(novelty.reset_index().rename(columns={"period": "days_since_exposure"})
               .assign(bundle_rate_pct=lambda d: d.bundle_rate * 100).drop(columns="bundle_rate"),
               "ab_novelty", "처치군 경과일 구간별 주문 수·번들 수락률(%)")
export_tableau(user.groupby(["country", "variant"]).agg(users=("user_id", "count"), rpu_eur=("revenue", "mean"),
                                                         cvr=("converted", "mean")).reset_index(),
               "ab_by_country", "국가 × 그룹별 사용자 수·RPU·전환율 (긴 형식)")
