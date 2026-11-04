"""Treść wiadomości Telegram z typami."""
from datetime import datetime

import pandas as pd

from . import config as C
from .telegram import esc

DAYS = ["pon", "wt", "śr", "czw", "pt", "sob", "nd"]


def hhmm(iso, unknown=False):
    t = pd.Timestamp(iso).tz_convert(C.TZ)
    return f"{DAYS[t.weekday()]} {'?' if unknown else t.strftime('%H:%M')}"


def pct(p):
    return f"{p * 100:.0f}%"


def leg_line(l):
    return (f"{C.LEAGUES[l['league']]['flag']} {esc(l['home'])} – {esc(l['away'])}: "
            f"<b>{esc(l['label'])}</b> ({pct(l['p'])}, ~{l['odds']:.2f})")


def daily(result, title="Typy"):
    now = pd.Timestamp(result["generated"]).tz_convert(C.TZ)
    icon = "📅" if title != "Typy" else "🎯"
    out = [f"{icon} <b>{title} · {DAYS[now.weekday()]} {now.strftime('%d.%m')}</b>",
           f"Mecze w analizie: {len(result['matches'])}"]
    if not result["matches"]:
        return "\n".join(out + ["Brak meczów w tym okresie."])
    if result["singles"]:
        out.append("\n<b>SINGLE</b> (graj tylko, gdy kurs STS ≥ „opłaca się od”)")
        for c in result["singles"]:
            l = c["legs"][0]
            out.append(f"<code>{c['id']}</code> {hhmm(l['kickoff'])} {leg_line(l)}\n"
                       f"     przewaga {l['edge'] * 100:+.1f}% · fair {l['fair']} · opłaca się od <b>{l['min_sts']}</b>")
        if not result["singles"][0].get("value", True):
            out.append("<i>Dziś brak wyraźnej przewagi – to typy najbliżej wartości. Graj tylko, gdy STS da „opłaca się od”.</i>")
    else:
        out.append("\nSingle: brak meczów z kursami rynkowymi.")
    if result["combos"]:
        out.append("\n<b>KUPONY 2–3</b>")
        for c in result["combos"]:
            out.append(f"<code>{c['id']}</code> {c['type']} · kurs ~{c['odds']} · szansa {pct(c['p'])} · "
                       f"wartość {c['ev_pct'] * 100:+.0f}% (po podatku)")
            out += [f"   • {leg_line(l)}" for l in c["legs"]]
    if result["long"]:
        out.append("\n<b>DŁUGIE KUPONY za 2 zł</b> 🎰 (loteria – dla zabawy)")
        for c in result["long"]:
            out.append(f"<code>{c['id']}</code> {c['type']} · kurs ~{c['odds']:.0f} · "
                       f"wypłata ~{c['payout']:.0f} zł · szansa 1 na {c['one_in']:.0f} · "
                       f"średnio wraca {c['p'] * c['payout']:.2f} zł z 2 zł")
            out += [f"   • {leg_line(l)}" for l in c["legs"]]
    for cid, why in (result.get("long_skipped") or {}).items():
        out.append(f"<code>{cid}</code> szalona: dziś nie ma – {esc(why)}.")
    # „dlaczego” skrótowo: składy i zmęczenie przy meczach z typów
    ids = {l["match_id"] for g in ("singles", "combos", "long") for c in result.get(g, []) for l in c["legs"]}
    whys = [(m, w) for m in result["matches"] if m["id"] in ids for w in m.get("why", [])
            if w["factor"] in ("skład", "zmęczenie")]
    if whys:
        out.append("\n🔎 <b>Dlaczego (składy, zmęczenie):</b>")
        out += [f"• {esc(w['text'])}" + (f" ({w['impact']:+.1f} pkt proc.)" if w.get("impact") else "")
                for _, w in whys[:6]]
    big = []
    for m in result["matches"]:
        for side in ("home", "away"):
            for p in m["absences"][side][:2]:
                if p["value"] >= 15e6 and p["weight"] >= 1:
                    big.append(f"{esc(p['player'])} ({esc(m[side])})")
    if big:
        out.append("\n🚑 <b>Ważne braki:</b> " + ", ".join(big[:10]))
    out.append("\nZapisz zagrany: /zagrane ID stawka kurs")
    if C.SITE_URL:
        out.append(f'📊 <a href="{C.SITE_URL}">Pełna analiza meczów</a>')
    return "\n".join(out)


def why_hard():
    """Prosto: dlaczego w Polsce trudno wyjść na plus."""
    t = C.STS_TAX
    be = 1 / ((1 - t) * 2.0)
    return ("<b>Dlaczego w Polsce trudno wyjść na plus</b>\n"
            f"• Podatek {t * 100:.0f}% od stawki: z 10 zł w grze jest tylko {10 * (1 - t):.2f} zł.\n"
            "• Marża bukmachera: kursy są zaniżone o kilka procent (na 1X2 zwykle 5–8%).\n"
            f"• Razem: przy kursie 2.00 musisz trafiać {be * 100:.0f}% zakładów, żeby wyjść na zero "
            "(bez podatku i marży wystarczyłoby 50%).\n"
            "• Kupony: marża mnoży się z każdym zdarzeniem – 10 zdarzeń oddaje średnio ok. 50–60% stawki.")


def model_vs_market(bt):
    """Wynik backtestu modelu vs rynek (state/backtest.json -> summary)."""
    s = (bt or {}).get("summary")
    if not s:
        return ""
    return ("<b>Model vs rynek</b> (backtest {seasons}, {n} meczów, kursy zamknięcia; log-loss – niżej = lepiej)\n"
            "• 1X2: model {ll_model_1x2} vs rynek {ll_market_1x2}\n"
            "• Powyżej/Poniżej 2.5: model {ll_model_o25} vs rynek {ll_market_o25}\n"
            "• Single „z przewagą” poza próbą: zwrot {r:+.0f}% przed podatkiem, {r2:+.0f}% po kursie STS i podatku.\n"
            "Rynek przewiduje lepiej niż model – dlatego bot nie obiecuje zysku.").format(
        r=100 * s["single_roi_test_1x2"], r2=100 * s["single_roi_test_1x2_sts"], **s)


def lineup_alert(m, ctx, ch):
    """Alert po potwierdzonych składach: kto wypadł ze zwykłej XI, dlaczego i jak zmieniły się szanse."""
    from .team_news import _reason
    out = [f"📋 <b>Składy</b> {hhmm(m['kickoff'])} {m['flag']} {esc(m['home'])} – {esc(m['away'])}"]
    for side in ("home", "away"):
        t = ctx[side]
        if t.get("d") is None:
            continue
        line = f"<b>{esc(m[side])}</b>: bez {len(t['out'])} z „zwykłej jedenastki”"
        if t["out"]:
            line += "\n   brak: " + ", ".join(f"{esc(p['name'])} ({esc(_reason(p, t['unavailable']))})" for p in t["out"][:5])
        if t["into"]:
            line += "\n   w składzie: " + ", ".join(esc(p["name"]) for p in t["into"][:5])
        out.append(line)
    names = {"1": "1", "X": "X", "2": "2"}
    out.append("Szanse: " + " · ".join(f"{names[k]} {a * 100:.0f}% → <b>{b * 100:.0f}%</b>" for k, (a, b) in ch.items()))
    out.append("<i>Kursy STS mogły już zareagować – sprawdź przed grą.</i>")
    return "\n".join(out)


def prematch(m, new_news):
    out = [f"⏰ <b>Przed meczem</b> {hhmm(m['kickoff'])} {m['flag']} {esc(m['home'])} – {esc(m['away'])}"]
    for n in new_news[:4]:
        out.append(f"• {'🚑 ' if n['injury'] else ''}<a href=\"{n['link']}\">{esc(n['title'])}</a> ({esc(n['source'])})")
    return "\n".join(out)


def settled(c, mine=False):
    icon = "✅" if c["status"] == "won" else "❌"
    who = "Twój zakład" if mine else "Typ bota"
    head = f"{icon} {who} {esc(c.get('ref') or c.get('id'))}: {'WYGRANY' if c['status'] == 'won' else 'przegrany'}"
    if mine and c["status"] == "won":
        head += f" · wypłata {c['payout']:.2f} zł"
    return head
