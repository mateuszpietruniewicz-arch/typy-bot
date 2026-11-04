"""Backtest czynnika składu (FotMob): czy różnica wartości wyjściowej XI względem „zwykłej jedenastki”
(najwięcej minut w 8 poprzednich meczach ligowych) poprawia prognozy modelu.

  python tests/backtest_lineups.py fetch     # pobiera składy (wznawialne, cache w .cache/)
  python tests/backtest_lineups.py           # analiza (wymaga .cache/bt_preds.pkl z backtest_closing.py)

Model: λh' = λh·exp(a·dH + b·dA), λa' = λa·exp(a·dA + b·dH), d = −(liczba zawodników zwykłej XI poza składem)/11
(--value: d = względna zmiana wartości XI – sprawdzone, pogarsza log-loss).
Współczynniki a, b dopasowane metodą największej wiarygodności (Poisson) na rezydułach modelu;
ocena poza próbą: fit na pozostałych sezonach, test na danym sezonie.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from bot import config as C  # noqa: E402
from bot import fotmob as F  # noqa: E402
from bot.model import markets, score_matrix  # noqa: E402
from bot.names import Matcher  # noqa: E402

SEASONS = {"2024/2025": "2425", "2025/2026": "2526", "2026/2027": "2627"}
OUT = C.CACHE / "bt_lineups.pkl"
FEATURE = "value" if "--value" in sys.argv else "miss"   # d = −braki/11 (domyślnie) albo zmiana wartości XI


def prefetch(ids, workers=3):
    """Równoległe pobranie szczegółów meczów do cache (3 wątki), potem liczenie już z cache."""
    from concurrent.futures import ThreadPoolExecutor

    from bot.data_sources import get

    def one(mid):
        try:
            get(f"{F.BASE}/matchDetails", params={"matchId": mid}, cache_h=F.FOREVER, tries=2)
        except Exception as e:  # noqa: BLE001
            print("  błąd", mid, e, flush=True)
    with ThreadPoolExecutor(workers) as ex:
        list(ex.map(one, ids))


def fetch():
    rows = []
    for lg in C.DOMESTIC:
        for fs, code in SEASONS.items():
            try:
                ms = [m for m in F.league_season(lg, fs) if m["finished"]]
            except Exception as e:  # noqa: BLE001
                print(lg, fs, "błąd listy:", e, flush=True)
                continue
            print(f"{lg} {fs}: {len(ms)} meczów", flush=True)
            prefetch([m["id"] for m in ms])
            hist = {}  # team_id -> lista (kickoff, {pid: (min, name, value)})
            for i, m in enumerate(sorted(ms, key=lambda x: x["kickoff"])):
                try:
                    md = F.match_details(m["id"], finished=True)
                except Exception as e:  # noqa: BLE001
                    print("  pominięty", m["id"], e, flush=True)
                    continue
                mp = F.minutes_played(md)
                lu = F.lineups(md)
                row = dict(league=lg, season=code, kickoff=m["kickoff"], home=m["home"], away=m["away"],
                           fm_id=m["id"])
                for side, tid in (("h", m["home_id"]), ("a", m["away_id"])):
                    prev = hist.get(tid, [])[-8:]
                    tot = {}
                    for _, mins in prev:
                        for pid, (mn, name, val) in mins.items():
                            a = tot.setdefault(pid, [0, val])
                            a[0] += mn
                            a[1] = val or a[1]
                    usual = sorted(tot.items(), key=lambda x: -x[1][0])[:11]
                    st = lu["home" if side == "h" else "away"]["starters"]
                    vu = sum(v[1] for _, v in usual)
                    vn = sum(p["value"] for p in st)
                    row[f"n_prev_{side}"] = len(prev)
                    row[f"d_{side}"] = (vn - vu) / vu if vu > 0 and len(st) == 11 and len(prev) >= 3 else np.nan
                    row[f"miss_{side}"] = len({pid for pid, _ in usual} - {p["id"] for p in st}) if usual else np.nan
                rows.append(row)
                for tid in (m["home_id"], m["away_id"]):
                    if tid in mp:
                        hist.setdefault(tid, []).append((m["kickoff"], mp[tid]))
                if i % 100 == 0:
                    print(f"  {i}/{len(ms)}", flush=True)
            pd.DataFrame(rows).to_pickle(OUT)  # zapis po każdej lidze/sezonie
    pd.DataFrame(rows).to_pickle(OUT)
    print("zapisano", OUT, len(rows))


def poisson_ll(y, lam):
    return y * np.log(lam) - lam


def fit_ab(df):
    from scipy.optimize import minimize

    def nll(x):
        a, b = x
        lh = df.lh * np.exp(a * df.d_h + b * df.d_a)
        la = df.la * np.exp(a * df.d_a + b * df.d_h)
        return -(poisson_ll(df.hg, lh) + poisson_ll(df.ag, la)).sum()
    return minimize(nll, [0.0, 0.0], method="Nelder-Mead").x


def probs(lh, la, rho=-0.05):
    out = []
    for h, a in zip(lh, la):
        mk = markets(score_matrix(h, a, rho))
        out.append((mk["1"], mk["X"], mk["2"], mk["O2.5"]))
    return np.array(out)


def ll(P, df):
    res = np.where(df.hg > df.ag, 0, np.where(df.hg == df.ag, 1, 2))
    l1 = -np.log(np.clip(P[np.arange(len(df)), res], 1e-6, 1))
    y = ((df.hg + df.ag) > 2.5).values
    po = np.clip(P[:, 3], 1e-6, 1 - 1e-6)
    lo = -(y * np.log(po) + (1 - y) * np.log(1 - po))
    return l1.mean(), lo.mean()


def analyse(variant="mu_xi.020"):
    L = pd.read_pickle(OUT)
    P = pd.read_pickle(C.CACHE / "bt_preds.pkl")
    if f"lh_{variant}" not in P:
        sys.exit("Brak lambd w bt_preds.pkl – uruchom: python tests/backtest_closing.py --refit")
    # dopasowanie meczów FotMob <-> football-data.co.uk (liga, data ±1, nazwy)
    rows = []
    for lg in L.league.unique():
        p = P[P.league == lg]
        mt = Matcher(pd.concat([p.home, p.away]).unique())
        idx = {(r["date"].normalize(), r["home"], r["away"]): r for r in p.to_dict("records")}
        for r in L[L.league == lg].itertuples():
            h, a = mt.match(r.home), mt.match(r.away)
            d0 = r.kickoff.tz_convert(None).normalize()
            hit = next((idx[k] for k in ((d0 + pd.Timedelta(days=dd), h, a) for dd in (0, -1, 1)) if k in idx), None)
            if hit is None:
                continue
            rows.append(dict(league=lg, season=r.season, hg=hit["hg"], ag=hit["ag"], d_h=r.d_h, d_a=r.d_a,
                             miss_h=r.miss_h, miss_a=r.miss_a,
                             lh=hit[f"lh_{variant}"], la=hit[f"la_{variant}"]))
    df = pd.DataFrame(rows).dropna(subset=["d_h", "d_a", "lh", "la", "miss_h", "miss_a"])
    df[["d_h", "d_a"]] = df[["d_h", "d_a"]].clip(-0.6, 0.6)
    if FEATURE == "miss":  # wybrana cecha: liczba braków ze zwykłej XI (lepsza niż wartość XI)
        df["d_h"], df["d_a"] = -df.miss_h / 11, -df.miss_a / 11
    print(f"Dopasowane mecze ze składami: {len(df)} (z {len(L)} z FotMob)")
    print(f"Średnia zmiana wartości XI vs zwykła: {df.d_h.mean():+.3f}; mediana braków ze zwykłej XI: "
          f"{df.miss_h.median():.0f}")
    print("\n== Współczynniki (fit na wszystkich danych) ==")
    a, b = fit_ab(df)
    print(f"  a (własny skład -> własne gole) = {a:+.3f}   b (własny skład -> gole rywala) = {b:+.3f}")
    print("  czyli XI o 10%% słabsza niż zwykle: własne gole ×%.3f, gole rywala ×%.3f" % (np.exp(-0.1 * a), np.exp(-0.1 * b)))
    print("\n== Poza próbą (fit na pozostałych sezonach) – log-loss, niżej = lepiej ==")
    print(f"{'sezon':6} {'n':>5} {'1X2 bez':>9} {'1X2 ze składem':>15} {'O2.5 bez':>9} {'O2.5 ze składem':>16}")
    tot = []
    for s in sorted(df.season.unique()):
        tr, te = df[df.season != s], df[df.season == s]
        a_, b_ = fit_ab(tr)
        base = probs(te.lh, te.la)
        adj = probs(te.lh * np.exp(a_ * te.d_h + b_ * te.d_a), te.la * np.exp(a_ * te.d_a + b_ * te.d_h))
        l0, l1 = ll(base, te), ll(adj, te)
        tot.append((len(te), l0, l1))
        print(f"{s:6} {len(te):5d} {l0[0]:9.4f} {l1[0]:15.4f} {l0[1]:9.4f} {l1[1]:16.4f}  (a={a_:+.2f}, b={b_:+.2f})")
    n = sum(t[0] for t in tot)
    w = lambda k, j: sum(t[0] * t[k][j] for t in tot) / n  # noqa: E731
    print(f"{'razem':6} {n:5d} {w(1, 0):9.4f} {w(2, 0):15.4f} {w(1, 1):9.4f} {w(2, 1):16.4f}")
    return dict(a=a, b=b, n=n, ll_1x2=(w(1, 0), w(2, 0)), ll_o25=(w(1, 1), w(2, 1)))


if __name__ == "__main__":
    if sys.argv[1:2] == ["fetch"]:
        fetch()
    else:
        r = analyse()
        (C.STATE / "backtest_lineups.json").write_text(__import__("json").dumps(
            dict(feature=FEATURE, a=float(r["a"]), b=float(r["b"]), n=r["n"],
                 ll_1x2=[round(float(x), 4) for x in r["ll_1x2"]], ll_o25=[round(float(x), 4) for x in r["ll_o25"]]),
            indent=1))
