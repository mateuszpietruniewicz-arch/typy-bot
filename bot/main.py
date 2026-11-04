"""Punkt wejścia. `python -m bot.main auto` uruchamia GitHub Actions co godzinę."""
import argparse
import logging
import sys
from datetime import datetime, timedelta, timezone

import pandas as pd

from . import config as C
from . import message as M
from . import news as N
from . import telegram as TG
from . import tracker as T
from .site import build_site

log = logging.getLogger("main")


def local_now():
    return pd.Timestamp.now(tz=C.TZ)


def run_daily(send=True):
    from .pipeline import analyse
    result, hist = analyse()
    day = local_now().date().isoformat()
    result["day"] = day
    result["message"] = M.daily(result)
    T.save(f"picks/{day}.json", result)
    T.save("picks_latest.json", result)
    T.record_day(day, result, result["matches"])
    if send:
        TG.send(result["message"])
    return result, hist


def run_settle(hist=None):
    rec = T.load("record.json", {"coupons": [], "predictions": []})
    bets = T.load_bets()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=2, minutes=30)
    pend = set()
    for c in rec["coupons"]:
        if c["status"] == "pending":
            pend |= {l["match_id"] for l in c["legs"] if pd.Timestamp(l["kickoff"]) < cutoff}
    for p in rec["predictions"]:
        if p["result"] is None and pd.Timestamp(p["kickoff"]) < cutoff:
            pend.add(p["match_id"])
    for b in bets:
        if b["status"] == "pending":
            pend |= {l["match_id"] for l in b.get("legs", [])}
    if not pend:
        return
    from .pipeline import collect_results
    results = collect_results(sorted(pend), hist)
    log.info("Wyniki: %d/%d meczów", len(results), len(pend))
    for c in T.settle(results):
        if c["id"].startswith(("S", "K", "D")):
            TG.send(M.settled(c))
    changed = T.settle_bets(bets, results)
    if changed:
        T.save_bets(bets)
        for b in changed:
            TG.send(M.settled(b, mine=True))
        s = T.bets_summary(bets)
        TG.send(f"Bilans: {s['profit']:+.2f} zł po {s['settled']} kuponach")


def run_prematch():
    latest = T.load("picks_latest.json", {})
    st = T.load("run.json", {})
    sent = set(st.get("prematch_sent", []))
    now = datetime.now(timezone.utc)
    lo, hi = C.PREMATCH_MIN
    due = [m for m in latest.get("matches", [])
           if lo <= (pd.Timestamp(m["kickoff"]) - now).total_seconds() / 60 <= hi and m["id"] not in sent
           and any(l["match_id"] == m["id"] for g in ("singles", "combos", "long") for c in latest.get(g, [])
                   for l in c["legs"])]
    if not due:
        return
    items = N.fetch_all(hours=24)
    gen = latest.get("generated", "")
    for m in due:
        fresh = [n for side in ("home", "away") for n in N.for_team(items, m[side])
                 if n["injury"] and (n["published"] or "") > gen]
        if fresh:
            TG.send(M.prematch(m, fresh))
        sent.add(m["id"])
    st["prematch_sent"] = sorted(sent)[-200:]
    T.save("run.json", st)


def run_auto():
    st = T.load("run.json", {})
    for text in TG.poll_updates():
        try:
            TG.send(TG.handle(text))
        except Exception as e:  # noqa: BLE001
            log.exception("komenda %s", text)
            TG.send(f"Błąd komendy: {TG.esc(e)}")
    hist = None
    now = local_now()
    if now.hour >= C.DAILY_HOUR and st.get("daily_done") != now.date().isoformat():
        _, hist = run_daily()
        st = T.load("run.json", {})
        st["daily_done"] = now.date().isoformat()
        T.save("run.json", st)
    try:
        run_settle(hist)
    except Exception:  # noqa: BLE001
        log.exception("rozliczanie")
    try:
        run_prematch()
    except Exception:  # noqa: BLE001
        log.exception("przed meczem")
    build_site()


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s", stream=sys.stdout)
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["auto", "daily", "settle", "site", "commands"])
    ap.add_argument("--no-send", action="store_true")
    a = ap.parse_args()
    if a.mode == "auto":
        run_auto()
    elif a.mode == "daily":
        run_daily(send=not a.no_send)
        build_site()
    elif a.mode == "settle":
        run_settle()
        build_site()
    elif a.mode == "site":
        build_site()
    elif a.mode == "commands":
        for text in TG.poll_updates():
            TG.send(TG.handle(text))


if __name__ == "__main__":
    main()
