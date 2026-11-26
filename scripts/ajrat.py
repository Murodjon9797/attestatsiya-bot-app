"""Takrorlanuvchi juftlikdagi qisqaroq variantni yangi matn bilan almashtirish.
python scripts/ajrat.py <slug> <patch.txt>   qator: <indeks>|<yangi matn>"""
import json, re, sys
from pathlib import Path
p = Path(__file__).resolve().parent.parent / "data" / "savollar" / f"{sys.argv[1]}.json"
d = json.loads(p.read_text())
W = lambda t: {w for w in re.findall(r"[\w'ʻ’]+", t.lower()) if len(w) > 3}
for line in Path(sys.argv[2]).read_text().splitlines():
    if not line.strip():
        continue
    i, t = line.split("|", 1); i = int(i); t = t.strip()
    a = d["savollar"][i]["a"]
    best = None
    for x in range(1, 4):
        for y in range(x + 1, 4):
            A, B = W(a[x]), W(a[y]); sm = A if len(A) <= len(B) else B
            if len(sm) >= 2 and len(A & B) / len(sm) >= 0.75:
                best = x if len(a[x]) < len(a[y]) else y
    if best is None or t in a:
        print("o'tkazildi", i); continue
    a[best] = t
    print(i, a)
p.write_text(json.dumps(d, ensure_ascii=False, indent=1))
