# %% [markdown]
# # K-Means 고객 클러스터링
# - 데이터: spigen-synthetic-data (합성 데이터) — orders, order_items, products, sessions
# - 목적: 구매·방문 행동으로 고객을 묶어 세그먼트별 마케팅 전략을 정한다
# - scikit-learn이 있으면 그대로 쓰고, 없으면(이 PC는 보안 정책으로 scipy/sklearn DLL 차단) numpy 구현으로 대체한다

# %% [0] 설정
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.ticker import PercentFormatter

sys.path.insert(0, str(Path(__file__).resolve().parent))
from style import (CATEGORICAL, DIVERGING, FIG, HIGHLIGHT, INK, MARKERS, MUTED, export_tableau,  # noqa: E402
                   finish, headline, insight, reset_catalog, setup)

setup()                                                  # 색맹 친화 팔레트·한글 폰트·기본 스타일
ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
SEED = 42
K_RANGE = range(2, 9)          # 비교할 군집 수
K_BUSINESS = range(3, 7)       # 마케팅에서 운영 가능한 세그먼트 수 (너무 적거나 많으면 실행이 어려움)

try:                            # sklearn 사용 가능 여부 확인
    from sklearn.cluster import KMeans
    from sklearn.metrics import silhouette_score
    HAS_SKLEARN = True
except (ImportError, OSError):
    HAS_SKLEARN = False


def kmeans_numpy(X, k, n_init=5, max_iter=100, seed=SEED):
    """k-means++ 초기화 + Lloyd 반복. 여러 번 시작해 관성(inertia)이 가장 작은 결과를 고른다."""
    rng = np.random.default_rng(seed)
    best = None
    for _ in range(n_init):
        centers = [X[rng.integers(len(X))]]                                   # 첫 중심은 무작위
        for _ in range(k - 1):                                               # 나머지는 멀리 있는 점일수록 높은 확률로 선택
            d2 = np.min(((X[:, None, :] - np.array(centers)[None]) ** 2).sum(-1), axis=1)
            centers.append(X[rng.choice(len(X), p=d2 / d2.sum())])
        C = np.array(centers)
        for _ in range(max_iter):
            labels = ((X[:, None, :] - C[None]) ** 2).sum(-1).argmin(1)        # 가장 가까운 중심에 배정
            newC = np.array([X[labels == j].mean(0) if (labels == j).any() else C[j] for j in range(k)])
            if np.allclose(newC, C):
                break
            C = newC
        inertia = ((X - C[labels]) ** 2).sum()
        if best is None or inertia < best[2]:
            best = (labels, C, inertia)
    return best


def silhouette_numpy(X, labels):
    """실루엣 계수: (가장 가까운 다른 군집까지 평균거리 − 자기 군집 평균거리) / 둘 중 큰 값."""
    sq = (X ** 2).sum(1)                                                     # 거리행렬을 메모리 효율적으로 계산
    D = np.sqrt(np.clip(sq[:, None] + sq[None] - 2 * X @ X.T, 0, None))
    ks = np.unique(labels)
    s = np.zeros(len(X))
    for i in range(len(X)):
        own = labels == labels[i]
        a = D[i, own].sum() / max(own.sum() - 1, 1)
        b = min(D[i, labels == j].mean() for j in ks if j != labels[i])
        s[i] = (b - a) / max(a, b)
    return s.mean()


def fit_kmeans(X, k):
    if HAS_SKLEARN:
        m = KMeans(n_clusters=k, n_init=5, random_state=SEED).fit(X)
        return m.labels_, m.cluster_centers_, m.inertia_
    return kmeans_numpy(X, k)


def silhouette(X, labels):
    return silhouette_score(X, labels) if HAS_SKLEARN else silhouette_numpy(X, labels)


# %% [1] 데이터 로드
orders = pd.read_csv(RAW / "orders.csv", parse_dates=["order_ts"], dtype={"ab_variant": "string"})
items = pd.read_csv(RAW / "order_items.csv")
products = pd.read_csv(RAW / "products.csv", usecols=["product_id", "category"])
sessions = pd.read_csv(RAW / "sessions.csv", usecols=["user_id", "session_start_ts"], parse_dates=["session_start_ts"])
print(f"주문 {len(orders):,} / 주문상세 {len(items):,} / 세션 {len(sessions):,} (sklearn 사용: {HAS_SKLEARN})")

# %% [2] 전처리: 고객 단위 피처 만들기
snapshot = orders.order_ts.max().normalize() + pd.Timedelta(days=1)      # 기준일 = 마지막 주문 다음 날

# 2-1. 주문 기반 피처 (반품 주문은 매출에서 제외)
orders["net_kept"] = orders.net_amount_eur.where(~orders.is_returned, 0)
cust = orders.groupby("user_id").agg(
    recency_days=("order_ts", lambda s: (snapshot - s.max()).days),     # 최근 구매 경과일
    frequency=("order_id", "count"),                                    # 구매 횟수
    monetary=("net_kept", "sum"),                                       # 누적 순매출
    aov=("net_amount_eur", "mean"),                                     # 평균 객단가
    discount_share=("promo_code", lambda s: s.notna().mean()),          # 할인코드 사용 주문 비율
    tenure_days=("order_ts", lambda s: (snapshot - s.min()).days),      # 첫 구매 후 경과일
)

# 2-2. 상품 구성 피처: 매출 중 케이스·강화유리 외 액세서리 비중
it = items.merge(products, on="product_id").merge(orders[["order_id", "user_id"]], on="order_id")
it["acc_amount"] = it.line_amount_eur.where(~it.category.isin(["case", "protector"]), 0)
g = it.groupby("user_id")[["acc_amount", "line_amount_eur"]].sum()
cust["accessory_share"] = g.acc_amount / g.line_amount_eur.replace(0, np.nan)

# 2-3. 방문 피처: 최근 90일 세션 수
recent = sessions[sessions.session_start_ts >= snapshot - pd.Timedelta(days=90)]
cust["sessions_90d"] = recent.groupby("user_id").size()
cust = cust.fillna({"sessions_90d": 0, "accessory_share": 0})

# 2-4. 왜도가 큰 변수는 log1p 변환 → 표준화 (K-Means는 거리 기반이라 단위·스케일 영향을 크게 받음)
FEATURES = ["recency_days", "frequency", "monetary", "aov", "discount_share",
            "accessory_share", "sessions_90d", "tenure_days"]
LOG = ["recency_days", "frequency", "monetary", "aov", "sessions_90d", "tenure_days"]
Xdf = cust[FEATURES].copy()
Xdf[LOG] = np.log1p(Xdf[LOG])
X = ((Xdf - Xdf.mean()) / Xdf.std()).to_numpy()
print(cust[FEATURES].describe().T.round(2))

# %% [3] 분석
# 3-1. 군집 수 결정: 관성(엘보) + 실루엣 계수 (실루엣은 계산량이 커서 4,000명 표본으로 계산)
rng = np.random.default_rng(SEED)
sample = rng.choice(len(X), size=min(4000, len(X)), replace=False)
scores = []
for k in K_RANGE:
    labels, _, inertia = fit_kmeans(X, k)
    scores.append(dict(k=k, inertia=inertia, silhouette=silhouette(X[sample], labels[sample])))
    print(f"  k={k}  inertia={inertia:,.0f}  silhouette={scores[-1]['silhouette']:.3f}")
scores = pd.DataFrame(scores)
best_k = int(scores[scores.k.isin(K_BUSINESS)].sort_values("silhouette", ascending=False).k.iloc[0])
print(f"선택한 k = {best_k} (운영 가능 범위 {K_BUSINESS.start}–{K_BUSINESS.stop - 1} 중 실루엣 최대)")

# 3-2. 최종 모델 학습
labels, centers, _ = fit_kmeans(X, best_k)
cust["cluster"] = labels

# 3-3. 군집 프로파일: 원래 단위의 평균 + 규모·매출 비중
profile = cust.groupby("cluster").agg(customers=("frequency", "size"), **{f: (f, "mean") for f in FEATURES})
profile["customer_share"] = profile.customers / profile.customers.sum()
profile["revenue_share"] = cust.groupby("cluster").monetary.sum() / cust.monetary.sum()

# 3-4. 군집 이름 자동 부여: 전체 평균 대비 가장 두드러진 특징 2개 (표준화 중심값 기준)
KOR = {"recency_days": "구매경과일", "frequency": "구매횟수", "monetary": "누적매출", "aov": "객단가",
       "discount_share": "할인의존", "accessory_share": "액세서리비중", "sessions_90d": "최근방문", "tenure_days": "가입기간"}
z_centers = pd.DataFrame(centers, columns=FEATURES)


def describe(row):
    top = row.abs().sort_values(ascending=False).index[:2]
    return " · ".join(f"{KOR[f]}{'↑' if row[f] > 0 else '↓'}" for f in top)


profile["label"] = [describe(z_centers.loc[c]) for c in profile.index]
profile = profile.sort_values("revenue_share", ascending=False)
print(profile.round(2).to_string())

# 3-5. [검증 전용] 합성 데이터의 숨은 정답 세그먼트와 비교 — 실무 데이터에는 없는 단계
truth = pd.read_csv(ROOT / "data" / "truth" / "truth_users.csv", usecols=["user_id", "latent_segment"])
ct = pd.crosstab(cust.cluster, cust.join(truth.set_index("user_id")).latent_segment)
purity = ct.max(axis=1).sum() / ct.values.sum()
print(ct, f"\n군집 순도(purity) = {purity:.1%}")

# %% [4] 시각화 — 제목은 결론 한 문장, 차트 안에 인사이트를 직접 표시
# 4-0. 군집 역할 이름: 매출 비중 1위 = 핵심, 구매경과일 최대 = 휴면, 남은 것 중 가입기간 최소 = 신규
roles = {int(profile.index[0]): "핵심 고객"}
rest = profile.drop(index=list(roles))
if len(rest):
    roles[int(rest.recency_days.idxmax())] = "휴면·이탈 위험"
    rest = rest.drop(index=list(roles), errors="ignore")
if len(rest):
    roles[int(rest.tenure_days.idxmin())] = "신규 고객"
for c in profile.index:
    roles.setdefault(int(c), "일반 고객")
profile["role"] = [roles[int(c)] for c in profile.index]
name = {c: f"C{c} {roles[int(c)]}" for c in profile.index}
color = {c: CATEGORICAL[int(c) % len(CATEGORICAL)] for c in profile.index}     # 색은 군집 번호에 고정
marker = {c: MARKERS[int(c) % len(MARKERS)] for c in profile.index}
core = profile.iloc[0]

fig, ax = plt.subplots(1, 3, figsize=(18, 5.6), gridspec_kw={"width_ratios": [1, 1.05, 1.15]})
headline(fig,
         f"고객 {core.customer_share:.0%}인 '{roles[int(core.name)]}' 군집이 매출의 {core.revenue_share:.0%}를 만든다",
         f"고객 {len(cust):,}명 · 피처 {len(FEATURES)}개(구매·방문·상품 구성) · K-Means k={best_k} · "
         f"기준일 {snapshot:%Y-%m-%d} · 합성 데이터")

# 4-1. 고객 비중 vs 매출 비중 (군집마다 두 막대: 연한 빗금 = 고객 비중, 진한 = 매출 비중)
order = list(profile.index)[::-1]
y = np.arange(len(order))
for yi, c in zip(y, order):
    r = profile.loc[c]
    ax[0].barh(yi + 0.19, r.customer_share * 100, height=0.36, color="white", edgecolor=color[c], hatch="///", lw=1.2)
    ax[0].barh(yi - 0.19, r.revenue_share * 100, height=0.36, color=color[c])
    ax[0].text(r.customer_share * 100 + 1, yi + 0.19, f"고객 {r.customer_share:.0%}", va="center", fontsize=9, color=MUTED)
    ax[0].text(r.revenue_share * 100 + 1, yi - 0.19, f"매출 {r.revenue_share:.0%}", va="center", fontsize=9,
               color=INK, fontweight="bold")
ax[0].set_yticks(y, [f"{name[c]}\n({profile.loc[c, 'label']})" for c in order], fontsize=9)
ax[0].set_xlim(0, max(profile.customer_share.max(), profile.revenue_share.max()) * 100 * 1.3)
ax[0].xaxis.set_major_formatter(PercentFormatter(decimals=0))
ax[0].set_xlabel("전체 대비 비중 (%)")
ax[0].set_title("군집별 고객 비중 vs 매출 비중")
ax[0].grid(axis="y", visible=False)
insight(ax[0], f"1인당 누적매출: {name[core.name]} €{core.monetary:,.0f}\n"
               f"→ 나머지 평균 €{cust[cust.cluster != core.name].monetary.mean():,.0f}의 "
               f"{core.monetary / cust[cust.cluster != core.name].monetary.mean():.1f}배",
        xy=(0.98, 0.03), ha="right", va="bottom")

# 4-2. PCA 2차원 산점도 (5,000명 표본). 색 + 마커 모양으로 이중 구분, 군집 중심에 이름 직접 표시
idx = rng.choice(len(X), size=min(5000, len(X)), replace=False)
mu = X.mean(0)
U, S, Vt = np.linalg.svd(X - mu, full_matrices=False)
pc_all = (X - mu) @ Vt[:2].T
for c in sorted(profile.index):
    m = labels[idx] == c
    ax[1].scatter(pc_all[idx][m, 0], pc_all[idx][m, 1], s=7, alpha=0.35, color=color[c], marker=marker[c],
                  linewidths=0)
    cx, cy = pc_all[labels == c].mean(0)
    ax[1].annotate(name[c], (cx, cy), ha="center", va="center", fontsize=10, fontweight="bold", color=INK,
                   bbox=dict(boxstyle="round,pad=0.3", fc="white", ec=color[c], lw=1.5))
ev = S[:2] ** 2 / (S ** 2).sum()
loading = pd.Series(Vt[0], index=FEATURES)
top_load = loading.abs().nlargest(2).index
ax[1].set_xlabel(f"주성분 1 (분산의 {ev[0]:.0%}) — 주로 {', '.join(KOR[f] for f in top_load)}")
ax[1].set_ylabel(f"주성분 2 (분산의 {ev[1]:.0%})")
ax[1].set_title(f"고객 분포 (PCA 2차원, 표본 {len(idx):,}명)")
sil = scores.set_index("k").silhouette[best_k]
insight(ax[1], f"실루엣 {sil:.2f}: 군집 경계가 겹치는 고객이 있다\n→ 경계 고객은 두 전략을 모두 테스트",
        xy=(0.02, 0.03), va="bottom")

# 4-3. 군집 중심 히트맵: 발산형 보라↔주황(색맹 안전), 칸마다 값 표시
hm = z_centers.loc[profile.index, FEATURES]
im = ax[2].imshow(hm.values, cmap=DIVERGING, vmin=-2, vmax=2, aspect="auto")
ax[2].set_xticks(range(len(FEATURES)), [KOR[f] for f in FEATURES], rotation=35, ha="right")
ax[2].set_yticks(range(len(hm)), [name[c] for c in hm.index])
for i in range(hm.shape[0]):
    for j in range(hm.shape[1]):
        v = hm.values[i, j]
        ax[2].text(j, i, f"{v:+.1f}", ha="center", va="center", fontsize=9,
                   color="white" if abs(v) > 1.2 else INK, fontweight="bold" if abs(v) > 1 else "normal")
ax[2].grid(False)
cb = fig.colorbar(im, ax=ax[2], fraction=0.035, pad=0.02)
cb.set_label("전체 평균 대비 (표준편차 단위)")
ax[2].set_title("군집별 특징: 전체 평균과의 차이")
finish(fig, FIG / "kmeans_clusters.png")

# 4-4. 군집 수 선택 근거 (별도 그림): 관성과 실루엣을 나란히 (이중 축 대신 두 패널)
fig2, ax2 = plt.subplots(1, 2, figsize=(11, 3.8))
headline(fig2, f"k={best_k} 선택: 운영 가능한 {K_BUSINESS.start}–{K_BUSINESS.stop - 1}개 중 실루엣이 가장 높다",
         "관성(inertia)은 k가 늘면 항상 줄어든다 → 꺾이는 지점(엘보)과 실루엣 계수를 함께 본다")
ax2[0].plot(scores.k, scores.inertia, marker="o", color=CATEGORICAL[0])
ax2[0].set_title("관성 (작을수록 군집 내부가 촘촘)")
ax2[0].set_xlabel("군집 수 k")
ax2[0].set_ylabel("관성 (군집 내 거리 제곱합)")
ax2[1].plot(scores.k, scores.silhouette, marker="s", color=CATEGORICAL[1])
ax2[1].axvspan(K_BUSINESS.start - 0.5, K_BUSINESS.stop - 0.5, color=CATEGORICAL[4], alpha=0.12, label="운영 가능 범위")
ax2[1].plot(best_k, sil, marker="*", ms=16, color=HIGHLIGHT, label=f"선택 k={best_k}")
ax2[1].set_title("실루엣 계수 (클수록 군집이 잘 분리)")
ax2[1].set_xlabel("군집 수 k")
ax2[1].set_ylabel("실루엣 계수")
ax2[1].legend(loc="lower left")
k2 = scores.iloc[0]
ax2[1].annotate(f"k={int(k2.k)} 최고({k2.silhouette:.2f})지만\n2개로는 전략을 나누기 어려움", (k2.k, k2.silhouette),
                xytext=(4.0, scores.silhouette.max() - 0.012), textcoords="data", fontsize=9, color=INK,
                arrowprops=dict(arrowstyle="->", color=MUTED))
for a in ax2:
    a.set_xticks(list(K_RANGE))
finish(fig2, FIG / "kmeans_k_selection.png")
print(f"그래프 저장: {FIG / 'kmeans_clusters.png'}, {FIG / 'kmeans_k_selection.png'}")

# %% [5] 인사이트 도출 (수치는 모두 위 결과에서 자동으로 채움)
top = profile.iloc[0]                                           # 매출 비중 1위 군집
risk = profile.sort_values("recency_days", ascending=False).iloc[0]   # 가장 오래 구매 안 한 군집
disc = profile.drop(index=[top.name, risk.name], errors="ignore")      # 앞에서 다룬 군집을 뺀 나머지 중
disc = disc.sort_values("discount_share", ascending=False).iloc[0] if len(disc) else risk  # 할인 의존 최대 군집
lines = [f"| C{c} | {r.label} | {r.customer_share:.1%} | {r.revenue_share:.1%} | {r.frequency:.1f} | "
         f"€{r.monetary:,.0f} | {r.recency_days:.0f}일 | {r.discount_share:.0%} | {r.sessions_90d:.1f} |"
         for c, r in profile.iterrows()]
insights = f"""# K-Means 고객 클러스터링 인사이트 (합성 데이터)

- 고객 {len(cust):,}명, 피처 {len(FEATURES)}개, k={best_k} (실루엣 {scores.set_index('k').silhouette[best_k]:.3f})

| 군집 | 특징 | 고객 비중 | 매출 비중 | 평균 구매횟수 | 평균 누적매출 | 평균 구매경과일 | 할인 사용률 | 최근 90일 방문 |
|---|---|---|---|---|---|---|---|---|
{chr(10).join(lines)}

1. **핵심 고객 군집 C{top.name}**: 고객 {top.customer_share:.1%}가 매출 {top.revenue_share:.1%}를 만든다(1인당 €{top.monetary:,.0f}).
   → 신모델 출시 사전 알림, 액세서리 번들 등 **할인보다 신제품 접근성** 중심으로 관리한다.
2. **이탈 위험 군집 C{risk.name}**: 평균 {risk.recency_days:.0f}일째 구매가 없고, 최근 90일 방문은 {risk.sessions_90d:.1f}회다.
   → 재활성화 캠페인은 비용 대비 효과를 먼저 소규모로 테스트한다 (전원 발송 금지).
3. **신규·할인 반응 군집 C{disc.name}**: 평균 가입 {disc.tenure_days:.0f}일, 구매 {disc.frequency:.1f}회, 주문의 {disc.discount_share:.0%}에 할인코드 사용.
   → 두 번째 구매 전환이 관건이다. 상시 쿠폰 대신 블랙프라이데이·크리스마스 같은 수요 피크에 할인을 집중해 마진을 지킨다.
4. **군집 수 선택**: 실루엣은 k=2가 가장 높지만({scores.silhouette.iloc[0]:.3f}) 두 그룹으로는 운영 전략을 나누기 어려워 {K_BUSINESS.start}–{K_BUSINESS.stop - 1} 중에서 골랐다.
   k=3은 1회 구매자와 일반 고객이 한 군집(C{risk.name})으로 묶인다. 더 세분화하려면 k=5–6과 비교해 본다.
5. **검증**: 숨은 정답 세그먼트 기준 군집 순도 {purity:.1%}. 구매 행동만으로 숨은 고객 유형을 어느 정도 복원했다는 뜻이지만,
   이 값은 합성 데이터라서 계산할 수 있는 지표이고 실무 성과로 쓰면 안 된다.
"""
(ROOT / "outputs" / "insights_kmeans.md").write_text(insights, encoding="utf-8")
print(insights)

# %% [6] Tableau Public용 CSV 내보내기 (개인정보 없이 user_id만 포함)
reset_catalog("kmeans")
export_tableau(cust.reset_index()[["user_id", "cluster", *FEATURES]]
               .assign(cluster_role=lambda d: d.cluster.map(roles), pc1=pc_all[:, 0], pc2=pc_all[:, 1]),
               "kmeans_customers", "고객 1명 = 1행: 군집, 역할, 피처 원값, PCA 좌표(산점도용)")
export_tableau(profile.reset_index().rename(columns={"label": "top_features"})
               .assign(customer_share_pct=lambda d: d.customer_share * 100,
                       revenue_share_pct=lambda d: d.revenue_share * 100)
               .drop(columns=["customer_share", "revenue_share"]),
               "kmeans_cluster_profile", "군집별 고객 수·비중·매출 비중·피처 평균")
export_tableau(z_centers.rename_axis("cluster").reset_index()
               .melt(id_vars="cluster", var_name="feature", value_name="z_value")
               .assign(feature_ko=lambda d: d.feature.map(KOR), cluster_role=lambda d: d.cluster.map(roles)),
               "kmeans_cluster_centers_long", "군집 × 피처 표준화 중심값 (긴 형식, 히트맵용)")
export_tableau(scores, "kmeans_k_selection", "k별 관성·실루엣 (군집 수 선택 근거)")
