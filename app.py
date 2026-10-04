from fastapi import FastAPI, Request, Form, Cookie
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pathlib import Path

import db
from scenarios import SCENARIOS, DZWIGNIE, lista_scenariuszy

BASE = Path(__file__).parent
app = FastAPI(title="PhishWars")
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
templates = Jinja2Templates(directory=BASE / "templates")

COOKIE = "pw_session"


@app.on_event("startup")
def _startup():
    db.init_db()


# --- Pomocnicze --------------------------------------------------------------

def current_player(session: str | None):
    return db.player_by_session(session)


def room_of(player):
    conn = db.get_db()
    row = conn.execute("SELECT * FROM rooms WHERE id = ?", (player["room_id"],)).fetchone()
    conn.close()
    return row


def render(request, name, player=None, **ctx):
    base = {"request": request}
    if player is not None:
        base["player"] = player
        base["room"] = room_of(player)
    base.update(ctx)
    return templates.TemplateResponse(
        request=request,
        name=name,
        context=base,
    )



def need_login():
    return RedirectResponse("/", status_code=303)


# --- Wejscie / pokoj ---------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def home(request: Request, pw_session: str | None = Cookie(default=None)):
    player = current_player(pw_session)
    if player:
        return RedirectResponse("/inbox", status_code=303)
    return render(request, "home.html", error=request.query_params.get("error"))


@app.post("/room/create")
def room_create(name: str = Form(...), room_name: str = Form(...)):
    if not name.strip() or not room_name.strip():
        return RedirectResponse("/?error=Podaj+nazwe+pokoju+i+swoje+imie", status_code=303)
    room_id, code = db.create_room(room_name.strip())
    _, session = db.create_player(room_id, name.strip())
    resp = RedirectResponse("/inbox", status_code=303)
    resp.set_cookie(COOKIE, session, httponly=True, samesite="lax")
    return resp


@app.post("/room/join")
def room_join(name: str = Form(...), code: str = Form(...)):
    room = db.find_room_by_code(code)
    if room is None:
        return RedirectResponse("/?error=Nie+ma+pokoju+o+takim+kodzie", status_code=303)
    if not name.strip():
        return RedirectResponse("/?error=Podaj+swoje+imie", status_code=303)
    _, session = db.create_player(room["id"], name.strip())
    resp = RedirectResponse("/inbox", status_code=303)
    resp.set_cookie(COOKIE, session, httponly=True, samesite="lax")
    return resp


@app.get("/logout")
def logout():
    resp = RedirectResponse("/", status_code=303)
    resp.delete_cookie(COOKIE)
    return resp


# --- Kompozytor (atak) -------------------------------------------------------

@app.get("/compose", response_class=HTMLResponse)
def compose_get(request: Request, scenario: str | None = None,
                pw_session: str | None = Cookie(default=None)):
    player = current_player(pw_session)
    if not player:
        return need_login()
    klucz = scenario if scenario in SCENARIOS else "paczka"
    return render(
        request, "compose.html", player=player,
        cele=db.players_in_room(player["room_id"], exclude_id=player["id"]),
        scenariusze=lista_scenariuszy(),
        wybrany=klucz,
        s=SCENARIOS[klucz],
        dzwignie=DZWIGNIE,
    )


@app.post("/compose")
def compose_post(target_id: int = Form(...), scenario: str = Form(...),
                 sender_name: str = Form(...), subject: str = Form(...),
                 body: str = Form(...), link_label: str = Form(...),
                 pw_session: str | None = Cookie(default=None)):
    player = current_player(pw_session)
    if not player:
        return need_login()
    if target_id == player["id"]:
        return RedirectResponse("/compose?error=self", status_code=303)
    scenario = scenario if scenario in SCENARIOS else "open"
    db.create_challenge(
        room_id=player["room_id"], sender_id=player["id"], target_id=target_id,
        scenario=scenario, sender_name=sender_name.strip() or "Nieznany",
        subject=subject.strip() or "(bez tematu)", body=body.strip(),
        link_label=link_label.strip() or "Kliknij tutaj",
    )
    return RedirectResponse("/sent", status_code=303)


# --- Skrzynka odbiorcza (obrona) --------------------------------------------

@app.get("/inbox", response_class=HTMLResponse)
def inbox(request: Request, pw_session: str | None = Cookie(default=None)):
    player = current_player(pw_session)
    if not player:
        return need_login()
    return render(request, "inbox.html", player=player, wiadomosci=db.inbox_for(player["id"]))


@app.get("/m/{cid}", response_class=HTMLResponse)
def message(request: Request, cid: int, pw_session: str | None = Cookie(default=None)):
    player = current_player(pw_session)
    if not player:
        return need_login()
    c = db.challenge_by_id(cid)
    if c is None or c["target_id"] != player["id"]:
        return RedirectResponse("/inbox", status_code=303)
    return render(request, "message.html", player=player, c=c, s=SCENARIOS.get(c["scenario"]))


@app.get("/t/{token}", response_class=HTMLResponse)
def track(request: Request, token: str, pw_session: str | None = Cookie(default=None)):
    """Link sledzacy: rejestruje klikniecie, przyznaje punkt atakujacemu."""
    c = db.challenge_by_token(token)
    if c is None:
        return RedirectResponse("/", status_code=303)
    zaliczone = db.resolve_challenge(c["id"], "click")
    player = current_player(pw_session)
    return render(request, "phished.html", player=player, c=c,
                  s=SCENARIOS.get(c["scenario"]), zaliczone=zaliczone, dzwignie=DZWIGNIE)


@app.post("/report/{cid}")
def report(cid: int, pw_session: str | None = Cookie(default=None)):
    """Zgloszenie phishingu: przyznaje punkt obroncy (celowi)."""
    player = current_player(pw_session)
    if not player:
        return need_login()
    c = db.challenge_by_id(cid)
    if c is None or c["target_id"] != player["id"]:
        return RedirectResponse("/inbox", status_code=303)
    db.resolve_challenge(c["id"], "report")
    return RedirectResponse(f"/m/{cid}", status_code=303)


# --- Panel wyslanych (atakujacy) + ranking ----------------------------------

@app.get("/sent", response_class=HTMLResponse)
def sent(request: Request, pw_session: str | None = Cookie(default=None)):
    player = current_player(pw_session)
    if not player:
        return need_login()
    return render(request, "sent.html", player=player, wyslane=db.sent_by(player["id"]))


@app.get("/leaderboard", response_class=HTMLResponse)
def board(request: Request, pw_session: str | None = Cookie(default=None)):
    player = current_player(pw_session)
    if not player:
        return need_login()
    return render(request, "leaderboard.html", player=player,
                  ranking=db.leaderboard(player["room_id"]))
