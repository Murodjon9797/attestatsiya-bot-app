"""Attestatsiya Telegram boti.

Oqim: Bilim sohasi -> Yo'nalish -> Mutaxassislik -> Fan -> Savollar soni -> Test -> Natija.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from html import escape

import anthropic
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (BotCommand, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup,
                           MenuButtonWebApp, Message, WebAppInfo)

from bot.bank import QuestionBank
from bot.data import Catalog
from bot.db import ResultsDB
from bot.premium import Premium
from bot import quiz
from claude_json import ClaudeError

log = logging.getLogger("bot")
router = Router()

PAGE = 10
COUNTS = (10, 20, 30)
LETTERS = "ABCD"

catalog: Catalog
bank: QuestionBank
db: ResultsDB
premium: Premium
claude: anthropic.AsyncAnthropic
PASS_PERCENT = 60
WEBAPP_URL = ""


class St(StatesGroup):
    fan_yozish = State()
    test = State()


# ---------------- klaviaturalar ----------------
def btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text[:120], callback_data=data)


def paged(items: list[tuple[str, str]], page: int, page_fmt: str, back: str | None,
          extra: list[list[InlineKeyboardButton]] | None = None) -> InlineKeyboardMarkup:
    pages = max(1, (len(items) + PAGE - 1) // PAGE)
    page = min(max(page, 0), pages - 1)
    rows = [[btn(t, d)] for t, d in items[page * PAGE:(page + 1) * PAGE]]
    if pages > 1:
        nav = []
        if page > 0:
            nav.append(btn("⬅️", page_fmt.format(page - 1)))
        nav.append(btn(f"{page + 1}/{pages}", "noop"))
        if page < pages - 1:
            nav.append(btn("➡️", page_fmt.format(page + 1)))
        rows.append(nav)
    rows += extra or []
    if back:
        rows.append([btn("🔙 Orqaga", back), btn("🏠 Bosh menyu", "home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def show(cb_or_msg: CallbackQuery | Message, text: str, kb: InlineKeyboardMarkup) -> None:
    if isinstance(cb_or_msg, CallbackQuery):
        try:
            await cb_or_msg.message.edit_text(text, reply_markup=kb)
        except Exception:  # xabar o'zgarmagan bo'lsa yoki juda eski bo'lsa
            await cb_or_msg.message.answer(text, reply_markup=kb)
        await cb_or_msg.answer()
    else:
        await cb_or_msg.answer(text, reply_markup=kb)


# ---------------- menyular ----------------
def sohalar_kb() -> InlineKeyboardMarkup:
    items = [(f"{s['nomi']} ({sum(len(y['mutaxassisliklar']) for y in s['yunalishlar'])})", f"b:{i}:0")
             for i, s in enumerate(catalog.sohalar)]
    kb = paged(items, 0, "noop", None)
    if bank.subjects:
        kb.inline_keyboard.insert(0, [btn(f"📚 Attestatsiya fanlari — tayyor savollar ({len(bank.subjects)})", "bk:0")])
    kb.inline_keyboard.insert(0, [btn("💎 Premium", "premium"), btn("📊 Tahlil", "tahlil")])
    if WEBAPP_URL:
        kb.inline_keyboard.insert(0, [InlineKeyboardButton(text="📱 Ilovani ochish", web_app=WebAppInfo(url=WEBAPP_URL))])
    return kb


def access(uid: int) -> tuple[bool, int]:
    """(premium faolmi, qolgan bepul savollar soni)."""
    if db.premium_until(uid):
        return True, 10 ** 6
    return False, max(0, premium.free_questions - db.answered_count(uid))


def paywall_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[btn("💎 Premium olish", "premium")], [btn("🏠 Bosh menyu", "home")]])


async def menu_home(target: CallbackQuery | Message, state: FSMContext) -> None:
    await state.clear()
    uid = target.from_user.id
    db.touch_user(uid, target.from_user.full_name, target.from_user.username or "")
    is_p, left = access(uid)
    until = db.premium_until(uid)
    holat = (f"💎 Premium: <b>{until.strftime('%d.%m.%Y')}</b> gacha" if is_p
             else f"🆓 Bepul savollar qoldi: <b>{left}</b> / {premium.free_questions}")
    text = (f"<b>🎓 Texnikum o'qituvchilari attestatsiyasiga tayyorlov — {catalog.yil}</b>\n\n"
            f"{holat}\n\n"
            f"📚 {len(bank.subjects)} ta attestatsiya fani bo'yicha tayyor savollar, "
            "bo'limlar kesimida tahlil va zaif mavzular bo'yicha tavsiyalar.\n\n"
            "Fanni tanlang yoki mutaxassislik bo'yicha qidiring:")
    await show(target, text, sohalar_kb())


@router.message(CommandStart())
async def on_start(msg: Message, state: FSMContext) -> None:
    await menu_home(msg, state)


@router.message(Command("menu"))
async def on_menu(msg: Message, state: FSMContext) -> None:
    await menu_home(msg, state)


@router.callback_query(F.data == "home")
async def cb_home(cb: CallbackQuery, state: FSMContext) -> None:
    await menu_home(cb, state)


@router.callback_query(F.data == "noop")
async def cb_noop(cb: CallbackQuery) -> None:
    await cb.answer()


@router.callback_query(F.data.startswith("b:"))
async def cb_soha(cb: CallbackQuery) -> None:
    _, bi, page = cb.data.split(":")
    bi, page = int(bi), int(page)
    s = catalog.soha(bi)
    items = [(f"{y['kod']} {y['nomi']} ({len(y['mutaxassisliklar'])})", f"y:{bi}:{yi}:0")
             for yi, y in enumerate(s["yunalishlar"])]
    await show(cb, f"<b>{escape(s['nomi'])}</b>\n\nYo'nalishni tanlang:",
               paged(items, page, f"b:{bi}:{{}}", "home"))


@router.callback_query(F.data.startswith("y:"))
async def cb_yunalish(cb: CallbackQuery) -> None:
    _, bi, yi, page = cb.data.split(":")
    bi, yi, page = int(bi), int(yi), int(page)
    y = catalog.yunalish(bi, yi)
    items = [(f"{m['kod']} {m['nomi']}", f"m:{bi}:{yi}:{mi}:0")
             for mi, m in enumerate(y["mutaxassisliklar"])]
    await show(cb, f"<b>{escape(y['kod'])} {escape(y['nomi'])}</b>\n\nMutaxassislikni tanlang:",
               paged(items, page, f"y:{bi}:{yi}:{{}}", f"b:{bi}:0"))


@router.callback_query(F.data.startswith("m:"))
async def cb_mutaxassislik(cb: CallbackQuery, state: FSMContext) -> None:
    _, bi, yi, mi, page = cb.data.split(":")
    bi, yi, mi, page = int(bi), int(yi), int(mi), int(page)
    m = catalog.mutaxassislik(bi, yi, mi)
    await state.set_state(None)
    await state.update_data(bi=bi, yi=yi, mi=mi, bank=None)
    head = f"<b>{escape(m['kod'])} — {escape(m['nomi'])}</b>\n<a href=\"{m['url']}\">Saytdagi sahifasi</a>\n\n"
    write_btn = [[btn("✍️ Fan nomini o'zim yozaman", "type")]]
    if m["fanlar"]:
        items = [((f"{f['kod']} " if f.get("kod") else "") + f["nomi"], f"f:{fi}")
                 for fi, f in enumerate(m["fanlar"])]
        await show(cb, head + f"O'quv dasturidagi fanlar ({len(m['fanlar'])} ta). Attestatsiya fanini tanlang:",
                   paged(items, page, f"m:{bi}:{yi}:{mi}:{{}}", f"y:{bi}:{yi}:0", write_btn))
    else:
        await state.set_state(St.fan_yozish)
        await show(cb, head + "Bu mutaxassislik uchun fanlar ro'yxati hali yuklanmagan.\n"
                              "✍️ Attestatsiya topshiradigan <b>fan nomini yozib yuboring</b>:",
                   paged([], 0, "noop", f"y:{bi}:{yi}:0"))


@router.callback_query(F.data.startswith("bk:"))
async def cb_bank_list(cb: CallbackQuery) -> None:
    page = int(cb.data[3:])
    icon = {"umumtalim": "📘", "maxsus": "🛠", "bosqich1": "🧑‍🏫"}
    items = [(f"{icon.get(x['turi'], '')} {x['nomi']} ({x['soni']})", f"bs:{x['id']}") for x in bank.listing()]
    await show(cb, "<b>📚 Attestatsiya fanlari</b>\n\n"
                   "🛠 — umumkasbiy va maxsus fanlar. Nizomga ko'ra o'quv yuklamasi eng ko'p bo'lgan bitta fan "
                   "bo'yicha attestatsiyadan o'tasiz.\n📘 — umumta'lim fanlari.\n🧑‍🏫 — 1-bosqichga tayyorgarlik "
                   "(pedagogik mahoratni kengash baholaydi, 20 ball).\n\n2-bosqich: fan bo'yicha 40 ta test, 80 ball.",
               paged(items, page, "bk:{}", "home"))


@router.callback_query(F.data.startswith("bs:"))
async def cb_bank_pick(cb: CallbackQuery, state: FSMContext) -> None:
    sid = cb.data[3:]
    if sid not in bank.subjects:
        return await cb.answer("Fan topilmadi", show_alert=True)
    await state.set_state(None)
    await state.update_data(fan=bank.subjects[sid]["nomi"], bank=sid, blok="", natijalar="", mazmun="",
                            bi=None, yi=None, mi=None)
    await ask_count(cb, bank.subjects[sid]["nomi"])


@router.callback_query(F.data == "type")
async def cb_type(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(St.fan_yozish)
    await cb.message.answer("✍️ Fan nomini yozib yuboring:")
    await cb.answer()


def count_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [btn(f"{n} ta savol", f"n:{n}") for n in COUNTS],
        [btn("🏠 Bosh menyu", "home")],
    ])


async def ask_count(target: CallbackQuery | Message, fan: str) -> None:
    await show(target, f"📘 Fan: <b>{escape(fan)}</b>\n\nNechta savoldan iborat test tuzilsin?", count_kb())


@router.callback_query(F.data.startswith("f:"))
async def cb_fan(cb: CallbackQuery, state: FSMContext) -> None:
    d = await state.get_data()
    if "mi" not in d:
        return await menu_home(cb, state)
    f = catalog.mutaxassislik(d["bi"], d["yi"], d["mi"])["fanlar"][int(cb.data[2:])]
    await state.update_data(fan=f["nomi"], blok=f.get("blok", ""),
                            natijalar=f.get("natijalar", ""), mazmun=f.get("mazmun", ""))
    await ask_count(cb, f["nomi"])


@router.message(St.fan_yozish, F.text)
async def on_fan_text(msg: Message, state: FSMContext) -> None:
    fan = " ".join(msg.text.split())[:150]
    if len(fan) < 3 or fan.startswith("/"):
        return await msg.answer("Fan nomini to'liqroq yozing.")
    await state.set_state(None)
    await state.update_data(fan=fan, blok="", natijalar="", mazmun="")
    await ask_count(msg, fan)


# ---------------- test ----------------
def question_view(q: dict, i: int, n: int) -> tuple[str, InlineKeyboardMarkup]:
    text = f"<b>Savol {i + 1}/{n}</b>\n\n{escape(q['savol'])}\n\n" + "\n".join(
        f"<b>{LETTERS[k]})</b> {escape(v)}" for k, v in enumerate(q["variantlar"]))
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [btn(LETTERS[k], f"a:{i}:{k}") for k in range(4)],
        [btn("⛔ Testni to'xtatish", "stop")],
    ])
    return text, kb


@router.callback_query(F.data.startswith("n:"))
async def cb_start_test(cb: CallbackQuery, state: FSMContext) -> None:
    d = await state.get_data()
    if "fan" not in d or ("mi" not in d and not d.get("bank")):
        return await menu_home(cb, state)
    if d.get("busy"):
        return await cb.answer("Test tayyorlanmoqda, kuting...", show_alert=True)
    soni = int(cb.data[2:])
    is_p, left = access(cb.from_user.id)
    if left <= 0:
        await cb.answer()
        return await cb.message.edit_text(
            f"🔒 Bepul {premium.free_questions} ta savol tugadi.\n\n" + premium.payment_text(), reply_markup=paywall_kb())
    soni = min(soni, left)
    sid = d.get("bank") or bank.match(d["fan"])
    await cb.answer()
    if sid:  # tayyor savollar bazasi — API kaliti kerak emas
        qs = bank.draw(sid, soni)
    elif is_p and (os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN")):
        y = catalog.yunalish(d["bi"], d["yi"])
        m = catalog.mutaxassislik(d["bi"], d["yi"], d["mi"])
        await state.update_data(busy=True)
        await cb.message.edit_text(
            f"⏳ <b>{escape(d['fan'])}</b> fanidan {soni} ta savol tuzilmoqda...\n"
            "Bu 1-2 daqiqa vaqt olishi mumkin.")
        try:
            qs = await quiz.generate(claude, fan=d["fan"], blok=d.get("blok", ""),
                                     natijalar=d.get("natijalar", ""), mazmun=d.get("mazmun", ""),
                                     mutaxassislik=f"{m['kod']} {m['nomi']}",
                                     yunalish=f"{y['kod']} {y['nomi']}", soni=soni)
        except ClaudeError as e:
            await state.update_data(busy=False)
            return await cb.message.edit_text(f"❌ Xatolik: {escape(str(e))}", reply_markup=count_kb())
        except Exception:
            log.exception("test tuzishda xato")
            await state.update_data(busy=False)
            return await cb.message.edit_text("❌ Kutilmagan xatolik. Qayta urinib ko'ring.", reply_markup=count_kb())
    else:
        return await cb.message.edit_text(
            f"ℹ️ <b>{escape(d['fan'])}</b> fani bo'yicha tayyor savollar hali yo'q.\n"
            "\"📚 Attestatsiya fanlari\" bo'limidan yaqin fanni tanlang.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[btn("📚 Attestatsiya fanlari", "bk:0")],
                                                               [btn("🏠 Bosh menyu", "home")]]))

    await state.set_state(St.test)
    await state.update_data(busy=False, qs=qs, qi=0, score=0, wrong=[], sid=sid or "", trial=not is_p)
    text, kb = question_view(qs[0], 0, len(qs))
    await cb.message.edit_text(text, reply_markup=kb)


@router.callback_query(St.test, F.data.startswith("a:"))
async def cb_answer(cb: CallbackQuery, state: FSMContext) -> None:
    _, qi, k = cb.data.split(":")
    qi, k = int(qi), int(k)
    d = await state.get_data()
    if qi != d["qi"]:
        return await cb.answer("Bu savolga javob berilgan.")
    qs = d["qs"]
    q = qs[qi]
    if d.get("trial") and access(cb.from_user.id)[1] <= 0:
        await state.update_data(qs=qs[:qi])
        await cb.answer()
        await cb.message.answer(f"🔒 Bepul {premium.free_questions} ta savol tugadi.\n\n" + premium.payment_text(),
                                reply_markup=paywall_kb())
        return await finish(cb, state) if qi > 0 else await state.set_state(None)
    ok = k == q["togri"]
    db.record_answer(cb.from_user.id, q.get("sid", ""), q.get("qid", ""), q.get("bolim", ""), ok)
    score = d["score"] + ok
    wrong = d["wrong"] + ([] if ok else [qi])
    mark = "✅ To'g'ri!" if ok else f"❌ Noto'g'ri. To'g'ri javob: <b>{LETTERS[q['togri']]}</b>"
    text, _ = question_view(q, qi, len(qs))
    await cb.message.edit_text(f"{text}\n\nSizning javobingiz: <b>{LETTERS[k]}</b>\n{mark}\n"
                               f"<i>{escape(q['izoh'])}</i>")
    await cb.answer("✅" if ok else "❌")
    qi += 1
    await state.update_data(qi=qi, score=score, wrong=wrong)
    if qi < len(qs) and not (d.get("trial") and access(cb.from_user.id)[1] <= 0):
        text, kb = question_view(qs[qi], qi, len(qs))
        await cb.message.answer(text, reply_markup=kb)
    else:
        if qi < len(qs):
            await state.update_data(qs=qs[:qi])
        await finish(cb, state)
        if d.get("trial") and access(cb.from_user.id)[1] <= 0:
            await cb.message.answer(f"🔒 Bepul {premium.free_questions} ta savol tugadi. Tayyorgarlikni davom "
                                    "ettirish uchun premium oling.\n\n" + premium.payment_text(), reply_markup=paywall_kb())


@router.callback_query(F.data.startswith("a:"))
async def cb_answer_stale(cb: CallbackQuery) -> None:
    await cb.answer("Bu test yakunlangan. /start bosing.", show_alert=True)


@router.callback_query(F.data == "stop")
async def cb_stop(cb: CallbackQuery, state: FSMContext) -> None:
    d = await state.get_data()
    if await state.get_state() == St.test.state and d.get("qi", 0) > 0:
        await state.update_data(qs=d["qs"][:d["qi"]])
        await cb.message.edit_reply_markup(reply_markup=None)
        await finish(cb, state)
    else:
        await menu_home(cb, state)


async def finish(cb: CallbackQuery, state: FSMContext) -> None:
    d = await state.get_data()
    n, score = len(d["qs"]), d["score"]
    pct = round(100 * score / n, 1)
    if d.get("mi") is not None:
        m = catalog.mutaxassislik(d["bi"], d["yi"], d["mi"])
        mutax = f"{m['kod']} {m['nomi']}"
    else:
        mutax = "Attestatsiya fanlari"
    u = cb.from_user
    db.save(u.id, d["fan"], score, n, d.get("sid", ""), "mashq")
    verdict = "🟢 <b>O'tdi</b>" if pct >= PASS_PERCENT else "🔴 <b>O'tmadi</b>"
    text = (f"🏁 <b>Test yakunlandi</b>\n\n"
            f"Fan: {escape(d['fan'])}\nMutaxassislik: {escape(mutax)}\n\n"
            f"Natija: <b>{score}/{n}</b> ({pct}%) — {verdict} (o'tish bali {PASS_PERCENT}%)")
    bol: dict[str, list[int]] = {}
    for i, q in enumerate(d["qs"]):
        b = bol.setdefault(q.get("bolim") or "Umumiy", [0, 0])
        b[1] += 1
        b[0] += int(i not in d["wrong"])
    if len(bol) > 1 or "Umumiy" not in bol:
        text += "\n\n<b>Bo'limlar bo'yicha:</b>\n" + "\n".join(
            f"{'🟢' if v[0] / v[1] >= PASS_PERCENT / 100 else '🔴'} {escape(k)}: {v[0]}/{v[1]}"
            for k, v in sorted(bol.items(), key=lambda x: x[1][0] / x[1][1]))
    if d["wrong"]:
        text += "\n\n<b>Qayta ko'rib chiqing:</b>\n" + "\n".join(
            f"• {i + 1}-savol: {escape(d['qs'][i]['savol'][:90])}" for i in d["wrong"][:15])
    await state.set_state(None)
    await state.update_data(qs=None, wrong=None)
    await cb.message.answer(text[:4000], reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [btn("🔁 Shu fandan yana test", "again")],
        [btn("📚 Boshqa fan", f"m:{d['bi']}:{d['yi']}:{d['mi']}:0" if d.get("mi") is not None else "bk:0"),
         btn("🏠 Bosh menyu", "home")],
    ]))


@router.callback_query(F.data == "again")
async def cb_again(cb: CallbackQuery, state: FSMContext) -> None:
    d = await state.get_data()
    if "fan" not in d:
        return await menu_home(cb, state)
    await ask_count(cb, d["fan"])


@router.message(Command("natijalar"))
async def on_results(msg: Message) -> None:
    rows = db.last(msg.from_user.id)
    if not rows:
        return await msg.answer("Hali test topshirmagansiz. /start")
    await msg.answer("<b>Oxirgi natijalaringiz:</b>\n\n" + "\n".join(
        f"{v[:16]} — {escape(f)}: {t}/{j} ({p}%)" for v, f, t, j, p, _ in rows))


@router.message(Command("tahlil"))
async def on_tahlil(msg: Message) -> None:
    await msg.answer(tahlil_text(msg.from_user.id))


@router.callback_query(F.data == "tahlil")
async def cb_tahlil(cb: CallbackQuery) -> None:
    await cb.answer()
    await cb.message.answer(tahlil_text(cb.from_user.id))


def tahlil_text(uid: int) -> str:
    a = db.analytics(uid)
    if not a["jami"]:
        return "📊 Hali savollarga javob bermadingiz. Testni boshlang — tahlil shu yerda paydo bo'ladi."
    names = {s["id"]: s["nomi"] for s in bank.listing()}
    pct = round(100 * a["togri"] / a["jami"])
    lines = [f"📊 <b>Tahlil</b>\n\nJami javoblar: {a['jami']}, to'g'ri: {a['togri']} (<b>{pct}%</b>)"]
    if a["fanlar"]:
        lines.append("\n<b>Fanlar bo'yicha:</b>")
        for f in sorted(a["fanlar"], key=lambda x: x["togri"] / x["jami"]):
            p = round(100 * f["togri"] / f["jami"])
            lines.append(f"{'🟢' if p >= PASS_PERCENT else '🔴'} {escape(names.get(f['sid'], f['sid']))}: {p}% ({f['jami']} ta javob)")
    weak = sorted((b for b in a["bolimlar"] if b["jami"] >= 2), key=lambda b: b["togri"] / b["jami"])[:5]
    weak = [b for b in weak if b["togri"] / b["jami"] < PASS_PERCENT / 100]
    if weak:
        lines.append("\n<b>Zaif mavzular — takrorlang:</b>")
        lines += [f"• {escape(b['bolim'])} ({escape(names.get(b['sid'], ''))}): {b['togri']}/{b['jami']}" for b in weak]
    return "\n".join(lines)


@router.message(Command("help"))
async def on_help(msg: Message) -> None:
    await msg.answer(
        "Bot texnikum o'qituvchilarini attestatsiyaga tayyorlaydi: fanlar bo'yicha test, "
        "bo'limlar kesimida tahlil va zaif mavzular.\n\n"
        f"Bepul: {premium.free_questions} ta savol. Keyin — premium (/premium).\n\n"
        "/start — bosh menyu\n/tahlil — natijalar tahlili\n/natijalar — oxirgi testlar\n"
        "/premium — tariflar va to'lov\n/kod — faollashtirish kodini kiritish")


@router.message(St.test)
async def on_text_in_test(msg: Message) -> None:
    await msg.answer("Javobni savol ostidagi A/B/C/D tugmalari orqali tanlang.")


# ---------------- ishga tushirish ----------------
async def run() -> None:
    global catalog, db, claude, PASS_PERCENT, WEBAPP_URL, premium
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise SystemExit(".env faylida BOT_TOKEN ko'rsatilmagan.")
    catalog = Catalog(os.getenv("DATA_FILE", "data/fanlar_2026.json"))
    db = ResultsDB(os.getenv("DB_FILE", "data/natijalar.sqlite3"), os.getenv("DATABASE_URL", ""))
    log.info("Ma'lumotlar bazasi: %s", "PostgreSQL" if db.pg else "SQLite (server qayta ishga tushsa o'chadi!)")
    premium = Premium(db)
    global bank
    bank = QuestionBank(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "savollar"))
    log.info("Savollar bazasi: %d ta fan, %d ta savol", len(bank.subjects),
             sum(len(x["savollar"]) for x in bank.subjects.values()))
    claude = anthropic.AsyncAnthropic()
    PASS_PERCENT = int(os.getenv("PASS_PERCENT", "60"))
    # Render.com o'zi RENDER_EXTERNAL_URL (https://<nom>.onrender.com) beradi
    public_url = (os.getenv("PUBLIC_URL") or os.getenv("RENDER_EXTERNAL_URL") or "").strip().rstrip("/")
    WEBAPP_URL = os.getenv("WEBAPP_URL", "").strip() or (public_url + "/" if public_url else "")

    bot = Bot(token, default=DefaultBotProperties(parse_mode=ParseMode.HTML,
                                                  link_preview_is_disabled=True))
    dp = Dispatcher(storage=MemoryStorage())
    premium.bot = bot
    dp.include_router(premium.router())  # chek rasmlari va admin tugmalari test holatidan oldin ushlanadi
    dp.include_router(router)
    await bot.set_my_commands([
        BotCommand(command="start", description="Bosh menyu"),
        BotCommand(command="tahlil", description="Natijalar tahlili"),
        BotCommand(command="premium", description="Premium va to'lov"),
        BotCommand(command="kod", description="Faollashtirish kodini kiritish"),
        BotCommand(command="natijalar", description="Oxirgi testlar"),
        BotCommand(command="help", description="Yordam"),
    ])
    if not premium.admins:
        log.warning("ADMIN_IDS ko'rsatilmagan — to'lov cheklari hech kimga yuborilmaydi!")

    # Mini App veb-serveri (API + sahifa) bot bilan bitta jarayonda ishlaydi
    from aiohttp import web as aioweb

    from bot.web import build_app

    me = await bot.get_me()
    app = build_app(token=token, catalog=catalog, db=db, claude=claude, pass_percent=PASS_PERCENT, bank=bank,
                    premium=premium, bot_username=me.username or "")

    # Ommaviy manzil bo'lsa webhook: Telegram xabari uxlab qolgan bepul serverni ham uyg'otadi
    webhook_path = webhook_secret = ""
    if public_url:
        from aiogram.webhook.aiohttp_server import SimpleRequestHandler

        webhook_secret = hashlib.sha256(("wh:" + token).encode()).hexdigest()[:48]
        webhook_path = "/tg/" + hashlib.sha256(token.encode()).hexdigest()[:24]
        SimpleRequestHandler(dispatcher=dp, bot=bot, secret_token=webhook_secret).register(app, path=webhook_path)

    runner = aioweb.AppRunner(app)
    await runner.setup()
    host = os.getenv("WEB_HOST", "0.0.0.0")
    port = int(os.getenv("PORT") or os.getenv("WEB_PORT", "8080"))  # Render PORT ni o'zi beradi
    await aioweb.TCPSite(runner, host, port).start()
    log.info("Mini App serveri: http://%s:%d", host, port)
    if WEBAPP_URL:
        await bot.set_chat_menu_button(menu_button=MenuButtonWebApp(text="Ilova", web_app=WebAppInfo(url=WEBAPP_URL)))
        log.info("Menyu tugmasi: %s", WEBAPP_URL)
    else:
        log.warning("WEBAPP_URL ko'rsatilmagan — Mini App tugmasi chiqmaydi (faqat chat rejimi).")

    log.info("Bot ishga tushdi: %d ta mutaxassislik", catalog.stats()[1])
    try:
        if webhook_path:
            await bot.set_webhook(public_url + webhook_path, secret_token=webhook_secret,
                                  allowed_updates=dp.resolve_used_update_types())
            log.info("Webhook rejimi: %s/tg/…", public_url)
            await dp.emit_startup(bot=bot)
            await asyncio.Event().wait()
        else:
            await bot.delete_webhook()
            await dp.start_polling(bot)
    finally:
        await runner.cleanup()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(run())
