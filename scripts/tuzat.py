"""Distraktorlarni almashtirish: python scripts/tuzat.py <slug> <patch.txt>
patch qatori:  <indeks>|<variant raqami 1-3>|<yangi matn>
Almashtirilgandan keyin variantlar bir-birini takrorlasa ogohlantiradi."""
import json, re, sys
from pathlib import Path
p = Path(__file__).resolve().parent.parent / "data" / "savollar" / f"{sys.argv[1]}.json"
d = json.loads(p.read_text())
W = lambda t: {w for w in re.findall(r"[\w'ʻ’]+", t.lower()) if len(w) > 3}
for line in Path(sys.argv[2]).read_text().splitlines():
    if not line.strip():
        continue
    i, j, t = line.split("|", 2)
    a = d["savollar"][int(i)]["a"]
    if j == "s":  # eng qisqa noto'g'ri variantni almashtirish
        j = str(min(range(1, 4), key=lambda k: len(a[k])))
    if t.strip() in a:
        print(f"TAKROR {i}: '{t.strip()[:50]}' allaqachon bor — o'tkazildi")
        continue
    a[int(j)] = t.strip()
    for x in range(1, 4):
        if x == int(j):
            continue
        A, B = W(a[x]), W(a[int(j)])
        small, big = (A, B) if len(A) <= len(B) else (B, A)
        if len(small) >= 2 and len(small & big) / len(small) >= 0.75:
            print(f"OGOHLANTIRISH {i}: '{a[int(j)][:50]}' ~ '{a[x][:50]}'")
    if len(a[0]) > max(len(x) for x in a[1:]):
        print(f"HALI ENG UZUN {i}: {a[0][:50]}")
p.write_text(json.dumps(d, ensure_ascii=False, indent=1))
