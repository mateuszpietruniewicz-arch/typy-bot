# TypyBot – podsumowanie dla Mateusza

*Stan na 4 listopada 2026. Prostym językiem: co bot robi, jak z niego korzystać i czego się po nim spodziewać.*

---

## 1. Co to jest i jak działa

TypyBot to Twój prywatny asystent do analizy meczów piłkarskich: top 5 lig (Anglia, Hiszpania, Włochy, Niemcy, Francja), Ekstraklasa i Liga Mistrzów. Działa sam na serwerach GitHuba, co 15 minut, i pisze do Ciebie na Telegramie (@mateusz_typy_bot).

Dane bierze z darmowych źródeł: wyniki i kursy z ostatnich 3 sezonów, aktualne kursy wielu bukmacherów, terminarze, składy i kontuzje. Dla każdej ligi liczy model statystyczny, który na podstawie wyników ocenia siłę ataku i obrony każdej drużyny i przelicza ją na szanse wyników. Ostatnio grające składy też mają wpływ: brak zawodników, którzy zwykle grają, obniża szanse drużyny.

Potem bot porównuje swoje szanse z rynkiem, czyli kursami bukmacherów po usunięciu marży. Rynek okazał się w testach lepszy od modelu, więc ostateczna szansa to w **90% rynek i w 10% model**. Typy to zdarzenia, przy których ta szansa najlepiej wypada względem kursu. To narzędzie do analizy i zabawy, nie maszynka do zarabiania.

---

## 2. Co i kiedy przychodzi na Telegram

| Kiedy | Co przychodzi |
|---|---|
| **Codziennie ok. 9:00** | Typy na mecze **dzisiaj** (do 23:59): single, kupony, długie kupony i krótko „dlaczego” (składy, zmęczenie, braki). |
| **Czwartek i piątek ok. 9:00** | Dodatkowo **zapowiedź weekendu**: mecze do niedzieli, typy z literą **W** (WS1, WK1, WD1…). |
| **35–80 min przed meczem** | **Alert o składach**, ale tylko wtedy, gdy potwierdzone składy zmieniają szanse o co najmniej 3 punkty procentowe. Podaje, kogo brakuje i dlaczego (kontuzja, zawieszenie, rotacja) oraz szanse przed i po. |
| **1–2,5 h przed meczem** | Alert o newsie, jeśli przy meczu z typów pojawi się świeża wiadomość o kontuzji. |
| **Po meczach** | Rozliczenia: ✅/❌ dla typów bota i dla Twoich zagranych zakładów oraz aktualny bilans. |

GitHub czasem uruchamia bota z opóźnieniem 5–20 minut, więc „9:00” może oznaczać 9:15. Komendy, które wyślesz, bot czyta co ok. 15 minut. Nie odpowiada natychmiast.

---

## 3. Rodzaje typów i jak je czytać

| Oznaczenie | Co to jest |
|---|---|
| **S1, S2…** – single | Pojedynczy zakład na jeden mecz (1, X, 2 albo podwójna szansa). Najlepsze zdarzenia dnia. |
| **K1, K2** – kupony 2–3 | 2 lub 3 zdarzenia z różnych meczów, każde z szansą co najmniej 50%. |
| **D1** – „dużo zdarzeń” | Długi kupon za 2 zł: 6–12 pewniejszych zdarzeń (kursy ok. 1,18–1,6). |
| **D2** – „duży przelicznik” | Długi kupon za 2 zł: 5–8 zdarzeń po kursach ok. 1,7–2,8. |
| **D3** – „szalona” | Długi kupon za 2 zł: 15–20 zdarzeń z różnych lig, max 1 na mecz. Gdy danego dnia jest za mało meczów z kursami, D3 się nie pojawia, a bot pisze dlaczego. |
| **WS1, WK1, WD1, WD2, WD3** | To samo w zapowiedzi weekendu (czwartek i piątek). |

Na razie typy dotyczą tylko **1X2 i podwójnej szansy**. Rynki Powyżej/Poniżej goli są oznaczone jako **„model w kalibracji”**, bo nie przeszły testu (patrz punkt 6).

**Jak czytać liczby:**

- **szansa**: z jakim prawdopodobieństwem to się wydarzy według bota (90% rynek + 10% model). 60% znaczy, że w 10 takich sytuacjach zdarzy się średnio 6 razy.
- **fair**: uczciwy kurs bez marży i podatku, czyli 1 ÷ szansa. Przy szansie 50% fair to 2,00.
- **opłaca się od**: najniższy kurs w STS, przy którym zakład ma sens **po 12% podatku**, czyli 1 ÷ (0,88 × szansa). Przy szansie 50% to 2,27. Jeśli STS daje mniej, w długim okresie tracisz.
- **przewaga**: o ile szacowany kurs STS przebija fair. Wartość ujemna oznacza zakład bez przewagi (najczęstszy przypadek).
- **1 na X**: przy długich kuponach mówi, jak często kupon wchodzi. „1 na 139” znaczy, że średnio 1 raz na 139 prób.
- **średnio wraca**: ile przeciętnie wraca z 2 zł stawki po podatku i marży. „0,78 zł z 2 zł” oznacza, że na dłuższą metę z każdych 2 zł zostaje 78 groszy.

---

## 4. Jak grać z botem – krok po kroku

1. **Rano przeczytaj wiadomość** z typami albo wejdź na stronę (link w punkcie 8).
2. **Znajdź ten mecz w STS** i sprawdź kurs na to samo zdarzenie.
3. **Porównaj z „opłaca się od”:**
    - kurs STS **≥** „opłaca się od”: zakład ma sens matematycznie,
    - kurs STS **<** „opłaca się od”: odpuść albo graj świadomie „dla zabawy”.
    - Na stronie w zakładce Typy jest pole **„Twój kurs w STS”**: wpisz kurs, a strona policzy, czy się opłaca.
4. **Postaw stałą, małą kwotę**, zawsze tę samą.
5. **Zapisz zakład w bocie**, żeby liczył Twój bilans: `/zagrane S1 10 2.05`, czyli typ S1, stawka 10 zł, kurs w STS 2,05.
6. **Bot sam rozliczy** zakład po meczu i napisze wynik. Bilans sprawdzisz komendą `/bilans`.

---

## 5. Komendy Telegram

| Komenda | Co robi | Przykład |
|---|---|---|
| `/typy` | Pokazuje dzisiejsze typy jeszcze raz | `/typy` |
| `/weekend` | Pokazuje zapowiedź weekendu | `/weekend` |
| `/zagrane ID stawka kurs` | Zapisuje zagrany typ bota | `/zagrane S1 10 2.05` |
| | Długi kupon | `/zagrane D3 2 412000` |
| | Typ z weekendu | `/zagrane WK1 5 2.40` |
| | Typ z wcześniejszego dnia | `/zagrane 2026-11-07:S2 10 1.95` |
| `/zagrane wlasny stawka kurs opis` | Twój własny kupon spoza bota | `/zagrane wlasny 5 3.40 Legia+Lech` |
| `/wynik nr w` albo `/wynik nr p` | Ręczne rozliczenie własnego kuponu (w = wygrany, p = przegrany) | `/wynik 7 w` |
| `/usun nr` | Usuwa zakład nr 7 (np. pomyłka) | `/usun 7` |
| `/bilans` | Twój wynik: postawione, wypłacone, zysk/strata, ROI, co w grze | `/bilans` |
| `/model` | Skuteczność bota i porównanie model vs rynek | `/model` |
| `/pomoc` | Lista komend | `/pomoc` |

---

## 6. Uczciwe wyniki testu (backtest)

Bot został sprawdzony na **8 873 meczach z sezonów 2022/23–2026/27**. Dla każdego meczu liczył szanse tylko z danych sprzed meczu i porównywał je z kursami zamknięcia, czyli ostatnimi kursami przed gwizdkiem, które są najlepszą znaną oceną szans. Log-loss to „błąd prognozy”: im niżej, tym lepiej.

| Co porównujemy | Model bota | Rynek (bukmacherzy) |
|---|---|---|
| Wynik meczu 1X2 (log-loss) | 0,997 | **0,976** ✅ |
| Powyżej/Poniżej 2,5 gola (log-loss) | 0,679 | **0,666** ✅ |
| Single „z przewagą” – zwrot przed podatkiem | **od −4% do −13%** | – |
| Single „z przewagą” – zwrot po kursie STS i podatku | **ok. −18% do −26%** | – |
| Powyżej/Poniżej – zwrot (test) | **od −24% do −51%** | – |

Składy z FotMob poprawiły model (1X2: 0,9994 → 0,9982), ale to mała zmiana, a rynek nadal jest wyraźnie lepszy.

**Wniosek:** rynek przewiduje lepiej niż bot, a zakłady, w których bot widział „przewagę”, w teście przegrywały.

**Dlaczego w Polsce trudno wyjść na plus:** od każdej stawki państwo bierze 12% podatku, a bukmacher wbudowuje w kursy kilka procent marży. Przy kursie 2,00 trzeba więc trafiać ok. **57%** zakładów, żeby wyjść na zero, choć uczciwa szansa przy takim kursie to ok. 50%.

---

## 7. Skąd są dane i co może się zepsuć

| Źródło | Do czego | Czy oficjalne | Co się dzieje, gdy padnie |
|---|---|---|---|
| football-data.co.uk | Wyniki i kursy historyczne | darmowe pliki, stabilne | bot nie policzy modelu dla ligi i ją pominie |
| football-data.org | Terminarz, wyniki, Liga Mistrzów | oficjalne API (klucz) | brak meczów LM; ligi biorą terminarz z The Odds API |
| The Odds API | Aktualne kursy wielu bukmacherów | oficjalne API (klucz, **500 zapytań/mies.**) | brak kursów, a więc brak typów; bot oszczędza limit sam |
| **FotMob** | Składy, kontuzje, zawieszenia, minuty | **nieoficjalne**, może się zmienić | brak „dlaczego”, alertów o składach i korekty za braki; typy dalej działają |
| **elofootball.com** | Siła klubów do Ligi Mistrzów | **nieoficjalne** (strona www) | bot używa ostatniego zapisanego rankingu; bez niego pomija mecze LM |
| ClubElo | Siła klubów (główne źródło Elo) | nieoficjalne, **teraz nie działa** | zastępuje go elofootball |
| **Understat** | xG (jakość sytuacji) | **nieoficjalne**, **teraz przerwa techniczna** | model liczy na samych golach |
| Transfermarkt | Kontuzje, terminarz | blokuje serwery GitHuba | używany tylko lokalnie, zastępuje go FotMob |
| RSS (BBC, Sky, Guardian, Sportowe Fakty, Weszło, Marca, Gazzetta, Kicker, RMC) | Newsy | oficjalne kanały | brak newsów przy meczach |
| API-Football | – | klucz jest, ale darmowy plan nie obejmuje bieżącego sezonu | nieużywane |

**Gdy coś się zepsuje** (np. brak typów, dziwne liczby, błąd w Actions), otwórz Claude Code w folderze projektu i wklej:

> Przeczytaj CLAUDE.md. Sprawdź ostatnie przebiegi w GitHub Actions (gh run list, gh run view --log) i uruchom lokalnie `python -m bot.main daily --no-send`. Znajdź, które źródło danych przestało działać, napraw je i pokaż mi, co zmieniłeś. Commituj po naprawie.

Konkretnie dla FotMob:

> FotMob przestał działać (brak składów/„dlaczego”). Sprawdź, co zmieniło się w api/data/matchDetails i api/data/teams, popraw bot/fotmob.py i przetestuj na meczach z najbliższego dnia.

Gdy wróci Understat:

> Sprawdź, czy Understat działa. Jeśli tak, przetestuj pobieranie xG (bot/data_sources.py) i uruchom backtest tests/backtest_closing.py – zostaw xG tylko, jeśli poprawia log-loss.

---

## 8. Gdzie co jest

- **Strona z analizą:** https://mateuszpietruniewicz-arch.github.io/typy-bot/
- **Kod (repozytorium):** https://github.com/mateuszpietruniewicz-arch/typy-bot
- **Przebiegi bota (GitHub Actions):** https://github.com/mateuszpietruniewicz-arch/typy-bot/actions. Tu widać, czy bot działa; czerwony krzyżyk oznacza błąd. Przycisk „Run workflow” uruchamia bota ręcznie (tryby: auto, daily, preview, lineups, settle, site).
- **Folder projektu:** `~/Desktop/bukma`.

**Klucze (bez wartości – nigdy ich nikomu nie wysyłaj):**

- lokalnie: plik **`.env`** w folderze projektu (nie trafia do repozytorium),
- na GitHubie: **Settings → Secrets and variables → Actions**: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `FOOTBALL_DATA_ORG_KEY`, `ODDS_API_KEY`, `API_FOOTBALL_KEY`, `BETS_ENCRYPTION_KEY`.

⚠️ **Klucz szyfrujący zakładów (`BETS_ENCRYPTION_KEY`) musisz mieć w menedżerze haseł.** Repozytorium jest publiczne, więc Twoje zakłady są w nim zaszyfrowane (`state/bets.enc`). Bez tego klucza nikt, łącznie z Tobą, nie odczyta Twojego rejestru zakładów.

---

## 9. Co sprawdzić później (z gotowymi poleceniami dla Claude Code)

**Po pierwszym weekendzie:**

- Czy przyszły wszystkie wiadomości (typy, zapowiedź w czwartek i piątek, rozliczenia)?
- Czy przyszedł choć jeden alert o składach i czy miał sens?
- Czy `/bilans` liczy poprawnie Twoje zakłady?

> Przeczytaj CLAUDE.md. Sprawdź przebiegi Actions z weekendu: czy były błędy, ile trwały, ile kredytów The Odds API zostało (state/odds_api.json), czy alerty o składach zadziałały (logi „składy”). Pokaż mi krótkie podsumowanie i napraw, co nie działa.

**Po 2–3 tygodniach:**

> Przeanalizuj rejestr state/record.json: ile typów bota się rozliczyło, jaki jest wynik i ROI dla S, K, D1, D2, D3 osobno, ile trafień oczekiwano, a ile było, i porównaj log-loss modelu z rynkiem na tych meczach. Napisz po polsku prostym językiem, czy wyniki są w granicach przypadku, czy coś jest nie tak.

> Zaktualizuj backtest (tests/backtest_closing.py i tests/backtest_lineups.py) o nowe mecze i powiedz, czy MARKET_WEIGHT=0.9 i współczynniki składu nadal są dobre.

> Sprawdź, czy rynki Powyżej/Poniżej po kalibracji przechodzą backtest (ROI ≥ 0 poza próbą). Jeśli nie – zostaw je wyłączone.

**Gdy chcesz coś zmienić:**

> Zmień godzinę porannych typów na 8:00 (bot/config.py, DAILY_HOUR) i zrób commit.

---

## 10. Zasady

- **Gram dla zabawy**, nie dla zarobku. Bot nie obiecuje zysku, a test pokazał, że rynek wie więcej niż on.
- **Stała, mała kwota.** Zawsze ta sama, niezależnie od wygranych i przegranych. Nigdy nie odgrywam strat.
- **Długie kupony (D1, D2, D3) to loteria za 2 zł.** Patrz na „1 na X” i „średnio wraca”: to koszt rozrywki, nie inwestycja.
- **Gram tylko, gdy kurs w STS ≥ „opłaca się od”**, albo świadomie „dla zabawy”.
- Jeśli granie przestaje być zabawą: **Telefon Zaufania Uzależnień Behawioralnych 800 889 880** (bezpłatny) i strona https://uzaleznieniabehawioralne.pl/.
