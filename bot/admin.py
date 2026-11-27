"""Admin paneli: barcha foydalanuvchilarga xabar yuborish (matn, rasm, video, fayl — istalgan turdagi
xabar nusxalanadi), bitta foydalanuvchiga xabar, statistika va kod yaratish tugmalari.

Buyruqlar (faqat adminlar):
  /panel             — admin paneli
  /xabar             — keyingi yuborgan xabaringiz hammaga tarqatiladi (tasdiqlashdan so'ng)
  /xabar ID matn     — bitta foydalanuvchiga xabar
  /bekor             — boshlangan amalni bekor qilish
"""
from __future__ import annotations

import asyncio
import logging
from html import escape

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.db import ResultsDB

log = logging.getLogger("admin")


class AdminSt(StatesGroup):
    xabar = State()      # tarqatiladigan xabarni kutmoqda
    tasdiq = State()     # yuborishni tasdiqlashni kutmoqda


def _kb(rows: list[list[tuple[str, str]]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=t, callback_data=d) for t, d in r]
                                                 for r in rows])


PANEL_KB = _kb([
    [("📢 Hammaga xabar yuborish", "adm:xabar")],
    [("📊 Statistika", "adm:stat")],
    [("🔑 1 oylik kod", "adm:kod1"), ("🔑 3 oylik kod", "adm:kod3")],
])

PANEL_TEXT = ("🛠 <b>Admin paneli</b>\n\n"
              "📢 <b>Hammaga xabar</b> — matn, rasm, video yoki fayl yuborasiz, bot uni barcha "
              "foydalanuvchilarga tarqatadi (oldin tasdiqlaysiz).\n"
              "✉️ Bitta foydalanuvchiga: <code>/xabar ID matn</code>\n\n"
              "🔑 Kod: <code>/kod1 ID</code> yoki <code>/kod3 ID</code> — kod shu foydalanuvchiga bog'lanadi va "
              "unga avtomatik yuboriladi. Bir foydalanuvchiga amaldagi kod bo'lsa, yangi kod berilmaydi.\n\n"
              "💾 /backup — ma'lumotlar zaxirasi\n/statistika — qisqa statistika\n/bekor — amalni bekor qilish")


def build_router(db: ResultsDB, admins: list[int]) -> Router:
    r = Router()
    r.message.filter(F.from_user.id.func(lambda uid: uid in admins))
    r.callback_query.filter(F.from_user.id.func(lambda uid: uid in admins))
    running: dict[str, bool] = {"on": False}

    @r.message(Command("panel"))
    async def panel(msg: Message, state: FSMContext) -> None:
        await state.clear()
        await msg.answer(PANEL_TEXT, reply_markup=PANEL_KB)

    @r.message(Command("bekor"))
    async def cancel(msg: Message, state: FSMContext) -> None:
        await state.clear()
        await msg.answer("Bekor qilindi.", reply_markup=PANEL_KB)

    @r.callback_query(F.data == "adm:stat")
    async def stat(cb: CallbackQuery) -> None:
        s = db.codes_stats()
        await cb.answer()
        await cb.message.answer(f"📊 Foydalanuvchilar: <b>{s['foydalanuvchilar']}</b>\nFaol premium: <b>{s['premium']}</b>\n"
                                f"Kodlar: {s['kodlar']} (ishlatilgan: {s['ishlatilgan']})")

    @r.callback_query(F.data.in_({"adm:kod1", "adm:kod3"}))
    async def kod_hint(cb: CallbackQuery) -> None:
        n = cb.data[-1]
        await cb.answer()
        await cb.message.answer(f"Kodni foydalanuvchi ID si bilan yarating:\n<code>/kod{n} 123456789</code>\n\n"
                                "ID ni foydalanuvchining to'lov chekidagi xabardan olasiz (yoki u /id buyrug'i bilan "
                                "biladi). ID siz <code>/kod" + n + "</code> — hech kimga bog'lanmagan kod.")

    # ---------- bitta foydalanuvchiga ----------
    @r.message(Command("xabar"), F.text.regexp(r"^/xabar(@\w+)?\s+\d+\s+\S"))
    async def to_one(msg: Message) -> None:
        _, uid, text = msg.text.split(maxsplit=2)
        try:
            await msg.bot.send_message(int(uid), f"📩 <b>Admin xabari:</b>\n\n{escape(text)}")
            await msg.answer(f"✅ Xabar ID <code>{uid}</code> ga yuborildi.")
        except Exception as e:  # noqa: BLE001
            await msg.answer(f"❌ Yuborib bo'lmadi: {escape(str(e)[:200])}")

    # ---------- hammaga ----------
    async def ask_message(target: Message, state: FSMContext) -> None:
        await state.set_state(AdminSt.xabar)
        await target.answer(f"📢 Barcha foydalanuvchilarga ({len(db.user_ids())} ta) yuboriladigan xabarni jo'nating.\n"
                            "Matn, rasm (izoh bilan), video, fayl yoki ovozli xabar bo'lishi mumkin.\n\n"
                            "Bekor qilish: /bekor")

    @r.message(Command("xabar"))
    async def broadcast_start(msg: Message, state: FSMContext) -> None:
        await ask_message(msg, state)

    @r.callback_query(F.data == "adm:xabar")
    async def broadcast_start_cb(cb: CallbackQuery, state: FSMContext) -> None:
        await cb.answer()
        await ask_message(cb.message, state)

    @r.message(StateFilter(AdminSt.xabar))
    async def broadcast_preview(msg: Message, state: FSMContext) -> None:
        if msg.text and msg.text.startswith("/"):
            return await msg.answer("Xabarni yuboring yoki /bekor bosing.")
        await state.update_data(src_chat=msg.chat.id, src_id=msg.message_id)
        await state.set_state(AdminSt.tasdiq)
        await msg.answer(f"☝️ Shu xabar <b>{len(db.user_ids())}</b> ta foydalanuvchiga yuboriladi. Tasdiqlaysizmi?",
                         reply_markup=_kb([[("✅ Yuborish", "adm:send"), ("❌ Bekor qilish", "adm:cancel")]]))

    @r.callback_query(F.data == "adm:cancel")
    async def broadcast_cancel(cb: CallbackQuery, state: FSMContext) -> None:
        await state.clear()
        await cb.answer("Bekor qilindi")
        await cb.message.edit_text("Bekor qilindi.")

    @r.callback_query(F.data == "adm:send", StateFilter(AdminSt.tasdiq))
    async def broadcast_send(cb: CallbackQuery, state: FSMContext) -> None:
        d = await state.get_data()
        await state.clear()
        if running["on"]:
            return await cb.answer("Boshqa tarqatish hali tugamagan, kuting.", show_alert=True)
        await cb.answer("Yuborish boshlandi")
        await cb.message.edit_text("⏳ Yuborilmoqda...")
        asyncio.create_task(_broadcast(cb.bot, cb.message, d["src_chat"], d["src_id"]))

    @r.callback_query(F.data == "adm:send")
    async def broadcast_stale(cb: CallbackQuery) -> None:
        await cb.answer("Bu so'rov eskirgan. /xabar bilan qaytadan boshlang.", show_alert=True)

    async def _broadcast(bot: Bot, status_msg: Message, src_chat: int, src_id: int) -> None:
        running["on"] = True
        ids = db.user_ids()
        ok = blocked = failed = 0
        try:
            for n, uid in enumerate(ids, 1):
                for _ in range(3):
                    try:
                        await bot.copy_message(uid, src_chat, src_id)
                        ok += 1
                        break
                    except TelegramRetryAfter as e:  # Telegram limiti — aytilgan vaqt kutamiz
                        await asyncio.sleep(e.retry_after + 1)
                    except TelegramForbiddenError:  # botni bloklagan
                        blocked += 1
                        break
                    except Exception as e:  # noqa: BLE001
                        log.warning("xabar %s ga yetmadi: %s", uid, e)
                        failed += 1
                        break
                await asyncio.sleep(0.05)  # ~20 xabar/soniya — Telegram cheklovidan past
                if n % 200 == 0:
                    try:
                        await status_msg.edit_text(f"⏳ Yuborilmoqda: {n}/{len(ids)}")
                    except Exception:  # noqa: BLE001
                        pass
        finally:
            running["on"] = False
        text = (f"✅ <b>Tarqatish tugadi</b>\n\nJami: {len(ids)}\nYetkazildi: <b>{ok}</b>\n"
                f"Botni bloklagan: {blocked}\nXato: {failed}")
        try:
            await status_msg.edit_text(text)
        except Exception:  # noqa: BLE001
            await bot.send_message(status_msg.chat.id, text)

    return r
