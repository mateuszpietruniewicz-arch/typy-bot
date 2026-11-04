"""FotMob (bez klucza, działa też z GitHub Actions): składy przewidywane i potwierdzone,
niedostępni zawodnicy (kontuzje/zawieszenia), minuty z rozegranych meczów, terminarz drużyn.

Szczegóły rozegranych meczów się nie zmieniają -> cache na stałe w .cache/.
"""
import json
import logging
import time
from datetime import datetime, timezone

import pandas as pd

from . import config as C
from .data_sources import LAST_HEADERS, get

log = logging.getLogger("fotmob")
BASE = "https://www.fotmob.com/api/data"
FOREVER = 24 * 365 * 5
_last_call = [0.0]


def _get(path, params=None, cache_h=1):
    """Zapytanie z grzecznym odstępem (~0.4 s) między wywołaniami sieciowymi."""
    LAST_HEADERS.pop("www.fotmob.com", None)
    wait = 0.4 - (time.time() - _last_call[0])
    if wait > 0:
        time.sleep(wait)
    raw = get(f"{BASE}/{path}", params=params, cache_h=cache_h, tries=2)
    if "www.fotmob.com" in LAST_HEADERS:
        _last_call[0] = time.time()
    return json.loads(raw)


# --- listy meczów --------------------------------------------------------------------------
def day_matches(day):
    """Mecze naszych lig danego dnia (data jak w FotMob, YYYY-MM-DD)."""
    fm2lg = {v["fotmob"]: k for k, v in C.LEAGUES.items() if v.get("fotmob")}
    d = pd.Timestamp(day)
    past = d.date() < datetime.now(timezone.utc).date()
    js = _get("matches", {"date": d.strftime("%Y%m%d")}, cache_h=FOREVER if past else 0.5)
    out = []
    for lg in js.get("leagues", []):
        ours = fm2lg.get(lg.get("primaryId"))
        if not ours:
            continue
        for m in lg.get("matches", []):
            st = m.get("status") or {}
            out.append(dict(id=int(m["id"]), league=ours, kickoff=pd.Timestamp(st.get("utcTime")),
                            home_id=int(m["home"]["id"]), home=m["home"]["name"],
                            away_id=int(m["away"]["id"]), away=m["away"]["name"],
                            finished=bool(st.get("finished")), cancelled=bool(st.get("cancelled"))))
    return out


def league_season(league, season):
    """Wszystkie mecze ligi w sezonie ('2025/2026') – do backtestu."""
    fid = C.LEAGUES[league].get("fotmob")
    js = _get("leagues", {"id": fid, "season": season}, cache_h=24 * 7)
    out = []
    for m in (js.get("fixtures") or {}).get("allMatches", []):
        st = m.get("status") or {}
        out.append(dict(id=int(m["id"]), league=league, kickoff=pd.Timestamp(st.get("utcTime")),
                        home_id=int(m["home"]["id"]), home=m["home"]["name"],
                        away_id=int(m["away"]["id"]), away=m["away"]["name"],
                        finished=bool(st.get("finished"))))
    return out


def team_fixtures(team_id):
    """Terminarz drużyny ze wszystkich rozgrywek (liga, puchary, Europa)."""
    js = _get("teams", {"id": team_id}, cache_h=12)
    out = []
    for f in ((js.get("fixtures") or {}).get("allFixtures") or {}).get("fixtures", []):
        st = f.get("status") or {}
        out.append(dict(id=int(f["id"]), kickoff=pd.Timestamp(st.get("utcTime")),
                        finished=bool(st.get("finished")), cancelled=bool(st.get("cancelled")),
                        tournament=(f.get("tournament") or {}).get("name", ""),
                        league_id=(f.get("tournament") or {}).get("leagueId"),
                        home_id=int(f["home"]["id"]), away_id=int(f["away"]["id"]),
                        home=f["home"]["name"], away=f["away"]["name"]))
    return sorted(out, key=lambda x: x["kickoff"])


# --- szczegóły meczu -----------------------------------------------------------------------
def match_details(mid, finished=False, cache_h=None):
    if cache_h is None:
        cache_h = FOREVER if finished else 0.2
    return _get("matchDetails", {"matchId": mid}, cache_h=cache_h)


def _player(p):
    return dict(id=int(p["id"]), name=p.get("name", "?"), value=float(p.get("marketValue") or 0))


def lineups(md):
    """-> {'type': 'predicted'|'standard'|..., 'home'/'away': dict(team_id, name, starters, unavailable)}"""
    lu = ((md or {}).get("content") or {}).get("lineup") or {}
    out = {"type": lu.get("lineupType")}
    for side, key in (("home", "homeTeam"), ("away", "awayTeam")):
        t = lu.get(key) or {}
        out[side] = dict(
            team_id=t.get("id"), name=t.get("name"),
            starters=[_player(p) for p in t.get("starters") or []],
            unavailable=[{**_player(p), "type": (p.get("unavailability") or {}).get("type", ""),
                          "expected_return": (p.get("unavailability") or {}).get("expectedReturn", "")}
                         for p in t.get("unavailable") or []])
    return out


def confirmed(lu):
    """Skład potwierdzony (nie przewidywany) i pełny."""
    # "predicted" = prognoza FotMob, "lastStarting11" = zastępczo ostatnia XI; oficjalny skład = "standard"
    return (lu.get("type") == "standard"
            and all(len(lu[s]["starters"]) == 11 for s in ("home", "away")))


def minutes_played(md):
    """{team_id: {player_id: (minuty, nazwisko, wartość)}} z rozegranego meczu."""
    lu = ((md or {}).get("content") or {}).get("lineup") or {}
    out = {}
    for key in ("homeTeam", "awayTeam"):
        t = lu.get(key) or {}
        if not t.get("id"):
            continue
        mins = {}
        for p in t.get("starters") or []:
            ev = ((p.get("performance") or {}).get("substitutionEvents") or [])
            off = next((e["time"] for e in ev if e.get("type") == "subOut"), 90)
            mins[int(p["id"])] = (min(off, 90), p.get("name"), float(p.get("marketValue") or 0))
        for p in t.get("subs") or []:
            ev = ((p.get("performance") or {}).get("substitutionEvents") or [])
            on = next((e["time"] for e in ev if e.get("type") == "subIn"), None)
            if on is not None:
                off = next((e["time"] for e in ev if e.get("type") == "subOut"), 90)
                mins[int(p["id"])] = (max(min(off, 90) - on, 1), p.get("name"), float(p.get("marketValue") or 0))
        out[int(t["id"])] = mins
    return out


MINUTES_DIR = C.CACHE / "fm_minutes"


def match_minutes(mid):
    """Minuty z rozegranego meczu w zwięzłej postaci (~2 KB zamiast ~300 KB szczegółów) – cache na stałe."""
    MINUTES_DIR.mkdir(parents=True, exist_ok=True)
    f = MINUTES_DIR / f"{mid}.json"
    if f.exists():
        return {int(t): {int(p): tuple(v) for p, v in d.items()} for t, d in json.loads(f.read_text()).items()}
    mp = minutes_played(match_details(mid, cache_h=0))
    f.write_text(json.dumps({t: {p: list(v) for p, v in d.items()} for t, d in mp.items()}, ensure_ascii=False))
    return mp


def usual_xi(team_id, before, n=8, fixtures=None):
    """„Zwykła jedenastka”: 11 zawodników z największą liczbą minut w n ostatnich meczach
    (wszystkie rozgrywki) przed `before`. -> lista dict(id, name, value, minutes), liczba meczów."""
    fixtures = fixtures if fixtures is not None else team_fixtures(team_id)
    past = [f for f in fixtures if f["finished"] and not f["cancelled"] and f["kickoff"] < pd.Timestamp(before)]
    past = past[-n:]
    tot = {}
    used = 0
    for f in past:
        try:
            mp = match_minutes(f["id"]).get(int(team_id))
        except Exception as e:  # noqa: BLE001
            log.warning("fotmob mecz %s: %s", f["id"], e)
            continue
        if not mp:
            continue
        used += 1
        for pid, (mins, name, val) in mp.items():
            a = tot.setdefault(pid, dict(id=pid, name=name, value=val, minutes=0))
            a["minutes"] += mins
            a["value"] = val or a["value"]
    xi = sorted(tot.values(), key=lambda x: -x["minutes"])[:11]
    return xi, used


def lineup_change(xi_now, usual):
    """Porównanie składu (11 nazwisk z wartościami) ze zwykłą jedenastką.
    -> dict(delta=względna zmiana wartości XI, out=[...], in=[...])"""
    u_ids = {p["id"] for p in usual}
    n_ids = {p["id"] for p in xi_now}
    vu = sum(p["value"] for p in usual) or 1.0
    vn = sum(p["value"] for p in xi_now)
    return dict(delta=(vn - vu) / vu,
                out=[p for p in usual if p["id"] not in n_ids],
                into=[p for p in xi_now if p["id"] not in u_ids])


def schedule_info(fixtures, kickoff):
    """Zmęczenie (tylko informacyjnie): dni od ostatniego meczu, mecze w 14 dniach, mecz europejski w tygodniu."""
    ko = pd.Timestamp(kickoff)
    past = [f for f in fixtures if f["kickoff"] < ko - pd.Timedelta(hours=3) and not f["cancelled"]]
    nxt = [f for f in fixtures if f["kickoff"] > ko + pd.Timedelta(hours=3) and not f["cancelled"]]
    euro = ("Champions League", "Europa League", "Conference League")
    last = past[-1] if past else None
    return dict(
        rest_days=round((ko - last["kickoff"]).total_seconds() / 86400, 1) if last else None,
        last_tournament=last["tournament"] if last else None,
        games_14d=sum(1 for f in past if ko - f["kickoff"] <= pd.Timedelta(days=14)),
        euro_before=any(f["tournament"].startswith(euro) and ko - f["kickoff"] <= pd.Timedelta(days=4) for f in past),
        euro_after=any(f["tournament"].startswith(euro) and f["kickoff"] - ko <= pd.Timedelta(days=4) for f in nxt),
    )
