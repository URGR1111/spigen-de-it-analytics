"""
합성 이커머스 데이터 생성기 (독일·이탈리아 D2C 모바일 액세서리 스토어 가정).

생성 테이블 (data/raw/):
  products.csv          상품 마스터 (기종 × 케이스 시리즈 × 컬러, 강화유리, 범용 액세서리)
  users.csv             고객 (가입일, 국가, 유입채널, 연령대, 기기)
  orders.csv            주문 헤더 (금액, 할인, 반품, 실험군)
  order_items.csv       주문 상세
  sessions.csv          세션 요약
  events.csv            행동 로그 (session_start → page_view → product_view → add_to_cart
                        → begin_checkout → purchase)
  ab_assignments.csv    A/B 테스트 노출·배정
  marketing_spend.csv   일별 채널 광고비·노출·클릭 (월 예산 균등 배분 = 현재 방식)
  dim_calendar.csv      일별 국가 수요지수 (Google Trends 기반)·프로모션

검증용 정답 (data/truth/) — 분석에는 쓰지 않는다:
  truth_users.csv       숨은 세그먼트, 이탈일
  truth_experiment.json A/B 테스트 실제 효과
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from faker import Faker

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from config import taxonomy as T  # noqa: E402

N_DAYS = (T.END_DATE - T.START_DATE).days + 1
BASE_TS = np.datetime64(T.START_DATE.isoformat() + "T00:00:00")
MIN = 1 / 1440  # 1분 (일 단위)


def day_of(d: date) -> int:
    return (d - T.START_DATE).days


def to_ts(x) -> np.ndarray:
    """시뮬레이션 시각(시작일 기준 경과일, float) → datetime64[s]."""
    secs = np.round(np.asarray(x, dtype=float) * 86400).astype("int64")
    return BASE_TS + secs.astype("timedelta64[s]")


def weighted_choice(rng, options: dict):
    keys = list(options)
    p = np.array([options[k] for k in keys], dtype=float)
    return keys[rng.choice(len(keys), p=p / p.sum())]


# ---------------------------------------------------------------------------
# 1. 수요지수 (실측 Google Trends → 일간)
# ---------------------------------------------------------------------------
def build_demand() -> dict[str, np.ndarray]:
    tr = pd.read_csv(ROOT / "data_seed" / "google_trends_weekly.csv")
    days = np.arange(N_DAYS)
    weekday = (T.START_DATE.weekday() + days) % 7
    demand = {}
    for c, w in T.DEMAND_KEYWORD_WEIGHTS.items():
        t = tr[tr.country == c].sort_values("week_start")
        weekly = sum(t[k].to_numpy(float) * v for k, v in w.items())
        d = weekly[days // 7] * np.array(T.WEEKDAY_MULT)[weekday]
        demand[c] = d / d.mean()
    return demand


def growth(day_idx) -> np.ndarray:
    return np.exp(math.log(1 + T.ANNUAL_GROWTH) * np.asarray(day_idx) / 365)


# ---------------------------------------------------------------------------
# 2. 상품 마스터
# ---------------------------------------------------------------------------
COLOR_BY_STYLE = {
    "clear": ["Crystal Clear", "Matte Black", "Frost Blue"],
    "slim": ["Black", "Navy", "Sage", "Rose", "Sand"],
    "rugged": ["Matte Black", "Gunmetal", "Military Green"],
    "camera": ["Black", "Navy Blue", "Abyss Green"],
    "wallet": ["Black", "Saddle Brown", "Navy"],
}
TIER_PRICE_ADJ = {"flagship": 2.0, "mid": 0.0, "budget": -3.0, "legacy": -2.0}


def build_products() -> pd.DataFrame:
    rows = []
    for brand, model, rel, tier in T.DEVICE_MODELS:
        launch = max(rel - timedelta(days=7), T.START_DATE)
        qi2 = brand == "Apple" or model.startswith(("Galaxy S25", "Galaxy S26", "Pixel 10"))
        for series, (price, cost, style, n_col) in T.CASE_SERIES.items():
            if tier == "budget" and style in ("camera",):
                continue
            for color in COLOR_BY_STYLE[style][:n_col]:
                p = round(price + TIER_PRICE_ADJ[tier], 2)
                rows.append(dict(category="case", series=series, style=style, compatible_brand=brand,
                                 compatible_model=model, color=color, magsafe=bool(qi2 and style != "wallet"),
                                 list_price_eur=p, unit_cost_eur=round(p * cost, 2), launch_date=launch))
        for name, (price, cost) in T.PROTECTOR_TYPES.items():
            rows.append(dict(category="protector", series=name, style="glass", compatible_brand=brand,
                             compatible_model=model, color="Clear", magsafe=False,
                             list_price_eur=price, unit_cost_eur=round(price * cost, 2), launch_date=launch))
    for cat, name, price, cost in T.UNIVERSAL_ACCESSORIES:
        rows.append(dict(category=cat, series=name, style="accessory", compatible_brand="Universal",
                         compatible_model="Universal", color="Black", magsafe="MagFit" in name,
                         list_price_eur=price, unit_cost_eur=round(price * cost, 2), launch_date=T.START_DATE))
    df = pd.DataFrame(rows)
    df.insert(0, "product_id", [f"P{i:05d}" for i in range(1, len(df) + 1)])
    df.insert(1, "sku", [f"SG-{c[:3].upper()}-{i:05d}" for i, c in enumerate(df.category, 1)])
    df["product_name"] = np.where(df.compatible_model == "Universal", df.series,
                                  df.compatible_model + " " + df.series + " (" + df.color + ")")
    return df


class Catalog:
    """기종·스타일별 상품 조회 인덱스."""

    def __init__(self, products: pd.DataFrame):
        self.p = products
        self.price = dict(zip(products.product_id, products.list_price_eur))
        self.cases = {}
        self.protectors = {}
        for (model, style), g in products[products.category == "case"].groupby(["compatible_model", "style"]):
            self.cases[(model, style)] = g.product_id.tolist()
        for model, g in products[products.category == "protector"].groupby("compatible_model"):
            self.protectors[model] = g.product_id.tolist()
        acc = products[products.compatible_model == "Universal"]
        self.acc_ids = acc.product_id.to_numpy()
        prices = acc.list_price_eur.to_numpy(float)
        self.acc_w_vip = prices ** 0.8 / (prices ** 0.8).sum()
        self.acc_w_std = prices ** -0.5 / (prices ** -0.5).sum()
        self.chargers = acc[acc.category.isin(["charger", "power_bank"])].product_id.tolist()

    def case(self, rng, model, style):
        opts = self.cases.get((model, style))
        if not opts:
            opts = [pid for (m, _), ids in self.cases.items() if m == model for pid in ids]
        return opts[rng.integers(len(opts))]

    def protector(self, rng, model):
        opts = self.protectors[model]
        return opts[rng.integers(len(opts))]

    def accessory(self, rng, vip: bool):
        return self.acc_ids[rng.choice(len(self.acc_ids), p=self.acc_w_vip if vip else self.acc_w_std)]


# ---------------------------------------------------------------------------
# 3. 고객
# ---------------------------------------------------------------------------
MODELS_BY_BRAND: dict[str, list[tuple[str, int, str]]] = {}
for _b, _m, _rel, _tier in T.DEVICE_MODELS:
    MODELS_BY_BRAND.setdefault(_b, []).append((_m, (_rel - T.START_DATE).days, _tier))

# 브랜드별 신모델 출시 이벤트 (기간 내, flagship/mid) → 업그레이드 구매 트리거
LAUNCHES: dict[str, list[tuple[int, list[str]]]] = {}
for _b, lst in MODELS_BY_BRAND.items():
    by_day: dict[int, list[str]] = {}
    for _m, _d, _tier in lst:
        if 0 < _d < N_DAYS and _tier in ("flagship", "mid"):
            by_day.setdefault(_d, []).append(_m)
    LAUNCHES[_b] = sorted(by_day.items())


def pick_device(rng, brand: str, day: float) -> str:
    cands = [(m, d) for m, d, _ in MODELS_BY_BRAND[brand] if d <= day]
    ages = np.array([day - d for _, d in cands], dtype=float)
    w = np.exp(-ages / T.DEVICE_RECENCY_DAYS)
    return cands[rng.choice(len(cands), p=w / w.sum())][0]


def build_users(n_users: int, demand, rng) -> pd.DataFrame:
    frames = []
    seg_names = list(T.SEGMENTS)
    base_seg = np.array([T.SEGMENTS[s]["share"] for s in seg_names])
    ch_names = list(T.CHANNELS)
    for c, cfg in T.COUNTRIES.items():
        n = int(round(n_users * cfg["user_share"]))
        p_day = demand[c] * growth(np.arange(N_DAYS))
        day = rng.choice(N_DAYS, size=n, p=p_day / p_day.sum())
        hours = rng.choice(24, size=n, p=np.array(T.HOUR_WEIGHTS) / sum(T.HOUR_WEIGHTS))
        x = day + (hours + rng.random(n)) / 24

        acq = np.array([T.CHANNELS[ch]["acq_share"][c] for ch in ch_names])
        channel = np.array(ch_names)[rng.choice(len(ch_names), size=n, p=acq / acq.sum())]

        age = np.empty(n, dtype=object)
        segment = np.empty(n, dtype=object)
        for ch in ch_names:
            idx = np.where(channel == ch)[0]
            ad = np.array(T.CHANNELS[ch].get("age_dist", T.AGE_DIST[c]))
            age[idx] = np.array(T.AGE_BANDS)[rng.choice(6, size=len(idx), p=ad / ad.sum())]
            tilt = np.array([T.CHANNELS[ch]["segment_tilt"][s] for s in seg_names]) * base_seg
            segment[idx] = np.array(seg_names)[rng.choice(len(seg_names), size=len(idx), p=tilt / tilt.sum())]

        gp = cfg["gender_p"]
        gender = rng.choice(list(gp), size=n, p=list(gp.values()))
        bs = T.DEVICE_BRAND_SHARE[c]
        brand = rng.choice(list(bs), size=n, p=np.array(list(bs.values())) / sum(bs.values()))
        model = [pick_device(rng, b, d) for b, d in zip(brand, day)]

        life_mean = np.array([T.SEGMENTS[s]["lifetime_mean_days"] for s in segment], dtype=float)
        life_mean *= np.array([T.CHANNELS[ch]["lifetime_mult"] for ch in channel])
        life_mean *= np.where(age == "18-24", 0.8, 1.0)
        lifetime = rng.exponential(life_mean)

        opt_p = np.select([segment == "vip", segment == "loyal", segment == "regular"], [0.8, 0.65, 0.45], 0.3)
        style_pref = [weighted_choice(rng, T.CASE_STYLE_PREF_BY_AGE[a]) for a in age]

        fk = Faker(cfg["faker_locale"])
        fk.seed_instance(int(rng.integers(1 << 31)))
        frames.append(pd.DataFrame(dict(
            country=c, signup_x=x, acquisition_channel=channel, age_band=age, gender=gender,
            device_brand=brand, device_model_at_signup=model, segment=segment, lifetime_days=lifetime,
            marketing_opt_in=rng.random(n) < opt_p,
            platform_pref=rng.choice(list(T.PLATFORM_P), size=n, p=list(T.PLATFORM_P.values())),
            style_pref=style_pref,
            first_name=[fk.first_name() for _ in range(n)],
            last_name=[fk.last_name() for _ in range(n)],
            city=[fk.city() for _ in range(n)],
            postcode=[fk.postcode() for _ in range(n)],
        )))
    users = pd.concat(frames, ignore_index=True).sort_values("signup_x", ignore_index=True)
    users.insert(0, "user_id", [f"U{i:06d}" for i in range(1, len(users) + 1)])
    slug = (users.first_name.str.normalize("NFKD").str.encode("ascii", "ignore").str.decode("ascii")
            .str.lower().str.replace(r"[^a-z]", "", regex=True))
    users["email"] = slug + "." + users.user_id.str[1:] + "@example.com"
    return users


# ---------------------------------------------------------------------------
# 4. 주문 (의도) 시뮬레이션: 첫 구매 + 신모델 업그레이드 + 계절성 재구매
# ---------------------------------------------------------------------------
def simulate_orders(users: pd.DataFrame, demand, rng) -> tuple[list[dict], dict]:
    orders = []
    timelines = {}
    dmax = {c: d.max() for c, d in demand.items()}
    for u in users.itertuples(index=False):
        seg = T.SEGMENTS[u.segment]
        s = u.signup_x
        end_active = min(N_DAYS - 1e-4, s + u.lifetime_days)
        timeline = [(s, u.device_model_at_signup)]
        evs = [(s, "first", None)]
        for lday, models in LAUNCHES[u.device_brand]:
            if s < lday <= end_active and rng.random() < seg["upgrade_prob"]:
                t = lday + rng.exponential(9)
                if t <= end_active:
                    evs.append((t, "upgrade", models[rng.integers(len(models))]))
        span = end_active - s
        if span > 0:
            d = demand[u.country]
            k = rng.poisson(seg["repeat_rate"] * dmax[u.country] * span)
            ts = s + rng.random(k) * span
            keep = rng.random(k) < d[ts.astype(int)] / dmax[u.country]
            evs += [(t, "repeat", None) for t in ts[keep]]
        evs.sort(key=lambda e: e[0])
        mix = T.REPEAT_SOURCE_MIX[u.segment]
        for t, kind, new_model in evs:
            if kind == "upgrade":
                timeline.append((t, new_model))
            orders.append(dict(user_id=u.user_id, x=t, order_type=kind, country=u.country,
                               device_model=timeline[-1][1], segment=u.segment,
                               channel=u.acquisition_channel if kind == "first" else weighted_choice(rng, mix),
                               sess_start=t - rng.uniform(4, 30) * MIN))
        timelines[u.user_id] = (timeline, end_active)
    orders.sort(key=lambda o: o["x"])
    for i, o in enumerate(orders, 1):
        o["order_id"] = f"O{i:07d}"
    return orders, timelines


def model_at(timeline, t):
    m = timeline[0][1]
    for ts, mm in timeline:
        if ts <= t:
            m = mm
    return m


# ---------------------------------------------------------------------------
# 5. 브라우징 세션 (구매 없는 방문) + 이탈 후 잔존 방문
# ---------------------------------------------------------------------------
def simulate_browse_sessions(users: pd.DataFrame, timelines, demand, rng) -> list[dict]:
    out = []
    dmax = {c: d.max() for c, d in demand.items()}
    f = T.BROWSE_FUNNEL
    for u in users.itertuples(index=False):
        seg = T.SEGMENTS[u.segment]
        timeline, end_active = timelines[u.user_id]
        s = u.signup_x
        span = end_active - s
        starts = []
        if span > 0:
            k = rng.poisson(seg["browse_rate"] * dmax[u.country] * span)
            ts = s + rng.random(k) * span
            starts += list(ts[rng.random(k) < demand[u.country][ts.astype(int)] / dmax[u.country]])
        lapsed_end = min(N_DAYS - 1e-4, end_active + T.LAPSED_VISIT_DAYS)
        if lapsed_end > end_active:
            k = rng.poisson(T.LAPSED_VISIT_RATE * (lapsed_end - end_active))
            starts += list(end_active + rng.random(k) * (lapsed_end - end_active))
        mix = T.REPEAT_SOURCE_MIX[u.segment]
        for t in starts:
            pv = rng.random() < f["product_view"]
            atc = pv and rng.random() < f["add_to_cart"]
            co = atc and rng.random() < f["begin_checkout"]
            out.append(dict(user_id=u.user_id, start=t, country=u.country, source=weighted_choice(rng, mix),
                            model=model_at(timeline, t), style=u.style_pref,
                            stage=3 if co else 2 if atc else 1 if pv else 0, order=None))
    return out


# ---------------------------------------------------------------------------
# 6. A/B 테스트: 노출·배정·실제 효과 적용
# ---------------------------------------------------------------------------
def assign_variant(user_id: str, exp_id: str, share: float) -> str:
    h = int(hashlib.md5(f"{exp_id}:{user_id}".encode()).hexdigest(), 16) % 10_000
    return "treatment" if h < share * 10_000 else "control"


def apply_experiment(orders, browse, rng) -> pd.DataFrame:
    E = T.EXPERIMENT
    ws, we = day_of(E["start"]), day_of(E["end"]) + 1
    first_exp: dict[str, float] = {}
    for b in browse:  # 장바구니 페이지 도달 = 노출
        if b["stage"] >= 2 and ws <= b["start"] < we:
            t = b["start"] + 3 * MIN
            first_exp[b["user_id"]] = min(first_exp.get(b["user_id"], 1e9), t)
    for o in orders:
        if ws <= o["sess_start"] < we:
            t = o["sess_start"] + 3 * MIN
            first_exp[o["user_id"]] = min(first_exp.get(o["user_id"], 1e9), t)
    variant = {u: assign_variant(u, E["exp_id"], E["treatment_share"]) for u in first_exp}
    for o in orders:
        o["exp_variant"], o["bundle"], o["dropped"] = None, False, False
        u = o["user_id"]
        if u in first_exp and first_exp[u] - 5 * MIN <= o["sess_start"] < we:
            o["exp_variant"] = variant[u]
            if variant[u] == "treatment":
                if rng.random() < E["purchase_loss_prob"]:
                    o["dropped"] = True
                    continue
                days_in = o["x"] - first_exp[u]
                p = E["bundle_prob_novelty"] if days_in < E["novelty_days"] else E["bundle_prob"]
                o["bundle"] = rng.random() < p
    for b in browse:
        u = b["user_id"]
        b["exp_variant"] = variant[u] if (u in first_exp and first_exp[u] - 5 * MIN <= b["start"] < we) else None
    users_first_country = {o["user_id"]: o["country"] for o in orders}
    return pd.DataFrame(dict(
        exp_id=E["exp_id"], user_id=list(first_exp),
        variant=[variant[u] for u in first_exp],
        first_exposure_ts=to_ts(list(first_exp.values())),
        country=[users_first_country.get(u) for u in first_exp],
    )).sort_values("first_exposure_ts", ignore_index=True)


# ---------------------------------------------------------------------------
# 7. 장바구니·가격·할인·반품
# ---------------------------------------------------------------------------
PROMO_DAYS = [(code, day_of(s), day_of(e) + 1, pct, prob) for code, s, e, pct, prob in T.PROMOS]


def promo_for(x: float):
    for code, s, e, pct, prob in PROMO_DAYS:
        if s <= x < e:
            return code, pct, prob
    return None


def build_items_and_amounts(orders, users: pd.DataFrame, cat: Catalog, rng):
    uinfo = users.set_index("user_id")[["style_pref", "acquisition_channel"]].to_dict("index")
    items = []
    E = T.EXPERIMENT
    for o in orders:
        if o["dropped"]:
            continue
        seg = T.SEGMENTS[o["segment"]]
        vip = o["segment"] == "vip"
        style = uinfo[o["user_id"]]["style_pref"]
        model = o["device_model"]
        basket = []
        n = 1 + rng.poisson(max(seg["items_mean"] - 1, 0.01))
        if o["order_type"] in ("first", "upgrade"):
            basket.append(cat.case(rng, model, style if rng.random() < 0.7 else weighted_choice(
                rng, T.CASE_STYLE_PREF_BY_AGE["25-34"])))
            if rng.random() < (0.6 if o["order_type"] == "upgrade" else 0.3):
                basket.append(cat.protector(rng, model))
        else:
            mix = dict(T.REPEAT_CATEGORY_MIX)
            mix["accessory"] *= 1 + 2 * seg["accessory_affinity"]
            first = weighted_choice(rng, mix)
            basket.append(cat.case(rng, model, style) if first == "case" else
                          cat.protector(rng, model) if first == "protector" else cat.accessory(rng, vip))
        while len(basket) < n:
            r = rng.random()
            if r < seg["accessory_affinity"] + 0.2:
                basket.append(cat.accessory(rng, vip))
            elif r < 0.75:
                basket.append(cat.protector(rng, model))
            else:
                basket.append(cat.case(rng, model, style))
        # 할인
        promo = promo_for(o["x"])
        code, pct = None, 0.0
        if promo and rng.random() < promo[2] * seg["discount_sensitivity"]:
            code, pct = promo[0], promo[1]
        elif o["order_type"] == "first" and rng.random() < T.WELCOME_COUPON[2]:
            code, pct = T.WELCOME_COUPON[0], T.WELCOME_COUPON[1]
        elif rng.random() < T.ALWAYS_ON_COUPON[2] * seg["discount_sensitivity"]:
            code, pct = T.ALWAYS_ON_COUPON[0], T.ALWAYS_ON_COUPON[1]
        lines = [(pid, 2 if rng.random() < 0.04 else 1, pct, False) for pid in basket]
        if o["bundle"]:
            has_prot = any(pid in cat.protectors.get(model, []) for pid in basket)
            add = cat.chargers[rng.integers(len(cat.chargers))] if has_prot else cat.protector(rng, model)
            lines.append((add, 1, max(pct, E["bundle_discount"]), True))
        gross = disc = 0.0
        for pid, qty, p, is_bundle in lines:
            up = cat.price[pid]
            line_disc = round(up * qty * p, 2)
            items.append(dict(order_id=o["order_id"], product_id=pid, quantity=qty, unit_price_eur=up,
                              discount_pct=p, discount_eur=line_disc,
                              line_amount_eur=round(up * qty - line_disc, 2), is_bundle_upsell=is_bundle))
            gross += up * qty
            disc += line_disc
        net = round(gross - disc, 2)
        cfg = T.COUNTRIES[o["country"]]
        o.update(items_count=sum(q for _, q, _, _ in lines), gross_amount_eur=round(gross, 2),
                 discount_amount_eur=round(disc, 2), net_amount_eur=net, promo_code=code,
                 shipping_fee_eur=0.0 if net >= cfg["free_shipping_over"] else cfg["shipping_fee"],
                 basket=[pid for pid, *_ in lines])
        # 반품
        acq = uinfo[o["user_id"]]["acquisition_channel"]
        p_ret = T.BASE_RETURN_RATE * T.CHANNELS[acq]["return_mult"] * (1.3 if o["segment"] == "one_off" else 1.0)
        if o["bundle"]:
            p_ret *= E["bundle_return_mult"]
        o["is_returned"] = bool(rng.random() < p_ret)
        o["return_x"] = o["x"] + rng.uniform(4, 25) if o["is_returned"] else None
    return pd.DataFrame(items)


# ---------------------------------------------------------------------------
# 8. 세션·이벤트 로그 생성
# ---------------------------------------------------------------------------
def build_sessions_events(orders, browse, timelines, cat: Catalog, users, rng):
    platform_pref = dict(zip(users.user_id, users.platform_pref))
    sessions, events = [], []
    sid = 0

    def plat(u):
        return platform_pref[u] if rng.random() < 0.8 else ("desktop" if platform_pref[u] == "mobile" else "mobile")

    def emit(sess_id, user, t, name, product=None, order=None):
        events.append((sess_id, user, t, name, product, order))

    for o in orders:  # 구매 세션 (실험으로 이탈된 구매는 checkout까지 가고 이탈)
        sid += 1
        s_id = f"S{sid:08d}"
        t = o["sess_start"]
        emit(s_id, o["user_id"], t, "session_start")
        t += rng.exponential(10) / 86400
        emit(s_id, o["user_id"], t, "page_view")
        basket = o.get("basket") or [cat.case(rng, o["device_model"], "clear")]
        viewed = list(basket) + [cat.case(rng, o["device_model"], "slim") for _ in range(rng.poisson(1.0))]
        for pid in viewed:
            t += rng.exponential(45) / 86400
            emit(s_id, o["user_id"], t, "product_view", pid)
        for pid in basket:
            t += rng.exponential(20) / 86400
            emit(s_id, o["user_id"], t, "add_to_cart", pid)
        t += rng.exponential(60) / 86400
        emit(s_id, o["user_id"], t, "begin_checkout")
        if not o["dropped"]:
            t = max(t + 30 / 86400, o["x"])
            emit(s_id, o["user_id"], t, "purchase", None, o["order_id"])
        o["session_id"] = s_id
        sessions.append(dict(session_id=s_id, user_id=o["user_id"], session_start_x=o["sess_start"],
                             country=o["country"], traffic_source=o["channel"], platform=plat(o["user_id"]),
                             is_converted=not o["dropped"], exp_variant=o["exp_variant"]))
    for b in browse:
        sid += 1
        s_id = f"S{sid:08d}"
        t = b["start"]
        emit(s_id, b["user_id"], t, "session_start")
        t += rng.exponential(10) / 86400
        emit(s_id, b["user_id"], t, "page_view")
        if b["stage"] >= 1:
            pids = [cat.case(rng, b["model"], b["style"]) for _ in range(1 + rng.poisson(1.2))]
            for pid in pids:
                t += rng.exponential(45) / 86400
                emit(s_id, b["user_id"], t, "product_view", pid)
            if b["stage"] >= 2:
                t += rng.exponential(20) / 86400
                emit(s_id, b["user_id"], t, "add_to_cart", pids[0])
            if b["stage"] >= 3:
                t += rng.exponential(60) / 86400
                emit(s_id, b["user_id"], t, "begin_checkout")
        sessions.append(dict(session_id=s_id, user_id=b["user_id"], session_start_x=b["start"],
                             country=b["country"], traffic_source=b["source"], platform=plat(b["user_id"]),
                             is_converted=False, exp_variant=b["exp_variant"]))
    sessions_df = pd.DataFrame(sessions)
    sessions_df.insert(2, "session_start_ts", to_ts(sessions_df.pop("session_start_x")))
    ev = pd.DataFrame(events, columns=["session_id", "user_id", "t", "event_name", "product_id", "order_id"])
    ev = ev.sort_values("t", kind="stable", ignore_index=True)
    ev.insert(0, "event_id", [f"E{i:09d}" for i in range(1, len(ev) + 1)])
    ev.insert(3, "event_ts", to_ts(ev.pop("t")))
    sessions_df = sessions_df.sort_values("session_start_ts", ignore_index=True)
    return sessions_df, ev


# ---------------------------------------------------------------------------
# 9. 마케팅 비용 (현재 방식: 월 예산 균등 배분)
# ---------------------------------------------------------------------------
def build_marketing_spend(users: pd.DataFrame, demand, rng) -> pd.DataFrame:
    dates = pd.date_range(T.START_DATE, T.END_DATE, freq="D")
    months = dates.to_period("M")
    n_months = months.nunique()
    rows = []
    for c in T.COUNTRIES:
        for ch, cfg in T.CHANNELS.items():
            if not cfg["paid"]:
                continue
            n_acq = ((users.country == c) & (users.acquisition_channel == ch)).sum()
            base_month = n_acq / n_months * cfg["cac_target"][c]
            g = growth(np.arange(N_DAYS))
            g = g / g.mean()
            days_in_month = pd.Series(months).map(pd.Series(months).value_counts()).to_numpy()
            spend = base_month / days_in_month * g * (1 + rng.normal(0, T.SPEND_DAILY_NOISE, N_DAYS))
            spend = np.round(np.clip(spend, 0, None), 2)
            impressions = np.round(spend / T.CPM[ch][c] * 1000).astype(int)
            ctr = T.BASE_CTR[ch] * (0.75 + 0.25 * demand[c]) * rng.lognormal(0, 0.05, N_DAYS)
            clicks = rng.binomial(impressions, np.clip(ctr, 0, 1))
            rows.append(pd.DataFrame(dict(date=dates.date, country=c, channel=ch, spend_eur=spend,
                                          impressions=impressions, clicks=clicks)))
    return pd.concat(rows, ignore_index=True).sort_values(["date", "country", "channel"], ignore_index=True)


def build_calendar(demand) -> pd.DataFrame:
    dates = pd.date_range(T.START_DATE, T.END_DATE, freq="D")
    rows = []
    for c, d in demand.items():
        promo = [(promo_for(i) or (None,))[0] for i in range(N_DAYS)]
        rows.append(pd.DataFrame(dict(date=dates.date, country=c,
                                      week_start=(dates - pd.to_timedelta((dates.weekday + 1) % 7, unit="D")).date,
                                      demand_index=np.round(d, 4), promo_code=promo)))
    return pd.concat(rows, ignore_index=True)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def generate(n_users: int, seed: int, out: Path) -> dict:
    t0 = time.time()
    rng = np.random.default_rng(seed)
    raw, truth = out / "raw", out / "truth"
    raw.mkdir(parents=True, exist_ok=True)
    truth.mkdir(parents=True, exist_ok=True)

    demand = build_demand()
    products = build_products()
    cat = Catalog(products)
    users = build_users(n_users, demand, rng)
    print(f"  users        {len(users):>9,}")
    orders, timelines = simulate_orders(users, demand, rng)
    browse = simulate_browse_sessions(users, timelines, demand, rng)
    ab = apply_experiment(orders, browse, rng)
    items = build_items_and_amounts(orders, users, cat, rng)
    sessions, events = build_sessions_events(orders, browse, timelines, cat, users, rng)
    spend = build_marketing_spend(users, demand, rng)
    calendar = build_calendar(demand)

    kept = [o for o in orders if not o["dropped"]]
    orders_df = pd.DataFrame(kept)
    orders_df["order_ts"] = to_ts(orders_df.x)
    orders_df["returned_ts"] = pd.Series(to_ts(orders_df.return_x.fillna(0))).where(orders_df.is_returned)
    orders_df = orders_df.rename(columns={"channel": "traffic_source", "device_model": "device_model_at_order",
                                          "exp_variant": "ab_variant", "bundle": "has_bundle_upsell"})
    orders_df = orders_df[["order_id", "user_id", "session_id", "order_ts", "country", "order_type",
                           "traffic_source", "device_model_at_order", "items_count", "gross_amount_eur",
                           "discount_amount_eur", "net_amount_eur", "shipping_fee_eur", "promo_code",
                           "is_returned", "returned_ts", "ab_variant", "has_bundle_upsell"]]
    item_ids = items.merge(orders_df[["order_id", "order_ts"]], on="order_id").sort_values(["order_ts", "order_id"])
    items = item_ids.drop(columns="order_ts").reset_index(drop=True)
    items.insert(0, "order_item_id", [f"OI{i:08d}" for i in range(1, len(items) + 1)])

    users_out = users.assign(signup_ts=to_ts(users.signup_x))[
        ["user_id", "signup_ts", "country", "acquisition_channel", "age_band", "gender", "device_brand",
         "device_model_at_signup", "platform_pref", "marketing_opt_in", "first_name", "last_name",
         "email", "city", "postcode"]]
    truth_users = users.assign(churn_ts=to_ts(np.minimum(users.signup_x + users.lifetime_days, N_DAYS)),
                               censored=users.signup_x + users.lifetime_days >= N_DAYS)[
        ["user_id", "segment", "lifetime_days", "churn_ts", "censored"]].rename(columns={"segment": "latent_segment"})

    tables = dict(products=products, users=users_out, orders=orders_df, order_items=items, sessions=sessions,
                  events=events, ab_assignments=ab, marketing_spend=spend, dim_calendar=calendar)
    for name, df in tables.items():
        df.to_csv(raw / f"{name}.csv", index=False)
        print(f"  {name:<16} {len(df):>9,} rows")
    truth_users.round({"lifetime_days": 1}).to_csv(truth / "truth_users.csv", index=False)
    E = {k: (v.isoformat() if isinstance(v, date) else v) for k, v in T.EXPERIMENT.items()}
    (truth / "truth_experiment.json").write_text(json.dumps(E, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  done in {time.time() - t0:.1f}s → {raw}")
    return {k: len(v) for k, v in tables.items()}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="합성 이커머스 데이터 생성")
    ap.add_argument("--users", type=int, default=30_000)
    ap.add_argument("--seed", type=int, default=T.SEED)
    ap.add_argument("--out", type=Path, default=ROOT / "data")
    a = ap.parse_args()
    generate(a.users, a.seed, a.out)
