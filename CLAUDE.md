# TypyBot – kontekst projektu

Bot do analizy prawdopodobieństw meczów piłkarskich (top 5 lig, Ekstraklasa, Liga Mistrzów).
Właściciel gra w STS dla zabawy, stałą małą kwotą. Cel: narzędzie analityczne, nie "pewniaki".
Komunikacja z użytkownikiem i teksty w bocie: po polsku.

## Stan (v1, napisane w sesji Claude na claude.ai)
- Kod napisany i przetestowany OFFLINE (dane openfootball + sztuczne kursy). Pobieranie z prawdziwych
  źródeł NIE było testowane (sandbox bez internetu) – pierwsza rzecz do sprawdzenia i naprawy.
- Repo na GitHubie jeszcze NIE istnieje – do założenia: `gh repo create typy-bot --public --source=. --push`
  (publiczne, bo darmowe GitHub Pages).

## Architektura (`bot/`)
- `config.py` – WSZYSTKIE ustawienia: ligi i kody źródeł, wagi modelu, progi typów, sekrety z env, RSS.
- `data_sources.py` – pobieranie z cache w `.cache/`: football-data.co.uk (wyniki + kursy średnie/zamknięcia,
  CSV `mmz4281/{sezon}/{E0..}` i `new/POL.csv`, terminarz `fixtures.csv`/`new_league_fixtures.csv`),
  football-data.org v4 (klucz; terminarz, wyniki, jedyne źródło LM; limit 10/min), ClubElo (`api.clubelo.com`),
  The Odds API (opcjonalny klucz), Understat xG (dwie metody: getLeagueData JSON i stary HTML).
  Stan źródeł na 2026-11-04 (pierwszy przebieg na żywo): football-data.co.uk OK (CSV z BOM -> dekodowanie utf-8-sig),
  Transfermarkt OK (kontuzje, wartości kadr, terminarz `gesamtspielplan` – zapasowy dla wszystkich lig, jedyny dla
  Ekstraklasy; godziny w CET), RSS OK. ClubElo API Fixtures WYŁĄCZONE na stałe; ranking ClubElo bywa 502 ->
  fallback `state/clubelo.csv`. Understat był w przerwie technicznej (nieprzetestowany format getLeagueData).
- `names.py` + `aliases.json` – ujednolicanie nazw drużyn między źródłami (kanoniczne = nazwy football-data.co.uk),
  fuzzy match rapidfuzz. Nowe niedopasowania -> dopisać alias.
- `model.py` – Dixon-Coles per liga: atak/obrona, przewaga gospodarzy, rho, waga czasowa XI=0.0022,
  ridge=2.0, cel = 50% gole + 50% xG (top 5). `markets()` liczy 1X2, DC, O/U 0.5–4.5, BTTS.
  `EloBridge` – LM: regresja siły z modeli ligowych na Elo -> lambdy.
  Backtest (tests/backtest_openfootball.py, ~1700 meczów): log-loss 1X2 0.974 vs 1.048 bazowo.
- `injuries.py` – Transfermarkt (scraping tabel `verletztespieler` + wartości kadr) i opcjonalnie API-Football.
  Brakujący udział wartości kadry -> korekta lambd (INJURY_K_ATT/DEF, cap 25%). Absencje >45 dni ważą 0.4.
  Selektory HTML Transfermarkt są zgadywane – najpewniej do poprawy.
- `news.py` – RSS (lista w config), dopasowanie newsów do drużyn, flaga "injury" po słowach kluczowych.
- `picks.py` – zdjęcie marży (metoda potęgowa), p = 0.35*model + 0.65*rynek (MARKET_WEIGHT),
  kurs STS szacowany jako rynek -3%, podatek 12% od stawki, "opłaca się od" = 1/(0.88*p).
  Typy: single (S1..), kupony 2–3 (K1..), długie za 2 zł: D1 "dużo zdarzeń" (6–12, kursy 1.18–1.6),
  D2 "duży przelicznik" (5–8, kursy 1.7–2.8). Gdy brak przewagi – single "najbliżej wartości" z oznaczeniem.
- `pipeline.py` – analyse(): historia -> modele -> Elo -> terminarz (horyzont 40 h) -> kontuzje/newsy ->
  prawdopodobieństwa -> typy. `match_id` = `LIGA:data:home-away` (znormalizowane). collect_results() do rozliczeń.
- `tracker.py` – `state/record.json` (publiczny rejestr typów + kalibracja vs rynek),
  `state/bets.enc` (zakłady użytkownika, Fernet, klucz BETS_ENCRYPTION_KEY – repo jest publiczne!).
- `telegram.py` – wysyłka + komendy czytane przez getUpdates przy każdym przebiegu:
  /typy /zagrane ID stawka kurs /zagrane wlasny ... /wynik nr w|p /usun nr /bilans /model. Tylko TELEGRAM_CHAT_ID.
- `message.py` – treść wiadomości. `site.py` + `template.html` – statyczna strona `docs/index.html`
  (zakładki Typy/Mecze/Skuteczność/Jak to działa, pole "Twój kurs w STS" liczy wartość po podatku).
- `main.py` – tryby: auto (co godzinę: komendy, typy o 9:00 PL raz dziennie, rozliczenia, alert przed meczem
  60–150 min jeśli nowy news o kontuzji, strona), daily, settle, site, commands. `--no-send` = bez Telegrama.

## GitHub Actions (`.github/workflows/bot.yml`)
Cron co godzinę (:17), commituje `state/` i `docs/`. Sekrety: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
FOOTBALL_DATA_ORG_KEY, BETS_ENCRYPTION_KEY, opcjonalnie ODDS_API_KEY, API_FOOTBALL_KEY.
Pages: main /docs. Workflow permissions: read/write.

## Testy
- `python tests/offline_demo.py` – pełny przebieg bez internetu (wymaga danych openfootball w /home/claude/data –
  lokalnie podmień ścieżkę albo pobierz z raw.githubusercontent.com/openfootball/football.json/master/{sezon}/{en.1,...}.json).
- `python -m bot.main daily --no-send` – prawdziwy przebieg.

## Do zrobienia (priorytety)
1. Sprawdzić Understat i ranking ClubElo, gdy wrócą (LM wymaga Elo + klucza football-data.org).
2. Sprawdzić dopasowanie nazw (log ostrzeżeń, aliases.json), szczególnie Ekstraklasa i LM.
3. Założyć repo, Pages, sekrety; przeprowadzić użytkownika przez BotFather i klucz football-data.org.
4. Potem: kalibracja MARKET_WEIGHT na danych z kursami zamknięcia (backtest z kursami z football-data.co.uk),
   ew. więcej rynków (rożne, kartki), Ekstraklasa xG.

## Zasady
- Uczciwość: nie obiecywać zysku; przy długich kuponach zawsze pokazywać szansę "1 na X" i oczekiwany zwrot.
- Nie scrapować STS (regulamin) – kurs STS użytkownik wpisuje ręcznie.
- Nie commitować sekretów ani `.cache/`.
