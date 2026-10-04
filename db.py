"""
Warstwa dostepu do SQLite. Baza to jeden plik (phishwars.db).
Polaczenie otwieramy per-zadanie -- przy skali hackathonu to w zupelnosci wystarcza.
"""
import sqlite3
import secrets
from pathlib import Path

DB_PATH = Path(__file__).parent / "phishwars.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS rooms (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    code        TEXT UNIQUE NOT NULL,         -- kod dolaczenia, np. FOX-2931
    name        TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS players (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    room_id     INTEGER NOT NULL REFERENCES rooms(id),
    name        TEXT NOT NULL,
    session     TEXT UNIQUE NOT NULL,          -- token trzymany w ciasteczku = tozsamosc
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS challenges (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    room_id     INTEGER NOT NULL REFERENCES rooms(id),
    sender_id   INTEGER NOT NULL REFERENCES players(id),   -- atakujacy
    target_id   INTEGER NOT NULL REFERENCES players(id),   -- cel
    scenario    TEXT NOT NULL,
    sender_name TEXT NOT NULL,                 -- wyswietlana (fikcyjna) nazwa nadawcy
    subject     TEXT NOT NULL,
    body        TEXT NOT NULL,
    link_label  TEXT NOT NULL,                 -- napis na przycisku-linku
    token       TEXT UNIQUE NOT NULL,          -- token sledzacy: /t/<token>
    status      TEXT NOT NULL DEFAULT 'pending', -- pending | clicked | reported
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    challenge_id INTEGER NOT NULL REFERENCES challenges(id),
    type         TEXT NOT NULL,                -- click | report
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

# Punktacja
PKT_KLIK = 10     # atakujacy nabral cel
PKT_WYKRYCIE = 10  # cel wykryl phishing


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_db()
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()


def gen_room_code():
    """Czytelny kod pokoju, np. FOX-2931."""
    slowa = ["FOX", "OWL", "CAT", "JAY", "ELK", "RAM", "BEE", "KOI"]
    return f"{secrets.choice(slowa)}-{secrets.randbelow(9000) + 1000}"


def gen_token():
    return secrets.token_urlsafe(12)


# --- Operacje domenowe -------------------------------------------------------

def create_room(name):
    conn = get_db()
    # Gwarancja unikalnosci kodu
    for _ in range(10):
        code = gen_room_code()
        try:
            cur = conn.execute("INSERT INTO rooms (code, name) VALUES (?, ?)", (code, name))
            conn.commit()
            room_id = cur.lastrowid
            conn.close()
            return room_id, code
        except sqlite3.IntegrityError:
            continue
    conn.close()
    raise RuntimeError("Nie udalo sie wygenerowac unikalnego kodu pokoju")


def find_room_by_code(code):
    conn = get_db()
    row = conn.execute("SELECT * FROM rooms WHERE code = ?", (code.strip().upper(),)).fetchone()
    conn.close()
    return row


def create_player(room_id, name):
    conn = get_db()
    session = gen_token()
    cur = conn.execute(
        "INSERT INTO players (room_id, name, session) VALUES (?, ?, ?)",
        (room_id, name.strip(), session),
    )
    conn.commit()
    pid = cur.lastrowid
    conn.close()
    return pid, session


def player_by_session(session):
    if not session:
        return None
    conn = get_db()
    row = conn.execute("SELECT * FROM players WHERE session = ?", (session,)).fetchone()
    conn.close()
    return row


def players_in_room(room_id, exclude_id=None):
    conn = get_db()
    if exclude_id:
        rows = conn.execute(
            "SELECT * FROM players WHERE room_id = ? AND id != ? ORDER BY name",
            (room_id, exclude_id),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM players WHERE room_id = ? ORDER BY name", (room_id,)
        ).fetchall()
    conn.close()
    return rows


def create_challenge(room_id, sender_id, target_id, scenario, sender_name, subject, body, link_label):
    conn = get_db()
    token = gen_token()
    cur = conn.execute(
        """INSERT INTO challenges
           (room_id, sender_id, target_id, scenario, sender_name, subject, body, link_label, token)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (room_id, sender_id, target_id, scenario, sender_name, subject, body, link_label, token),
    )
    conn.commit()
    cid = cur.lastrowid
    conn.close()
    return cid, token


def inbox_for(player_id):
    """Wyzwania, w ktorych gracz jest celem (jego skrzynka odbiorcza)."""
    conn = get_db()
    rows = conn.execute(
        """SELECT c.*, p.name AS sender_real
           FROM challenges c JOIN players p ON p.id = c.sender_id
           WHERE c.target_id = ? ORDER BY c.created_at DESC""",
        (player_id,),
    ).fetchall()
    conn.close()
    return rows


def sent_by(player_id):
    """Wyzwania wyslane przez gracza (jego panel atakujacego)."""
    conn = get_db()
    rows = conn.execute(
        """SELECT c.*, p.name AS target_name
           FROM challenges c JOIN players p ON p.id = c.target_id
           WHERE c.sender_id = ? ORDER BY c.created_at DESC""",
        (player_id,),
    ).fetchall()
    conn.close()
    return rows


def challenge_by_id(cid):
    conn = get_db()
    row = conn.execute("SELECT * FROM challenges WHERE id = ?", (cid,)).fetchone()
    conn.close()
    return row


def challenge_by_token(token):
    conn = get_db()
    row = conn.execute("SELECT * FROM challenges WHERE token = ?", (token,)).fetchone()
    conn.close()
    return row


def resolve_challenge(cid, event_type):
    """
    Domyka wyzwanie JEDNYM zdarzeniem (resolve-once).
    Zwraca True jesli to zdarzenie faktycznie zaliczylo wynik,
    False jesli wyzwanie bylo juz rozstrzygniete wczesniej.
    """
    conn = get_db()
    row = conn.execute("SELECT status FROM challenges WHERE id = ?", (cid,)).fetchone()
    if row is None or row["status"] != "pending":
        conn.close()
        return False
    new_status = "clicked" if event_type == "click" else "reported"
    conn.execute("UPDATE challenges SET status = ? WHERE id = ?", (new_status, cid))
    conn.execute("INSERT INTO events (challenge_id, type) VALUES (?, ?)", (cid, event_type))
    conn.commit()
    conn.close()
    return True


def leaderboard(room_id):
    """
    Liczy punkty per gracz w pokoju:
      - atak:    PKT_KLIK za kazde wyzwanie ze statusem 'clicked', ktore gracz wyslal
      - obrona:  PKT_WYKRYCIE za kazde wyzwanie ze statusem 'reported', w ktorym byl celem
    """
    conn = get_db()
    players = conn.execute(
        "SELECT * FROM players WHERE room_id = ?", (room_id,)
    ).fetchall()
    wynik = []
    for p in players:
        klik = conn.execute(
            "SELECT COUNT(*) c FROM challenges WHERE sender_id = ? AND status = 'clicked'",
            (p["id"],),
        ).fetchone()["c"]
        wykr = conn.execute(
            "SELECT COUNT(*) c FROM challenges WHERE target_id = ? AND status = 'reported'",
            (p["id"],),
        ).fetchone()["c"]
        wynik.append({
            "name": p["name"],
            "atak": klik * PKT_KLIK,
            "obrona": wykr * PKT_WYKRYCIE,
            "razem": klik * PKT_KLIK + wykr * PKT_WYKRYCIE,
            "trafienia": klik,
            "wykrycia": wykr,
        })
    conn.close()
    wynik.sort(key=lambda x: x["razem"], reverse=True)
    return wynik
