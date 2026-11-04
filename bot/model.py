"""Model Dixon-Coles z wagą czasową i mieszanką goli/xG + rynki zakładów."""
import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy.optimize import minimize, minimize_scalar
from scipy.stats import poisson

from . import config as C

log = logging.getLogger("model")
MAXG = 10


@dataclass
class LeagueModel:
    league: str
    teams: list
    att: dict
    dfn: dict          # "dziurawość" obrony: wyżej = więcej traconych
    mu: float
    home: float
    rho: float
    n_matches: int
    last_date: pd.Timestamp
    avg_goals: float = 2.7
    meta: dict = field(default_factory=dict)

    def strength(self, team):
        """Siła drużyny w skali log-goli (atak - obrona)."""
        a, d = self._ad(team)
        return a - d

    def _ad(self, team):
        if team in self.att:
            return self.att[team], self.dfn[team]
        # nieznana drużyna (np. beniaminek bez meczów) -> poziom słabszych drużyn ligi
        return (float(np.quantile(list(self.att.values()), 0.2)),
                float(np.quantile(list(self.dfn.values()), 0.8)))

    def lambdas(self, home, away, neutral=False):
        ah, dh = self._ad(home)
        aa, da = self._ad(away)
        hadv = 0.0 if neutral else self.home
        return float(np.exp(self.mu + hadv + ah + da)), float(np.exp(self.mu + aa + dh))


def fit_league(df, league, ref_date=None, xi=C.XI, xg_weight=C.XG_WEIGHT, ridge=2.0):
    """df: kolumny date, home, away, hg, ag (+ opcjonalnie hxg, axg)."""
    df = df.dropna(subset=["hg", "ag"]).copy()
    ref_date = pd.Timestamp(ref_date) if ref_date is not None else df.date.max()
    df = df[df.date <= ref_date]
    age = (ref_date - df.date).dt.days.values
    w = np.exp(-xi * age)

    # cel: gole albo mieszanka goli i xG
    yh = df.hg.values.astype(float)
    ya = df.ag.values.astype(float)
    if xg_weight > 0 and "hxg" in df and df.hxg.notna().any():
        hx = df.hxg.values
        ax = df.axg.values
        ok = ~np.isnan(hx) & ~np.isnan(ax)
        yh = np.where(ok, (1 - xg_weight) * yh + xg_weight * np.nan_to_num(hx), yh)
        ya = np.where(ok, (1 - xg_weight) * ya + xg_weight * np.nan_to_num(ax), ya)

    # drużyny z bieżącego sezonu mają pełne parametry; reszta i tak dostaje regularyzację
    teams = sorted(set(df.home) | set(df.away))
    idx = {t: i for i, t in enumerate(teams)}
    hi = df.home.map(idx).values
    ai = df.away.map(idx).values
    n = len(teams)

    def unpack(p):
        return p[:n], p[n:2 * n], p[2 * n], p[2 * n + 1]

    def nll(p):
        att, dfn, mu, home = unpack(p)
        lh = mu + home + att[hi] + dfn[ai]
        la = mu + att[ai] + dfn[hi]
        eh, ea = np.exp(lh), np.exp(la)
        ll = w * (yh * lh - eh + ya * la - ea)
        reg = ridge * (np.sum(att ** 2) + np.sum(dfn ** 2)) + 50 * np.sum(att) ** 2
        g_lh = w * (yh - eh)
        g_la = w * (ya - ea)
        g_att = np.bincount(hi, g_lh, n) + np.bincount(ai, g_la, n)
        g_dfn = np.bincount(ai, g_lh, n) + np.bincount(hi, g_la, n)
        grad = -np.concatenate([g_att, g_dfn, [g_lh.sum() + g_la.sum()], [g_lh.sum()]])
        grad[:n] += 2 * ridge * att + 100 * np.sum(att)
        grad[n:2 * n] += 2 * ridge * dfn
        return -ll.sum() + reg, grad

    p0 = np.zeros(2 * n + 2)
    p0[2 * n] = np.log(max(np.average(yh + ya, weights=w) / 2, 0.3))
    p0[2 * n + 1] = 0.25
    res = minimize(nll, p0, jac=True, method="L-BFGS-B")
    att, dfn, mu, home = unpack(res.x)

    # rho (korekta niskich wyników) – osobno, na prawdziwych golach
    lh = np.exp(mu + home + att[hi] + dfn[ai])
    la = np.exp(mu + att[ai] + dfn[hi])
    gh, ga = df.hg.values, df.ag.values

    def rho_nll(r):
        t = np.ones_like(lh)
        m00 = (gh == 0) & (ga == 0)
        m01 = (gh == 0) & (ga == 1)
        m10 = (gh == 1) & (ga == 0)
        m11 = (gh == 1) & (ga == 1)
        t[m00] = 1 - lh[m00] * la[m00] * r
        t[m01] = 1 + lh[m01] * r
        t[m10] = 1 + la[m10] * r
        t[m11] = 1 - r
        if np.any(t <= 0):
            return 1e9
        return -np.sum(w * np.log(t))

    rho = minimize_scalar(rho_nll, bounds=(-0.25, 0.15), method="bounded").x
    model = LeagueModel(league, teams, dict(zip(teams, att)), dict(zip(teams, dfn)),
                        float(mu), float(home), float(rho), len(df), ref_date,
                        avg_goals=float(np.average(gh + ga, weights=w)))
    log.info("%s: %d meczów, %d drużyn, przewaga gosp. %.2f, rho %.3f", league, len(df), n, home, rho)
    return model


def score_matrix(lh, la, rho=-0.05):
    g = np.arange(MAXG + 1)
    m = np.outer(poisson.pmf(g, lh), poisson.pmf(g, la))
    m[0, 0] *= max(1 - lh * la * rho, 1e-6)
    m[0, 1] *= max(1 + lh * rho, 1e-6)
    m[1, 0] *= max(1 + la * rho, 1e-6)
    m[1, 1] *= max(1 - rho, 1e-6)
    return m / m.sum()


def markets(m):
    """Prawdopodobieństwa rynków z macierzy wyników."""
    g = np.arange(m.shape[0])
    tot = g[:, None] + g[None, :]
    h = float(np.tril(m, -1).sum())
    d = float(np.trace(m))
    a = float(np.triu(m, 1).sum())
    out = {"1": h, "X": d, "2": a, "1X": h + d, "X2": d + a, "12": h + a}
    for line in (0.5, 1.5, 2.5, 3.5, 4.5):
        o = float(m[tot > line].sum())
        out[f"O{line}"] = o
        out[f"U{line}"] = 1 - o
    btts = float(m[1:, 1:].sum())
    out["BTTS"] = btts
    out["BTTS_NO"] = 1 - btts
    # najbardziej prawdopodobne wyniki
    flat = [(float(m[i, j]), f"{i}:{j}") for i in range(6) for j in range(6)]
    out["_top_scores"] = sorted(flat, reverse=True)[:5]
    return out


MARKET_LABELS = {
    "1": "1 (gospodarz)", "X": "X (remis)", "2": "2 (gość)",
    "1X": "1X", "X2": "X2", "12": "12",
    "O1.5": "Powyżej 1.5 gola", "U1.5": "Poniżej 1.5 gola",
    "O2.5": "Powyżej 2.5 gola", "U2.5": "Poniżej 2.5 gola",
    "O3.5": "Powyżej 3.5 gola", "U3.5": "Poniżej 3.5 gola",
    "BTTS": "Obie strzelą: TAK", "BTTS_NO": "Obie strzelą: NIE",
}


# ---------------------------------------------------------------------------
# Most Elo -> gole (mecze pucharowe między ligami)
# ---------------------------------------------------------------------------
@dataclass
class EloBridge:
    k: float            # log-przewaga goli na 1 pkt Elo
    hadv: float
    total: float
    rho: float = -0.05

    def lambdas(self, elo_h, elo_a, neutral=False):
        sup = self.k * (elo_h - elo_a) + (0 if neutral else self.hadv)
        # suma goli lekko rośnie przy dużej różnicy sił
        tot = self.total * (1 + 0.08 * min(abs(sup), 1.5))
        lh = tot * np.exp(sup / 2) / (np.exp(sup / 2) + np.exp(-sup / 2))
        return float(lh), float(tot - lh)


def fit_elo_bridge(models, elo_map):
    """Regresja: siła drużyny w modelu ligowym ~ stała ligi + k * Elo."""
    xs, ys, grp = [], [], []
    for lg, m in models.items():
        for t in m.teams:
            e = elo_map.get((lg, t))
            if e is not None:
                xs.append(e)
                ys.append(m.strength(t))
                grp.append(lg)
    if len(xs) < 20:
        return EloBridge(k=0.0028, hadv=0.22, total=2.9)
    df = pd.DataFrame(dict(x=xs, y=ys, g=grp))
    df["xc"] = df.x - df.groupby("g").x.transform("mean")
    df["yc"] = df.y - df.groupby("g").y.transform("mean")
    k_strength = float((df.xc * df.yc).sum() / (df.xc ** 2).sum())
    # strength = att - dfn; przewaga w meczu = różnica sił (log λh - log λa)
    hadv = float(np.mean([m.home for m in models.values()])) * 0.8  # w LM przewaga nieco mniejsza
    log.info("Most Elo: k=%.5f (log-gole/pkt Elo)", k_strength)
    return EloBridge(k=k_strength, hadv=hadv, total=2.95)
