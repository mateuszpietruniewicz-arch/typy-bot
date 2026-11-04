"""Backtest z kursami zamknięcia (football-data.co.uk), walk-forward.

Model przeliczany co tydzień na danych sprzed tygodnia (okno 3 sezony), prognozy dla sezonów
2022/23–2026/27. Porównanie z kursami zamknięcia (AvgC*, zapas: Pinnacle PSC*).

Uruchom:  python tests/backtest_closing.py            (pełny raport)
          python tests/backtest_closing.py --fast     (bez wariantów poziomu goli)
Wyniki (predykcje) w .cache/bt_preds.pkl – kolejne uruchomienia liczą tylko raport.
"""
import io
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from bot import config as C  # noqa: E402
from bot import data_sources as D  # noqa: E402
from bot.model import fit_league, markets, score_matrix  # noqa: E402
from bot.picks import fair_probs  # noqa: E402

SEASONS = ["1920", "2021", "2122", "2223", "2324", "2425", "2526", "2627"]
PRED_SEASONS = ["2223", "2324", "2425", "2526", "2627"]
TUNE = ["2223", "2324", "2425"]          # tu dobieramy parametry
TEST = ["2526", "2627"]                  # tu raportujemy (poza próbą)
WINDOW_DAYS = 3 * 365
VARIANTS = {
    "base": dict(level_xi=0.0),
    "mu_xi.006": dict(level_xi=0.006),
    "mu_xi.012": dict(level_xi=0.012),
    "mu_xi.020": dict(level_xi=0.020),
    "sezon": dict(level_xi=0.0, season=True),
}
CACHE = C.CACHE / "bt_preds.pkl"


def _n(df, *cols):
    for c in cols:
        if c in df.columns:
            v = pd.to_numeric(df[c], errors="coerce")
            if v.notna().mean() > 0.5:
                return v
    return pd.Series(np.nan, index=df.index)


def load(lg):
    cfg = C.LEAGUES[lg]
    frames = []
    if cfg.get("fdcuk"):
        for sc in SEASONS:
            raw = D.get(f"https://www.football-data.co.uk/mmz4281/{sc}/{cfg['fdcuk']}.csv",
                        cache_h=24 * (1 if sc == SEASONS[-1] else 365))
            df = pd.read_csv(io.StringIO(raw), on_bad_lines="skip")
            df = df[df.HomeTeam.notna()]
            frames.append(pd.DataFrame(dict(
                season=sc, date=pd.to_datetime(df.Date, dayfirst=True, errors="coerce", format="mixed"),
                home=df.HomeTeam, away=df.AwayTeam, hg=_n(df, "FTHG"), ag=_n(df, "FTAG"),
                c1=_n(df, "AvgCH", "PSCH"), cx=_n(df, "AvgCD", "PSCD"), c2=_n(df, "AvgCA", "PSCA"),
                co=_n(df, "AvgC>2.5", "PC>2.5"), cu=_n(df, "AvgC<2.5", "PC<2.5"))))
    else:
        raw = D.get(f"https://www.football-data.co.uk/new/{cfg['fdcuk_extra']}.csv", cache_h=24)
        df = pd.read_csv(io.StringIO(raw), on_bad_lines="skip")
        df["season"] = df.Season.astype(str).str[2:4] + df.Season.astype(str).str[7:9]
        df = df[df.season.isin(SEASONS)]
        frames.append(pd.DataFrame(dict(
            season=df.season, date=pd.to_datetime(df.Date, dayfirst=True, errors="coerce", format="mixed"),
            home=df.Home, away=df.Away, hg=_n(df, "HG"), ag=_n(df, "AG"),
            c1=_n(df, "AvgCH", "PSCH"), cx=_n(df, "AvgCD", "PSCD"), c2=_n(df, "AvgCA", "PSCA"),
            co=np.nan, cu=np.nan)))
    out = pd.concat(frames, ignore_index=True).dropna(subset=["date", "hg", "ag"])
    out["league"] = lg
    return out.sort_values("date").reset_index(drop=True)


def season_start(sc):
    return pd.Timestamp(f"20{sc[:2]}-07-01")


def walk_forward(df, lg, variants):
    rows = []
    test = df[df.season.isin(PRED_SEASONS)]
    weeks = test.date.dt.to_period("W-SUN").dt.start_time
    for wk, chunk in test.groupby(weeks):
        train = df[(df.date < wk) & (df.date >= wk - pd.Timedelta(days=WINDOW_DAYS))]
        if len(train) < 200:
            continue
        preds = {}
        for name, kw in variants.items():
            kw = dict(kw)
            season = kw.pop("season", False)
            m = fit_league(train, lg, ref_date=wk, level_season=season_start(chunk.season.iloc[0]) if season else None,
                           **kw)
            ps = []
            for r in chunk.itertuples():
                mk = markets(score_matrix(*m.lambdas(r.home, r.away), m.rho))
                ps.append((mk["1"], mk["X"], mk["2"], mk["O2.5"]))
            preds[name] = ps
        for i, r in enumerate(chunk.itertuples()):
            row = dict(league=lg, season=r.season, date=r.date, home=r.home, away=r.away, hg=r.hg, ag=r.ag,
                       c1=r.c1, cx=r.cx, c2=r.c2, co=r.co, cu=r.cu)
            for name, ps in preds.items():
                row.update({f"{k}_{name}": v for k, v in zip(("p1", "px", "p2", "po"), ps[i])})
            rows.append(row)
    return rows


def market_probs(P):
    m1 = np.full((len(P), 3), np.nan)
    mo = np.full(len(P), np.nan)
    for i, r in enumerate(P.itertuples()):
        f = fair_probs([r.c1, r.cx, r.c2]) if np.isfinite([r.c1, r.cx, r.c2]).all() else None
        if f is not None:
            m1[i] = f
        f = fair_probs([r.co, r.cu]) if np.isfinite([r.co, r.cu]).all() else None
        if f is not None:
            mo[i] = f[0]
    P[["m1", "mx", "m2"]] = m1
    P["mo"] = mo
    return P


# --- kalibracja O2.5 ----------------------------------------------------------------------
def _logit(p):
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return np.log(p / (1 - p))


def platt_fit(p, y):
    from scipy.optimize import minimize
    x = _logit(p)

    def nll(ab):
        q = 1 / (1 + np.exp(-(ab[0] + ab[1] * x)))
        q = np.clip(q, 1e-6, 1 - 1e-6)
        return -np.mean(y * np.log(q) + (1 - y) * np.log(1 - q))
    ab = minimize(nll, [0.0, 1.0], method="Nelder-Mead").x
    return lambda p2: 1 / (1 + np.exp(-(ab[0] + ab[1] * _logit(p2))))


def isotonic_fit(p, y):
    o = np.argsort(p)
    xs, ys = p[o], y[o].astype(float)
    blocks = [[ys[i], 1.0, xs[i], xs[i]] for i in range(len(xs))]  # suma, waga, xmin, xmax
    out = []
    for b in blocks:
        out.append(b)
        while len(out) > 1 and out[-2][0] / out[-2][1] > out[-1][0] / out[-1][1]:
            s, w, lo, _ = out.pop(-2)
            out[-1] = [out[-1][0] + s, out[-1][1] + w, lo, out[-1][3]]
    cx = np.array([(b[2] + b[3]) / 2 for b in out])
    cy = np.array([b[0] / b[1] for b in out])
    return lambda p2: np.clip(np.interp(p2, cx, cy), 0.02, 0.98)


def calibrated(P, col, kind):
    """Kalibracja O2.5 walk-forward: dla sezonu s fit tylko na sezonach < s."""
    out = P[col].copy()
    y = ((P.hg + P.ag) > 2.5).values
    for s in PRED_SEASONS[1:]:
        tr = P.season < s
        te = P.season == s
        if tr.sum() < 300:
            continue
        f = (platt_fit if kind == "platt" else isotonic_fit)(P.loc[tr, col].values, y[tr.values])
        out[te] = f(P.loc[te, col].values)
    out[P.season == PRED_SEASONS[0]] = np.nan  # brak wcześniejszych danych do kalibracji
    return out


# --- metryki ------------------------------------------------------------------------------
def ll_1x2(p1, px, p2, res):
    p = np.where(res == "H", p1, np.where(res == "D", px, p2))
    return -np.log(np.clip(p, 1e-6, 1))


def ll_bin(p, y):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def bets(P, v, w, min_edge, market, min_p=C.MIN_PROB_SINGLE, po_col=None):
    """Symulacja singli jak w picks.build: najlepsza opcja w meczu, edge = p·kurs_zamknięcia − 1."""
    res = np.where(P.hg > P.ag, "H", np.where(P.hg == P.ag, "D", "A"))
    if market == "1x2":
        pm = np.c_[P[f"p1_{v}"], P[f"px_{v}"], P[f"p2_{v}"]]
        pk = P[["m1", "mx", "m2"]].values
        odds = P[["c1", "cx", "c2"]].values
        win = np.c_[res == "H", res == "D", res == "A"]
    else:
        po = P[po_col or f"po_{v}"].values
        pm = np.c_[po, 1 - po]
        pk = np.c_[P.mo, 1 - P.mo]
        odds = P[["co", "cu"]].values
        tot = (P.hg + P.ag).values
        win = np.c_[tot > 2.5, tot < 2.5]
    p = (1 - w) * pm + w * pk
    edge = p * odds - 1
    edge[~np.isfinite(edge) | (p < min_p)] = -9
    j = edge.argmax(1)
    e = edge[np.arange(len(P)), j]
    sel = e >= min_edge
    o = odds[np.arange(len(P)), j][sel]
    wn = win[np.arange(len(P)), j][sel]
    profit = np.where(wn, o - 1, -1.0)
    sts = np.where(wn, o * (1 - C.STS_MARGIN_DISCOUNT) * (1 - C.STS_TAX) - 1, -1.0)
    return dict(n=int(sel.sum()), roi=float(profit.mean()) if sel.any() else np.nan,
                roi_sts=float(sts.mean()) if sel.any() else np.nan,
                se=float(profit.std() / np.sqrt(sel.sum())) if sel.sum() > 1 else np.nan)


def main():
    fast = "--fast" in sys.argv
    variants = {"base": VARIANTS["base"]} if fast else VARIANTS
    if CACHE.exists() and "--refit" not in sys.argv:
        P = pd.read_pickle(CACHE)
        missing = [v for v in variants if f"p1_{v}" not in P]
    else:
        P, missing = None, list(variants)
    if missing:
        rows = []
        for lg in C.DOMESTIC:
            df = load(lg)
            print(f"{lg}: {len(df)} meczów, prognozy …", flush=True)
            rows += walk_forward(df, lg, {k: variants[k] for k in missing})
        new = pd.DataFrame(rows)
        P = new if P is None else P.merge(new[["league", "date", "home", "away"] +
                                               [c for c in new if c.endswith(tuple("_" + m for m in missing))]],
                                          on=["league", "date", "home", "away"], how="left")
        P = market_probs(P)
        P.to_pickle(CACHE)
    report(P, list(variants))


def report(P, variants):
    res = np.where(P.hg > P.ag, "H", np.where(P.hg == P.ag, "D", "A"))
    y = ((P.hg + P.ag) > 2.5).values.astype(float)
    ok1 = P[["m1"]].notna().values.ravel()
    oko = P.mo.notna().values
    print(f"\nMecze z prognozą: {len(P)}; z kursem zamknięcia 1X2: {ok1.sum()}, O/U: {oko.sum()} "
          f"(Ekstraklasa bez O/U w danych)\n")

    # 1. jakość prawdopodobieństw
    print("== 1. Log-loss (niżej = lepiej), wszystkie sezony prognoz z kursami ==")
    print(f"{'wariant':12} {'1X2 model':>10} {'O2.5 model':>11} {'śr. O2.5':>9} {'faktycznie':>10}")
    for v in variants:
        l1 = ll_1x2(P[f"p1_{v}"], P[f"px_{v}"], P[f"p2_{v}"], res)[ok1].mean()
        lo = ll_bin(P[f"po_{v}"].values, y)[oko].mean()
        print(f"{v:12} {l1:10.4f} {lo:11.4f} {P[f'po_{v}'][oko].mean():9.3f} {y[oko].mean():10.3f}")
    l1m = ll_1x2(P.m1, P.mx, P.m2, res)[ok1].mean()
    lom = ll_bin(P.mo.values, y)[oko].mean()
    print(f"{'RYNEK zamkn.':12} {l1m:10.4f} {lom:11.4f} {P.mo[oko].mean():9.3f}")

    print("\n== Bias O2.5 (model − faktycznie) per sezon, wariant base ==")
    for s in PRED_SEASONS:
        m = oko & (P.season == s).values
        if m.sum():
            print(f"  {s}: n={m.sum():4d} model {P.po_base[m].mean():.3f} rynek {P.mo[m].mean():.3f} "
                  f"faktycznie {y[m].mean():.3f}")

    # wybór wariantu poziomu goli na sezonach TUNE (log-loss O2.5)
    tune = P.season.isin(TUNE).values
    test = P.season.isin(TEST).values
    best_v = min(variants, key=lambda v: ll_bin(P[f"po_{v}"].values, y)[oko & tune].mean())
    print(f"\nNajlepszy wariant poziomu goli na sezonach {TUNE}: {best_v}")

    # kalibracja O2.5
    P["po_platt"] = calibrated(P, f"po_{best_v}", "platt")
    P["po_iso"] = calibrated(P, f"po_{best_v}", "iso")
    m = oko & P.po_platt.notna().values
    print("\n== 2. Kalibracja O2.5 (walk-forward, fit na wcześniejszych sezonach) – log-loss ==")
    for name, col in (("bez kalibracji", f"po_{best_v}"), ("Platt", "po_platt"), ("izotoniczna", "po_iso"),
                      ("RYNEK", "mo")):
        a = ll_bin(P[col].values, y)
        print(f"  {name:15} 2023–25 {a[m & tune].mean():.4f}   test 2025–27 {a[m & test].mean():.4f}")

    # 3. blend + MIN_EDGE
    def blend_ll(market, w, v, col=None):
        if market == "1x2":
            p = [(1 - w) * P[f"{k}_{v}"] + w * P[mk] for k, mk in (("p1", "m1"), ("px", "mx"), ("p2", "m2"))]
            return ll_1x2(*p, res)
        po = (1 - w) * P[col or f"po_{v}"] + w * P.mo
        return ll_bin(po.values, y)

    W = [0.0, 0.2, 0.35, 0.5, 0.65, 0.8, 0.9, 0.95, 1.0]
    E = [0.0, 0.02, 0.03, 0.05, 0.08, 0.10, 0.15]
    out = {}
    for market, v, col, mask in (("1x2", "base", None, ok1), ("1x2", best_v, None, ok1),
                                 ("ou", best_v, None, oko), ("ou", best_v, "po_platt", oko & P.po_platt.notna().values),
                                 ("ou", best_v, "po_iso", oko & P.po_iso.notna().values)):
        label = f"{market} {col or v}"
        lls = {w: blend_ll(market, w, v, col)[mask & tune].mean() for w in W}
        w_best = min(lls, key=lls.get)
        print(f"\n== 3. {label}: log-loss mieszanki na 2023–25 wg MARKET_WEIGHT ==")
        print("  " + "  ".join(f"w={w:.2f}:{lls[w]:.4f}" for w in W))
        print(f"  najlepsze MARKET_WEIGHT={w_best}; test 2025–27: mieszanka "
              f"{blend_ll(market, w_best, v, col)[mask & test].mean():.4f} vs rynek "
              f"{blend_ll(market, 1.0, v, col)[mask & test].mean():.4f} vs model {blend_ll(market, 0.0, v, col)[mask & test].mean():.4f}")
        print(f"  Single (najlepsza opcja w meczu, edge vs kurs zamknięcia), ROI przed podatkiem | po STS i 12% podatku:")
        print(f"  {'w':>5} {'min_edge':>8} | {'n 23–25':>8} {'ROI':>7} | {'n test':>7} {'ROI':>7} {'±SE':>6} {'ROI STS':>8}")
        grid = []
        for w in (0.35, 0.5, 0.65, 0.8, 0.9):
            for e in E:
                a = bets(P[mask & tune], v, w, e, market, po_col=col)
                b = bets(P[mask & test], v, w, e, market, po_col=col)
                grid.append((w, e, a, b))
                if w in (0.65, w_best) or e in (0.03,):
                    print(f"  {w:5.2f} {e:8.2f} | {a['n']:8d} {a['roi']:+7.3f} | {b['n']:7d} {b['roi']:+7.3f} "
                          f"{b['se']:6.3f} {b['roi_sts']:+8.3f}")
        # wybór na TUNE: maks. ROI przy n >= 150
        cand = [g for g in grid if g[2]["n"] >= 150]
        pick = max(cand, key=lambda g: g[2]["roi"]) if cand else None
        if pick:
            w, e, a, b = pick
            print(f"  >> wybór na 2023–25: w={w}, min_edge={e}: ROI {a['roi']:+.3f} (n={a['n']}) -> "
                  f"TEST ROI {b['roi']:+.3f} ±{b['se']:.3f} (n={b['n']}), po STS+podatku {b['roi_sts']:+.3f}")
        out[label] = dict(w_ll=w_best, pick=None if not pick else dict(
            w=pick[0], min_edge=pick[1], tune=pick[2], test=pick[3]))
    (C.STATE / "backtest.json").write_text(json.dumps(dict(best_variant=best_v, results=out), indent=1,
                                                      default=float))
    print("\nZapisano state/backtest.json")


if __name__ == "__main__":
    main()
