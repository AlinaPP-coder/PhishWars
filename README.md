# PhishWars

Gamifikowany symulator phishingu w **petli zamknietej** (red team vs blue team) — narzedzie
treningowe security awareness. Gracze dolaczaja do pokoju, wysylaja sobie nawzajem maile-wyzwania
i zdobywaja punkty: nadawca za nabranie celu (klikniecie w link), cel za wykrycie phishingu.

> **Zasada bezpieczenstwa:** wszystko dzieje sie wewnatrz aplikacji. Zaden mail nie wychodzi
> na zewnatrz, link sledzacy tylko liczy klikniecie i pokazuje strone edukacyjna. Aplikacja
> nie zbiera hasel i nie podszywa sie pod realne marki.

## Uruchomienie

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app:app --reload
```

Aplikacja: http://127.0.0.1:8000
Baza (`phishwars.db`) tworzy sie sama przy pierwszym starcie. Reset = usun ten plik.

**Test wieloosobowy lokalnie:** otworz gre w kilku oknach incognito / roznych przegladarkach —
kazde okno to osobny gracz (tozsamosc trzymana w ciasteczku).

## Przeplyw gry

1. Jeden gracz **zaklada pokoj** → dostaje kod (np. `FOX-2931`).
2. Reszta **dolacza** kodem.
3. **Nowy atak:** wybierz cel + scenariusz, skorzystaj z podpowiedzi, napisz maila z `{link}`.
4. Cel w **Skrzynce** albo klika link (punkt dla nadawcy) albo zglasza phishing (punkt dla siebie).
5. **Ranking** aktualizuje sie na zywo (atak / obrona / razem).

## Struktura

| plik | rola |
|------|------|
| `app.py` | FastAPI: routing, sesje (ciasteczko), logika punktacji |
| `db.py` | SQLite: schema + operacje domenowe, funkcja `leaderboard()` |
| `scenarios.py` | 5 scenariuszy + dzwignie perswazji (rdzen edukacyjny) |
| `templates/` | widoki Jinja2 (autoescaping chroni przed XSS w tresci maili) |
| `static/style.css` | motyw graficzny |

## Gdzie rozbudowac

- **Punktacja:** stale `PKT_KLIK` / `PKT_WYKRYCIE` w `db.py`.
- **Scenariusze:** dopisz wpis w `SCENARIOS` w `scenarios.py` — reszta UI podepnie sie sama.
- **Rundy / limit czasu:** dodaj `round` do `rooms` i filtruj `challenges`.
- **Realne maile (opcjonalnie, poza zakresem MVP):** podmien krok „inbox" na wysylke przez
  API (Resend/SendGrid) — wtedy dochodzi SPF/DKIM/DMARC i trzeba zachowac zgody uczestnikow.
