# TypyBot ⚽

Samodzielny bot do analizy prawdopodobieństw w piłce nożnej (top 5 lig, Ekstraklasa, Liga Mistrzów).
Działa w GitHub Actions co godzinę. Codziennie rano wysyła typy na Telegram i publikuje analizę na GitHub Pages.

**To narzędzie do zabawy i nauki, nie maszynka do zarabiania.** Bukmacher ma marżę, w Polsce dochodzi 12% podatku od stawki,
a w kuponach łączonych marża mnoży się z każdym zdarzeniem. Bot mówi to wprost przy każdym typie.

## Co robi

| Krok | Źródło (darmowe) | Co z tego wynika |
|---|---|---|
| Wyniki, kursy rynkowe (średnie i zamknięcia) | football-data.co.uk | historia do modelu + kursy do porównania |
| xG (top 5 lig) | Understat | mniej szumu niż same gole |
| Terminarz, wyniki na bieżąco, Liga Mistrzów | football-data.org (klucz) | mecze i rozliczenia |
| Siła klubów między ligami | ClubElo | model meczów LM, terminarz Ekstraklasy |
| Kontuzje + wartości kadr | Transfermarkt (+ API-Football opcjonalnie) | korekta oczekiwanych goli |
| Newsy | RSS (BBC, Sky, Guardian, Sportowe Fakty, Weszło, Marca, Gazzetta, Kicker, RMC Sport) | kontekst + alert przed meczem |
| Kursy wielu bukmacherów | The Odds API (klucz, opcjonalnie) | świeższe kursy, Pinnacle |

**Model:** Dixon-Coles per liga (siła ataku/obrony, przewaga gospodarzy, korekta niskich wyników),
waga czasowa (nowsze mecze ważą więcej), w top 5 ligach cel to 50% gole + 50% xG.
Backtest na ~1700 meczach: log-loss 1X2 0,974 vs 1,048 dla częstości bazowych.
Liga Mistrzów: Elo → gole przez regresję na ligach krajowych.

**Typy:** finalna szansa = 35% model + 65% rynek (bez marży). Przy każdym typie:
- **fair** – kurs uczciwy (1/szansa),
- **opłaca się od** – kurs, od którego zakład ma wartość po 12% podatku,
- przewaga względem szacowanego kursu STS (średnia rynkowa − 3%).

Rodzaje: single z przewagą, kupony 2–3 zdarzenia, długie kupony za 2 zł
(„dużo zdarzeń” – 6–12 pewniejszych; „duży przelicznik” – 5–8 po ~2.0).

## Telegram

```
/typy                     dzisiejsze typy
/zagrane S1 10 2.05       zagrałem typ S1 za 10 zł po kursie STS 2.05
/zagrane D1 2 87.3        długi kupon
/zagrane wlasny 5 3.4 x   własny kupon (rozliczasz /wynik nr w|p)
/bilans                   Twój bilans i ROI
/model                    skuteczność modelu
```
Bot nie działa non stop: komendy czyta przy najbliższym przebiegu (do godziny).
Twoje zakłady są w `state/bets.enc`, zaszyfrowane kluczem z sekretów (repo jest publiczne).

## Uruchomienie (jednorazowo, ~15 min)

1. **Telegram:** napisz do [@BotFather](https://t.me/BotFather) → `/newbot` → skopiuj token.
   Napisz `/start` do swojego nowego bota.
2. **Klucze (darmowe):**
   - football-data.org → rejestracja na [football-data.org/client/register](https://www.football-data.org/client/register) (wymagany do LM)
   - The Odds API → [the-odds-api.com](https://the-odds-api.com) (opcjonalny, 500 zapytań/mies.)
   - API-Football → [dashboard.api-football.com](https://dashboard.api-football.com) (opcjonalny)
3. **Klucz szyfrujący zakłady:** `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
4. **GitHub → Settings → Secrets and variables → Actions → New repository secret:**
   `TELEGRAM_BOT_TOKEN`, `FOOTBALL_DATA_ORG_KEY`, `BETS_ENCRYPTION_KEY`, opcjonalnie `ODDS_API_KEY`, `API_FOOTBALL_KEY`.
5. **Actions → typy-bot → Run workflow** (mode `auto`). Bot odpisze na Telegramie Twoim `chat_id` →
   dodaj sekret `TELEGRAM_CHAT_ID`.
6. **Settings → Pages:** Deploy from a branch → `main` / `docs`.
7. **Settings → Actions → General → Workflow permissions:** Read and write.
8. Pierwsze typy: Actions → Run workflow, mode `daily`.

## Konfiguracja

Wszystko w `bot/config.py`: ligi, waga rynku, minimalna przewaga, długość kuponów, godzina typów,
siła korekty za kontuzje, lista kanałów RSS.

## Testy lokalne

```
pip install -r requirements.txt
python tests/backtest_openfootball.py /ścieżka/do/openfootball   # kalibracja modelu
python -m bot.main daily --no-send                                # pełny przebieg bez Telegrama
```
