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
  football-data.org v4 (klucz; terminarz, wyniki, terminarz LM + kraje drużyn `competitions/CL/teams`;
  limit czytany z nagłówków X-Requests-Available-Minute / X-RequestCounter-Reset w `fdorg_get`, 429 -> czekanie),
  Elo (`elo_ratings`: ClubElo -> elofootball.com `country.php` tylko dla potrzebnych krajów -> `state/elo.csv`),
  The Odds API (`odds_api`: tylko ligi z meczami w horyzoncie, liga max co ODDS_MIN_INTERVAL_H=11 h, stan i kursy
  w `state/odds_api.json`, loguje x-requests-remaining, poniżej ODDS_RESERVE=25 nie pyta; h2h+totals/eu = 2 kredyty),
  Understat xG (dwie metody: getLeagueData JSON i stary HTML).
  Stan źródeł na 2026-11-04 (przebiegi na żywo): football-data.co.uk OK (CSV z BOM -> utf-8-sig), football-data.org OK,
  The Odds API OK (klucze sportów sprawdzone przez /v4/sports, 57/57 meczów weekendu z kursami, ~12 kredytów/przebieg),
  Transfermarkt OK (kontuzje, wartości kadr, terminarz `gesamtspielplan` – zapasowy dla wszystkich lig, jedyny dla
  Ekstraklasy; godziny w CET), RSS OK. ClubElo: API Fixtures wyłączone na stałe, ranking zwraca 502 -> elofootball.
  Understat w przerwie technicznej („We will come back soon”) -> model bez xG (nieprzetestowany format getLeagueData).
  UWAGA: Transfermarkt zwraca HTTP 202 (ochrona anty-bot) z serwerów GitHub Actions – tam brak kontuzji i terminarza TM;
  terminarz w Actions: football-data.org (top 5, LM) + The Odds API `/events` (darmowe, 0 kredytów; Ekstraklasa).
  Kontuzje w Actions wymagałyby API-Football (API_FOOTBALL_KEY). Lokalnie TM działa. Elo pobierane tylko gdy jest LM.
  Kody krajów ujednolicone do ISO-3 (`country_code`: GER->DEU, POR->PRT...).
- `names.py` + `aliases.json` – ujednolicanie nazw drużyn między źródłami (kanoniczne = nazwy football-data.co.uk),
  fuzzy match rapidfuzz. Nowe niedopasowania -> dopisać alias.
- `model.py` – Dixon-Coles per liga: atak/obrona, przewaga gospodarzy, rho, waga czasowa XI=0.0022,
  ridge=2.0, cel = 50% gole + 50% xG (top 5). `markets()` liczy 1X2, DC, O/U 0.5–4.5, BTTS.
  `EloBridge` – LM: różnica Elo -> lambdy. k dopasowane (`fit_k_to_probs`) do prognoz 1X2 publikowanych przez
  elofootball (ta sama skala, RMSE ~0.02; zapis w `state/elo_probs.json`), zapas: `elo_scale_k` ze wzoru Elo/400.
  Regresja siła~Elo z lig tylko diagnostycznie – zaniża k (korelacja ~0.6). LM w `pipeline.UclStrength`: wszystkie
  drużyny z jednego rankingu Elo (dopasowanie w obrębie kraju z football-data.org); klub naszej ligi bez Elo ->
  Elo z regresji Elo~siła w lidze; brak danych -> mecz pominięty z ostrzeżeniem.
  Backtest (tests/backtest_openfootball.py, ~1700 meczów): log-loss 1X2 0.974 vs 1.048 bazowo.
- `fotmob.py` – FotMob `api/data/*` (bez klucza, działa z GitHub Actions): `day_matches`, `matchDetails` (skład
  przewidywany `predicted` / zastępczy `lastStarting11` / oficjalny `standard`, niedostępni z typem i powrotem,
  wartości rynkowe), `teams` (terminarz drużyny ze wszystkich rozgrywek), `leagues` (sezon – backtest).
  „Zwykła jedenastka” = najwięcej minut w 8 ostatnich meczach LIGOWYCH; minuty w `.cache/fm_minutes/` (zwięźle).
- `team_news.py` – kontekst kadrowy meczu, lista „dlaczego” (czynnik, opis, wpływ w pkt proc. lub None = info),
  efekt składu λ·exp(a·d_własne + b·d_rywala), d = −braki_ze_zwykłej_XI/11, LINEUP_A=0.179, LINEUP_B=−0.220
  (z backtestu), `reprice` – przeliczenie finalnych szans po potwierdzonych składach (zmiana względem rana).
- `injuries.py` – STARE: Transfermarkt (blokuje GitHub Actions – HTTP 202) i API-Football; nieużywane w pipeline.
  API-Football: klucz w Secrets, ALE darmowy plan nie ma bieżącego sezonu („try from 2022 to 2024”) – bezużyteczny.
- `news.py` – RSS (lista w config), dopasowanie newsów do drużyn, flaga "injury" po słowach kluczowych.
- `picks.py` – zdjęcie marży (metoda potęgowa), p = 0.1*model + 0.9*rynek (MARKET_WEIGHT=0.9 z backtestu),
  typy tylko na rynkach `PICK_MARKETS` (1X2, DC); O/U i BTTS „w kalibracji” (pole `calibrating`, bez typów),
  kurs STS szacowany jako rynek -3%, podatek 12% od stawki, "opłaca się od" = 1/(0.88*p).
  Typy: single (S1..), kupony 2–3 (K1..), długie za 2 zł: D1 "dużo zdarzeń" (6–12, kursy 1.18–1.6),
  D2 "duży przelicznik" (5–8, kursy 1.7–2.8), D3 „szalona” (15–20 zdarzeń tylko z prawdziwym kursem, max 1 na mecz,
  ligi przeplatane, wg najmniejszej straty wartości; gdy za mało – `long_skipped` z powodem). Gdy brak przewagi – single "najbliżej wartości" z oznaczeniem.
- `pipeline.py` – analyse(): historia -> modele -> Elo -> terminarz (horyzont 40 h) -> kontuzje/newsy ->
  prawdopodobieństwa -> typy. `match_id` = `LIGA:data:home-away` (znormalizowane). collect_results() do rozliczeń.
- `tracker.py` – `state/record.json` (publiczny rejestr typów + kalibracja vs rynek),
  `state/bets.enc` (zakłady użytkownika, Fernet, klucz BETS_ENCRYPTION_KEY – repo jest publiczne!).
- `telegram.py` – wysyłka + komendy czytane przez getUpdates przy każdym przebiegu:
  /typy /zagrane ID stawka kurs /zagrane wlasny ... /wynik nr w|p /usun nr /bilans /model. Tylko TELEGRAM_CHAT_ID.
- `message.py` – treść wiadomości. `site.py` + `template.html` – statyczna strona `docs/index.html`
  (zakładki Typy/Mecze/Skuteczność/Jak to działa, pole "Twój kurs w STS" liczy wartość po podatku).
- `main.py` – tryby: auto (co godzinę: komendy, typy o 9:00 PL raz dziennie NA DZIŚ (do 23:59), w czw/pt dodatkowo
  `preview` – zapowiedź weekendu do niedzieli, ID z prefiksem W: WS1/WK1/WD1, plik `picks_preview.json`,
  komenda /weekend; `lineups` – potwierdzone składy 35–80 min przed meczem (FotMob), alert ≥3 pkt proc.
  (LINEUP_ALERT_PP) z listą braków i powodem; rozliczenia, alert przed meczem
  60–150 min jeśli nowy news o kontuzji, strona), daily, settle, site, commands. `--no-send` = bez Telegrama.

## GitHub Actions (`.github/workflows/bot.yml`)
Cron co 15 min (:02/:17/:32/:47 – składy przed meczem), commituje `state/` i `docs/`; cache `.cache` z kluczem
godzinowym. Sekrety: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
FOOTBALL_DATA_ORG_KEY, BETS_ENCRYPTION_KEY, opcjonalnie ODDS_API_KEY, API_FOOTBALL_KEY.
Pages: main /docs. Workflow permissions: read/write.

## Testy
- `python tests/offline_demo.py` – pełny przebieg bez internetu (wymaga danych openfootball w /home/claude/data –
  lokalnie podmień ścieżkę albo pobierz z raw.githubusercontent.com/openfootball/football.json/master/{sezon}/{en.1,...}.json).
- `python -m bot.main daily --no-send` – prawdziwy przebieg.

## Do zrobienia (priorytety)
0. BACKTEST (2026-11-04, `tests/backtest_closing.py`, walk-forward co tydzień, ~8 900 meczów 2022/23–2026/27,
   kursy zamknięcia AvgC; parametry dobierane na 2022–25, raport na 2025–27):
   - log-loss 1X2: model 0.997 vs rynek zamknięcia 0.976; O2.5: model 0.679 vs rynek 0.666 -> optimum
     MARKET_WEIGHT 0.9–1.0 dla obu rynków (ustawione 0.9).
   - single „z przewagą”: ROI poza próbą ujemne w każdej konfiguracji (1X2 −4…−13% przed podatkiem,
     −18…−26% po STS+podatku; O/U −24…−51%). Żaden MIN_EDGE nie daje ROI ≥ 0 -> O/U zostaje wyłączone.
   - poziom goli: LEVEL_XI=0.02 (osobny zanik dla mu) minimalnie lepszy log-loss O2.5 (0.6794 -> 0.6788) – włączone;
     korekta tylko z bieżącego sezonu – bez poprawy. Kalibracja Platta O2.5 poprawia test (0.6848 -> 0.6806),
     izotoniczna 0.6823 – nie wdrożone (wciąż daleko od rynku 0.668). Bias O2.5 głównie w sezonie 2026/27.
   Każda zmiana z Etapu 2 musi poprawić ten backtest (log-loss 1X2 i O2.5).
   ETAP 2 (2026-11-04, `tests/backtest_lineups.py`, 4080 meczów 2024/25–2026/27 ze składami FotMob, poza próbą
   leave-one-season-out): liczba braków ze „zwykłej XI” poprawia log-loss 1X2 0.9994 -> 0.9982 i O2.5
   0.6836 -> 0.6830 (w każdym sezonie) – WDROŻONE. Zmiana WARTOŚCI XI pogarszała (1.0011) – odrzucona.
   Kontuzji samych nie da się zbacktestować (FotMob nie trzyma listy niedostępnych dla rozegranych meczów) –
   ich wpływ wchodzi przez przewidywaną XI. Zmęczenie: tylko informacja w „dlaczego” (bez backtestu wpływu).
   Pominięte decyzją użytkownika: model zawodników/FBref, tabela/derby/trener, ruch kursów, rynki poboczne.
   Historyczny opis problemu: model zaniżał O2.5 względem rynku o 5–11 pkt proc. w każdej lidze (w tym sezonie
   pada więcej goli niż w poprzednim, a XI ma półokres ~10 mies.) -> fałszywe „przewagi” na Poniżej 2.5 w singlach.
   Próba z szybszą wagą dla poziomu goli (półokres ~2 mies.) dała niespójny efekt na 40–70 meczach – cofnięta.
   Do rozstrzygnięcia w backteście z kursami zamknięcia (MARKET_WEIGHT/MIN_EDGE osobno dla 1X2 i O/U).
1. Sprawdzić Understat i ranking ClubElo, gdy wrócą.
2. Sprawdzić dopasowanie nazw (log ostrzeżeń, aliases.json), szczególnie Ekstraklasa i LM.
3. ZROBIONE: repo, Pages, sekrety (TELEGRAM_*, FOOTBALL_DATA_ORG_KEY, ODDS_API_KEY, BETS_ENCRYPTION_KEY);
   lokalnie klucze w `.env` (ignorowany, wczytywany przez config.py). Bot: @mateusz_typy_bot.
4. Potem: kalibracja MARKET_WEIGHT na danych z kursami zamknięcia (backtest z kursami z football-data.co.uk),
   ew. więcej rynków (rożne, kartki), Ekstraklasa xG.

## Zasady
- Uczciwość: nie obiecywać zysku; przy długich kuponach zawsze pokazywać szansę "1 na X" i oczekiwany zwrot.
- Nie scrapować STS (regulamin) – kurs STS użytkownik wpisuje ręcznie.
- Nie commitować sekretów ani `.cache/`.
