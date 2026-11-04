"""Rejestry: (1) publiczny rejestr typów i kalibracji modelu, (2) prywatny,
szyfrowany rejestr Twoich zagranych kuponów."""
import json
import logging
from datetime import datetime, timezone

import numpy as np
from cryptography.fernet import Fernet, InvalidToken

from . import config as C

log = logging.getLogger("tracker")


def load(name, default):
    p = C.STATE / name
    try:
        return json.loads(p.read_text())
    except Exception:  # noqa: BLE001
        return default


def save(name, data):
    (C.STATE / name).parent.mkdir(parents=True, exist_ok=True)
    (C.STATE / name).write_text(json.dumps(data, ensure_ascii=False, indent=1, default=str))


def won(market, hg, ag):
    tot = hg + ag
    if market in ("1", "X", "2", "1X", "X2", "12"):
        r = "1" if hg > ag else "X" if hg == ag else "2"
        return r in market
    if market[0] in "OU" and market[1:].replace(".", "").isdigit():
        line = float(market[1:])
        return tot > line if market[0] == "O" else tot < line
    if market == "BTTS":
        return hg > 0 and ag > 0
    if market == "BTTS_NO":
        return not (hg > 0 and ag > 0)
    raise ValueError(market)


# ---------------------------------------------------------------------------
# Rejestr modelu (publiczny)
# ---------------------------------------------------------------------------
def record_day(day, picks, matches):
    rec = load("record.json", {"coupons": [], "predictions": []})
    known = {c["uid"] for c in rec["coupons"]}
    for group in ("singles", "combos", "long"):
        for c in picks[group]:
            uid = f"{day}:{c['id']}"
            if uid in known:
                continue
            rec["coupons"].append(dict(uid=uid, day=day, id=c["id"], type=c["type"], legs=c["legs"],
                                       odds=c["odds"], p=c["p"], stake=c["stake"], status="pending"))
    known_m = {p["match_id"] for p in rec["predictions"]}
    for m in matches:
        if m["id"] in known_m:
            continue
        rec["predictions"].append(dict(
            match_id=m["id"], league=m["league"], home=m["home"], away=m["away"], kickoff=m["kickoff"],
            p1=m["probs"]["1"], px=m["probs"]["X"], p2=m["probs"]["2"], po25=m["probs"]["O2.5"],
            pbtts=m["probs"]["BTTS"], market=m.get("market_probs"), result=None))
    save("record.json", rec)


def settle(results):
    """results: {match_id: (hg, ag)} -> aktualizuje rejestry, zwraca listę rozliczeń."""
    rec = load("record.json", {"coupons": [], "predictions": []})
    changed = []
    for p in rec["predictions"]:
        if p["result"] is None and p["match_id"] in results:
            p["result"] = list(results[p["match_id"]])
    for c in rec["coupons"]:
        if c["status"] != "pending":
            continue
        res = []
        for leg in c["legs"]:
            if leg["match_id"] in results:
                hg, ag = results[leg["match_id"]]
                leg["result"] = f"{hg}:{ag}"
                leg["won"] = won(leg["market"], hg, ag)
            res.append(leg.get("won"))
        if any(r is False for r in res):
            c["status"] = "lost"
        elif all(r is True for r in res):
            c["status"] = "won"
        if c["status"] != "pending":
            c["settled_at"] = datetime.now(timezone.utc).isoformat()
            changed.append(c)
    save("record.json", rec)
    return changed


def model_stats():
    rec = load("record.json", {"coupons": [], "predictions": []})
    out = {}
    for group, ids in (("single", "S"), ("kupon", "K"), ("długi", "D")):
        cs = [c for c in rec["coupons"] if c["id"].startswith(ids) and c["status"] in ("won", "lost")]
        stake = sum(c["stake"] for c in cs)
        ret = sum(c["stake"] * (1 - C.STS_TAX) * c["odds"] for c in cs if c["status"] == "won")
        out[group] = dict(n=len(cs), won=sum(c["status"] == "won" for c in cs), stake=round(stake, 2),
                          returned=round(ret, 2), profit=round(ret - stake, 2),
                          roi=round((ret - stake) / stake, 4) if stake else None,
                          expected_hits=round(sum(c["p"] for c in cs), 2))
    pr = [p for p in rec["predictions"] if p["result"]]
    if pr:
        ll, br, ll_mkt, n_mkt = [], [], [], 0
        for p in pr:
            hg, ag = p["result"]
            r = 0 if hg > ag else 1 if hg == ag else 2
            probs = [p["p1"], p["px"], p["p2"]]
            ll.append(-np.log(max(probs[r], 1e-9)))
            br.append(((p["po25"] - (hg + ag > 2)) ** 2))
            if p.get("market"):
                mk = p["market"]
                ll_mkt.append(-np.log(max([mk["1"], mk["X"], mk["2"]][r], 1e-9)))
        out["calibration"] = dict(n=len(pr), logloss_1x2=round(float(np.mean(ll)), 4),
                                  logloss_market=round(float(np.mean(ll_mkt)), 4) if ll_mkt else None,
                                  n_market=len(ll_mkt), brier_o25=round(float(np.mean(br)), 4))
    # krzywa bilansu singli (1 j. = stawka)
    curve, bal = [], 0.0
    for c in sorted((c for c in rec["coupons"] if c["status"] in ("won", "lost")), key=lambda c: c.get("settled_at", "")):
        bal += (c["stake"] * (1 - C.STS_TAX) * c["odds"] if c["status"] == "won" else 0) - c["stake"]
        curve.append(dict(t=c.get("settled_at", "")[:10], id=c["uid"], bal=round(bal, 2)))
    out["curve"] = curve
    return out


# ---------------------------------------------------------------------------
# Twój prywatny rejestr (szyfrowany, bo repo jest publiczne)
# ---------------------------------------------------------------------------
def _fernet():
    if not C.BETS_KEY:
        return None
    return Fernet(C.BETS_KEY.encode())


def load_bets():
    f = _fernet()
    p = C.STATE / "bets.enc"
    if not f or not p.exists():
        return []
    try:
        return json.loads(f.decrypt(p.read_bytes()))
    except InvalidToken:
        log.error("Nie da się odszyfrować bets.enc – zły BETS_ENCRYPTION_KEY?")
        raise


def save_bets(bets):
    f = _fernet()
    if not f:
        log.warning("Brak BETS_ENCRYPTION_KEY – nie zapisuję zakładów")
        return
    C.STATE.mkdir(exist_ok=True)
    (C.STATE / "bets.enc").write_bytes(f.encrypt(json.dumps(bets, ensure_ascii=False, default=str).encode()))


def settle_bets(bets, results):
    changed = []
    for b in bets:
        if b["status"] != "pending" or not b.get("legs"):
            continue
        res = []
        for leg in b["legs"]:
            if leg["match_id"] in results:
                hg, ag = results[leg["match_id"]]
                leg["won"] = won(leg["market"], hg, ag)
            res.append(leg.get("won"))
        if any(r is False for r in res):
            b["status"] = "lost"
        elif all(r is True for r in res):
            b["status"] = "won"
        if b["status"] != "pending":
            b["payout"] = payout(b) if b["status"] == "won" else 0.0
            changed.append(b)
    return changed


def payout(b):
    v = b["stake"] * (1 - C.STS_TAX) * b["odds"]
    return round(v * 0.9 if v > C.BIG_WIN_TAX_LIMIT else v, 2)


def bets_summary(bets):
    done = [b for b in bets if b["status"] in ("won", "lost")]
    stake = sum(b["stake"] for b in done)
    ret = sum(b.get("payout", 0) for b in done)
    return dict(n=len(bets), settled=len(done), won=sum(b["status"] == "won" for b in done),
                pending=sum(b["status"] == "pending" for b in bets), stake=round(stake, 2),
                returned=round(ret, 2), profit=round(ret - stake, 2),
                roi=round((ret - stake) / stake, 4) if stake else None)
