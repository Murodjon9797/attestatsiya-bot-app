"""Premium: tariflar, karta orqali to'lov cheki, admin tasdig'i va faollashtirish kodlari.

Oqim:
  1. Foydalanuvchi tarifni tanlaydi, kartaga pul o'tkazadi va chek rasmini yuboradi
     (Mini App yoki chatda rasm sifatida).
  2. Chek adminga keladi: [✅ 1 oylik kod] [✅ 3 oylik kod] [❌ Rad etish] tugmalari bilan.
  3. Admin tasdiqlasa, bot kod yaratib foydalanuvchiga yuboradi; foydalanuvchi kodni kiritadi.
  Admin buyruqlari: /kod1, /kod3 (qo'lda kod yaratish), /statistika, /id.
Sozlamalar muhit o'zgaruvchilaridan olinadi (kod ichida karta raqami saqlanmaydi).
"""
from __future__ import annotations

import logging
import os
import secrets
from html import escape

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import (BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup,
                           Message)

from bot.db import ResultsDB

log = logging.getLogger("premium")


def _fmt_sum(n: int) -> str:
    return f"{n:,}".replace(",", " ") + " so'm"


class Premium:
    def __init__(self, db: ResultsDB):
        self.db = db
        self.bot: Bot | None = None
        self.free_questions = int(os.getenv("FREE_QUESTIONS", "5"))
        self.plans = {
            "1oy": {"nomi": "1 oylik", "kun": 30, "narx": int(os.getenv("PRICE_1M", "40000"))},
            "3oy": {"nomi": "3 oylik", "kun": 90, "narx": int(os.getenv("PRICE_3M", "60000"))},
        }
        self.card = os.getenv("CARD_NUMBER", "").replace(" ", "")
        self.card_owner = os.getenv("CARD_OWNER", "")
        env_admins = [int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x.isdigit()]
        self.admins = list(dict.fromkeys(env_admins + db.admin_ids()))
        self.claim_code = os.getenv("ADMIN_CLAIM_CODE", "").strip()
        self.admin_contact = os.getenv("ADMIN_CONTACT", "")
        self.exam_date = os.getenv("EXAM_DATE", "2026-12-04")

    def public_plans(self) -> list[dict]:
        return [{"id": k, **v, "narx_text": _fmt_sum(v["narx"])} for k, v in self.plans.items()]

    def card_pretty(self) -> str:
        c = self.card
        return " ".join(c[i:i + 4] for i in range(0, len(c), 4)) if c else "—"

    def payment_text(self) -> str:
        plans = "\n".join(f"• {p['nomi']} — <b>{_fmt_sum(p['narx'])}</b>" for p in self.plans.values())
        return (f"💎 <b>Premium obuna</b>\n\n{plans}\n\n"
                "Premium bilan: barcha fanlar bo'yicha cheksiz test, vaqtli sinov imtihoni (40 savol / 80 daqiqa), "
                "xatolar ustida ishlash va to'liq tahlil.\n\n"
                f"<b>To'lov:</b> quyidagi kartaga pul o'tkazing:\n<code>{self.card_pretty()}</code>\n"
                f"Karta egasi: <b>{escape(self.card_owner)}</b>\n\n"
                "So'ng <b>chek rasmini (skrinshot)</b> shu chatga yuboring. Admin tekshirib, "
                "sizga faollashtirish kodini yuboradi. Kodni /kod buyrug'i bilan yoki ilovada kiriting.")

    async def notify_admins(self, text: str) -> None:
        if not self.bot:
            return
        for a in self.admins:
            try:
                await self.bot.send_message(a, text)
            except Exception as e:  # noqa: BLE001
                log.warning("adminga yuborib bo'lmadi %s: %s", a, e)

    def _admin_kb(self, pid: int) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ 1 oylik kod", callback_data=f"pay:{pid}:1oy"),
             InlineKeyboardButton(text="✅ 3 oylik kod", callback_data=f"pay:{pid}:3oy")],
            [InlineKeyboardButton(text="❌ Rad etish", callback_data=f"pay:{pid}:no")],
        ])

    async def submit_receipt(self, user: dict, tarif: str, *, photo: bytes | None = None,
                             file_id: str | None = None, filename: str = "chek.jpg") -> int:
        """Chekni bazaga yozadi va barcha adminlarga tasdiqlash tugmalari bilan yuboradi."""
        if not self.bot or not self.admins:
            raise RuntimeError("Admin sozlanmagan (ADMIN_IDS)")
        p = self.plans.get(tarif, {"nomi": "tanlanmagan", "narx": 0})
        pid = self.db.create_payment(user["id"], tarif, file_id or "")
        caption = (f"🧾 <b>Yangi to'lov cheki #{pid}</b>\n"
                   f"Foydalanuvchi: {escape(user['name'])}"
                   + (f" (@{escape(user['username'])})" if user.get("username") else "")
                   + f"\nID: <code>{user['id']}</code>\nTarif: <b>{p['nomi']}</b>"
                   + (f" — {_fmt_sum(p['narx'])}" if p.get("narx") else "")
                   + "\n\nChekni tekshiring va kod turini tanlang:")
        for a in self.admins:
            try:
                media = file_id or BufferedInputFile(photo or b"", filename=filename)
                if filename.lower().endswith(".pdf") and not file_id:
                    await self.bot.send_document(a, media, caption=caption, reply_markup=self._admin_kb(pid))
                else:
                    await self.bot.send_photo(a, media, caption=caption, reply_markup=self._admin_kb(pid))
            except Exception as e:  # noqa: BLE001
                log.warning("chekni adminga yuborib bo'lmadi %s: %s", a, e)
        return pid

    # ---------------- Telegram handlerlari ----------------
    def router(self) -> Router:
        r = Router()

        def is_admin(uid: int) -> bool:
            return uid in self.admins

        @r.message(Command("admin"))
        async def claim_admin(msg: Message) -> None:
            parts = (msg.text or "").split(maxsplit=1)
            if is_admin(msg.from_user.id):
                return await msg.answer("Siz adminsiz. Admin paneli: /panel")
            if self.db.admin_ids():  # kod bir martalik: admin allaqachon tayinlangan
                return await msg.answer("Admin allaqachon tayinlangan.")
            if not self.claim_code or len(parts) < 2 or not secrets.compare_digest(parts[1].strip(), self.claim_code):
                return await msg.answer("Noto'g'ri admin kodi.")
            self.db.add_admin(msg.from_user.id)
            self.admins.append(msg.from_user.id)
            await msg.answer("✅ Siz admin bo'ldingiz. To'lov cheklari endi sizga keladi.\n\n"
                             "Admin paneli: /panel")

        @r.message(Command("id"))
        async def my_id(msg: Message) -> None:
            await msg.answer(f"Sizning Telegram ID: <code>{msg.from_user.id}</code>")

        @r.message(Command("premium"))
        async def premium_info(msg: Message) -> None:
            await self.show_premium(msg)

        @r.callback_query(F.data == "premium")
        async def premium_cb(cb: CallbackQuery) -> None:
            await cb.answer()
            await self.show_premium(cb.message, cb.from_user.id)

        @r.message(Command("kod"))
        async def redeem(msg: Message) -> None:
            parts = (msg.text or "").split(maxsplit=1)
            if len(parts) < 2:
                return await msg.answer("Kodni shunday yuboring:\n<code>/kod ABCD-EFGH-JKLM</code>")
            ok, text, _ = self.db.redeem_code(msg.from_user.id, parts[1])
            await msg.answer(("✅ " if ok else "❌ ") + text)
            if ok:
                await self.notify_admins(f"🔑 Kod ishlatildi: {escape(msg.from_user.full_name)} "
                                         f"(id {msg.from_user.id}) — {text}")

        @r.message(Command("kod1", "kod3"))
        async def make_code(msg: Message) -> None:
            if not is_admin(msg.from_user.id):
                return
            days = 30 if msg.text.startswith("/kod1") else 90
            parts = (msg.text or "").split()
            uid = int(parts[1]) if len(parts) > 1 and parts[1].lstrip("-").isdigit() else None
            if len(parts) > 1 and uid is None:
                return await msg.answer("Foydalanuvchi ID raqam bo'lishi kerak: <code>/kod1 123456789</code>")
            if uid is not None:
                old = self.db.code_for_user(uid)
                if old:
                    holat = "ishlatilgan, premium faol" if old["used"] else "hali ishlatilmagan"
                    return await msg.answer(f"⚠️ ID <code>{uid}</code> ga kod allaqachon berilgan ({holat}):\n"
                                            f"<code>{old['code']}</code>\n\nYangi kod yaratilmadi.")
            code = self.db.create_code(days, msg.from_user.id, for_user=uid)
            text = (f"Yangi {'1' if days == 30 else '3'} oylik kod:\n<code>{code}</code>\n\n"
                    "Foydalanuvchi uni botda <code>/kod " + code + "</code> deb kiritadi.")
            if uid is None:
                text += ("\n\n💡 Kodni aniq bir foydalanuvchiga bog'lash uchun ID bilan yarating: "
                         "<code>/kod1 ID</code> — shunda bitta odamga ikki marta kod berilmaydi.")
            else:
                text += f"\nFaqat ID <code>{uid}</code> ishlata oladi."
                try:
                    await self.bot.send_message(uid, f"🎁 Sizga {'1' if days == 30 else '3'} oylik premium kodi berildi:\n"
                                                f"<code>/kod {code}</code>")
                    text += "\n✅ Kod foydalanuvchiga yuborildi."
                except Exception:  # noqa: BLE001
                    text += "\n⚠️ Foydalanuvchiga yuborib bo'lmadi — kodni o'zingiz yuboring."
            await msg.answer(text)

        @r.message(Command("statistika"))
        async def stats(msg: Message) -> None:
            if not is_admin(msg.from_user.id):
                return
            s = self.db.codes_stats()
            await msg.answer(f"📊 Foydalanuvchilar: {s['foydalanuvchilar']}\nFaol premium: {s['premium']}\n"
                             f"Kodlar: {s['kodlar']} (ishlatilgan: {s['ishlatilgan']})")

        @r.message(F.photo | (F.document & F.document.mime_type.in_({"application/pdf", "image/jpeg", "image/png"})))
        async def receipt(msg: Message) -> None:
            u = {"id": msg.from_user.id, "name": msg.from_user.full_name, "username": msg.from_user.username or ""}
            if self.db.premium_until(u["id"]):
                return await msg.answer("Sizda premium allaqachon faol.")
            if self.db.pending_payment(u["id"]):
                return await msg.answer("Oldingi chekingiz hali ko'rib chiqilmoqda, iltimos kuting.")
            old = self.db.code_for_user(u["id"])
            if old and not old["used"]:
                return await msg.answer("Sizga kod allaqachon berilgan. Faollashtirish uchun yuboring:\n"
                                        f"<code>/kod {old['code']}</code>")
            cap = (msg.caption or "").lower()
            tarif = "3oy" if "3" in cap else ("1oy" if "1" in cap else "")
            file_id = msg.photo[-1].file_id if msg.photo else msg.document.file_id
            try:
                if msg.document:
                    pid = self.db.create_payment(u["id"], tarif, file_id)
                    for a in self.admins:
                        await self.bot.send_document(a, file_id, caption=f"🧾 Chek #{pid} — {escape(u['name'])} "
                                                     f"(ID <code>{u['id']}</code>)", reply_markup=self._admin_kb(pid))
                else:
                    await self.submit_receipt(u, tarif, file_id=file_id)
            except RuntimeError:
                return await msg.answer("To'lovlarni qabul qilish hali sozlanmagan. Keyinroq urinib ko'ring.")
            await msg.answer("✅ Chek qabul qilindi. Admin tekshirgach, sizga faollashtirish kodi yuboriladi.")

        @r.callback_query(F.data.startswith("pay:"))
        async def decide(cb: CallbackQuery) -> None:
            if not is_admin(cb.from_user.id):
                return await cb.answer("Faqat admin uchun", show_alert=True)
            _, pid, action = cb.data.split(":")
            p = self.db.payment(int(pid))
            if not p:
                return await cb.answer("To'lov topilmadi", show_alert=True)
            # Bitta to'lovga faqat bir marta qaror: ikkinchi bosish yoki ikkinchi admin "ko'rib chiqilgan" deb oladi
            if p["status"] != "kutilmoqda" or not self.db.claim_payment(p["id"], cb.from_user.id):
                p = self.db.payment(int(pid)) or p
                return await cb.answer(f"Bu chek allaqachon ko'rib chiqilgan: {p['status']}", show_alert=True)
            base = cb.message.caption or ""
            if action == "no":
                self.db.decide_payment(p["id"], "rad etildi", cb.from_user.id)
                await cb.message.edit_caption(caption=base + "\n\n❌ <b>Rad etildi</b>", reply_markup=None)
                try:
                    await self.bot.send_message(p["user_id"], "❌ To'lov chekingiz tasdiqlanmadi. Savollar bo'lsa, "
                                                "admin bilan bog'laning" + (f": {self.admin_contact}" if self.admin_contact else "."))
                except Exception:  # noqa: BLE001
                    pass
                return await cb.answer("Rad etildi")
            old = self.db.code_for_user(p["user_id"])
            if old:  # bitta foydalanuvchiga bitta (amaldagi) kod
                holat = "ishlatilgan, premium faol" if old["used"] else "hali ishlatilmagan"
                self.db.decide_payment(p["id"], "takroriy", cb.from_user.id, old["code"])
                await cb.message.edit_caption(
                    caption=base + f"\n\n⚠️ <b>Kod allaqachon berilgan</b> ({holat}): <code>{old['code']}</code>",
                    reply_markup=None)
                if not old["used"]:
                    try:
                        await self.bot.send_message(p["user_id"], "Sizga kod allaqachon berilgan. Faollashtirish uchun "
                                                    f"yuboring:\n<code>/kod {old['code']}</code>")
                    except Exception:  # noqa: BLE001
                        pass
                return await cb.answer(f"Bu foydalanuvchiga kod allaqachon berilgan ({holat}).", show_alert=True)
            plan = self.plans[action]
            code = self.db.create_code(plan["kun"], cb.from_user.id, for_user=p["user_id"])
            self.db.decide_payment(p["id"], f"tasdiqlandi {plan['nomi']}", cb.from_user.id, code)
            await cb.message.edit_caption(caption=base + f"\n\n✅ <b>{plan['nomi']} kod yuborildi:</b> <code>{code}</code>",
                                          reply_markup=None)
            try:
                await self.bot.send_message(
                    p["user_id"],
                    f"✅ To'lovingiz tasdiqlandi! <b>{plan['nomi']}</b> premium kodingiz:\n\n<code>{code}</code>\n\n"
                    f"Faollashtirish uchun shu xabarni yuboring:\n<code>/kod {code}</code>\n"
                    "yoki ilovadagi \"Premium\" bo'limiga kiriting.")
            except Exception as e:  # noqa: BLE001
                log.warning("foydalanuvchiga kod yuborilmadi: %s", e)
                await cb.message.answer(f"⚠️ Foydalanuvchiga xabar yetmadi. Kodni o'zingiz yuboring: <code>{code}</code>")
            await cb.answer("Kod yuborildi")

        return r

    async def show_premium(self, msg: Message, uid: int | None = None) -> None:
        uid = uid or msg.chat.id
        until = self.db.premium_until(uid)
        if until:
            return await msg.answer(f"💎 Premium faol: <b>{until.strftime('%d.%m.%Y')}</b> gacha.")
        await msg.answer(self.payment_text())
