"""Telegram Mini App: statik sahifa + JSON API (aiohttp).

Har bir API so'rovi `Authorization: tma <initData>` sarlavhasi bilan keladi va bot tokeni bilan
imzosi tekshiriladi (Telegram WebApp initData). To'g'ri javoblar faqat serverda saqlanadi,
mijozga har bir javobdan keyingina ochiladi.
"""
from __future__ import annotations

import logging
import os
import secrets
import time
from pathlib import Path

from aiogram.utils.web_app import safe_parse_webapp_init_data
from aiohttp import web

from bot import quiz
from bot.bank import QuestionBank
from bot.data import Catalog
from bot.db import XP_PASS_BONUS, XP_PER_CORRECT, ResultsDB, level_info
from claude_json import ClaudeError

log = logging.getLogger("web")
STATIC = Path(__file__).resolve().parent.parent / "webapp"
QUIZ_TTL = 3 * 3600
MAX_GENERATIONS = 30  # butun server bo'yicha bir vaqtda tuzilayotgan testlar


def has_ai() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"))


def build_app(*, token: str, catalog: Catalog, db: ResultsDB, claude, pass_percent: int,
              bank: QuestionBank | None = None) -> web.Application:
    bank = bank or QuestionBank(Path(__file__).resolve().parent.parent / "data" / "savollar")
    quizzes: dict[str, dict] = {}
    generating: set[int] = set()
    dev_user = os.getenv("WEBAPP_DEV_USER")  # faqat lokal sinov uchun (brauzerda Telegram'siz)

    def auth(request: web.Request) -> dict:
        h = request.headers.get("Authorization", "")
        if h.startswith("tma "):
            try:
                data = safe_parse_webapp_init_data(token, h[4:])
            except ValueError:
                raise web.HTTPUnauthorized(text="initData imzosi noto'g'ri")
            if time.time() - data.auth_date.timestamp() > 7 * 24 * 3600:
                raise web.HTTPUnauthorized(text="initData eskirgan")
            u = data.user
            name = " ".join(x for x in (u.first_name, u.last_name) if x)
            user = {"id": u.id, "name": name, "username": u.username or "", "photo": u.photo_url or ""}
        elif dev_user:
            user = {"id": int(dev_user), "name": "Sinov foydalanuvchi", "username": "", "photo": ""}
        else:
            raise web.HTTPUnauthorized(text="Telegram orqali oching")
        db.touch_user(user["id"], user["name"], user["username"], user["photo"])
        return user

    def cleanup() -> None:
        now = time.time()
        for k in [k for k, q in quizzes.items() if now - q["created"] > QUIZ_TTL]:
            quizzes.pop(k, None)

    # ---------------- sahifa ----------------
    async def index(_: web.Request) -> web.FileResponse:
        return web.FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})

    # ---------------- katalog ----------------
    async def api_catalog(request: web.Request) -> web.Response:
        auth(request)
        out = []
        for b in catalog.sohalar:
            out.append({"n": b["nomi"], "y": [
                {"k": y["kod"], "n": y["nomi"], "m": [
                    {"k": m["kod"], "n": m["nomi"], "f": len(m["fanlar"])} for m in y["mutaxassisliklar"]]}
                for y in b["yunalishlar"]]})
        return web.json_response({"yil": catalog.yil, "sohalar": out})

    async def api_fanlar(request: web.Request) -> web.Response:
        auth(request)
        try:
            bi, yi, mi = (int(request.query[k]) for k in ("b", "y", "m"))
            m = catalog.mutaxassislik(bi, yi, mi)
        except (KeyError, ValueError, IndexError):
            raise web.HTTPBadRequest(text="noto'g'ri manzil")
        return web.json_response({
            "kod": m["kod"], "nomi": m["nomi"], "url": m["url"],
            "fanlar": [{"kod": f.get("kod", ""), "nomi": f["nomi"], "blok": f.get("blok", ""),
                        "soat": f.get("soat", ""), "dastur": bool(f.get("mazmun") or f.get("natijalar")),
                        "bank": bank.match(f["nomi"], f.get("kod", "")) is not None}
                       for f in m["fanlar"]],
        })

    # ---------------- profil ----------------
    async def api_me(request: web.Request) -> web.Response:
        u = auth(request)
        p = db.profile(u["id"])
        p["history"] = [{"vaqt": v, "fan": f, "togri": t, "jami": j, "foiz": pc} for v, f, t, j, pc in p["history"]]
        p["pass_percent"] = pass_percent
        return web.json_response(p)

    async def api_checkin(request: web.Request) -> web.Response:
        u = auth(request)
        res = db.checkin(u["id"])
        return web.json_response({**res, "profile": db.profile(u["id"]) | {"history": []}})

    async def api_leaderboard(request: web.Request) -> web.Response:
        u = auth(request)
        rows = db.leaderboard(50)
        me = db.profile(u["id"])
        return web.json_response({"top": rows, "me": {"user_id": u["id"], "name": u["name"], "photo": u["photo"],
                                                     "xp": me["xp"], "rank": me["rank"],
                                                     "level": me["level"]["level"]}})

    # ---------------- test ----------------
    async def api_bank(request: web.Request) -> web.Response:
        auth(request)
        return web.json_response({"fanlar": bank.listing()})

    async def api_quiz_new(request: web.Request) -> web.Response:
        u = auth(request)
        cleanup()
        body = await request.json()
        try:
            soni = int(body.get("soni", 10))
        except (ValueError, TypeError):
            raise web.HTTPBadRequest(text="noto'g'ri so'rov")
        if soni not in (10, 20, 30):
            raise web.HTTPBadRequest(text="savollar soni 10, 20 yoki 30 bo'lishi kerak")

        m = y = None
        if body.get("bank"):  # to'g'ridan-to'g'ri "Attestatsiya fanlari" bo'limidan
            sid = str(body["bank"])
            if sid not in bank.subjects:
                raise web.HTTPBadRequest(text="fan topilmadi")
            f = {"nomi": bank.subjects[sid]["nomi"]}
        else:
            try:
                bi, yi, mi = int(body["b"]), int(body["y"]), int(body["m"])
                m = catalog.mutaxassislik(bi, yi, mi)
                y = catalog.yunalish(bi, yi)
            except (KeyError, ValueError, IndexError, TypeError):
                raise web.HTTPBadRequest(text="noto'g'ri so'rov")
            fi = body.get("f")
            if fi is not None:
                try:
                    f = m["fanlar"][int(fi)]
                except (ValueError, IndexError, TypeError):
                    raise web.HTTPBadRequest(text="fan topilmadi")
            else:
                nomi = " ".join(str(body.get("fan", "")).split())[:150]
                if len(nomi) < 3:
                    raise web.HTTPBadRequest(text="fan nomini kiriting")
                f = {"nomi": nomi}
            sid = bank.match(f["nomi"], f.get("kod", ""))
        mutax = f"{m['kod']} {m['nomi']}" if m else "Attestatsiya fanlari"

        if sid:  # tayyor savollar bazasi — API kaliti kerak emas
            qs = bank.draw(sid, soni)
            fan_nomi = bank.subjects[sid]["nomi"]
        elif has_ai():
            if u["id"] in generating:
                raise web.HTTPTooManyRequests(text="Oldingi test hali tayyorlanmoqda")
            if len(generating) >= MAX_GENERATIONS:
                raise web.HTTPServiceUnavailable(text="Server band, birozdan so'ng urinib ko'ring")
            generating.add(u["id"])
            try:
                qs = await quiz.generate(claude, fan=f["nomi"], blok=f.get("blok", ""),
                                         natijalar=f.get("natijalar", ""), mazmun=f.get("mazmun", ""),
                                         mutaxassislik=mutax, yunalish=f"{y['kod']} {y['nomi']}" if y else "",
                                         soni=soni)
            except ClaudeError as e:
                raise web.HTTPBadGateway(text=str(e))
            finally:
                generating.discard(u["id"])
            fan_nomi = f["nomi"]
        else:
            raise web.HTTPNotFound(text=f"\"{f['nomi']}\" fani bo'yicha tayyor savollar hali yo'q. "
                                        "\"Attestatsiya fanlari\" bo'limidagi fanlardan birini tanlang.")
        qid = secrets.token_urlsafe(12)
        quizzes[qid] = {"user": u["id"], "name": u["name"], "fan": fan_nomi,
                        "mutaxassislik": mutax, "qs": qs, "answers": {},
                        "created": time.time(), "done": False}
        return web.json_response({
            "id": qid, "fan": fan_nomi, "mutaxassislik": mutax, "bank": bool(sid),
            "savollar": [{"savol": q["savol"], "variantlar": q["variantlar"], "bolim": q.get("bolim", "")}
                         for q in qs],
        })

    def get_quiz(u: dict, qid: str) -> dict:
        q = quizzes.get(qid)
        if not q or q["user"] != u["id"]:
            raise web.HTTPNotFound(text="test topilmadi yoki muddati o'tgan")
        return q

    async def api_quiz_answer(request: web.Request) -> web.Response:
        u = auth(request)
        body = await request.json()
        q = get_quiz(u, str(body.get("id", "")))
        try:
            i, choice = int(body["i"]), int(body["javob"])
            item = q["qs"][i]
        except (KeyError, ValueError, IndexError, TypeError):
            raise web.HTTPBadRequest(text="noto'g'ri javob")
        if q["done"]:
            raise web.HTTPConflict(text="test yakunlangan")
        if i in q["answers"]:
            choice = q["answers"][i]  # qayta yuborilsa, birinchi javob hisobga olinadi
        elif not 0 <= choice <= 3:
            raise web.HTTPBadRequest(text="variant 0..3")
        else:
            q["answers"][i] = choice
        return web.json_response({"togri": item["togri"], "correct": choice == item["togri"], "izoh": item["izoh"]})

    async def api_quiz_finish(request: web.Request) -> web.Response:
        u = auth(request)
        body = await request.json()
        q = get_quiz(u, str(body.get("id", "")))
        answered = len(q["answers"])
        if answered == 0:
            q["done"] = True
            return web.json_response({"saved": False})
        if not q["done"]:
            q["done"] = True
            score = sum(1 for i, c in q["answers"].items() if c == q["qs"][i]["togri"])
            pct = round(100 * score / answered, 1)
            passed = pct >= pass_percent and answered == len(q["qs"])
            gained = score * XP_PER_CORRECT + (XP_PASS_BONUS if passed else 0)
            before = db.profile(u["id"])["level"]["level"]
            db.save(u["id"], q["name"], q["mutaxassislik"], q["fan"], score, answered)
            xp = db.add_xp(u["id"], gained)
            q["result"] = {"togri": score, "jami": answered, "foiz": pct, "passed": passed,
                           "xp_gained": gained, "xp": xp, "level": level_info(xp),
                           "level_up": level_info(xp)["level"] > before,
                           "wrong": [{"savol": q["qs"][i]["savol"],
                                      "togri_javob": q["qs"][i]["variantlar"][q["qs"][i]["togri"]],
                                      "izoh": q["qs"][i]["izoh"]}
                                     for i in sorted(q["answers"]) if q["answers"][i] != q["qs"][i]["togri"]]}
        return web.json_response({"saved": True, **q["result"]})

    async def health(_: web.Request) -> web.Response:
        return web.Response(text="ok")

    app = web.Application(client_max_size=1024 * 1024)
    app.router.add_get("/", index)
    app.router.add_get("/health", health)
    app.router.add_get("/api/catalog", api_catalog)
    app.router.add_get("/api/fanlar", api_fanlar)
    app.router.add_get("/api/bank", api_bank)
    app.router.add_get("/api/me", api_me)
    app.router.add_post("/api/checkin", api_checkin)
    app.router.add_get("/api/leaderboard", api_leaderboard)
    app.router.add_post("/api/quiz", api_quiz_new)
    app.router.add_post("/api/quiz/answer", api_quiz_answer)
    app.router.add_post("/api/quiz/finish", api_quiz_finish)
    app.router.add_static("/static/", STATIC, show_index=False)
    return app
