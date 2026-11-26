"""Claude yordamida attestatsiya test savollarini tuzish."""
from __future__ import annotations

import random

import anthropic

from claude_json import ClaudeError, ask_json

SYSTEM = """Sen O'zbekiston Respublikasi kasbiy ta'lim tizimi (texnikumlar) pedagog kadrlarini \
attestatsiyadan o'tkazish uchun test topshiriqlari tuzuvchi tajribali ekspertsan.

Talablar:
- Savollar o'zbek tilida, lotin yozuvida, imloviy xatosiz yoziladi.
- Har bir savolda 4 ta javob varianti bo'ladi, ulardan faqat bittasi to'g'ri.
- Noto'g'ri variantlar ishonarli bo'lsin (aniq bema'ni variantlar bo'lmasin), uzunligi to'g'ri \
javobnikiga yaqin bo'lsin; "barchasi to'g'ri" / "hech biri" kabi variantlardan foydalanma.
- Savollarning taxminan 80 foizi fanning mazmuni (nazariya, atamalar, qonuniyatlar, amaliy \
vaziyatlar, hisob-kitoblar), 20 foizi shu fanni texnikumda o'qitish metodikasi (dars shakllari, \
baholash, kasbiy kompetensiyalar, amaliy mashg'ulotlar) bo'yicha bo'lsin.
- Qiyinlik: o'qituvchi uchun o'rta va yuqori daraja; faqat ta'rifni yodlashni emas, tushunishni tekshirsin.
- Savollar bir-birini takrorlamasin va fanning turli bo'limlarini qamrab olsin.
- Faqat aniq, umume'tirof etilgan bilimlarga tayan; munozarali yoki tez eskiradigan faktlardan qoch.
- "izoh" maydonida to'g'ri javob nima uchun to'g'riligini 1-2 gapda tushuntir."""

SCHEMA = {
    "type": "object",
    "properties": {
        "savollar": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "savol": {"type": "string"},
                    "variantlar": {"type": "array", "items": {"type": "string"}},
                    "togri": {"type": "integer", "enum": [0, 1, 2, 3],
                              "description": "To'g'ri variant indeksi (0 dan boshlab)"},
                    "izoh": {"type": "string"},
                },
                "required": ["savol", "variantlar", "togri", "izoh"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["savollar"],
    "additionalProperties": False,
}


async def generate(client: anthropic.AsyncAnthropic, *, fan: str, mutaxassislik: str,
                   yunalish: str, soni: int, blok: str = "", natijalar: str = "",
                   mazmun: str = "") -> list[dict]:
    """`soni` ta savol qaytaradi: [{savol, variantlar[4], togri, izoh}], variantlar aralashtirilgan."""
    prompt = (
        f"Fan: {fan}\n"
        + (f"Fan bloki: {blok}\n" if blok else "")
        + f"Mutaxassislik: {mutaxassislik}\n"
        f"Yo'nalish: {yunalish}\n"
        f"Ta'lim turi: o'rta maxsus professional ta'lim (texnikum), 2026/2027 o'quv yili\n\n"
    )
    if natijalar or mazmun:
        prompt += (
            "\nQuyida shu fanning 2026-yilgi rasmiy o'quv dasturidan parcha bor. Savollarning asosiy "
            "qismi aynan shu mazmun va o'qitish natijalarini qamrab olsin:\n<oquv_dasturi>\n"
            + (f"O'qitish natijalari: {natijalar}\n" if natijalar else "")
            + (f"Modul mazmuni: {mazmun}\n" if mazmun else "")
            + "</oquv_dasturi>\n"
        )
    prompt += f"\nShu fan o'qituvchisining attestatsiyasi uchun {soni} ta test savolini tuz."
    res = await ask_json(client, system=SYSTEM, content=prompt, schema=SCHEMA, effort="medium")
    out = []
    for q in res["savollar"]:
        opts = [" ".join(str(v).split()) for v in q["variantlar"]]
        if len(opts) != 4 or not q["savol"].strip() or len(set(opts)) != 4:
            continue
        correct = opts[q["togri"]]
        random.shuffle(opts)  # to'g'ri javob doim bir joyda turmasligi uchun
        out.append({"savol": q["savol"].strip(), "variantlar": opts,
                    "togri": opts.index(correct), "izoh": q["izoh"].strip()})
    if len(out) < max(3, soni // 2):
        raise ClaudeError("Yetarlicha sifatli savol tuzilmadi, qayta urinib ko'ring.")
    return out[:soni]
