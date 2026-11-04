"""Ujednolicanie nazw drużyn między źródłami (football-data, ClubElo, Transfermarkt...)."""
import json
import re
import unicodedata

from rapidfuzz import fuzz, process

from .config import ROOT

_STOP = {"fc", "cf", "afc", "sc", "ac", "as", "ssc", "us", "sv", "vfb", "vfl", "tsg", "fsv",
         "rcd", "ca", "cd", "ud", "sd", "rc", "ogc", "losc", "stade", "olympique", "club",
         "de", "the", "1", "04", "05", "1899", "1846", "1907", "1910", "1913", "ks", "sk",
         "calcio", "bc", "hsc", "real club", "sp", "s.a.d", "ssd"}

# ręczne aliasy (klucz: znormalizowana nazwa z dowolnego źródła -> nazwa kanoniczna)
ALIASES_FILE = ROOT / "bot" / "aliases.json"
try:
    ALIASES = json.loads(ALIASES_FILE.read_text())
except Exception:  # noqa: BLE001
    ALIASES = {}


def norm(name: str) -> str:
    s = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode().lower()
    s = s.replace("&", " and ").replace("'", "")
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    toks = [t for t in s.split() if t not in _STOP]
    s = " ".join(toks) or s.strip()
    return ALIASES.get(s, s)


class Matcher:
    """Dopasowuje nazwy z obcego źródła do listy nazw kanonicznych."""

    def __init__(self, canonical):
        self.canon = list(dict.fromkeys(canonical))
        self.normed = {norm(c): c for c in self.canon}
        self.cache = {}

    def match(self, name, cutoff=82):
        if name in self.cache:
            return self.cache[name]
        n = norm(name)
        res = self.normed.get(n)
        if res is None and n:
            best = process.extractOne(n, list(self.normed), scorer=fuzz.token_set_ratio)
            if best and best[1] >= cutoff:
                # przy remisowych wynikach (np. "manchester") wymagamy też wysokiego ratio
                if fuzz.ratio(n, best[0]) >= 55 or len(n.split()) == 1 or len(best[0].split()) == 1:
                    res = self.normed[best[0]]
        self.cache[name] = res
        return res
