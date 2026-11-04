"""Wiadomości kadrowe z FotMob: niedostępni, przewidywana/potwierdzona XI vs „zwykła jedenastka”,
zmęczenie (informacyjnie). Wpływ składu na model: λ·exp(a·d_własne + b·d_rywala), a/b z backtestu
(tests/backtest_lineups.py, config LINEUP_A/LINEUP_B; 0 = tylko informacja)."""
import logging
from datetime import timedelta

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from . import config as C
from . import fotmob as F
from .model import markets, score_matrix
from .names import Matcher

log = logging.getLogger("team_news")


def find_fotmob_ids(fixtures):
    """{indeks terminarza: mecz FotMob} – dopasowanie po lidze, nazwach i godzinie (±3 h)."""
    days = set()
    for f in fixtures:
        ko = pd.Timestamp(f["kickoff"])
        days |= {ko.date(), ko.tz_convert(C.TZ).date()}
    fm = []
    for d in sorted(days):
        try:
            fm += F.day_matches(d.isoformat())
        except Exception as e:  # noqa: BLE001
            log.warning("fotmob %s: %s", d, e)
    out = {}
    for i, f in enumerate(fixtures):
        cands = [m for m in fm if m["league"] == f["league"]
                 and abs(m["kickoff"] - pd.Timestamp(f["kickoff"])) <= timedelta(hours=3)]
        if not cands:
            continue
        mt = Matcher([m["home"] for m in cands])
        h = mt.match(f.get("home_full", f["home"])) or mt.match(f["home"])
        hit = next((m for m in cands if m["home"] == h), None)
        if hit:
            out[i] = hit
    return out


def lineup_effect(lh, la, d_h, d_a, a=None, b=None):
    a = C.LINEUP_A if a is None else a
    b = C.LINEUP_B if b is None else b
    return lh * np.exp(a * d_h + b * d_a), la * np.exp(a * d_a + b * d_h)


def team_context(fm_match, league):
    """Skład (przewidywany/potwierdzony), zwykła XI, niedostępni i terminarz obu drużyn."""
    md = F.match_details(fm_match["id"])
    lu = F.lineups(md)
    lg_fm = C.LEAGUES[league].get("fotmob")
    ctx = dict(fm_id=fm_match["id"], lineup_type=lu.get("type"), confirmed=F.confirmed(lu))
    for side in ("home", "away"):
        tid = fm_match[f"{side}_id"]
        fx = F.team_fixtures(tid)
        info = dict(team_id=tid, unavailable=lu[side]["unavailable"], schedule=F.schedule_info(fx, fm_match["kickoff"]),
                    starters=lu[side]["starters"], d=None, out=[], into=[])
        if not C.LEAGUES[league].get("cup"):  # zwykła XI z meczów ligowych (jak w backteście)
            usual, used = F.usual_xi(tid, fm_match["kickoff"], fixtures=[f for f in fx if f["league_id"] == lg_fm])
            if used >= 3 and len(lu[side]["starters"]) == 11:
                ch = F.lineup_change(lu[side]["starters"], usual)
                # cecha z backtestu: liczba zawodników zwykłej XI poza składem (nie wartość XI)
                info.update(d=-len(ch["out"]) / 11, value_delta=ch["delta"], out=ch["out"], into=ch["into"],
                            usual=usual)
        ctx[side] = info
    return ctx


def _reason(p, unavailable):
    u = next((x for x in unavailable if x["id"] == p["id"]), None)
    if not u:
        return "rotacja/decyzja trenera"
    kind = {"injury": "kontuzja", "suspension": "zawieszenie", "international": "kadra"}.get(u["type"], u["type"] or "niedostępny")
    return f"{kind}" + (f", powrót: {u['expected_return']}" if u.get("expected_return") else "")


def why_items(ctx, home, away, impact_pp=None):
    """Lista „dlaczego” (czynnik, opis po polsku, wpływ w pkt proc. lub None = tylko informacja)."""
    out = []
    for side, name in (("home", home), ("away", away)):
        t = ctx.get(side) or {}
        if t.get("d") is not None and t["out"]:
            who = ", ".join(f"{p['name']} ({_reason(p, t['unavailable'])})" for p in t["out"][:4])
            kind = "potwierdzony" if ctx.get("confirmed") else (
                "ostatni" if ctx.get("lineup_type") == "lastStarting11" else "przewidywany")
            out.append(dict(factor="skład", text=f"{name}: {kind} skład bez {len(t['out'])} z „zwykłej jedenastki”"
                            + (f": {who}" if who else ""),
                            impact=(impact_pp or {}).get(side)))
        elif t.get("unavailable"):
            top = sorted(t["unavailable"], key=lambda p: -p["value"])[:3]
            out.append(dict(factor="absencje", text=f"{name}: niedostępni – " + ", ".join(
                f"{p['name']} ({_reason(p, t['unavailable'])})" for p in top), impact=None))
        s = t.get("schedule") or {}
        notes = []
        if s.get("rest_days") is not None and s["rest_days"] < 4:
            notes.append(f"tylko {s['rest_days']:.0f} dni odpoczynku")
        if s.get("euro_before"):
            notes.append("mecz europejski w tym tygodniu")
        if s.get("euro_after"):
            notes.append("mecz europejski za ≤4 dni (możliwa rotacja)")
        if s.get("games_14d", 0) >= 4:
            notes.append(f"{s['games_14d']} mecze w 14 dni")
        if notes:
            out.append(dict(factor="zmęczenie", text=f"{name}: " + ", ".join(notes) + " (tylko informacja)",
                            impact=None))
    return out


def implied_lambdas(p1, p2, po25=None, rho=-0.05):
    """λ gospodarzy i gości odpowiadające prawdopodobieństwom 1/2 (i O2.5, jeśli jest)."""
    def err(x):
        lh, la = np.exp(x)
        mk = markets(score_matrix(lh, la, rho))
        e = (mk["1"] - p1) ** 2 + (mk["2"] - p2) ** 2
        if po25 is not None:
            e += 0.5 * (mk["O2.5"] - po25) ** 2
        return e
    x = minimize(err, np.log([1.4, 1.1]), method="Nelder-Mead", options=dict(xatol=1e-4, fatol=1e-9)).x
    return tuple(np.exp(x))


def reprice(match, d_new, d_old):
    """Przeliczenie meczu po potwierdzonych składach: efekt zmiany (d_new vs d_old z rana)
    nakładamy na finalne prawdopodobieństwa (rynek + model) – rynek z rana nie znał składów."""
    opt = {o["key"]: o["p"] for o in match.get("options", [])}
    if not all(k in opt for k in ("1", "X", "2")):
        return None
    lh, la = implied_lambdas(opt["1"], opt["2"], opt.get("O2.5"))
    dh = (d_new[0] or 0) - (d_old[0] or 0)
    da = (d_new[1] or 0) - (d_old[1] or 0)
    lh2, la2 = lineup_effect(lh, la, dh, da)
    before = markets(score_matrix(lh, la))
    after = markets(score_matrix(lh2, la2))
    return {k: (opt[k], opt[k] + after[k] - before[k]) for k in ("1", "X", "2")}
