"""Konfiguracja bota. Wszystko, co warto zmieniać, jest tutaj."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv():
    """Lokalnie: wczytuje klucze z pliku .env (w GitHub Actions są w Secrets)."""
    f = ROOT / ".env"
    if f.exists():
        for line in f.read_text().splitlines():
            k, sep, v = line.partition("=")
            if sep and k.strip() and not k.startswith("#") and v.strip():
                os.environ.setdefault(k.strip(), v.strip())


_load_dotenv()
STATE = ROOT / "state"
DOCS = ROOT / "docs"
CACHE = ROOT / ".cache"
TZ = "Europe/Warsaw"

# --- Ligi -------------------------------------------------------------------
# fdcuk  = kod pliku na football-data.co.uk (wyniki + kursy rynkowe)
# fdorg  = kod rozgrywek na football-data.org (terminarz, wyniki na żywo)
# odds   = klucz sportu w The Odds API
# tm     = (slug, kod) ligi na Transfermarkt (kontuzje, wartości kadr)
# us     = nazwa ligi na Understat (xG)
LEAGUES = {
    "EPL": dict(name="Premier League", flag="🏴", fdcuk="E0", fdorg="PL",
                odds="soccer_epl", tm=("premier-league", "GB1"), us="EPL", elo_country="ENG"),
    "LALIGA": dict(name="LaLiga", flag="🇪🇸", fdcuk="SP1", fdorg="PD",
                   odds="soccer_spain_la_liga", tm=("laliga", "ES1"), us="La_liga", elo_country="ESP"),
    "SERIEA": dict(name="Serie A", flag="🇮🇹", fdcuk="I1", fdorg="SA",
                   odds="soccer_italy_serie_a", tm=("serie-a", "IT1"), us="Serie_A", elo_country="ITA"),
    "BUNDES": dict(name="Bundesliga", flag="🇩🇪", fdcuk="D1", fdorg="BL1",
                   odds="soccer_germany_bundesliga", tm=("bundesliga", "L1"), us="Bundesliga", elo_country="DEU"),
    "LIGUE1": dict(name="Ligue 1", flag="🇫🇷", fdcuk="F1", fdorg="FL1",
                   odds="soccer_france_ligue_one", tm=("ligue-1", "FR1"), us="Ligue_1", elo_country="FRA"),
    "EKSTRA": dict(name="Ekstraklasa", flag="🇵🇱", fdcuk_extra="POL", fdorg=None,
                   odds="soccer_poland_ekstraklasa", tm=("pko-bp-ekstraklasa", "PL1"), us=None, elo_country="POL"),
    "UCL": dict(name="Liga Mistrzów", flag="⭐", cup=True, fdorg="CL",
                odds="soccer_uefa_champs_league", tm=None, us=None, elo_country=None),
}
DOMESTIC = [k for k, v in LEAGUES.items() if not v.get("cup")]

SEASONS_BACK = 3          # ile sezonów historii do modelu
XI = 0.0022               # zanikanie wagi meczów w czasie (na dzień; półokres ~10 mies.)
LEVEL_XI = 0.02           # zanik wagi dla poziomu goli ligi (mu), półokres ~35 dni; backtest: lepszy log-loss O2.5
LEVEL_PRIOR = 40.0        # ściąganie korekty poziomu do 0 przy małej liczbie świeżych meczów
XG_WEIGHT = 0.5           # udział xG w ocenie siły (0 = tylko gole, 1 = tylko xG)

# --- Typy -------------------------------------------------------------------
MARKET_WEIGHT = 0.9       # backtest 2022–27 (kursy zamknięcia): optimum log-loss 0.9–1.0 dla 1X2 i O/U
ODDS_MIN_INTERVAL_H = 11  # The Odds API: liga odświeżana max ~2x dziennie (budżet 500 kredytów/mies.)
ODDS_RESERVE = 25         # poniżej tylu kredytów nie pytamy (zostają zapisane kursy)
HORIZON_HOURS = int(os.getenv("HORIZON_HOURS", "40"))  # jak daleko w przód szukamy meczów
# Rynki, na których bot daje typy (single, kupony, długie). O/U i BTTS wyłączone do czasu,
# aż przejdą backtest z kursami zamknięcia (model zaniżał gole) – na stronie "model w kalibracji".
PICK_MARKETS = {"1", "X", "2", "1X", "X2", "12"}
MIN_EDGE = 0.03           # minimalna przewaga dla singla (3%)
MIN_PROB_SINGLE = 0.28
STS_MARGIN_DISCOUNT = 0.03  # kursy STS są zwykle ~3% niższe od średniej rynkowej
STS_TAX = 0.12            # podatek od stawki w Polsce
BIG_WIN_TAX_LIMIT = 2280  # wygrana powyżej tej kwoty -> 10% podatku dochodowego
LONG_COUPON_LEGS = (6, 12)
LONG_COUPON_STAKE = 2.0

# Korekta za kontuzje
INJURY_K_ATT = 0.45       # spadek ataku na 100% brakującej wartości kadry
INJURY_K_DEF = 0.35       # wzrost goli traconych
INJURY_CAP = 0.25         # maks. korekta lambdy

# --- Sekrety (GitHub Secrets) ----------------------------------------------
FDORG_KEY = os.getenv("FOOTBALL_DATA_ORG_KEY", "")
ODDS_API_KEY = os.getenv("ODDS_API_KEY", "")
API_FOOTBALL_KEY = os.getenv("API_FOOTBALL_KEY", "")
TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TG_CHAT = os.getenv("TELEGRAM_CHAT_ID", "")
BETS_KEY = os.getenv("BETS_ENCRYPTION_KEY", "")
SITE_URL = os.getenv("SITE_URL", "")

PREVIEW_DAYS = (3, 4)     # czwartek, piątek: dodatkowa zapowiedź weekendu (do niedzieli 23:59)
DAILY_HOUR = 9            # godzina porannych typów (czas polski)
PREMATCH_MIN = (60, 150)  # okno aktualizacji przed meczem (minuty)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")

NEWS_FEEDS = [
    "https://feeds.bbci.co.uk/sport/football/rss.xml",
    "https://www.skysports.com/rss/12040",
    "https://www.theguardian.com/football/rss",
    "https://sportowefakty.wp.pl/pilka-nozna/rss.xml",
    "https://weszlo.com/feed/",
    "https://www.marca.com/rss/futbol/primera-division.xml",
    "https://www.gazzetta.it/rss/calcio.xml",
    "https://newsfeed.kicker.de/news/bundesliga",
    "https://rmcsport.bfmtv.com/rss/football/",
]
INJURY_WORDS = [
    "injur", "injured", "ruled out", "doubt", "hamstring", "knee", "ankle", "suspend",
    "kontuzj", "uraz", "zawieszon", "pauzuje", "nie zagra", "wypada",
    "lesión", "lesionado", "baja", "infortun", "squalific", "verletz", "gesperrt", "ausfall",
    "blessé", "blessure", "suspendu", "forfait",
]
