"""Telegram: wysyłka typów i obsługa komend (bot nie działa non stop –
komendy są odczytywane przy każdym przebiegu GitHub Actions, czyli co ~godzinę)."""
import html
import logging
from datetime import datetime, timezone

import requests

from . import config as C
from . import tracker

log = logging.getLogger("telegram")
API = "https://api.telegram.org/bot{}/{}"

HELP = """<b>Komendy</b>
/typy – dzisiejsze typy
/weekend – zapowiedź weekendu (czw/pt), typy WS1, WK1, WD1…
/zagrane S1 10 2.05 – zagrałem typ S1 za 10 zł po kursie 2.05 (ID z wiadomości z typami)
/zagrane D1 2 87.3 – to samo dla kuponu/długiego kuponu
/zagrane wlasny 5 3.40 opis – własny kupon spoza bota
/wynik 7 w|p – ręczne rozliczenie własnego kuponu nr 7
/usun 7 – usuń zakład nr 7
/bilans – Twój bilans, ROI, oczekujące
/model – skuteczność modelu
Komendy są czytane przy najbliższym przebiegu bota (zwykle do godziny)."""


def esc(s):
    return html.escape(str(s))


def send(text, chat=None):
    if not C.TG_TOKEN or not (chat or C.TG_CHAT):
        log.info("[telegram wyłączony]\n%s", text)
        return
    for chunk in _split(text):
        try:
            r = requests.post(API.format(C.TG_TOKEN, "sendMessage"), timeout=20, json=dict(
                chat_id=chat or C.TG_CHAT, text=chunk, parse_mode="HTML", disable_web_page_preview=True))
            if not r.ok:
                log.warning("telegram: %s", r.text[:200])
        except requests.RequestException as e:
            log.warning("telegram: %s", e)


def _split(text, n=3900):
    parts, cur = [], ""
    for line in text.split("\n"):
        if len(cur) + len(line) + 1 > n:
            parts.append(cur)
            cur = ""
        cur += line + "\n"
    return parts + [cur] if cur.strip() else parts


def poll_updates():
    if not C.TG_TOKEN:
        return []
    st = tracker.load("tg.json", {"offset": 0})
    try:
        r = requests.get(API.format(C.TG_TOKEN, "getUpdates"), timeout=20,
                         params={"offset": st["offset"] + 1, "timeout": 0})
        ups = r.json().get("result", [])
    except Exception as e:  # noqa: BLE001
        log.warning("telegram getUpdates: %s", e)
        return []
    msgs = []
    for u in ups:
        st["offset"] = max(st["offset"], u["update_id"])
        m = u.get("message") or {}
        chat = str((m.get("chat") or {}).get("id", ""))
        if chat != str(C.TG_CHAT):  # tylko Ty możesz sterować botem
            if m.get("text", "").startswith("/start") and not C.TG_CHAT:
                send(f"Twój chat_id: <code>{chat}</code> – wpisz go w GitHub Secrets jako TELEGRAM_CHAT_ID", chat)
            continue
        if m.get("text"):
            msgs.append(m["text"].strip())
    tracker.save("tg.json", st)
    return msgs


def _find_pick(ref):
    """'S1' (dzisiejszy/ostatni), 'WS1' (zapowiedź weekendu) albo '2026-11-05:S1'."""
    day, _, pid = ref.rpartition(":")
    if pid.upper().startswith("W"):  # zapowiedź weekendu
        latest = tracker.load("picks_preview.json", {})
        src = latest if not day or latest.get("day") == day else tracker.load(f"picks/{day}-weekend.json", {})
        for group in ("singles", "combos", "long"):
            for c in src.get(group, []):
                if c["id"].upper() == pid.upper():
                    return src.get("day"), c
        return day or latest.get("day"), None
    latest = tracker.load("picks_latest.json", {})
    if not day:
        day = latest.get("day")
    src = latest if latest.get("day") == day else tracker.load(f"picks/{day}.json", {})
    for group in ("singles", "combos", "long"):
        for c in src.get(group, []):
            if c["id"].upper() == pid.upper():
                return day, c
    return day, None


def handle(text):
    parts = text.split()
    cmd = parts[0].split("@")[0].lower()
    bets = tracker.load_bets()
    if cmd in ("/start", "/pomoc", "/help"):
        return HELP
    if cmd == "/zagrane" and len(parts) >= 4:
        try:
            stake = float(parts[2].replace(",", "."))
            odds = float(parts[3].replace(",", "."))
        except ValueError:
            return "Format: /zagrane S1 10 2.05"
        nr = max([b["nr"] for b in bets], default=0) + 1
        now = datetime.now(timezone.utc).isoformat()
        if parts[1].lower() in ("wlasny", "własny"):
            bets.append(dict(nr=nr, ref="własny", desc=" ".join(parts[4:]), stake=stake, odds=odds,
                             legs=[], status="pending", at=now))
        else:
            day, pick = _find_pick(parts[1])
            if not pick:
                return f"Nie znam typu {esc(parts[1])}. Sprawdź ID w ostatnich typach (/typy)."
            legs = [dict(match_id=l["match_id"], market=l["market"],
                         desc=f'{l["home"]} – {l["away"]}: {l["label"]}') for l in pick["legs"]]
            bets.append(dict(nr=nr, ref=f"{day}:{pick['id']}", desc=pick["type"], stake=stake, odds=odds,
                             legs=legs, status="pending", at=now, p_model=pick["p"]))
        tracker.save_bets(bets)
        warn = ""
        b = bets[-1]
        if b.get("legs"):
            day, pick = _find_pick(b["ref"])
            minimum = 1 / (pick["p"] * (1 - C.STS_TAX))
            if odds < 1 / pick["p"]:
                warn = f"\n⚠️ Kurs {odds} jest poniżej kursu uczciwego ({1 / pick['p']:.2f}) – wartość ujemna."
            elif odds < minimum:
                warn = f"\nℹ️ Po podatku opłaca się od {minimum:.2f}; to gra na lekkim minusie, ok dla zabawy."
        return f"✅ Zapisano zakład nr {nr}: {esc(b['desc'])}, {stake:.2f} zł × {odds} " \
               f"→ możliwa wypłata {tracker.payout(b):.2f} zł{warn}"
    if cmd == "/wynik" and len(parts) >= 3:
        for b in bets:
            if str(b["nr"]) == parts[1]:
                b["status"] = "won" if parts[2].lower().startswith("w") else "lost"
                b["payout"] = tracker.payout(b) if b["status"] == "won" else 0.0
                tracker.save_bets(bets)
                return f"Zakład {b['nr']}: {'wygrany 🎉' if b['status'] == 'won' else 'przegrany'}"
        return "Nie ma takiego zakładu."
    if cmd == "/usun" and len(parts) >= 2:
        n = len(bets)
        bets = [b for b in bets if str(b["nr"]) != parts[1]]
        tracker.save_bets(bets)
        return "Usunięto." if len(bets) < n else "Nie ma takiego zakładu."
    if cmd == "/bilans":
        s = tracker.bets_summary(bets)
        pend = "\n".join(f"• nr {b['nr']}: {esc(b['desc'])} {b['stake']} zł × {b['odds']}"
                         for b in bets if b["status"] == "pending")
        roi = f"{s['roi'] * 100:+.1f}%" if s["roi"] is not None else "–"
        return (f"<b>Twój bilans</b>\nRozliczone: {s['settled']} (wygrane {s['won']})\n"
                f"Postawione: {s['stake']:.2f} zł\nWypłacone: {s['returned']:.2f} zł\n"
                f"<b>Wynik: {s['profit']:+.2f} zł</b> (ROI {roi})\n"
                + (f"\n<b>W grze:</b>\n{pend}" if pend else ""))
    if cmd == "/weekend":
        return tracker.load("picks_preview.json", {}).get("message", "Zapowiedź weekendu pojawia się w czwartek i piątek rano.")
    if cmd == "/model":
        st = tracker.model_stats()
        lines = ["<b>Skuteczność modelu</b> (stawki wg typów, po podatku)"]
        for g in ("single", "kupon", "długi"):
            s = st[g]
            if s["n"]:
                lines.append(f"{g}: {s['won']}/{s['n']} (oczekiwano {s['expected_hits']}), "
                             f"wynik {s['profit']:+.2f} zł, ROI {s['roi'] * 100:+.1f}%")
        cal = st.get("calibration")
        if cal:
            lines.append(f"Log-loss 1X2: model {cal['logloss_1x2']} vs rynek {cal['logloss_market']} "
                         f"(niżej = lepiej, {cal['n']} meczów)")
        return "\n".join(lines) if len(lines) > 1 else "Jeszcze nic nie rozliczono."
    if cmd == "/typy":
        return tracker.load("picks_latest.json", {}).get("message", "Brak typów na dziś.")
    return "Nie rozumiem. /pomoc"
