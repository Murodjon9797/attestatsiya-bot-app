"""Qo'lda (API'siz) tuzilgan savollarni bazaga qo'shish.

Format (matn fayl):
    # Bo'lim nomi
    Q: savol matni
    + to'g'ri javob
    - noto'g'ri javob
    - noto'g'ri javob
    - noto'g'ri javob
    E: izoh (ixtiyoriy)

Ishlatish:
    python scripts/qoshish.py <slug> <fayl.txt> [--yangi]   # --yangi: eski savollarni almashtiradi
    python scripts/qoshish.py --holat                       # barcha bazalar statistikasi
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BANK = ROOT / "data" / "savollar"
GEN = ROOT / "data" / "generator" / "fanlar.json"


def parse(text: str) -> list[dict]:
    out, bolim, cur = [], "Umumiy", None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("# "):
            bolim = line[2:].strip()
        elif line.startswith("Q:"):
            if cur:
                out.append(cur)
            cur = {"b": bolim, "q": line[2:].strip(), "a": [], "e": ""}
        elif line.startswith("+ ") and cur is not None:
            cur["a"].insert(0, line[2:].strip())
            cur["_ok"] = cur.get("_ok", 0) + 1
        elif line.startswith("- ") and cur is not None:
            cur["a"].append(line[2:].strip())
        elif line.startswith("E:") and cur is not None:
            cur["e"] = line[2:].strip()
        elif cur is not None and cur["a"]:
            # oldingi variantning davomi
            cur["a"][-1] += " " + line
        elif cur is not None:
            cur["q"] += " " + line
    if cur:
        out.append(cur)
    good = []
    for c in out:
        ok = c.pop("_ok", 0)
        if ok != 1 or len(c["a"]) != 4 or len(set(c["a"])) != 4:
            print("XATO (o'tkazildi):", c["q"][:80], file=sys.stderr)
            continue
        good.append(c)
    return good


def stats(savollar: list[dict]) -> str:
    n = len(savollar) or 1
    longest = sum(1 for s in savollar if len(s["a"][0]) > max(len(x) for x in s["a"][1:]))
    shortest = sum(1 for s in savollar if len(s["a"][0]) < min(len(x) for x in s["a"][1:]))
    return f"{len(savollar)} ta | to'g'ri eng uzun {longest*100//n}% | eng qisqa {shortest*100//n}%"


def meta(slug: str) -> dict:
    for f in json.loads(GEN.read_text()):
        if f["slug"] == slug:
            return {"kod": f.get("kod") or "", "nomi": f["nomi"], "turi": "maxsus",
                    "manba": f"2026-yilgi texnikum o'quv rejalari ({f.get('mutaxassisliklar_soni', 0)} ta mutaxassislikda o'qitiladi)"}
    raise SystemExit(f"slug topilmadi: {slug}")


def main():
    if sys.argv[1] == "--holat":
        for p in sorted(BANK.glob("*.json")):
            d = json.loads(p.read_text())
            print(f"{p.stem:45} {stats(d['savollar'])}")
        return
    slug, fayl = sys.argv[1], Path(sys.argv[2])
    yangi = parse(fayl.read_text())
    path = BANK / f"{slug}.json"
    if path.exists() and "--yangi" not in sys.argv:
        d = json.loads(path.read_text())
    else:
        d = {**meta(slug), "savollar": []}
        if path.exists():
            old = json.loads(path.read_text())
            d.update({k: v for k, v in old.items() if k != "savollar"})
        d["manba"] = d["manba"].split(";")[0] + "; savollar davlat ta'lim standarti va o'quv dasturlari asosida tuzilgan"
    seen = {s["q"].lower() for s in d["savollar"]}
    added = 0
    for s in yangi:
        if s["q"].lower() in seen:
            print("TAKROR:", s["q"][:80], file=sys.stderr)
            continue
        seen.add(s["q"].lower())
        d["savollar"].append(s)
        added += 1
    path.write_text(json.dumps(d, ensure_ascii=False, indent=1))
    print(f"{slug}: +{added} → {stats(d['savollar'])} | qism: {stats(yangi)}")


if __name__ == "__main__":
    main()
