"""Zamiana prawdopodobieństw na typy: single z przewagą, kupony 2–3 i długie kupony.

Słownik pojęć:
- p_model  – prawdopodobieństwo z naszego modelu (po korekcie kontuzji)
- p_market – prawdopodobieństwo rynku (kursy średnie bez marży)
- p        – ostrożne połączenie obu (rynek dostaje większą wagę, bo zwykle wie więcej)
- kurs_fair – 1/p; poniżej tego kursu zakład ma ujemną wartość nawet bez podatku
- kurs_min_sts – kurs, przy którym zakład się opłaca PO polskim podatku 12% od stawki
"""
import itertools
import math

import numpy as np

from . import config as C
from .model import MARKET_LABELS

ODDS_MARKETS = {"1": "odds_h", "X": "odds_d", "2": "odds_a", "O2.5": "odds_o25", "U2.5": "odds_u25"}
TYPICAL_MARGIN = {"1X": 0.05, "X2": 0.05, "12": 0.05, "O1.5": 0.07, "U1.5": 0.07, "O3.5": 0.07,
                  "U3.5": 0.07, "BTTS": 0.06, "BTTS_NO": 0.06}


def fair_probs(odds):
    """Usunięcie marży metodą potęgową (lepiej oddaje faworyt/longshot bias)."""
    o = np.array([x for x in odds], dtype=float)
    if np.any(~np.isfinite(o)) or np.any(o <= 1):
        return None
    inv = 1 / o
    if inv.sum() <= 1:
        return inv / inv.sum()
    lo, hi = 1.0, 3.0
    for _ in range(60):
        k = (lo + hi) / 2
        s = (inv ** k).sum()
        lo, hi = (k, hi) if s > 1 else (lo, k)
    p = inv ** ((lo + hi) / 2)
    return p / p.sum()


def market_view(fx):
    """-> (prawdopodobieństwa rynkowe, kursy rynkowe, marża 1X2)."""
    pm, om = {}, {}
    margin = None
    oh, od, oa = fx.get("odds_h"), fx.get("odds_d"), fx.get("odds_a")
    f = fair_probs([oh, od, oa]) if oh and od and oa else None
    if f is not None:
        pm.update({"1": f[0], "X": f[1], "2": f[2], "1X": f[0] + f[1], "X2": f[1] + f[2], "12": f[0] + f[2]})
        om.update({"1": oh, "X": od, "2": oa})
        margin = 1 / oh + 1 / od + 1 / oa - 1
    oo, ou = fx.get("odds_o25"), fx.get("odds_u25")
    f = fair_probs([oo, ou]) if oo and ou else None
    if f is not None:
        pm.update({"O2.5": f[0], "U2.5": f[1]})
        om.update({"O2.5": oo, "U2.5": ou})
    return pm, om, margin


def _clean(x):
    try:
        x = float(x)
        return x if math.isfinite(x) and x > 1 else None
    except (TypeError, ValueError):
        return None


def evaluate_match(match):
    """Dodaje do meczu listę 'options' – każdy rynek z p, kursem i przewagą."""
    pm, om, margin = market_view({k: _clean(match.get(k)) for k in ODDS_MARKETS.values()})
    match["market_margin"] = round(margin, 4) if margin else None
    opts = []
    for key, label in MARKET_LABELS.items():
        p_mod = match["probs"][key]
        p_mkt = pm.get(key)
        p = (1 - C.MARKET_WEIGHT) * p_mod + C.MARKET_WEIGHT * p_mkt if p_mkt is not None else p_mod
        if key in om:
            odds_mkt, est = om[key], False
        elif p_mkt is not None:
            odds_mkt, est = 1 / (p_mkt * (1 + TYPICAL_MARGIN.get(key, 0.06))), True
        else:
            odds_mkt, est = 1 / (p_mod * (1 + TYPICAL_MARGIN.get(key, 0.07))), True
        odds_sts = odds_mkt * (1 - C.STS_MARGIN_DISCOUNT)
        opts.append(dict(
            key=key, label=label, p=round(p, 4), p_model=round(p_mod, 4),
            p_market=round(p_mkt, 4) if p_mkt is not None else None,
            odds_market=round(odds_mkt, 2), odds_estimated=est, odds_sts_est=round(odds_sts, 2),
            fair=round(1 / p, 2), min_sts=round(1 / (p * (1 - C.STS_TAX)), 2),
            edge=round(p * odds_sts - 1, 4),                       # przed podatkiem
            ev_after_tax=round(p * odds_sts * (1 - C.STS_TAX) - 1, 4),
            disagreement=round(p_mod - p_mkt, 4) if p_mkt is not None else None,
            verified=p_mkt is not None))
    for o in opts:
        o["pickable"] = o["key"] in C.PICK_MARKETS
        o["calibrating"] = not o["pickable"]
    match["options"] = opts
    return match


def _leg(match, opt):
    return dict(match_id=match["id"], league=match["league"], home=match["home"], away=match["away"],
                kickoff=match["kickoff"], market=opt["key"], label=opt["label"], p=opt["p"],
                odds=opt["odds_sts_est"], fair=opt["fair"], min_sts=opt["min_sts"], edge=opt["edge"])


def coupon_stats(legs, stake=1.0, bonus=0.0):
    p = float(np.prod([l["p"] for l in legs]))
    odds = float(np.prod([l["odds"] for l in legs])) * (1 + bonus)
    payout = stake * (1 - C.STS_TAX) * odds
    if payout > C.BIG_WIN_TAX_LIMIT:
        payout *= 0.9
    return dict(p=p, odds=round(odds, 2), payout=round(payout, 2), stake=stake,
                ev=round(p * payout - stake, 2), ev_pct=round(p * payout / stake - 1, 4),
                one_in=round(1 / p, 1) if p > 0 else None)


def build(matches, prefix=""):
    """-> dict(singles, combos, long, matches)"""
    for m in matches:
        evaluate_match(m)
    allowed = {id(m): [o for o in m["options"] if o["pickable"]] for m in matches}

    def score(o):  # przewaga z małą premią za zweryfikowany kurs rynkowy
        return o["edge"] + (0.01 if o["verified"] and not o["odds_estimated"] else -0.02)

    # --- single: tylko rynki z prawdziwym kursem, max 1 na mecz ---------------
    cands = []
    for m in matches:
        best = max((o for o in allowed[id(m)] if o["verified"] and not o["odds_estimated"]
                    and o["p"] >= C.MIN_PROB_SINGLE), key=lambda o: o["edge"], default=None)
        if best:
            cands.append((m, best))
    cands.sort(key=lambda x: -x[1]["edge"])
    value = [c for c in cands if c[1]["edge"] >= C.MIN_EDGE][:6]
    chosen = value or cands[:3]          # brak przewagi -> 3 typy "najbliżej wartości"
    singles = [dict(id=f"{prefix}S{i + 1}", type="single" if value else "single (bez przewagi)",
                    value=bool(value), legs=[_leg(m, o)], **coupon_stats([_leg(m, o)], 10))
               for i, (m, o) in enumerate(chosen)]

    # --- kupony 2–3 z różnych meczów, legi z p >= 50% -------------------------
    pool = []
    for m in matches:
        good = [o for o in allowed[id(m)] if o["verified"] and o["p"] >= 0.5]
        if good:
            pool.append((m, max(good, key=score)))
    pool.sort(key=lambda x: -score(x[1]))
    pool = pool[:10]
    combos, used = [], set()
    for n in (2, 3):
        best = None
        for comb in itertools.combinations(pool, n):
            if n == 3 and len({m["id"] for m, _ in comb} & used) > 1:
                continue
            legs = [_leg(m, o) for m, o in comb]
            st = coupon_stats(legs, 5)
            if st["p"] < (0.25 if n == 3 else 0.33):
                continue
            if best is None or st["ev_pct"] > best[0]:
                best = (st["ev_pct"], legs, st, comb)
        if best:
            used |= {m["id"] for m, _ in best[3]}
            combos.append(dict(id=f"{prefix}K{len(combos) + 1}", type=f"kupon {n}", legs=best[1], **best[2]))

    # --- długie kupony za 2 zł: dwa warianty ---------------------------------
    def long_coupon(name, kind, odds_lo, odds_hi, p_min, n_min, n_max):
        pool = []
        for m in matches:
            # tylko rynki z kursem rynkowym – bez niego "kurs" byłby wzięty z samego modelu
            opts = [o for o in allowed[id(m)] if o["verified"]
                    and odds_lo <= o["odds_sts_est"] <= odds_hi and o["p"] >= p_min]
            if opts:
                pool.append((m, max(opts, key=score)))
        pool.sort(key=lambda x: -score(x[1]))
        if len(pool) < n_min:
            return None
        legs = [_leg(m, o) for m, o in pool[:n_max]]
        return dict(id=prefix + name, type=f"{kind} · {len(legs)} zdarzeń", legs=legs,
                    **coupon_stats(legs, C.LONG_COUPON_STAKE))

    lo, hi = C.LONG_COUPON_LEGS
    longs = [c for c in (
        long_coupon("D1", "dużo zdarzeń", 1.18, 1.6, 0.6, lo, hi),
        long_coupon("D2", "duży przelicznik", 1.7, 2.8, 0.36, 5, 8),
    ) if c]
    return dict(singles=singles, combos=combos, long=longs, matches=matches)
