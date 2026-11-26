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


class QuestionBank:
    def __init__(self, folder: str | Path):
        self.subjects: dict[str, dict] = {}
        for p in sorted(Path(folder).glob("*.json")):
            d = json.loads(p.read_text(encoding="utf-8"))
            qs = [q for q in d.get("savollar", []) if len(q.get("a", [])) == 4]
            if qs:
                self.subjects[p.stem] = {**d, "id": p.stem, "savollar": qs}

    def listing(self) -> list[dict]:
        return [{"id": s["id"], "kod": s.get("kod", ""), "nomi": s["nomi"], "soni": len(s["savollar"]),
                 "umumiy": bool(s.get("umumiy")), "manba": s.get("manba", ""),
                 "bolimlar": list(dict.fromkeys(q.get("b", "") for q in s["savollar"] if q.get("b")))}
                for s in sorted(self.subjects.values(), key=lambda x: (not x.get("umumiy"), x["nomi"].lower()))]

    def match(self, nomi: str, kod: str = "") -> str | None:
        """Fan nomi yoki kodi bo'yicha bazadagi mos fanni topadi."""
        if kod:
            for s in self.subjects.values():
                if s.get("kod") and s["kod"] == kod:
                    return s["id"]
        k = _key(nomi)
        if len(k) < 4:
            return None
        for s in self.subjects.values():
            sk = _key(s["nomi"])
            if k == sk or (len(k) >= 6 and (k in sk or sk in k)):
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
