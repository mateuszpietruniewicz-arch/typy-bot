"""Kontuzje i zawieszenia: Transfermarkt (bez klucza) + API-Football (opcjonalnie).

Wpływ braku zawodnika liczymy przez jego wartość rynkową jako przybliżenie
ważności: suma wartości nieobecnych / wartość kadry = 'brakujący udział'.
Długie kontuzje (> 45 dni) model już częściowo 'widzi' w wynikach, więc ważą mniej.
"""
import logging
import re
from datetime import datetime, timezone

import pandas as pd
from bs4 import BeautifulSoup

from . import config as C
from .data_sources import get
from .names import Matcher

log = logging.getLogger("injuries")
TM = "https://www.transfermarkt.com"


def _money(txt):
    """'€45.00m' / '€800k' / '45,00 mln €' -> euro."""
    t = (txt or "").lower().replace(",", ".")
    m = re.search(r"([\d.]+)\s*(bn|b|mln|m|k|th|tys)?", t)
    if not m:
        return 0.0
    try:
        v = float(m.group(1))
    except ValueError:
        return 0.0
    mult = {"bn": 1e9, "b": 1e9, "m": 1e6, "mln": 1e6, "k": 1e3, "th": 1e3, "tys": 1e3}.get(m.group(2) or "", 1)
    return v * mult


def _date(txt):
    for fmt in ("%b %d, %Y", "%d/%m/%Y", "%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(txt.strip(), fmt).date()
        except (ValueError, AttributeError):
            continue
    return None


def tm_squad_values(slug, code):
    html = get(f"{TM}/{slug}/startseite/wettbewerb/{code}", cache_h=72)
    soup = BeautifulSoup(html, "lxml")
    out = {}
    tab = soup.select_one("table.items")
    if not tab:
        raise RuntimeError("brak tabeli klubów")
    for tr in tab.select("tbody > tr"):
        a = tr.select_one("td.hauptlink a[href*='/startseite/verein/']")
        vals = [td.get_text(" ", strip=True) for td in tr.select("td.rechts")]
        if a and vals:
            out[a.get("title") or a.get_text(strip=True)] = _money(vals[-1])
    return out


def tm_injuries(slug, code):
    html = get(f"{TM}/{slug}/verletztespieler/wettbewerb/{code}", cache_h=6)
    soup = BeautifulSoup(html, "lxml")
    tab = soup.select_one("table.items")
    if not tab:
        raise RuntimeError("brak tabeli kontuzji")
    rows = []
    # kolumny: Zawodnik/pozycja | Klub | Uraz | until (przewidywany powrót) | Wartość
    for tr in tab.select("tbody > tr"):
        if not {"odd", "even"} & set(tr.get("class") or []):
            continue
        name = tr.select_one("td.hauptlink a")
        club = tr.select_one("a[href*='/verein/']")
        reason = tr.select_one("td.links")
        tds = tr.find_all("td", recursive=False)
        until = _date(tds[-2].get_text(" ", strip=True)) if len(tds) >= 2 else None
        value = _money(tds[-1].get_text(" ", strip=True)) if tds else 0.0
        rows.append(dict(
            player=name.get_text(strip=True) if name else "?",
            club=(club.get("title") or club.get_text(strip=True)) if club else None,
            reason=reason.get_text(" ", strip=True) if reason else "",
            since=None, until=until, value=value, src="Transfermarkt"))
    return [r for r in rows if r["club"]]


def api_football_injuries(league_name):
    """Opcjonalnie: API-Football (darmowy plan ~100 zapytań/dzień)."""
    if not C.API_FOOTBALL_KEY:
        return []
    ids = {"EPL": 39, "LALIGA": 140, "SERIEA": 135, "BUNDES": 78, "LIGUE1": 61, "EKSTRA": 106, "UCL": 2}
    lid = ids.get(league_name)
    if not lid:
        return []
    now = datetime.now(timezone.utc)
    season = now.year if now.month >= 7 else now.year - 1
    import json
    try:
        js = json.loads(get("https://v3.football.api-sports.io/injuries",
                            headers={"x-apisports-key": C.API_FOOTBALL_KEY},
                            params={"league": lid, "season": season, "date": now.date().isoformat()},
                            cache_h=6))
        if js.get("errors"):
            log.warning("api-football: %s", js["errors"])
        return [dict(player=x["player"]["name"], club=x["team"]["name"],
                     reason=f'{x["player"].get("type", "")}: {x["player"].get("reason", "")}'.strip(": "),
                     since=None, until=None, value=0.0, src="API-Football")
                for x in js.get("response", [])]
    except Exception as e:  # noqa: BLE001
        log.warning("api-football %s: %s", league_name, e)
        return []


def league_absences(league, canonical_teams):
    """-> {drużyna: dict(players=[...], share=float)}"""
    cfg = C.LEAGUES[league]
    mt = Matcher(canonical_teams)
    rows, squads = [], {}
    if cfg.get("tm"):
        try:
            squads = {mt.match(k): v for k, v in tm_squad_values(*cfg["tm"]).items() if mt.match(k)}
            rows += tm_injuries(*cfg["tm"])
        except Exception as e:  # noqa: BLE001
            log.warning("Transfermarkt %s: %s", league, e)
    rows += api_football_injuries(league)
    today = datetime.now(timezone.utc).date()
    out = {}
    seen = set()
    for r in rows:
        team = mt.match(r["club"])
        if not team:
            continue
        key = (team, r["player"].lower().split()[-1] if r["player"] else "")
        if key in seen:
            continue
        seen.add(key)
        days_out = (today - r["since"]).days if r.get("since") else None
        days_left = (r["until"] - today).days if r.get("until") else None
        # długie absencje model już częściowo „widzi” w wynikach -> mniejsza waga
        long_out = (days_out is not None and days_out > 45) or (days_left is not None and days_left > 45)
        weight = 0.4 if long_out else 1.0
        r = {**r, "days_out": days_out, "weight": weight,
             "since": r["since"].isoformat() if r.get("since") else None,
             "until": r["until"].isoformat() if r.get("until") else None}
        out.setdefault(team, {"players": [], "share": 0.0})["players"].append(r)
    for team, v in out.items():
        squad = squads.get(team) or 0
        miss = sum(p["value"] * p["weight"] for p in v["players"])
        if squad > 0:
            v["share"] = min(miss / squad, 0.6)
        else:  # brak wartości -> ostrożnie: 2.5% za zawodnika
            v["share"] = min(0.025 * sum(p["weight"] for p in v["players"]), 0.3)
        v["players"].sort(key=lambda p: -p["value"])
    log.info("Absencje %s: %d drużyn, %d zawodników", league, len(out), sum(len(v["players"]) for v in out.values()))
    return out


def adjust_lambdas(lh, la, abs_h, abs_a):
    """Korekta oczekiwanych goli o braki kadrowe. Zwraca (lh, la, opis)."""
    sh = (abs_h or {}).get("share", 0.0)
    sa = (abs_a or {}).get("share", 0.0)
    fh_att = 1 - min(C.INJURY_K_ATT * sh, C.INJURY_CAP)
    fa_att = 1 - min(C.INJURY_K_ATT * sa, C.INJURY_CAP)
    fh_def = 1 + min(C.INJURY_K_DEF * sh, C.INJURY_CAP)
    fa_def = 1 + min(C.INJURY_K_DEF * sa, C.INJURY_CAP)
    new_lh = lh * fh_att * fa_def
    new_la = la * fa_att * fh_def
    return new_lh, new_la, dict(share_h=round(sh, 3), share_a=round(sa, 3),
                                d_lh=round(new_lh - lh, 3), d_la=round(new_la - la, 3))
