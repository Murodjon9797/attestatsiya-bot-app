"""data/fanlar_2026.json faylini o'qish."""
from __future__ import annotations

import json
from pathlib import Path


class Catalog:
    def __init__(self, path: str | Path):
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        self.yil = d.get("yil", 2026)
        self.yangilangan = d.get("yangilangan", "")
        self.sohalar: list[dict] = d["bilim_sohalari"]

    def soha(self, bi: int) -> dict:
        return self.sohalar[bi]

    def yunalish(self, bi: int, yi: int) -> dict:
        return self.sohalar[bi]["yunalishlar"][yi]

    def mutaxassislik(self, bi: int, yi: int, mi: int) -> dict:
        return self.yunalish(bi, yi)["mutaxassisliklar"][mi]

    def stats(self) -> tuple[int, int, int]:
        ys = [y for b in self.sohalar for y in b["yunalishlar"]]
        ms = [m for y in ys for m in y["mutaxassisliklar"]]
        return len(ys), len(ms), sum(1 for m in ms if m["fanlar"])
