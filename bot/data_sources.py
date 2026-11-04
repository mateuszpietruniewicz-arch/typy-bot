"""Pobieranie danych z darmowych źródeł. Każde źródło jest opcjonalne:
jeśli coś padnie, bot loguje ostrzeżenie i działa dalej na tym, co ma."""
import io
import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import requests

from . import config as C
from .names import Matcher

log = logging.getLogger("data")
S = requests.Session()
S.headers.update({"User-Agent": C.UA, "Accept-Language": "en-GB,en;q=0.9,pl;q=0.8"})


def get(url, *, headers=None, params=None, cache_h=0, tries=3, binary=False):
    """GET z ponawianiem i prostym cache na dysku (żeby nie męczyć źródeł)."""
    C.CACHE.mkdir(exist_ok=True)
    key = re.sub(r"[^A-Za-z0-9]+", "_", url + json.dumps(params or {}, sort_keys=True))[-180:]
    path = C.CACHE / key
    if cache_h and path.exists() and time.time() - path.stat().st_mtime < cache_h * 3600:
        return path.read_bytes() if binary else path.read_text(encoding="utf-8", errors="replace")
    last = None
    for i in range(tries):
        try:
            r = S.get(url, headers=headers, params=params, timeout=30)
            if r.status_code == 200:
                if cache_h:
                    path.write_bytes(r.content)
                return r.content if binary else r.content.decode(r.encoding or "utf-8", errors="replace")
            last = f"HTTP {r.status_code}"
            if r.status_code in (401, 403, 404):
                break
        except requests.RequestException as e:  # noqa: PERF203
            last = str(e)
        time.sleep(2 * (i + 1))
    raise RuntimeError(f"{url}: {last}")


def season_codes(n=C.SEASONS_BACK, today=None):
    today = today or datetime.now(timezone.utc)
    y = today.year if today.month >= 7 else today.year - 1
    return [f"{(y - i) % 100:02d}{(y - i + 1) % 100:02d}" for i in range(n)][::-1]


def _num(df, *cols):
    for c in cols:
        if c in df.columns:
            return pd.to_numeric(df[c], errors="coerce")
    return pd.Series(np.nan, index=df.index)


def _odds_cols(df):
    return dict(
        odds_h=_num(df, "AvgCH", "AvgH", "BbAvH", "PSCH", "PSH", "B365H"),
        odds_d=_num(df, "AvgCD", "AvgD", "BbAvD", "PSCD", "PSD", "B365D"),
        odds_a=_num(df, "AvgCA", "AvgA", "BbAvA", "PSCA", "PSA", "B365A"),
        odds_o25=_num(df, "AvgC>2.5", "Avg>2.5", "BbAv>2.5", "PC>2.5", "B365>2.5"),
        odds_u25=_num(df, "AvgC<2.5", "Avg<2.5", "BbAv<2.5", "PC<2.5", "B365<2.5"),
    )


# ---------------------------------------------------------------------------
# football-data.co.uk  (wyniki + kursy rynkowe, bez klucza)
# ---------------------------------------------------------------------------
def fdcuk_results(league):
    cfg = C.LEAGUES[league]
    frames = []
    if cfg.get("fdcuk"):
        for sc in season_codes():
            url = f"https://www.football-data.co.uk/mmz4281/{sc}/{cfg['fdcuk']}.csv"
            try:
                raw = get(url, cache_h=6)
            except RuntimeError as e:
                log.warning("fdcuk %s: %s", league, e)
                continue
            df = pd.read_csv(io.StringIO(raw), on_bad_lines="skip")
            if "HomeTeam" not in df:
                continue
            out = pd.DataFrame(dict(
                league=league,
                date=pd.to_datetime(df["Date"], dayfirst=True, errors="coerce", format="mixed"),
                home=df["HomeTeam"], away=df["AwayTeam"],
                hg=_num(df, "FTHG"), ag=_num(df, "FTAG"),
                hs=_num(df, "HST"), as_=_num(df, "AST"),  # strzały celne
                **_odds_cols(df)))
            frames.append(out)
    elif cfg.get("fdcuk_extra"):
        url = f"https://www.football-data.co.uk/new/{cfg['fdcuk_extra']}.csv"
        try:
            df = pd.read_csv(io.StringIO(get(url, cache_h=6)), on_bad_lines="skip")
            first = int("20" + season_codes()[0][:2])
            df["_y"] = df["Season"].astype(str).str[:4].astype(int, errors="ignore")
            df = df[pd.to_numeric(df["_y"], errors="coerce") >= first]
            frames.append(pd.DataFrame(dict(
                league=league,
                date=pd.to_datetime(df["Date"], dayfirst=True, errors="coerce", format="mixed"),
                home=df["Home"], away=df["Away"], hg=_num(df, "HG"), ag=_num(df, "AG"),
                **_odds_cols(df))))
        except Exception as e:  # noqa: BLE001
            log.warning("fdcuk %s: %s", league, e)
    if not frames:
        return pd.DataFrame()
    res = pd.concat(frames, ignore_index=True).dropna(subset=["date", "home", "away"])
    return res.sort_values("date").reset_index(drop=True)


def fdcuk_fixtures():
    """Nadchodzące mecze z kursami rynkowymi (top 5 + ligi 'extra')."""
    out = []
    code2lg = {v["fdcuk"]: k for k, v in C.LEAGUES.items() if v.get("fdcuk")}
    try:
        df = pd.read_csv(io.StringIO(get("https://www.football-data.co.uk/fixtures.csv", cache_h=3)),
                         on_bad_lines="skip")
        df.columns = [c.lstrip("﻿") for c in df.columns]
        df = df[df["Div"].isin(code2lg)]
        t = df["Time"] if "Time" in df else "15:00"
        ko = pd.to_datetime(df["Date"] + " " + t, dayfirst=True, errors="coerce", format="mixed")
        out.append(pd.DataFrame(dict(
            league=df["Div"].map(code2lg),
            kickoff=ko.dt.tz_localize("Europe/London", ambiguous="NaT", nonexistent="NaT").dt.tz_convert("UTC"),
            home=df["HomeTeam"], away=df["AwayTeam"], **_odds_cols(df))))
    except Exception as e:  # noqa: BLE001
        log.warning("fdcuk fixtures: %s", e)
    try:
        df = pd.read_csv(io.StringIO(get("https://www.football-data.co.uk/new_league_fixtures.csv",
                                         cache_h=3)), on_bad_lines="skip")
        df.columns = [c.lstrip("﻿") for c in df.columns]
        df = df[df["Country"].astype(str).str.lower() == "poland"]
        t = df["Time"] if "Time" in df else "18:00"
        ko = pd.to_datetime(df["Date"] + " " + t, dayfirst=True, errors="coerce", format="mixed")
        out.append(pd.DataFrame(dict(
            league="EKSTRA",
            kickoff=ko.dt.tz_localize("Europe/London", ambiguous="NaT", nonexistent="NaT").dt.tz_convert("UTC"),
            home=df["Home"], away=df["Away"], **_odds_cols(df))))
    except Exception as e:  # noqa: BLE001
        log.warning("fdcuk extra fixtures: %s", e)
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


# ---------------------------------------------------------------------------
# football-data.org  (terminarz + wyniki, darmowy klucz; jedyne źródło LM)
# ---------------------------------------------------------------------------
def fdorg_matches(comp, date_from, date_to):
    if not C.FDORG_KEY:
        return []
    url = f"https://api.football-data.org/v4/competitions/{comp}/matches"
    try:
        js = json.loads(get(url, headers={"X-Auth-Token": C.FDORG_KEY},
                            params={"dateFrom": date_from, "dateTo": date_to}, cache_h=1))
    except Exception as e:  # noqa: BLE001
        log.warning("football-data.org %s: %s", comp, e)
        return []
    time.sleep(6.5)  # limit 10 zapytań/min
    out = []
    for m in js.get("matches", []):
        ft = (m.get("score") or {}).get("fullTime") or {}
        out.append(dict(
            id=m["id"], kickoff=pd.Timestamp(m["utcDate"]), status=m["status"],
            home=m["homeTeam"].get("shortName") or m["homeTeam"]["name"],
            away=m["awayTeam"].get("shortName") or m["awayTeam"]["name"],
            home_full=m["homeTeam"]["name"], away_full=m["awayTeam"]["name"],
            hg=ft.get("home"), ag=ft.get("away"), stage=m.get("stage")))
    return out


def ucl_history():
    """Wyniki LM z ostatnich sezonów (do walidacji mostu Elo)."""
    if not C.FDORG_KEY:
        return pd.DataFrame()
    now = datetime.now(timezone.utc)
    rows = fdorg_matches("CL", (now - timedelta(days=120)).date().isoformat(), now.date().isoformat())
    df = pd.DataFrame([r for r in rows if r["status"] == "FINISHED"])
    if df.empty:
        return df
    df["league"] = "UCL"
    df["date"] = df["kickoff"].dt.tz_convert(None)
    return df[["league", "date", "home", "away", "hg", "ag"]]


# ---------------------------------------------------------------------------
# ClubElo (bez klucza) – ranking siły wszystkich klubów w Europie
# ---------------------------------------------------------------------------
def clubelo_ratings(day=None):
    day = day or datetime.now(timezone.utc).date().isoformat()
    try:
        df = pd.read_csv(io.StringIO(get(f"http://api.clubelo.com/{day}", cache_h=12)))
        return df[["Club", "Country", "Level", "Elo"]]
    except Exception as e:  # noqa: BLE001
        log.warning("clubelo: %s", e)
        return pd.DataFrame(columns=["Club", "Country", "Level", "Elo"])


def clubelo_fixtures():
    """Nadchodzące mecze z rozkładem wyników wg ClubElo (zawiera też puchary)."""
    try:
        df = pd.read_csv(io.StringIO(get("http://api.clubelo.com/Fixtures", cache_h=6)))
    except Exception as e:  # noqa: BLE001
        log.warning("clubelo fixtures: %s", e)
        return pd.DataFrame()
    return df


# ---------------------------------------------------------------------------
# The Odds API (darmowy klucz, 500 kredytów/mies.) – kursy wielu bukmacherów
# ---------------------------------------------------------------------------
def odds_api(league):
    if not C.ODDS_API_KEY or not C.LEAGUES[league].get("odds"):
        return []
    url = f"https://api.the-odds-api.com/v4/sports/{C.LEAGUES[league]['odds']}/odds"
    try:
        js = json.loads(get(url, params=dict(apiKey=C.ODDS_API_KEY, regions="eu",
                                             markets="h2h,totals", oddsFormat="decimal"),
                            cache_h=3))
    except Exception as e:  # noqa: BLE001
        log.warning("odds-api %s: %s", league, e)
        return []
    out = []
    for ev in js:
        h2h = {"h": [], "d": [], "a": []}
        tot = {"o25": [], "u25": []}
        best = {}
        books = []
        for bk in ev.get("bookmakers", []):
            books.append(bk["key"])
            for mk in bk.get("markets", []):
                for o in mk.get("outcomes", []):
                    if mk["key"] == "h2h":
                        k = "h" if o["name"] == ev["home_team"] else "a" if o["name"] == ev["away_team"] else "d"
                        h2h[k].append(o["price"])
                        if bk["key"] == "pinnacle":
                            best["pin_" + k] = o["price"]
                    elif mk["key"] == "totals" and abs(o.get("point", 0) - 2.5) < 1e-6:
                        k = "o25" if o["name"] == "Over" else "u25"
                        tot[k].append(o["price"])
        row = dict(kickoff=pd.Timestamp(ev["commence_time"]), home=ev["home_team"], away=ev["away_team"],
                   n_books=len(books), **best)
        for k, v in {**h2h, **tot}.items():
            row["odds_" + k] = float(np.mean(v)) if v else np.nan
            row["max_" + k] = float(np.max(v)) if v else np.nan
        out.append(row)
    return out


# ---------------------------------------------------------------------------
# Understat (bez klucza) – xG dla top 5 lig
# ---------------------------------------------------------------------------
def understat_xg(league):
    us = C.LEAGUES[league].get("us")
    if not us:
        return pd.DataFrame()
    rows = []
    for sc in season_codes():
        year = 2000 + int(sc[:2])
        try:
            js = _understat_season(us, year)
        except Exception as e:  # noqa: BLE001
            log.warning("understat %s %s: %s", league, year, e)
            continue
        for m in js:
            if not m.get("isResult"):
                continue
            rows.append(dict(date=pd.Timestamp(m["datetime"]).normalize(),
                             us_home=m["h"]["title"], us_away=m["a"]["title"],
                             hxg=float(m["xG"]["h"]), axg=float(m["xG"]["a"])))
    return pd.DataFrame(rows)


def _understat_season(us, year):
    # nowsze API (JSON)
    try:
        raw = get(f"https://understat.com/getLeagueData/{us}/{year}", cache_h=12,
                  headers={"X-Requested-With": "XMLHttpRequest",
                           "Referer": f"https://understat.com/league/{us}/{year}"})
        js = json.loads(raw)
        return js.get("dates", js)
    except Exception:  # noqa: BLE001
        pass
    # starsze: JSON zaszyty w HTML
    html = get(f"https://understat.com/league/{us}/{year}", cache_h=12)
    m = re.search(r"datesData\s*=\s*JSON\.parse\('(.+?)'\)", html)
    if not m:
        raise RuntimeError("brak datesData")
    return json.loads(m.group(1).encode().decode("unicode_escape"))


def attach_xg(results, league):
    xg = understat_xg(league)
    if xg.empty or results.empty:
        results["hxg"] = np.nan
        results["axg"] = np.nan
        return results
    mt = Matcher(pd.concat([results.home, results.away]).unique())
    xg["home"] = xg.us_home.map(mt.match)
    xg["away"] = xg.us_away.map(mt.match)
    xg = xg.dropna(subset=["home", "away"])
    r = results.copy()
    r["_d"] = r.date.dt.normalize()
    m = r.merge(xg.rename(columns={"date": "_d"})[["_d", "home", "away", "hxg", "axg"]],
                on=["_d", "home", "away"], how="left")
    # mecz po północy: druga próba z datą -1 dnia
    miss = m.hxg.isna()
    if miss.any():
        xg2 = xg.assign(_d=xg.date - pd.Timedelta(days=1))
        alt = r[miss.values].merge(xg2[["_d", "home", "away", "hxg", "axg"]], on=["_d", "home", "away"], how="left")
        m.loc[miss.values, ["hxg", "axg"]] = alt[["hxg", "axg"]].values
    log.info("xG %s: %d/%d meczów", league, m.hxg.notna().sum(), len(m))
    return m.drop(columns="_d")
