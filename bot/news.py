"""Newsy z kanałów RSS: nagłówki o drużynach z nadchodzących meczów,
ze szczególnym oznaczeniem tych o kontuzjach/zawieszeniach."""
import logging
import re
from datetime import datetime, timedelta, timezone

import feedparser

from . import config as C
from .data_sources import get
from .names import norm

log = logging.getLogger("news")


def fetch_all(hours=72):
    items = []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    for url in C.NEWS_FEEDS:
        try:
            fp = feedparser.parse(get(url, cache_h=1))
        except Exception as e:  # noqa: BLE001
            log.warning("RSS %s: %s", url, e)
            continue
        for e in fp.entries:
            t = e.get("published_parsed") or e.get("updated_parsed")
            dt = datetime(*t[:6], tzinfo=timezone.utc) if t else None
            if dt and dt < cutoff:
                continue
            summary = re.sub(r"<[^>]+>", " ", e.get("summary", ""))[:400]
            items.append(dict(title=e.get("title", "").strip(), link=e.get("link"), summary=summary,
                              published=dt.isoformat() if dt else None,
                              source=fp.feed.get("title", url)))
    log.info("RSS: %d wpisów", len(items))
    return items


def _keys(team):
    n = norm(team)
    keys = {n}
    parts = [p for p in n.split() if len(p) >= 5]
    keys.update(parts)
    return keys


def for_team(items, team, limit=4):
    keys = _keys(team)
    hits = []
    for it in items:
        text = norm(it["title"] + " " + it["summary"])
        if any(re.search(rf"\b{re.escape(k)}\b", text) for k in keys):
            low = (it["title"] + " " + it["summary"]).lower()
            inj = any(w in low for w in C.INJURY_WORDS)
            hits.append({**it, "injury": inj})
    hits.sort(key=lambda x: x["published"] or "", reverse=True)
    hits.sort(key=lambda x: not x["injury"])
    return hits[:limit]
