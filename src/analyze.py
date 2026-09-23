"""
SQL 실행 → 통계 검정 → 예산 시뮬레이션 → 결과 요약(outputs/summary.md).

SQL 파일 규칙: "-- @name: x" 블록은 조회 결과를 outputs/<파일>__<x>.csv로 저장하고,
"-- @ddl: x" 블록은 뷰 생성 등 실행만 한다.
"""
from __future__ import annotations

import json
import math
import re
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
BLOCK = re.compile(r"^-- @(name|ddl):\s*(\S+)\s*$", re.M)


# ---------------------------------------------------------------------------
# SQL 실행
# ---------------------------------------------------------------------------
def run_sql_files(con: sqlite3.Connection, sql_dir: Path, out_dir: Path) -> dict[str, pd.DataFrame]:
    results = {}
    for f in sorted(sql_dir.glob("*.sql")):
        text = f.read_text(encoding="utf-8")
        marks = list(BLOCK.finditer(text))
        for i, m in enumerate(marks):
            body = text[m.end(): marks[i + 1].start() if i + 1 < len(marks) else len(text)].strip()
            kind, name = m.group(1), m.group(2)
            if kind == "ddl":
                con.executescript(body)
                continue
            df = pd.read_sql_query(body.rstrip(";"), con)
            key = f"{f.stem}__{name}"
            df.to_csv(out_dir / f"{key}.csv", index=False)
            results[key] = df
            print(f"  {key:<52} {len(df):>6} rows")
    return results


# ---------------------------------------------------------------------------
# 통계 (scipy 없이 정규근사)
# ---------------------------------------------------------------------------
def p_two_sided(z: float) -> float:
    return math.erfc(abs(z) / math.sqrt(2))


def two_proportion_test(c1, n1, c2, n2) -> dict:
    p1, p2 = c1 / n1, c2 / n2
    pp = (c1 + c2) / (n1 + n2)
    z = (p2 - p1) / math.sqrt(pp * (1 - pp) * (1 / n1 + 1 / n2))
    se = math.sqrt(p1 * (1 - p1) / n1 + p2 * (1 - p2) / n2)
    d = p2 - p1
    return dict(control=p1, treatment=p2, abs_diff=d, rel_lift=d / p1 if p1 else float("nan"), ci_low=d - 1.96 * se,
                ci_high=d + 1.96 * se, z=z, p_value=p_two_sided(z))


def welch_test(m1, v1, n1, m2, v2, n2) -> dict:
    se = math.sqrt(v1 / n1 + v2 / n2)
    d = m2 - m1
    z = d / se
    return dict(control=m1, treatment=m2, abs_diff=d, rel_lift=d / m1, ci_low=d - 1.96 * se,
                ci_high=d + 1.96 * se, z=z, p_value=p_two_sided(z), mde_80pct_power=2.8 * se)


def srm_test(n_c, n_t, expected_t=0.5) -> dict:
    n = n_c + n_t
    e_c, e_t = n * (1 - expected_t), n * expected_t
    chi2 = (n_c - e_c) ** 2 / e_c + (n_t - e_t) ** 2 / e_t
    return dict(control=n_c, treatment=n_t, chi2=chi2, p_value=math.erfc(math.sqrt(chi2 / 2)))


def ab_analysis(res: dict) -> pd.DataFrame:
    srm = res["04_ab_test__srm_check"].set_index("variant")["users"]
    u = res["04_ab_test__ab_user_summary"].set_index("variant")
    o = res["04_ab_test__ab_order_summary"].set_index("variant")
    c, t = "control", "treatment"
    rows = {
        "SRM (배정 비율)": srm_test(srm[c], srm[t]),
        "구매전환율 (CVR)": two_proportion_test(u.converters[c], u.users[c], u.converters[t], u.users[t]),
        "사용자당 매출 (RPU, 주요 지표)": welch_test(u.rpu_eur[c], u.rpu_var[c], u.users[c],
                                          u.rpu_eur[t], u.rpu_var[t], u.users[t]),
        "객단가 (AOV)": welch_test(o.aov_eur[c], o.aov_var[c], o.orders[c], o.aov_eur[t], o.aov_var[t], o.orders[t]),
        "번들 수락률": two_proportion_test(round(u.bundle_attach_rate[c] * u.orders[c]), u.orders[c],
                                      round(u.bundle_attach_rate[t] * u.orders[t]), u.orders[t]),
        "반품률 (가드레일)": two_proportion_test(round(u.return_rate[c] * u.orders[c]), u.orders[c],
                                         round(u.return_rate[t] * u.orders[t]), u.orders[t]),
    }
    df = pd.DataFrame(rows).T
    df.index.name = "metric"
    return df


# ---------------------------------------------------------------------------
# 주제 1: 예산 재배분 시뮬레이션
# ---------------------------------------------------------------------------
def budget_simulation(weekly: pd.DataFrame, elasticities=(0.3, 0.5, 0.7), cap=0.5):
    """
    가정한 반응곡선: 주간 성과 R_w = k · D_w · S_w^b   (D=수요지수, S=광고비, 0<b<1 = 체감효과)
    총예산 B 고정 시 최적 배분: S_w ∝ D_w^(1/(1-b)).
    실무 제약으로 주별 광고비 변경폭을 현재 대비 ±cap으로 제한한 버전도 계산한다.
    주의: 합성 데이터에서 광고비는 성과에 인과적 영향을 주도록 만들지 않았다.
          그래서 b는 데이터에서 추정한 값이 아니라 가정이며, 결과는 b별 민감도로 제시한다.
    """
    rows, plans = [], []
    last = weekly[weekly.days == 7].copy()
    for c, g in last.groupby("country"):
        g = g.sort_values("week_start").tail(52)
        D, S = g.demand_index.to_numpy(float), g.spend_eur.to_numpy(float)
        B = S.sum()
        for b in elasticities:
            k = 1 / (1 - b)
            R0 = (D * S ** b).sum()
            s_opt = D ** k / (D ** k).sum() * B
            lo, hi = (1 - cap) * S, (1 + cap) * S
            a, z = 0.0, 1e9
            for _ in range(200):  # 이분법으로 총예산을 맞추는 배율 탐색
                mid = (a + z) / 2
                if np.clip(mid * D ** k, lo, hi).sum() > B:
                    z = mid
                else:
                    a = mid
            s_cap = np.clip(a * D ** k, lo, hi)
            rows.append(dict(country=c, elasticity_b=b, weekly_budget_total_eur=round(B, 0),
                             uplift_unconstrained_pct=round(((D * s_opt ** b).sum() / R0 - 1) * 100, 2),
                             uplift_capped_pct=round(((D * s_cap ** b).sum() / R0 - 1) * 100, 2)))
            if b == 0.5:
                plans.append(pd.DataFrame(dict(country=c, week_start=g.week_start, demand_index=D,
                                               current_spend_eur=S.round(2), proposed_spend_eur=s_cap.round(2))))
    return pd.DataFrame(rows), pd.concat(plans, ignore_index=True)


# ---------------------------------------------------------------------------
# 요약
# ---------------------------------------------------------------------------
def md_table(df: pd.DataFrame, floatfmt="{:,.3f}") -> str:
    df = df.reset_index() if df.index.name else df
    cols = list(df.columns)
    fmt = lambda v: floatfmt.format(v) if isinstance(v, (float, np.floating)) else f"{v:,}" if isinstance(v, (int, np.integer)) else str(v)
    lines = ["| " + " | ".join(map(str, cols)) + " |", "|" + "---|" * len(cols)]
    lines += ["| " + " | ".join(fmt(v) for v in r) + " |" for r in df.itertuples(index=False)]
    return "\n".join(lines)


def analyze(data_dir: Path, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(data_dir / "spigen_synth.db")
    res = run_sql_files(con, ROOT / "sql", out_dir)
    con.close()

    ab = ab_analysis(res)
    ab.to_csv(out_dir / "ab_test_stats.csv")
    sim, plan = budget_simulation(res["05_seasonality_budget__weekly_efficiency"])
    sim.to_csv(out_dir / "budget_simulation.csv", index=False)
    plan.to_csv(out_dir / "budget_plan_b05_cap50.csv", index=False)

    truth = json.loads((data_dir / "truth" / "truth_experiment.json").read_text(encoding="utf-8"))
    val = res["02_rfm__validation_rfm_vs_truth"].set_index("rfm_segment")
    top = val.loc[[i for i in val.index if i.startswith(("1_", "2_"))]]
    vip_recall = top.vip.sum() / val.vip.sum()
    top_precision = (top.vip.sum() + top.loyal.sum()) / top.values.sum()

    ab_view = ab[["control", "treatment", "rel_lift", "ci_low", "ci_high", "p_value"]].astype(float)
    md = [
        "# 분석 결과 요약 (합성 데이터)",
        "",
        "> 이 결과는 `config/taxonomy.py`의 가정으로 생성한 **합성 데이터**의 분석 결과입니다. 실제 기업 데이터가 아닙니다.",
        "",
        "## 1. 데이터 품질", "", md_table(res["01_data_quality__integrity_checks"]), "",
        "## 2. RFM 세그먼트", "", md_table(res["02_rfm__rfm_segment_summary"], "{:,.1f}"), "",
        md_table(res["02_rfm__pareto_top_customers"], "{:,.1f}"), "",
        f"- 검증: 숨은 VIP의 **{vip_recall:.0%}**가 RFM Champions·Loyal로 분류됨, "
        f"Champions·Loyal 중 실제 VIP·충성 고객 비율 **{top_precision:.0%}**", "",
        "## 3. 리텐션 (채널별 누적 재구매율)", "", md_table(res["03_cohort_retention__retention_by_channel"], "{:,.1f}"), "",
        "## 4. A/B 테스트: " + truth["name"], "", md_table(ab_view, "{:,.4f}"), "",
        md_table(res["04_ab_test__ab_novelty"], "{:,.3f}"), "",
        f"- 실제 설정값: 구매 손실 {truth['purchase_loss_prob']:.0%}, 번들 수락률 첫 7일 "
        f"{truth['bundle_prob_novelty']:.0%} → 이후 {truth['bundle_prob']:.0%}, 번들 반품률 ×{truth['bundle_return_mult']}", "",
        "## 5. 주제 1: 수요 캘린더 기반 예산 배분", "",
        md_table(res["05_seasonality_budget__top8_weeks_gap"], "{:,.1f}"), "",
        md_table(res["05_seasonality_budget__efficiency_by_demand_quintile"], "{:,.2f}"), "",
        "예산 재배분 시뮬레이션 (총예산 동일, 반응곡선 탄력성 b는 가정):", "",
        md_table(sim, "{:,.2f}"), "",
    ]
    (out_dir / "summary.md").write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    data = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data"
    analyze(data, ROOT / "outputs")
