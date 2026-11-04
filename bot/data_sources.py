"""Pobieranie danych z darmowych źródeł. Każde źródło jest opcjonalne:
jeśli coś padnie, bot loguje ostrzeżenie i działa dalej na tym, co ma."""
import io
import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import numpy as np
import pandas as pd
import requests

from . import config as C
from .names import Matcher

log = logging.getLogger("data")
S = requests.Session()
S.headers.update({"User-Agent": C.UA, "Accept-Language": "en-GB,en;q=0.9,pl;q=0.8"})


LAST_HEADERS = {}  # host -> nagłówki ostatniej odpowiedzi z sieci (limity API)


def get(url, *, headers=None, params=None, cache_h=0, tries=3, binary=False):
    """GET z ponawianiem i prostym cache na dysku (żeby nie męczyć źródeł)."""
    C.CACHE.mkdir(exist_ok=True)
    key = re.sub(r"[^A-Za-z0-9]+", "_", url + json.dumps(params or {}, sort_keys=True))[-180:]
    path = C.CACHE / key
    if cache_h and path.exists() and time.time() - path.stat().st_mtime < cache_h * 3600:
        return path.read_bytes() if binary else path.read_bytes().decode("utf-8-sig", errors="replace")
    last = None
    for i in range(tries):
        try:
            r = S.get(url, headers=headers, params=params, timeout=30)
            LAST_HEADERS[urlparse(url).netloc] = r.headers
            if r.status_code == 429:  # limit zapytań – czekamy tyle, ile każe serwer
                wait = int(r.headers.get("X-RequestCounter-Reset") or r.headers.get("Retry-After") or 10 * (i + 1))
                log.warning("%s: limit zapytań, czekam %d s", urlparse(url).netloc, wait)
                time.sleep(min(wait + 1, 65))
                last = "HTTP 429"
                continue
            if r.status_code == 200:
                if cache_h:
                    path.write_bytes(r.content)
                return r.content if binary else _decode(r)
            last = f"HTTP {r.status_code}"
            if r.status_code in (401, 403, 404):
                break
        except requests.RequestException as e:  # noqa: PERF203
            last = str(e)
        time.sleep(2 * (i + 1))
    raise RuntimeError(f"{url}: {last}")


def _decode(r):
    """UTF-8 (z BOM lub bez), a jak się nie da – kodowanie z nagłówka / latin-1."""
    try:
        return r.content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return r.content.decode(r.encoding or "latin-1", errors="replace")


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
FDORG_HOST = "api.football-data.org"
_FD_LIMIT = {"available": None, "reset_at": 0.0}


def fdorg_get(path, params=None, cache_h=1):
    """Zapytanie do football-data.org z limitem czytanym z nagłówków
    X-Requests-Available-Minute / X-RequestCounter-Reset (zamiast stałego sleep)."""
    if _FD_LIMIT["available"] is not None and _FD_LIMIT["available"] <= 0:
        wait = _FD_LIMIT["reset_at"] - time.time()
        if wait > 0:
            log.info("football-data.org: wyczerpany limit na minutę, czekam %.0f s", wait)
            time.sleep(wait + 1)
    LAST_HEADERS.pop(FDORG_HOST, None)
    raw = get(f"https://{FDORG_HOST}/v4/{path}", headers={"X-Auth-Token": C.FDORG_KEY},
              params=params, cache_h=cache_h)
    h = LAST_HEADERS.get(FDORG_HOST)
    if h is not None:  # było zapytanie do sieci (nie z cache)
        try:
            _FD_LIMIT["available"] = int(h.get("X-Requests-Available-Minute"))
            _FD_LIMIT["reset_at"] = time.time() + int(h.get("X-RequestCounter-Reset") or 60)
        except (TypeError, ValueError):
            pass
    return json.loads(raw)


def fdorg_teams(comp):
    """Drużyny rozgrywek z krajem (area.code) – potrzebne do Elo w LM."""
    if not C.FDORG_KEY:
        return []
    try:
        js = fdorg_get(f"competitions/{comp}/teams", cache_h=24)
    except Exception as e:  # noqa: BLE001
        log.warning("football-data.org teams %s: %s", comp, e)
        return []
    return [dict(id=t["id"], name=t["name"], short=t.get("shortName") or t["name"],
                 country=country_code((t.get("area") or {}).get("code"))) for t in js.get("teams", [])]


def fdorg_matches(comp, date_from, date_to):
    if not C.FDORG_KEY:
        return []
    try:
        js = fdorg_get(f"competitions/{comp}/matches", params={"dateFrom": date_from, "dateTo": date_to})
    except Exception as e:  # noqa: BLE001
        log.warning("football-data.org %s: %s", comp, e)
        return []
    out = []
    for m in js.get("matches", []):
        ft = (m.get("score") or {}).get("fullTime") or {}
        out.append(dict(
            id=m["id"], kickoff=pd.Timestamp(m["utcDate"]), status=m["status"],
            home_id=m["homeTeam"].get("id"), away_id=m["awayTeam"].get("id"),
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
# Kody krajów ujednolicone do ISO-3 (jak elofootball.com / football-data.org);
# ClubElo i football-data.org mają kilka własnych skrótów.
_CC = {"GER": "DEU", "POR": "PRT", "NED": "NLD", "SUI": "CHE", "DEN": "DNK", "CRO": "HRV",
       "GRE": "GRC", "BUL": "BGR", "SLO": "SVN", "ROM": "ROU", "LAT": "LVA", "BIH": "BIH"}
ELO_SNAPSHOT = C.STATE / "elo.csv"   # ostatni udany ranking (fallback, gdy źródła leżą)
ELO_PROBS_FILE = C.STATE / "elo_probs.json"
ELO_COLS = ["Club", "Country", "Elo", "Source", "Date"]


def country_code(c):
    c = (c or "").upper()
    return _CC.get(c, c)


def _clubelo(day):
    for back in range(3):
        d = (day - timedelta(days=back)).isoformat()
        try:
            df = pd.read_csv(io.StringIO(get(f"http://api.clubelo.com/{d}", cache_h=12, tries=2)))
            if "Elo" in df and len(df) > 100:
                return df.assign(Country=df.Country.map(country_code), Source="ClubElo", Date=d)
        except Exception as e:  # noqa: BLE001
            log.warning("clubelo %s: %s", d, e)
            if "HTTP 5" in str(e) or "timed out" in str(e):
                break  # serwer leży – nie ma sensu pytać o inne dni
    return None


ELO_PROBS = []  # (różnica Elo gosp.-gość, p1, pX, p2) z prognoz elofootball – do kalibracji mostu


def _elofootball(countries, day):
    """elofootball.com: ranking per kraj (country.php). Pobieramy tylko potrzebne kraje."""
    from bs4 import BeautifulSoup
    y = day.year if day.month >= 7 else day.year - 1
    rows = []
    for cc in sorted(countries):
        try:
            html = get("http://elofootball.com/country.php",
                       params={"countryiso": cc, "season": f"{y}-{y + 1}"}, cache_h=20, tries=2)
        except Exception as e:  # noqa: BLE001
            log.warning("elofootball %s: %s", cc, e)
            continue
        tables = BeautifulSoup(html, "lxml").find_all("table")
        for t in tables:  # prognozy samego elofootball: "Drużyna 1631" ... "51 / 26 / 23 %"
            if "Probabilities" not in [th.get_text(strip=True) for th in t.find_all("th")]:
                continue
            for tr in t.find_all("tr")[1:]:
                td = [x.get_text(" ", strip=True) for x in tr.find_all("td")]
                if len(td) < 6:
                    continue
                eh, ea = re.search(r"(\d{3,4})$", td[2]), re.search(r"(\d{3,4})$", td[4])
                pr = re.findall(r"\d+", td[5])
                if eh and ea and len(pr) == 3:
                    ELO_PROBS.append((int(eh.group(1)) - int(ea.group(1)), *[int(x) / 100 for x in pr]))
        tab = next((t for t in tables
                    if "Rating" in [th.get_text(strip=True) for th in t.find_all("th")]), None)
        if tab is None:
            log.warning("elofootball %s: brak tabeli rankingu", cc)
            continue
        heads = [th.get_text(strip=True) for th in tab.find("tr").find_all(["th", "td"])]
        ic, ir = heads.index("Club"), heads.index("Rating")
        for tr in tab.find_all("tr")[1:]:
            tds = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
            if len(tds) > max(ic, ir) and tds[ir].isdigit():
                rows.append(dict(Club=tds[ic], Country=cc, Elo=float(tds[ir]),
                                 Source="elofootball", Date=day.isoformat()))
    return pd.DataFrame(rows, columns=ELO_COLS) if rows else None


def elo_ratings(countries=(), day=None):
    """Ranking Elo klubów: ClubElo -> elofootball.com (tylko kraje z `countries`) -> zapis w state/elo.csv.
    W jednym przebiegu wszystkie oceny pochodzą z jednego źródła (różne skale!)."""
    day = datetime.fromisoformat(day).date() if day else datetime.now(timezone.utc).date()
    countries = {country_code(c) for c in countries if c}
    snap = pd.read_csv(ELO_SNAPSHOT) if ELO_SNAPSHOT.exists() else pd.DataFrame(columns=ELO_COLS)
    df = _clubelo(day)
    if df is None:
        df = _elofootball(countries, day)
    if df is not None:
        df = df[ELO_COLS]
        src = df.Source.iloc[0]
        # kraje pobrane teraz zastępują stare wpisy; reszta snapshotu zostaje (tylko z tego samego źródła)
        keep = snap[(snap.Source == src) & ~snap.Country.isin(set(df.Country))]
        out = pd.concat([keep, df], ignore_index=True) if len(keep) else df.reset_index(drop=True)
        C.STATE.mkdir(exist_ok=True)
        out.to_csv(ELO_SNAPSHOT, index=False)
        if src == "elofootball" and len(ELO_PROBS) >= 50:
            ELO_PROBS_FILE.write_text(json.dumps(ELO_PROBS[-1500:]))
        log.info("Elo: %s, %d klubów (%d krajów)", src, len(out), out.Country.nunique())
        return out
    if len(snap):
        if snap.Source.iloc[-1] == "elofootball" and ELO_PROBS_FILE.exists():
            ELO_PROBS[:] = [tuple(x) for x in json.loads(ELO_PROBS_FILE.read_text())]
        log.warning("Elo: źródła niedostępne – używam zapisanego rankingu (%s, %s)",
                    snap.Source.iloc[-1], snap.Date.max())
        return snap
    log.warning("Elo: brak źródeł i zapisanego rankingu")
    return pd.DataFrame(columns=ELO_COLS)


# ---------------------------------------------------------------------------
# Transfermarkt – terminarz ligi (Ekstraklasa nie ma go w darmowym football-data.org,
# a ClubElo wyłączyło swoje API Fixtures)
# ---------------------------------------------------------------------------
def tm_fixtures(slug, code, tz="Europe/Warsaw"):
    """Mecze sezonu z Transfermarkt: kickoff (UTC), home, away, hg, ag (NaN gdy nierozegrany)."""
    from bs4 import BeautifulSoup
    now = datetime.now(timezone.utc)
    season = now.year if now.month >= 7 else now.year - 1
    html = get(f"https://www.transfermarkt.com/{slug}/gesamtspielplan/wettbewerb/{code}/saison_id/{season}",
               cache_h=6)
    soup = BeautifulSoup(html, "lxml")
    rows, day, hour = [], None, None
    for tr in soup.select("div.box table tbody tr"):
        tds = tr.find_all("td", recursive=False)
        teams = tr.select("td.hauptlink a[href*='/verein/']")
        if len(tds) < 5 or len(teams) < 2:
            continue
        txt = tds[0].get_text(" ", strip=True)
        m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", txt)
        if m:
            y = int(m.group(3))
            day = (y + 2000 if y < 100 else y, int(m.group(2)), int(m.group(1)))
        t = re.search(r"(\d{1,2}):(\d{2})\s*([AP]M)?", tds[1].get_text(" ", strip=True))
        if t:
            h = int(t.group(1)) % 12 + (12 if t.group(3) == "PM" else 0) if t.group(3) else int(t.group(1))
            hour = (h, int(t.group(2)))
        if not day:
            continue
        res = tr.select_one("a.ergebnis-link")
        sc = re.match(r"\s*(\d+):(\d+)\s*$", res.get_text(strip=True)) if res else None
        ko = pd.Timestamp(*day, *(hour or (18, 0))).tz_localize(tz).tz_convert("UTC")
        rows.append(dict(kickoff=ko, home=teams[0].get("title") or teams[0].get_text(strip=True),
                         away=teams[-1].get("title") or teams[-1].get_text(strip=True),
                         hg=int(sc.group(1)) if sc else np.nan, ag=int(sc.group(2)) if sc else np.nan,
                         time_unknown=not hour))
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# The Odds API (darmowy klucz, 500 kredytów/mies.) – kursy wielu bukmacherów
# ---------------------------------------------------------------------------
ODDS_STATE = "odds_api.json"   # w state/: ostatnie pobranie per liga + pozostałe kredyty


def odds_api(league):
    """Kursy z The Odds API z pilnowaniem budżetu (500 kredytów/mies., h2h+totals = 2 kredyty):
    liga odświeżana najwyżej co ODDS_MIN_INTERVAL_H, a poniżej ODDS_RESERVE kredytów nie pytamy wcale."""
    from . import tracker as T
    sport = C.LEAGUES[league].get("odds")
    if not C.ODDS_API_KEY or not sport:
        return []
    st = T.load(ODDS_STATE, {"leagues": {}})
    prev = st["leagues"].get(league)
    now = datetime.now(timezone.utc)
    fresh = prev and now - datetime.fromisoformat(prev["fetched"]) < timedelta(hours=C.ODDS_MIN_INTERVAL_H)
    remaining = st.get("remaining")
    if fresh or (remaining is not None and remaining <= C.ODDS_RESERVE):
        if not fresh:
            log.warning("odds-api: zostało %s kredytów (rezerwa %d) – używam zapisanych kursów %s",
                        remaining, C.ODDS_RESERVE, league)
        evs = (prev or {}).get("events", [])
        return [{**e, "kickoff": pd.Timestamp(e["kickoff"])} for e in evs]
    try:
        js = json.loads(get(f"https://api.the-odds-api.com/v4/sports/{sport}/odds",
                            params=dict(apiKey=C.ODDS_API_KEY, regions="eu", markets="h2h,totals",
                                        oddsFormat="decimal"), tries=2))
    except Exception as e:  # noqa: BLE001
        log.warning("odds-api %s: %s", league, str(e).replace(C.ODDS_API_KEY, "***"))
        return []
    h = LAST_HEADERS.get("api.the-odds-api.com") or {}
    try:
        st["remaining"] = int(float(h.get("x-requests-remaining")))
        st["used"] = int(float(h.get("x-requests-used")))
    except (TypeError, ValueError):
        pass
    log.info("odds-api %s: %d meczów, koszt %s, zostało %s kredytów",
             league, len(js), h.get("x-requests-last"), st.get("remaining"))
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
    st["leagues"][league] = dict(fetched=now.isoformat(),
                                 events=[{**r, "kickoff": r["kickoff"].isoformat()} for r in out])
    st["updated"] = now.isoformat()
    T.save(ODDS_STATE, st)
    return out


# ---------------------------------------------------------------------------
# Understat (bez klucza) – xG dla top 5 lig
# ---------------------------------------------------------------------------
def understat_xg(league):
    us = C.LEAGUES[league].get("us")
    if not us:
        return pd.DataFrame()
    rows = []
    if not _understat_alive():
        return pd.DataFrame()
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


_US_ALIVE = None


def _understat_alive():
    """Understat czasem jest w przerwie technicznej ('We will come back soon')."""
    global _US_ALIVE
    if _US_ALIVE is None:
        try:
            html = get("https://understat.com/", cache_h=1)
            _US_ALIVE = "come back soon" not in html
        except Exception:  # noqa: BLE001
            _US_ALIVE = False
        if not _US_ALIVE:
            log.warning("understat: serwis niedostępny (przerwa techniczna) – model bez xG")
    return _US_ALIVE


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
