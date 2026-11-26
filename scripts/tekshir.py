"""Bir savoldagi noto'g'ri variantlardan biri ikkinchisini takrorlasa ko'rsatadi: python scripts/tekshir.py <slug>"""
import json, re, sys
from pathlib import Path
p = Path(__file__).resolve().parent.parent / "data" / "savollar" / f"{sys.argv[1]}.json"
d = json.loads(p.read_text())
W = lambda t: {w for w in re.findall(r"[\w'ʻ’]+", t.lower()) if len(w) > 3}
for i, s in enumerate(d["savollar"]):
    a = s["a"]
    for x in range(1, 4):
        for y in range(x + 1, 4):
            A, B = W(a[x]), W(a[y])
            small, big = (A, B) if len(A) <= len(B) else (B, A)
            if len(small) >= 2 and len(small & big) / len(small) >= 0.75:
                print(f"{i}|{x}|{y}| {a[x][:60]} || {a[y][:60]}")
