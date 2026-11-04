"""Główny przebieg: dane -> modele -> mecze -> typy -> rejestry."""
import logging
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from . import config as C
from . import data_sources as D
from . import injuries as I
from . import news as N
from . import picks as P
from . import tracker as T
from .model import fit_elo_bridge, fit_league, markets, score_matrix
from .names import Matcher, norm

log = logging.getLogger("pipeline")


def match_id(league, kickoff, home, away):
    return f"{league}:{pd.Timestamp(kickoff).strftime('%Y-%m-%d')}:{norm(home)}-{norm(away)}".replace(" ", "_")


def load_history():
    hist, models = {}, {}
    for lg in C.DOMESTIC:
        df = D.fdcuk_results(lg)
        if df.empty:
            log.error("Brak historii dla %s – liga pominięta", lg)
            continue
        if C.LEAGUES[lg].get("us"):
            df = D.attach_xg(df, lg)
        hist[lg] = df
        models[lg] = fit_league(df, lg)
    return hist, models


def current_teams(hist, lg, days=200):
    df = hist[lg]
    recent = df[df.date >= df.date.max() - pd.Timedelta(days=days)]
    return sorted(set(recent.home) | set(recent.away))


def elo_lookup(models, extra_countries=()):
    """{(liga, drużyna): Elo} dla drużyn naszych lig + cały ranking (do LM)."""
    countries = {C.LEAGUES[lg]["elo_country"] for lg in models} | set(extra_countries)
    elo = D.elo_ratings(countries)
    out = {}
    for lg in models:
        sub = elo[elo.Country == D.country_code(C.LEAGUES[lg]["elo_country"])]
        mt = Matcher(models[lg].teams)
        for r in sub.itertuples():
            t = mt.match(r.Club)
            if t:
                out[(lg, t)] = float(r.Elo)
    return out, elo


class UclStrength:
    """Siła drużyny LM w skali Elo – dla wszystkich z jednego rankingu (ta sama skala, na której
    skalibrowany jest most Elo -> gole). Klub z naszych lig, którego nie ma w rankingu: Elo
    przewidziane z siły w modelu ligowym (regresja Elo ~ siła w obrębie ligi).
    Brak danych -> None (mecz pomijamy, nie zgadujemy)."""

    def __init__(self, models, elo_map, elo_df, team_cc):
        self.models, self.elo, self.team_cc = models, elo_df, team_cc
        self.cc2lg = {D.country_code(C.LEAGUES[lg]["elo_country"]): lg for lg in models}
        self.reg = {}
        for lg, m in models.items():
            pairs = np.array([(m.strength(t), e) for (l, t), e in elo_map.items() if l == lg])
            if len(pairs) >= 8 and pairs[:, 0].std() > 0:
                b, a = np.polyfit(pairs[:, 0], pairs[:, 1], 1)
                self.reg[lg] = (a, b)

    def __call__(self, team_id, full, short):
        cc = self.team_cc.get(team_id)
        sub = self.elo[self.elo.Country == cc] if cc else self.elo
        if len(sub):
            mt = Matcher(sub.Club.tolist())
            club = mt.match(full) or mt.match(short)
            if club:
                row = sub[sub.Club == club].iloc[0]
                return float(row.Elo), f"{row.Source}: {club}"
        lg = self.cc2lg.get(cc)
        if lg in self.reg:
            mt = Matcher(self.models[lg].teams)
            t = mt.match(full) or mt.match(short)
            if t:
                a, b = self.reg[lg]
                return a + b * self.models[lg].strength(t), f"model {lg}"
        return None, None


def gather_fixtures(hist, models, now):
    horizon = now + timedelta(hours=C.HORIZON_HOURS)
    fx = D.fdcuk_fixtures()
    rows = []
    if not fx.empty:
        fx = fx[(fx.kickoff >= now - timedelta(hours=1)) & (fx.kickoff <= horizon)]
        for r in fx.to_dict("records"):
            if r["league"] in models:
                rows.append(r)
    have = {(r["league"], norm(r["home"])) for r in rows}
    # uzupełnienie z football-data.org (np. kolejka w tygodniu, której nie ma jeszcze w pliku)
    for lg in list(C.DOMESTIC) + ["UCL"]:
        comp = C.LEAGUES[lg].get("fdorg")
        if not comp:
            continue
        for m in D.fdorg_matches(comp, now.date().isoformat(), horizon.date().isoformat()):
            if m["status"] not in ("SCHEDULED", "TIMED") or not (now - timedelta(hours=1) <= m["kickoff"] <= horizon):
                continue
            if lg != "UCL":
                mt = Matcher(models[lg].teams) if lg in models else None
                h = mt.match(m["home_full"]) or mt.match(m["home"]) if mt else None
                a = mt.match(m["away_full"]) or mt.match(m["away"]) if mt else None
                if not h or not a or (lg, norm(h)) in have:
                    continue
                rows.append(dict(league=lg, kickoff=m["kickoff"], home=h, away=a))
            else:
                rows.append(dict(league="UCL", kickoff=m["kickoff"], home=m["home_full"], away=m["away_full"],
                                 short_home=m["home"], short_away=m["away"],
                                 home_id=m["home_id"], away_id=m["away_id"]))
    # Transfermarkt jako terminarz zapasowy dla wszystkich lig krajowych (jedyny dla Ekstraklasy,
    # której nie ma w darmowym football-data.org; ClubElo wyłączyło API Fixtures)
    have = {(r["league"], norm(r["home"])) for r in rows}
    for lg in models:
        cfg = C.LEAGUES[lg]
        if not cfg.get("tm"):
            continue
        try:
            tf = D.tm_fixtures(*cfg["tm"])
        except Exception as e:  # noqa: BLE001
            log.warning("terminarz Transfermarkt %s: %s", lg, e)
            continue
        if tf.empty:
            continue
        tf = tf[tf.hg.isna() & (tf.kickoff >= now - timedelta(hours=1)) & (tf.kickoff <= horizon)]
        mt = Matcher(models[lg].teams)
        for r in tf.itertuples():
            h, a = mt.match(r.home), mt.match(r.away)
            if not h or not a:
                log.warning("terminarz %s: nie dopasowano %s – %s", lg, r.home, r.away)
                continue
            if (lg, norm(h)) in have:
                continue
            rows.append(dict(league=lg, kickoff=r.kickoff, home=h, away=a, time_unknown=r.time_unknown))
    # kursy z The Odds API (nadpisują średnie z pliku, bo są świeższe)
    for lg in {r["league"] for r in rows}:
        evs = D.odds_api(lg)
        if not evs:
            continue
        names = [r["home"] for r in rows if r["league"] == lg] + [r["away"] for r in rows if r["league"] == lg]
        mt = Matcher(names)
        for ev in evs:
            h, a = mt.match(ev["home"]), mt.match(ev["away"])
            for r in rows:
                if r["league"] == lg and r["home"] == h and r["away"] == a:
                    for k, v in ev.items():
                        if k.startswith(("odds_", "max_", "pin_")) and v == v:
                            r[k] = v
                    r["n_books"] = ev["n_books"]
    log.info("Mecze w horyzoncie: %d", len(rows))
    return rows


def rest_days(hist, lg, team, kickoff):
    df = hist.get(lg)
    if df is None:
        return None
    prev = df[((df.home == team) | (df.away == team)) & (df.date < pd.Timestamp(kickoff).tz_localize(None))]
    return int((pd.Timestamp(kickoff).tz_localize(None) - prev.date.max()).days) if len(prev) else None


def analyse(now=None):
    now = now or datetime.now(timezone.utc)
    hist, models = load_history()
    fixtures = gather_fixtures(hist, models, now)
    team_cc = {}
    if any(f["league"] == "UCL" for f in fixtures):
        team_cc = {t["id"]: t["country"] for t in D.fdorg_teams("CL")}
    ucl_ids = {f[k] for f in fixtures if f["league"] == "UCL" for k in ("home_id", "away_id")}
    elo_map, elo_df = elo_lookup(models, {team_cc[i] for i in ucl_ids if team_cc.get(i)})
    bridge = fit_elo_bridge(models, elo_map, D.ELO_PROBS if any(f["league"] == "UCL" for f in fixtures) else None)
    ucl_strength = UclStrength(models, elo_map, elo_df, team_cc)
    news_items = N.fetch_all()

    absences = {}
    for lg in {f["league"] for f in fixtures if f["league"] in models}:
        absences[lg] = I.league_absences(lg, current_teams(hist, lg))

    matches = []
    for f in fixtures:
        lg = f["league"]
        home, away = f["home"], f["away"]
        info = {}
        if lg in models:
            m = models[lg]
            lh, la = m.lambdas(home, away)
            rho = m.rho
            info["source"] = "Dixon-Coles (gole + xG)" if C.LEAGUES[lg].get("us") else "Dixon-Coles (gole)"
            info["unknown"] = [t for t in (home, away) if t not in m.att]
        else:  # LM -> most Elo
            eh, sh = ucl_strength(f.get("home_id"), home, f.get("short_home", home))
            ea, sa = ucl_strength(f.get("away_id"), away, f.get("short_away", away))
            if eh is None or ea is None:
                log.warning("LM: brak Elo dla %s – pomijam mecz %s – %s",
                            " i ".join(n for n, e in ((home, eh), (away, ea)) if e is None), home, away)
                continue
            lh, la = bridge.lambdas(eh, ea)
            rho = bridge.rho
            info["source"] = f"Elo {eh:.0f} vs {ea:.0f} ({sh}; {sa})"
        ab_h = absences.get(lg, {}).get(home)
        ab_a = absences.get(lg, {}).get(away)
        lh2, la2, adj = I.adjust_lambdas(lh, la, ab_h, ab_a)
        mk = markets(score_matrix(lh2, la2, rho))
        top_scores = mk.pop("_top_scores")
        mid = match_id(lg, f["kickoff"], home, away)
        pm, _, _ = P.market_view({k: P._clean(f.get(k)) for k in P.ODDS_MARKETS.values()})
        matches.append(dict(
            id=mid, league=lg, league_name=C.LEAGUES[lg]["name"], flag=C.LEAGUES[lg]["flag"],
            kickoff=pd.Timestamp(f["kickoff"]).isoformat(), time_unknown=f.get("time_unknown", False),
            home=home, away=away, lambdas=[round(lh2, 3), round(la2, 3)],
            lambdas_raw=[round(lh, 3), round(la, 3)], injury_adj=adj,
            probs={k: round(v, 4) for k, v in mk.items()}, top_scores=[(round(p, 3), s) for p, s in top_scores],
            market_probs={k: round(float(v), 4) for k, v in pm.items()} or None,
            **{k: f.get(k) for k in ("odds_h", "odds_d", "odds_a", "odds_o25", "odds_u25",
                                       "max_h", "max_d", "max_a", "pin_h", "pin_d", "pin_a", "n_books")
               if f.get(k) == f.get(k) and f.get(k) is not None},
            absences=dict(home=(ab_h or {}).get("players", [])[:8], away=(ab_a or {}).get("players", [])[:8]),
            news=dict(home=N.for_team(news_items, f.get("short_home", home)),
                      away=N.for_team(news_items, f.get("short_away", away))),
            rest=dict(home=rest_days(hist, lg, home, f["kickoff"]), away=rest_days(hist, lg, away, f["kickoff"])),
            **info))
    matches.sort(key=lambda m: m["kickoff"])
    result = P.build(matches)
    result["generated"] = now.isoformat()
    result["models"] = {lg: dict(n=m.n_matches, home_adv=round(m.home, 3), rho=round(m.rho, 3),
                                 avg_goals=round(m.avg_goals, 2), last=str(m.last_date.date()),
                                 table=sorted(((t, round(m.strength(t), 3)) for t in current_teams(hist, lg)),
                                              key=lambda x: -x[1]))
                        for lg, m in models.items()}
    result["bridge_k"] = round(bridge.k, 5)
    return result, hist


# ---------------------------------------------------------------------------
# Wyniki do rozliczeń
# ---------------------------------------------------------------------------
def collect_results(pending_ids, hist=None):
    """{match_id: (hg, ag)} dla meczów oczekujących na rozliczenie."""
    if not pending_ids:
        return {}
    out = {}
    leagues = {pid.split(":")[0] for pid in pending_ids}
    now = datetime.now(timezone.utc)
    for lg in leagues:
        comp = C.LEAGUES.get(lg, {}).get("fdorg")
        if comp:
            for m in D.fdorg_matches(comp, (now - timedelta(days=5)).date().isoformat(), now.date().isoformat()):
                if m["status"] == "FINISHED" and m["hg"] is not None:
                    for nm in ((m["home_full"], m["away_full"]), (m["home"], m["away"])):
                        out[match_id(lg, m["kickoff"], *nm)] = (int(m["hg"]), int(m["ag"]))
        if lg in C.DOMESTIC:
            df = (hist or {}).get(lg)
            if df is None:
                df = D.fdcuk_results(lg)
            for r in df[df.date >= pd.Timestamp(now.date()) - pd.Timedelta(days=7)].dropna(subset=["hg"]).itertuples():
                out[match_id(lg, r.date, r.home, r.away)] = (int(r.hg), int(r.ag))
    # dopasowanie z tolerancją ±1 dzień (mecze po północy UTC)
    res = {}
    for pid in pending_ids:
        if pid in out:
            res[pid] = out[pid]
            continue
        lg, day, teams = pid.split(":", 2)
        for dd in (-1, 1):
            alt = f"{lg}:{(pd.Timestamp(day) + pd.Timedelta(days=dd)).strftime('%Y-%m-%d')}:{teams}"
            if alt in out:
                res[pid] = out[alt]
                break
        else:  # nazwy LM z różnych źródeł mogą się różnić -> fuzzy po tym samym dniu
            cands = {k: v for k, v in out.items() if k.startswith(f"{lg}:{day}:")}
            mt = Matcher([k.split(":", 2)[2] for k in cands])
            hit = mt.match(teams.replace("_", " "), cutoff=88)
            if hit:
                res[pid] = cands[f"{lg}:{day}:{hit}"]
    return res
