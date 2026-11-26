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
        return [{"id": s["id"], "kod": s.get("kod", ""), "nomi": s["nomi"], "soni": len(s["savollar"]),
                 "turi": s.get("turi", "maxsus"), "manba": s.get("manba", ""),
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
