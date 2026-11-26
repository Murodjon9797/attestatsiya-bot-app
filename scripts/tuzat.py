"""Distraktorlarni almashtirish: python scripts/tuzat.py <slug> <patch.txt>
patch qatori:  <indeks>|<variant raqami 1-3>|<yangi matn>"""
import json, sys
from pathlib import Path
p = Path(__file__).resolve().parent.parent / "data" / "savollar" / f"{sys.argv[1]}.json"
d = json.loads(p.read_text())
for line in Path(sys.argv[2]).read_text().splitlines():
    if not line.strip(): continue
    i, j, t = line.split("|", 2)
    d["savollar"][int(i)]["a"][int(j)] = t.strip()
p.write_text(json.dumps(d, ensure_ascii=False, indent=1))
sys.argv = [sys.argv[0], "--holat"]
