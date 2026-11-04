"""Generuje statyczną stronę (GitHub Pages) z najnowszej analizy."""
import json
import logging

from . import config as C
from . import tracker as T

log = logging.getLogger("site")


def build_site():
    latest = T.load("picks_latest.json", {})
    data = dict(latest=latest, stats=T.model_stats(),
                record=T.load("record.json", {"coupons": []})["coupons"][-150:],
                cfg=dict(tax=C.STS_TAX, market_weight=C.MARKET_WEIGHT, sts_disc=C.STS_MARGIN_DISCOUNT,
                         leagues={k: dict(name=v["name"], flag=v["flag"]) for k, v in C.LEAGUES.items()}))
    for m in data["latest"].get("matches", []):  # strona nie potrzebuje wszystkiego
        m.pop("lambdas_raw", None)
    tpl = (C.ROOT / "bot" / "template.html").read_text(encoding="utf-8")
    payload = json.dumps(data, ensure_ascii=False, default=str).replace("</", "<\\/")
    C.DOCS.mkdir(exist_ok=True)
    (C.DOCS / "index.html").write_text(tpl.replace("__DATA__", payload), encoding="utf-8")
    (C.DOCS / ".nojekyll").write_text("")
    log.info("Strona zapisana: docs/index.html")
