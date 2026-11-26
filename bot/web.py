"""Telegram Mini App: sahifa + JSON API (aiohttp).

Har bir API so'rovi `Authorization: tma <initData>` bilan keladi va bot tokeni bilan imzosi
tekshiriladi. To'g'ri javoblar faqat serverda saqlanadi. Bepul foydalanuvchiga FREE_QUESTIONS
ta savol beriladi, keyin premium (faollashtirish kodi) kerak bo'ladi.
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
from bot.db import ResultsDB
from bot.premium import Premium
from claude_json import ClaudeError

log = logging.getLogger("web")
STATIC = Path(__file__).resolve().parent.parent / "webapp"
QUIZ_TTL = 4 * 3600
MAX_GENERATIONS = 30
EXAM_SECONDS_PER_Q = 120  # rasmiy spetsifikatsiya: 40 ta topshiriq — 80 daqiqa


def has_ai() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"))


def build_app(*, token: str, catalog: Catalog, db: ResultsDB, claude, pass_percent: int,
              bank: QuestionBank, premium: Premium) -> web.Application:
    quizzes: dict[str, dict] = {}
    generating: set[int] = set()
    dev_user = os.getenv("WEBAPP_DEV_USER")  # faqat lokal sinov uchun

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
            user = {"id": u.id, "name": " ".join(x for x in (u.first_name, u.last_name) if x),
                    "username": u.username or ""}
        elif dev_user:
            user = {"id": int(dev_user), "name": "Sinov foydalanuvchi", "username": ""}
        else:
            raise web.HTTPUnauthorized(text="Telegram orqali oching")
        db.touch_user(user["id"], user["name"], user["username"])
        return user

    def cleanup() -> None:
        t = time.time()
        for k in [k for k, q in quizzes.items() if t - q["created"] > QUIZ_TTL]:
            quizzes.pop(k, None)

    def status(uid: int) -> dict:
        until = db.premium_until(uid)
        used = db.answered_count(uid)
        return {"premium": bool(until), "premium_until": until.strftime("%d.%m.%Y") if until else None,
                "free_left": max(0, premium.free_questions - used) if not until else None,
                "pending": db.pending_payment(uid)}

    async def index(_: web.Request) -> web.FileResponse:
        return web.FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})

    async def health(_: web.Request) -> web.Response:
        return web.Response(text="ok")

    # ---------------- katalog ----------------
    async def api_catalog(request: web.Request) -> web.Response:
        auth(request)
        return web.json_response({"yil": catalog.yil, "sohalar": [
            {"n": b["nomi"], "y": [{"k": y["kod"], "n": y["nomi"], "m": [
                {"k": m["kod"], "n": m["nomi"], "f": len(m["fanlar"])} for m in y["mutaxassisliklar"]]}
                for y in b["yunalishlar"]]} for b in catalog.sohalar]})

    async def api_fanlar(request: web.Request) -> web.Response:
        auth(request)
        try:
            m = catalog.mutaxassislik(*(int(request.query[k]) for k in ("b", "y", "m")))
        except (KeyError, ValueError, IndexError, TypeError):
            raise web.HTTPBadRequest(text="noto'g'ri manzil")
        return web.json_response({"kod": m["kod"], "nomi": m["nomi"], "fanlar": [
            {"kod": f.get("kod", ""), "nomi": f["nomi"], "blok": f.get("blok", ""), "soat": f.get("soat", ""),
             "bank": bank.match(f["nomi"], f.get("kod", ""))} for f in m["fanlar"]]})

    async def api_bank(request: web.Request) -> web.Response:
        auth(request)
        return web.json_response({"fanlar": bank.listing()})

    # ---------------- profil va tahlil ----------------
    async def api_me(request: web.Request) -> web.Response:
        u = auth(request)
        a = db.analytics(u["id"])
        names = {s["id"]: s["nomi"] for s in bank.listing()}
        for f in a["fanlar"]:
            f["nomi"] = names.get(f["sid"], f["sid"])
            f["bazada"] = len(bank.subjects[f["sid"]]["savollar"]) if f["sid"] in bank.subjects else 0
            f["xatolar"] = len(db.wrong_qids(u["id"], f["sid"]))
        for b in a["bolimlar"]:
            b["fan"] = names.get(b["sid"], b["sid"])
        return web.json_response({
            "name": u["name"], "id": u["id"], **status(u["id"]), "pass_percent": pass_percent,
            "free_questions": premium.free_questions, "tariflar": premium.public_plans(),
            "karta": premium.card, "karta_egasi": premium.card_owner, "admin": premium.admin_contact,
            "imtihon_sanasi": premium.exam_date, "tahlil": a,
        })

    async def api_code(request: web.Request) -> web.Response:
        u = auth(request)
        body = await request.json()
        ok, msg, _ = db.redeem_code(u["id"], str(body.get("code", ""))[:40])
        if ok:
            await premium.notify_admins(f"🔑 Kod ishlatildi: {u['name']} (id {u['id']}) — {msg}")
        return web.json_response({"ok": ok, "message": msg, **status(u["id"])}, status=200 if ok else 400)

    async def api_payment(request: web.Request) -> web.Response:
        u = auth(request)
        reader = await request.multipart()
        tarif, photo, fname = "", b"", "chek.jpg"
        async for part in reader:
            if part.name == "tarif":
                tarif = (await part.text())[:20]
            elif part.name == "chek":
                fname = part.filename or fname
                photo = await part.read(decode=False)
        if tarif not in premium.plans:
            raise web.HTTPBadRequest(text="Tarifni tanlang")
        if not photo or len(photo) > 8 * 1024 * 1024:
            raise web.HTTPBadRequest(text="Chek rasmini yuklang (8 MB gacha)")
        if db.pending_payment(u["id"]):
            raise web.HTTPConflict(text="Oldingi chekingiz hali ko'rib chiqilmoqda")
        await premium.submit_receipt(u, tarif, photo=photo, filename=fname)
        return web.json_response({"ok": True, **status(u["id"])})

    # ---------------- test ----------------
    async def api_quiz_new(request: web.Request) -> web.Response:
        u = auth(request)
        cleanup()
        body = await request.json()
        rejim = str(body.get("rejim", "mashq"))
        if rejim not in ("mashq", "imtihon", "xatolar"):
            raise web.HTTPBadRequest(text="noto'g'ri rejim")
        try:
            soni = int(body.get("soni", 10))
        except (ValueError, TypeError):
            raise web.HTTPBadRequest(text="noto'g'ri so'rov")
        st = status(u["id"])
        if not st["premium"]:
            if rejim != "mashq":
                raise web.HTTPPaymentRequired(text="Bu rejim faqat premium foydalanuvchilar uchun")
            if st["free_left"] <= 0:
                raise web.HTTPPaymentRequired(text="Bepul savollar tugadi. Davom etish uchun premium oling.")
            soni = min(soni, st["free_left"])
        soni = max(1, min(soni, 40))

        m = y = None
        if body.get("bank"):
            sid = str(body["bank"])
            if sid not in bank.subjects:
                raise web.HTTPBadRequest(text="fan topilmadi")
            f = {"nomi": bank.subjects[sid]["nomi"]}
        else:
            try:
                bi, yi, mi = int(body["b"]), int(body["y"]), int(body["m"])
                m, y = catalog.mutaxassislik(bi, yi, mi), catalog.yunalish(bi, yi)
            except (KeyError, ValueError, IndexError, TypeError):
                raise web.HTTPBadRequest(text="noto'g'ri so'rov")
            if body.get("f") is not None:
                try:
                    f = m["fanlar"][int(body["f"])]
                except (ValueError, IndexError, TypeError):
                    raise web.HTTPBadRequest(text="fan topilmadi")
            else:
                nomi = " ".join(str(body.get("fan", "")).split())[:150]
                if len(nomi) < 3:
                    raise web.HTTPBadRequest(text="fan nomini kiriting")
                f = {"nomi": nomi}
            sid = bank.match(f["nomi"], f.get("kod", ""))

        if sid:
            only = None
            if rejim == "xatolar":
                only = db.wrong_qids(u["id"], sid)
                if not only:
                    raise web.HTTPNotFound(text="Bu fanda xato javoblaringiz yo'q — ajoyib!")
            if rejim == "imtihon":
                soni = 40
            qs = bank.draw(sid, soni, only=only)
            fan_nomi = bank.subjects[sid]["nomi"]
        elif has_ai() and st["premium"] and rejim == "mashq":
            if u["id"] in generating or len(generating) >= MAX_GENERATIONS:
                raise web.HTTPTooManyRequests(text="Test tayyorlanmoqda, birozdan so'ng urinib ko'ring")
            generating.add(u["id"])
            try:
                qs = await quiz.generate(claude, fan=f["nomi"], blok=f.get("blok", ""),
                                         mutaxassislik=f"{m['kod']} {m['nomi']}" if m else "",
                                         yunalish=f"{y['kod']} {y['nomi']}" if y else "", soni=soni)
            except ClaudeError as e:
                raise web.HTTPBadGateway(text=str(e))
            finally:
                generating.discard(u["id"])
            for i, q in enumerate(qs):
                q.update(qid=f"ai:{i}", sid="", bolim="")
            fan_nomi = f["nomi"]
        else:
            raise web.HTTPNotFound(text=f"\"{f['nomi']}\" fani bo'yicha tayyor savollar hali yo'q. "
                                        "\"Attestatsiya fanlari\" ro'yxatidagi fanlardan birini tanlang.")
        qid = secrets.token_urlsafe(12)
        limit = len(qs) * EXAM_SECONDS_PER_Q if rejim == "imtihon" else None
        quizzes[qid] = {"user": u["id"], "fan": fan_nomi, "sid": sid or "", "rejim": rejim, "qs": qs,
                        "answers": {}, "created": time.time(), "limit": limit, "done": False,
                        "trial": not st["premium"]}
        return web.json_response({
            "id": qid, "fan": fan_nomi, "rejim": rejim, "vaqt_limit": limit, "trial": not st["premium"],
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
        if q["limit"] and time.time() - q["created"] > q["limit"] + 30:
            raise web.HTTPConflict(text="Imtihon vaqti tugadi")
        if not 0 <= choice <= 3:
            raise web.HTTPBadRequest(text="variant 0..3")
        if i not in q["answers"]:
            if q["trial"] and not db.premium_until(u["id"]) and db.answered_count(u["id"]) >= premium.free_questions:
                raise web.HTTPPaymentRequired(text="Bepul savollar tugadi. Davom etish uchun premium oling.")
            q["answers"][i] = choice
            db.record_answer(u["id"], item.get("sid", ""), item.get("qid", ""), item.get("bolim", ""),
                             choice == item["togri"])
        choice = q["answers"][i]
        if q["rejim"] == "imtihon":  # imtihon rejimida javoblar oxirida ochiladi
            return web.json_response({"saqlandi": True})
        return web.json_response({"togri": item["togri"], "correct": choice == item["togri"], "izoh": item["izoh"]})

    async def api_quiz_finish(request: web.Request) -> web.Response:
        u = auth(request)
        body = await request.json()
        q = get_quiz(u, str(body.get("id", "")))
        if not q["answers"]:
            q["done"] = True
            return web.json_response({"saved": False})
        if not q["done"]:
            q["done"] = True
            jami = len(q["qs"]) if q["rejim"] == "imtihon" else len(q["answers"])
            score = sum(1 for i, c in q["answers"].items() if c == q["qs"][i]["togri"])
            pct = round(100 * score / jami, 1)
            db.save(u["id"], q["fan"], score, jami, q["sid"], q["rejim"])
            bol: dict[str, list[int]] = {}
            for i, it in enumerate(q["qs"]):
                if i in q["answers"] or q["rejim"] == "imtihon":
                    b = bol.setdefault(it.get("bolim") or "Umumiy", [0, 0])
                    b[1] += 1
                    b[0] += int(q["answers"].get(i) == it["togri"])
            q["result"] = {
                "togri": score, "jami": jami, "foiz": pct, "passed": pct >= pass_percent, "rejim": q["rejim"],
                "ball": score * 2 if q["rejim"] == "imtihon" else None,
                "vaqt": round(time.time() - q["created"]),
                "bolimlar": sorted(({"bolim": k, "togri": v[0], "jami": v[1]} for k, v in bol.items()),
                                   key=lambda x: x["togri"] / x["jami"]),
                "xatolar": [{"savol": it["savol"],
                             "sizning": it["variantlar"][q["answers"][i]] if i in q["answers"] else "—",
                             "togri_javob": it["variantlar"][it["togri"]], "izoh": it["izoh"],
                             "bolim": it.get("bolim", "")}
                            for i, it in enumerate(q["qs"])
                            if (i in q["answers"] or q["rejim"] == "imtihon") and q["answers"].get(i) != it["togri"]],
            }
        return web.json_response({"saved": True, **q["result"], **status(u["id"])})

    app = web.Application(client_max_size=10 * 1024 * 1024)
    app.router.add_get("/", index)
    app.router.add_get("/health", health)
    app.router.add_get("/api/catalog", api_catalog)
    app.router.add_get("/api/fanlar", api_fanlar)
    app.router.add_get("/api/bank", api_bank)
    app.router.add_get("/api/me", api_me)
    app.router.add_post("/api/code", api_code)
    app.router.add_post("/api/payment", api_payment)
    app.router.add_post("/api/quiz", api_quiz_new)
    app.router.add_post("/api/quiz/answer", api_quiz_answer)
    app.router.add_post("/api/quiz/finish", api_quiz_finish)
    app.router.add_static("/static/", STATIC, show_index=False)
    return app
