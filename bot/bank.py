"""Tayyor savollar bazasi (data/savollar/*.json) — API kalitisiz ishlaydi.

Fayl tuzilishi: {"kod", "nomi", "manba", "savollar": [{"b": bo'lim, "q": savol,
"a": [to'g'ri javob, 3 ta noto'g'ri variant], "e": izoh}]}.
Faylda to'g'ri javob doim birinchi turadi, foydalanuvchiga berishda variantlar aralashtiriladi.
"""
from __future__ import annotations

import json
import random
import re
from pathlib import Path

APOS = "ʻʼ‘’`'"


def _key(s: str) -> str:
    s = re.sub(r"\(.*?\)", "", s.lower())
    s = re.sub(rf"[{APOS}]", "", s)
    return re.sub(r"[^0-9a-zа-яёўқғҳ]+", "", s)


def _words(s: str) -> list[str]:
    s = re.sub(r"\(.*?\)", " ", s.lower())
    s = re.sub(rf"[{APOS}]", "", s)
    return [w for w in re.split(r"[^0-9a-zа-яёўқғҳ]+", s) if w and not w.isdigit()]


class QuestionBank:
    def __init__(self, folder: str | Path):
        self.subjects: dict[str, dict] = {}
        for p in sorted(Path(folder).glob("*.json")):
            d = json.loads(p.read_text(encoding="utf-8"))
            qs = [q for q in d.get("savollar", []) if len(q.get("a", [])) == 4]
            if qs:
                self.subjects[p.stem] = {**d, "id": p.stem, "savollar": qs}

    def listing(self) -> list[dict]:
        order = {"umumtalim": 0, "maxsus": 1, "bosqich1": 2}
        cats = self.categories()  # type: ignore[attr-defined]
        kat = {sid: title for _, title, ids in cats for sid in ids}
        kat_n = {sid: n for n, (_, _, ids) in enumerate(cats) for sid in ids}
        return [{"id": s["id"], "kod": s.get("kod", ""), "nomi": s["nomi"], "soni": len(s["savollar"]),
                 "turi": s.get("turi", "maxsus"), "manba": s.get("manba", ""), "kat": kat.get(s["id"], ""), "kalit": s.get("kalit", ""), "kat_n": kat_n.get(s["id"], 99),
                 "bolimlar": list(dict.fromkeys(q.get("b", "") for q in s["savollar"] if q.get("b")))}
                for s in sorted(self.subjects.values(),
                                key=lambda x: (order.get(x.get("turi", "maxsus"), 1), x["nomi"].lower()))]

    def match(self, nomi: str, kod: str = "") -> str | None:
        """Fan nomi yoki kodi bo'yicha bazadagi mos fanni topadi.

        Nom bo'yicha: fan nomi baza fani nomi bilan boshlanishi kerak ("Kiberxavfsizlik asoslari" →
        "Kiberxavfsizlik") yoki "Oliy/Umumiy/Amaliy" so'zidan keyin shu nom kelishi kerak
        ("Oliy matematika" → "Matematika"). "Tizimli dasturlash" kabi o'rtadagi moslik hisoblanmaydi.
        """
        fw = _words(nomi)
        if not fw:
            return None
        subjects = [x for x in self.subjects.values() if x.get("turi") != "bosqich1"]
        for s in subjects:
            bw = _words(s["nomi"])
            if not bw:
                continue
            core = fw[1:] if fw[0] in ("oliy", "umumiy", "amaliy") else fw
            prefix = core[:len(bw)] == bw and (len(bw) > 1 or len(core) - len(bw) <= 2)
            shorter = len(fw) >= 2 and bw[:len(fw)] == fw
            if prefix or shorter:
                return s["id"]
        # kod bo'yicha — faqat nom ham yaqin bo'lsa (hujjatlarda kodlar ba'zan siljigan)
        if kod:
            for s in subjects:
                if s.get("kod") == kod and _words(s["nomi"])[:1] == fw[:1]:
                    return s["id"]
        return None

    def _render(self, sid: str, idx: int) -> dict:
        q = self.subjects[sid]["savollar"][idx]
        opts = list(q["a"])
        correct = opts[0]
        random.shuffle(opts)
        return {"qid": f"{sid}:{idx}", "sid": sid, "savol": q["q"], "variantlar": opts,
                "togri": opts.index(correct), "izoh": q.get("e", ""), "bolim": q.get("b", "")}

    def draw(self, sid: str, soni: int, only: list[str] | None = None) -> list[dict]:
        """Tasodifiy `soni` ta savol (variantlar aralashtirilgan). `only` — faqat shu qid'lardan."""
        n = len(self.subjects[sid]["savollar"])
        pool = list(range(n))
        if only is not None:
            allowed = {int(q.split(":")[1]) for q in only if q.startswith(sid + ":")}
            pool = [i for i in pool if i in allowed]
        return [self._render(sid, i) for i in random.sample(pool, min(soni, len(pool)))]


# ---------------- yo'nalishlar bo'yicha guruhlash va qidiruv ----------------
CATEGORIES: list[tuple[str, str, list[str]]] = [
    ("til", "🗣 Tillar", ["ingliz_tili", "rus_tili", "nemis_tili", "ona_tili_adabiyot"]),
    ("ijt", "🏛 Ijtimoiy fanlar", ["tarix", "davlat_va_huquq_asoslari", "tarbiya", "biznes_asoslari"]),
    ("it", "💻 Axborot texnologiyalari", [
        "shaxsiy_kompyuter_arxitekturasi", "dasturlash", "algoritmlar", "malumotlar_bazasi", "kompyuter_tarmoqlari", "kiberxavfsizlik",
        "dasturiy_taminotni_testlash", "iqtisodiyotda_axborot_kommunikatsiya_tex",
        "qishloq_xojaligida_axborot_kommunikatsio", "qurilishda_axborot_texnologiyalari",
        "texnik_tizimlarda_at", "tibbiyotda_axborot_texnologiyalari", "muhandislik_grafikasi"]),
    ("muh", "⚙️ Muhandislik va texnika", [
        "amaliy_matematika", "hisob", "mexanika", "texnik_mexanika", "elektrotexnika",
        "konstruksion_materiallar", "metrologiya", "chizma_geometriya", "issiqlik_texnikasi_va_gidroenergetika",
        "radiotexnika_antenna", "geodeziya", "mehnat_muhofazasi"]),
    ("tib", "🩺 Tibbiyot", [
        "hamshiralik_ishi", "farmakologiya",
        "lotin_tili_va_tibbiy_terminologiya", "mikrobiologiya_virusologiya_va_immunolog", "yuqumli_kasalliklar",
        "tibbiy_biologiya_umumiy_genetika", "tibbiy_psixologiya_va_shaxslararo_muloqo",
        "umumiy_gigiyena_va_ekologiya", "jamiyat_sogliqni_saqlash_va_tibbiy_stati", "valeologiya"]),
    ("tr", "🚆 Transport", [
        "temir_yol_umumiy_kursi", "temir_yollardan_texnik_foydalanish_qoida", "tashishlarni_tashkil_etish",
        "vagon_konteyner", "yol_harakati_qoidalari_va_harakat_xavfsi", "avtomobillar_tuzilishi"]),
    ("qx", "🌱 Qishloq xo'jaligi va biologiya", [
        "biologiya", "botanika_va_osimliklar_fiziologiyasi", "osimlikshunoslik", "ekologiya"]),
    ("iqt", "📈 Iqtisodiyot va boshqaruv", ["iqtisodiyot_nazariyasi", "menejment_asoslari"]),
    ("xiz", "✂️ Yengil sanoat, dizayn va xizmat", ["tikuvchilik", "kompyuter_grafikasi"]),
    ("ped", "🎵 San'at va pedagogika", ["maktabgacha_pedagogika", "musiqiy_talim", "pedagogik_mahorat"]),
    ("um", "📘 Umumta'lim fanlari", ["matematika", "fizika", "kimyo", "informatika", "jismoniy_tarbiya"]),
]

# Qidiruvda qo'shimcha kalit so'zlar (foydalanuvchi boshqacha yozishi mumkin)
ALIASES: dict[str, str] = {
    "it": "informatika axborot kompyuter dasturchi akt",
    "muh": "texnika muhandis texnik",
    "tib": "tibbiyot meditsina hamshira shifokor tibbiy",
    "tr": "transport temiryol temir yol poyezd avtomobil",
    "qx": "qishloq agronomiya dehqonchilik",
    "iqt": "iqtisod iqtisodiyot buxgalteriya boshqaruv",
    "xiz": "tikuv tikuvchi kiyim dizayn yengil sanoat xizmat",
    "ped": "musiqa pedagogika pedagogik",
    "um": "umumtalim",
    "til": "til tillar language english ingliz rus nemis",
    "ijt": "ijtimoiy tarix huquq",
}


CYR = dict(zip("абвгдезийклмнопрстуфхцчшэюяўқғҳыъь",
               ["a", "b", "v", "g", "d", "e", "z", "i", "y", "k", "l", "m", "n", "o", "p", "r", "s", "t", "u",
                "f", "x", "ts", "ch", "sh", "e", "yu", "ya", "o", "q", "g", "h", "i", "", ""]))
CYR.update({"ж": "j", "ё": "yo", "щ": "sh"})


def norm(s: str) -> str:
    """Kichik harf, apostrofsiz, kirill → lotin (foydalanuvchi kirillcha yozsa ham topilsin)."""
    s = "".join(CYR.get(ch, ch) for ch in s.lower())
    s = re.sub(rf"[{APOS}]", "", s)
    return " ".join(re.split(r"[^0-9a-z]+", s)).strip()


def _search(bank: "QuestionBank", query: str) -> tuple[list[str], list[str]]:
    """(mos fanlar id'lari, mos yo'nalishlar id'lari). Har bir so'z (3+ harf) fan nomidagi
    biror so'zning boshi bo'lishi kerak: "kiber", "temir yo'l", "tibbiy psix"."""
    qw = [w for w in norm(query).split() if len(w) >= 2]
    if not qw:
        return [], []
    hits: list[tuple[int, str]] = []
    for sid, s in bank.subjects.items():
        words = norm(s["nomi"] + " " + sid.replace("_", " ") + " " + s.get("kalit", "")).split()
        if all(any(w.startswith(q) or (len(q) >= 5 and q in w) for w in words) for q in qw):
            score = sum(1 for q in qw for w in words if w == q)
            hits.append((-score, s["nomi"].lower(), sid))
    cats = [cid for cid, title, _ in CATEGORIES
            if all(any(w.startswith(q) for w in norm(title + " " + ALIASES.get(cid, "")).split()) for q in qw)]
    return [h[-1] for h in sorted(hits)], cats


def _categories(bank: "QuestionBank") -> list[tuple[str, str, list[str]]]:
    """Faqat bazada bor fanlar; ro'yxatga kirmay qolgan yangi fanlar "Boshqa" guruhiga tushadi."""
    used: set[str] = set()
    out = []
    for cid, title, ids in CATEGORIES:
        ids = [i for i in ids if i in bank.subjects]
        used.update(ids)
        if ids:
            out.append((cid, title, ids))
    rest = sorted((i for i in bank.subjects if i not in used), key=lambda i: bank.subjects[i]["nomi"].lower())
    if rest:
        out.append(("boshqa", "📂 Boshqa fanlar", rest))
    return out


QuestionBank.search = _search  # type: ignore[attr-defined]
QuestionBank.categories = _categories  # type: ignore[attr-defined]
