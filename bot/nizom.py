"""VMning 2021-yil 17-sentabrdagi 572-son qarori bilan tasdiqlangan Nizom (amaldagi tahrirda) —
o'rta maxsus va professional ta'lim tashkilotlari pedagog kadrlari uchun qoidalar.

- 5-band: ishlab chiqarish ta'limi ustalari attestatsiyaga jalb etilmaydi (2026-yil 9-oktabrdagi 552-son qaror tahriri).
- 18-band: umumkasbiy va maxsus fan o'qituvchilari o'quv yuklamasi ko'p bo'lgan bitta fan bo'yicha
  (teng bo'lsa — o'zi tanlagan fan) attestatsiyadan o'tadi; natija fan sohasidagi boshqa fanlarga ham tegishli.
- 33-34-bandlar: 1-bosqich — pedagogik mahorat va psixologik tayyorgarlik, pedagogik (kuzatuv) kengashi, 20 ball;
  2-bosqich — o'quv fani bo'yicha 40 ta test, har biri 2 ball, jami 80 ball.
- 44-band: ikki bosqich natijasiga ko'ra malaka toifasi.
"""
LAVOZIMLAR = {
    "umumtalim": "Umumta'lim fani o'qituvchisi",
    "maxsus": "Umumkasbiy yoki maxsus fan o'qituvchisi",
    "usta": "Ishlab chiqarish ta'limi ustasi",
}
# toifa: (nomi, [(chegara, natija matni)] — yuqoridan pastga)
TOIFALAR = {
    "oliy": ("Oliy malaka toifasi (bosh o'qituvchi)",
             [(80, "Oliy toifa saqlanadi"), (0, "Birinchi toifaga tushiriladi")]),
    "birinchi": ("Birinchi malaka toifasi (yetakchi o'qituvchi)",
                 [(80, "Oliy toifa beriladi"), (70, "Birinchi toifa saqlanadi"), (0, "Ikkinchi toifaga tushiriladi")]),
    "ikkinchi": ("Ikkinchi malaka toifasi (katta o'qituvchi)",
                 [(70, "Birinchi toifa beriladi"), (60, "Ikkinchi toifa saqlanadi"), (0, "Mutaxassis lavozimiga tushiriladi")]),
    "mutaxassis": ("Mutaxassis (oliy ma'lumotli o'qituvchi)",
                   [(60, "Ikkinchi toifa beriladi"), (55, "Mutaxassis lavozimi saqlanadi"), (0, "Lavozimga muvofiq emas")]),
    "oliymalumotsiz": ("Oliy ma'lumotga ega emas",
                       [(55, "Lavozim saqlanadi"), (0, "Lavozimga muvofiq emas")]),
}
BOSQICH1_MAX, BOSQICH2_MAX, TEST_SONI = 20, 80, 40


def public() -> dict:
    return {"lavozimlar": LAVOZIMLAR,
            "toifalar": {k: {"nomi": v[0], "chegaralar": [{"ball": b, "natija": t} for b, t in v[1]]}
                         for k, v in TOIFALAR.items()},
            "bosqich1_max": BOSQICH1_MAX, "bosqich2_max": BOSQICH2_MAX, "test_soni": TEST_SONI}
