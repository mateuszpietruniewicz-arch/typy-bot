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
