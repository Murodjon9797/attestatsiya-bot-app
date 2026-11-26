"""Attestatsiya savollar bazasini Claude orqali tuzish (har bir fanga 300 ta tekshirilgan savol).

Bosqichlar (har biri Message Batches API orqali — 50% arzon):
  1. REJA       — fan mazmunidan bo'limlar va har bir bo'limga savollar soni.
  2. TUZISH     — bo'limlar bo'yicha 20 tadan savol: 1 to'g'ri + 3 ishonarli noto'g'ri javob + izoh.
  3. TEKSHIRUV  — boshqa so'rovda model javob kalitini ko'rmasdan savolni yechadi va xatolarni belgilaydi.
                  Faqat model kalitga mos javob bergan va hech qanday nuqson topmagan savollar qabul qilinadi.
  4. MUVOZANAT  — to'g'ri javob variantlar ichida uzunligi bilan ajralib tursa, noto'g'ri variantlar
                  qayta yoziladi va savol qayta tekshiruvdan o'tadi.
Mahalliy qoidalar: 4 ta har xil variant, kirill harfi yo'q, "barchasi/hech biri" yo'q, takroriy savol yo'q,
to'g'ri javob eng uzun variantdan sezilarli uzun emas; butun bazada to'g'ri javob eng uzun bo'lgan
savollar ulushi ~25% atrofida bo'lishi nazorat qilinadi.

Ishlatish:
    export ANTHROPIC_API_KEY=...
    python scripts/generate_bank.py --fanlar 2            # sinov: dastlabki 2 ta fan
    python scripts/generate_bank.py                        # barcha fanlar (data/generator/fanlar.json)
    python scripts/generate_bank.py --holat                # qayerga yetganini ko'rsatish
Natija: data/savollar/<slug>.json (mavjud tekshirilgan savollar saqlanadi va to'ldiriladi).
Holat data/generator/state/ papkasida saqlanadi — to'xtab qolsa, qayta ishga tushirish davom ettiradi.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FANLAR = ROOT / "data" / "generator" / "fanlar.json"
STATE = ROOT / "data" / "generator" / "state"
BANK = ROOT / "data" / "savollar"
MODEL = "claude-opus-5-5"
TARGET = 300
CHUNK = 20
MAX_ROUNDS = 5

SYSTEM = """Sen O'zbekiston Respublikasi kasbiy ta'lim tizimida (texnikumlar) o'rta maxsus va professional ta'lim \
pedagog kadrlarining attestatsiyasi uchun test topshiriqlari tuzuvchi tajribali fan eksperti va testolog-san.
Attestatsiya VMning 572-son qarori bilan tasdiqlangan Nizom asosida o'tkaziladi: 2-bosqichda o'quv fani bo'yicha
40 ta test topshirig'i, har biri 2 ball. Test o'qituvchining fanni chuqur bilishini tekshiradi.

Har bir test topshirig'iga qat'iy talablar:
1. Til: o'zbek tili, lotin yozuvi, imloviy xatosiz. Atamalar fan dasturidagi kabi.
2. Bitta va faqat bitta to'g'ri javob. Noto'g'ri javoblar aniq noto'g'ri bo'lsin, lekin fanni yaxshi bilmagan
   kishi uchun ishonarli bo'lsin (keng tarqalgan xato tushunchalar, o'xshash atamalar, yaqin qiymatlar).
3. UZUNLIK: to'rt variant uzunligi va tuzilishi bir-biriga yaqin bo'lsin (farq ~20% dan oshmasin).
   To'g'ri javob eng uzun, eng batafsil yoki yagona aniqlik kiritilgan variant BO'LMASIN.
   Noto'g'ri variantlar ham to'liq, grammatik jihatdan to'g'ri jumla yoki atama bo'lsin.
4. Taqiqlanadi: "barchasi to'g'ri", "hech biri", "A va B", hazil yoki bema'ni variantlar; to'g'ri javobni
   oshkor qiluvchi so'zlar ("faqat", "hech qachon", "har doim") faqat noto'g'ri variantlarda bo'lishi.
5. Faqat umume'tirof etilgan, tekshirsa bo'ladigan bilim. Munozarali, eskirgan yoki mintaqaga xos aniq bo'lmagan
   raqamlarni (masalan, aniq jarima summalari) so'rama. Hisoblash masalalarida natijani o'zing qayta tekshir.
6. Savol mustaqil va aniq bo'lsin: rasm, jadval yoki "yuqoridagi"ga tayanmasin.
7. Qiyinlik aralash: ~30% bilish/eslash, ~50% tushunish va qo'llash, ~20% tahlil (vaziyatli, hisoblash).
8. "izoh" — nima uchun to'g'ri javob to'g'ri ekanini 1–2 gapda tushuntiradi."""

GEN_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["savollar"], "properties": {
    "savollar": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                 "required": ["savol", "togri", "xato", "izoh"], "properties": {
                     "savol": {"type": "string"}, "togri": {"type": "string"},
                     "xato": {"type": "array", "items": {"type": "string"}}, "izoh": {"type": "string"}}}}}}
PLAN_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["bolimlar"], "properties": {
    "bolimlar": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                 "required": ["nomi", "mavzular", "ulush"], "properties": {
                     "nomi": {"type": "string"}, "mavzular": {"type": "string"},
                     "ulush": {"type": "integer"}}}}}}
VERIFY_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["javoblar"], "properties": {
    "javoblar": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                 "required": ["n", "tanlov", "nuqson"], "properties": {
                     "n": {"type": "integer"}, "tanlov": {"type": "string", "enum": ["A", "B", "C", "D"]},
                     "nuqson": {"type": "string", "description": "Bo'sh satr yoki nuqson tavsifi"}}}}}}
REBAL_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["xato"], "properties": {
    "xato": {"type": "array", "items": {"type": "string"}}}}

CYR = re.compile(r"[А-Яа-яЁё]")
BANNED = re.compile(r"barchasi|hech biri|hammasi to.g.ri|yuqoridagi", re.I)
LETTERS = "ABCD"


def norm(s: str) -> str:
    return re.sub(r"[^0-9a-z]+", "", s.lower().replace("ʻ", "").replace("’", "").replace("'", ""))


def length_ok(togri: str, xato: list[str]) -> bool:
    """To'g'ri javob eng uzun noto'g'ri variantdan sezilarli (15% va 8 belgidan ko'p) uzun bo'lmasin."""
    longest_wrong = max(len(x) for x in xato)
    return len(togri) <= max(longest_wrong * 1.15, longest_wrong + 8)


MAX_LONGEST = 0.25   # to'g'ri javob eng uzun bo'lgan savollar ulushi (tasodifiy daraja — 25%)
MAX_SHORTEST = 0.35  # to'g'ri javob eng qisqa bo'lishi ham oshkor qiluvchi belgi


def longest(q: dict) -> bool:
    return len(q["togri"]) > max(len(x) for x in q["xato"])


def shortest(q: dict) -> bool:
    return len(q["togri"]) < min(len(x) for x in q["xato"])


def pick_unbalanced(pool: list[dict], pending: list[dict]) -> list[dict]:
    """Butun fan bo'yicha to'g'ri javob eng uzun (yoki eng qisqa) bo'lgan savollar ulushini me'yorga keltirish
    uchun qayta yozilishi kerak bo'lgan savollarni tanlaydi (avval farqi eng kattalari)."""
    alls = pool + pending
    n = max(1, len(alls))
    out: list[dict] = []
    for pred, cap in ((longest, MAX_LONGEST), (shortest, MAX_SHORTEST)):
        cands = sorted((q for q in pending if pred(q)),
                       key=lambda q: -abs(len(q["togri"]) - sum(len(x) for x in q["xato"]) / 3))
        excess = sum(1 for q in alls if pred(q)) - int(cap * n)
        out += cands[:max(0, excess)]
    return out


def local_check(q: dict, seen: set[str]) -> str:
    opts = [q["togri"], *q["xato"]]
    if len(q["xato"]) != 3:
        return "variantlar soni"
    if len({norm(o) for o in opts}) != 4 or any(len(o.strip()) == 0 for o in opts):
        return "takroriy/bo'sh variant"
    blob = " ".join([q["savol"], *opts, q["izoh"]])
    if CYR.search(blob.replace("СУММ", "")):
        return "kirill harfi"
    if any(BANNED.search(o) for o in opts):
        return "taqiqlangan variant"
    if norm(q["savol"]) in seen:
        return "takroriy savol"
    if len(q["savol"]) < 12 or len(q["izoh"]) < 10:
        return "juda qisqa"
    return ""


# ---------------------------------------------------------------- Batch yordamchilari
class Batcher:
    def __init__(self, client, dry: bool = False):
        self.client, self.dry = client, dry

    def run(self, name: str, requests: list[tuple[str, dict]]) -> dict[str, dict]:
        """requests: [(custom_id, params)] → {custom_id: parsed_json}. Natija diskka keshlanadi."""
        cache = STATE / f"{name}.json"
        if cache.exists():
            return json.loads(cache.read_text())
        if not requests:
            return {}
        if self.dry:
            print(f"  [dry-run] {name}: {len(requests)} ta so'rov yuborilardi")
            return {}
        from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
        from anthropic.types.messages.batch_create_params import Request

        out: dict[str, dict] = {}
        for i in range(0, len(requests), 5000):
            part = requests[i:i + 5000]
            batch = self.client.messages.batches.create(requests=[
                Request(custom_id=cid, params=MessageCreateParamsNonStreaming(**p)) for cid, p in part])
            print(f"  {name}: batch {batch.id} ({len(part)} so'rov) yuborildi, kutilmoqda...", flush=True)
            while True:
                b = self.client.messages.batches.retrieve(batch.id)
                if b.processing_status == "ended":
                    break
                time.sleep(60)
            for r in self.client.messages.batches.results(batch.id):
                if r.result.type != "succeeded":
                    continue
                msg = r.result.message
                if msg.stop_reason in ("refusal", "max_tokens"):
                    continue
                text = "".join(b.text for b in msg.content if b.type == "text")
                try:
                    out[r.custom_id] = json.loads(text)
                except json.JSONDecodeError:
                    pass
        cache.write_text(json.dumps(out, ensure_ascii=False))
        return out


def params(system: str, user: str, schema: dict, effort: str = "medium", max_tokens: int = 32000) -> dict:
    return {"model": MODEL, "max_tokens": max_tokens, "system": system,
            "messages": [{"role": "user", "content": user}],
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": effort, "format": {"type": "json_schema", "schema": schema}}}


def subject_context(f: dict) -> str:
    maz = "\n".join(f"- {m}" for m in f.get("mazmun", [])[:8])
    nat = "\n".join(f"- {n}" for n in f.get("natijalar", [])[:6])
    mut = ", ".join(f.get("mutaxassisliklar", [])[:8])
    return (f"Fan: {f['nomi']}" + (f" (kod {f['kod']})" if f.get("kod") else "") +
            f"\nO'qitiladigan mutaxassisliklar ({f['mutaxassisliklar_soni']} ta), jumladan: {mut}\n"
            f"\n2026-yilgi rasmiy o'quv dasturlaridan fan mazmuni:\n{maz or '- (mazmun berilmagan)'}\n"
            f"\nO'qitish natijalari:\n{nat or '- (berilmagan)'}")


# ---------------------------------------------------------------- asosiy jarayon
def load_existing(slug: str) -> tuple[dict, list[dict]]:
    p = BANK / f"{slug}.json"
    if not p.exists():
        return {}, []
    d = json.loads(p.read_text())
    qs = [{"bolim": q.get("b", ""), "savol": q["q"], "togri": q["a"][0], "xato": q["a"][1:], "izoh": q.get("e", ""),
           "manba": q.get("src", "qo'lda")} for q in d.get("savollar", [])]
    return d, qs


def save_bank(f: dict, meta: dict, accepted: list[dict]) -> None:
    out = {"kod": meta.get("kod", f.get("kod", "")), "nomi": meta.get("nomi", f["nomi"]),
           "turi": meta.get("turi", "maxsus"),
           "manba": meta.get("manba") or "2026-yilgi texnikum o'quv rejalari va fan dasturlari mazmuni asosida",
           "savollar": [{"b": q["bolim"], "q": q["savol"], "a": [q["togri"], *q["xato"]], "e": q["izoh"],
                         "src": q.get("manba", "ai")} for q in accepted]}
    (BANK / f"{f['slug']}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fanlar", type=int, default=0, help="faqat dastlabki N ta fan (sinov uchun)")
    ap.add_argument("--slug", nargs="*", default=[], help="faqat shu fanlar")
    ap.add_argument("--target", type=int, default=TARGET)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--holat", action="store_true", help="holatni ko'rsatish va chiqish")
    args = ap.parse_args()
    STATE.mkdir(parents=True, exist_ok=True)
    fanlar = json.loads(FANLAR.read_text())
    if args.slug:
        fanlar = [f for f in fanlar if f["slug"] in args.slug]
    elif args.fanlar:
        fanlar = fanlar[:args.fanlar]

    if args.holat:
        for f in fanlar:
            n = len(load_existing(f["slug"])[1])
            print(f"{n:4d}/{args.target}  {f['nomi']}")
        return 0

    client = None
    if not args.dry_run:
        import anthropic
        client = anthropic.Anthropic()
    B = Batcher(client, args.dry_run)

    # holat: fan bo'yicha qabul qilingan savollar
    pool: dict[str, list[dict]] = {}
    meta: dict[str, dict] = {}
    for f in fanlar:
        meta[f["slug"]], pool[f["slug"]] = load_existing(f["slug"])

    # 0) mavjud savollarni tekshiruv navbatiga qo'yish (avval qo'lda yozilganlar ham tekshiriladi)
    pending: dict[str, list[dict]] = {f["slug"]: [] for f in fanlar}
    for f in fanlar:
        if not (STATE / f"existing_done_{f['slug']}").exists():
            pending[f["slug"]] = pool[f["slug"]]
            pool[f["slug"]] = []

    # 1) REJA
    plan_req = [(f"plan__{f['slug']}", params(SYSTEM, subject_context(f) +
                f"\n\nShu fan bo'yicha attestatsiya testlari uchun 8–14 ta bo'lim reja tuz. Har bo'limga mavzular "
                f"ro'yxatini va {args.target} ta savoldan unga to'g'ri keladigan ulushni (butun son, jami {args.target}) yoz. "
                "Bo'limlar fanning texnikumda o'qitiladigan asosiy mazmunini to'liq qamrasin.", PLAN_SCHEMA, "medium", 8000))
                for f in fanlar if not (STATE / f"plan__{f['slug']}.json").exists()]
    plans = B.run("plans", plan_req) if plan_req else {}
    for f in fanlar:
        p = STATE / f"plan__{f['slug']}.json"
        if f"plan__{f['slug']}" in plans:
            p.write_text(json.dumps(plans[f"plan__{f['slug']}"], ensure_ascii=False))

    for rnd in range(1, MAX_ROUNDS + 1):
        # 2) TUZISH — kerakli miqdorni bo'limlar ulushiga qarab
        gen_req = []
        for f in fanlar:
            slug = f["slug"]
            p = STATE / f"plan__{slug}.json"
            if not p.exists():
                continue
            need = args.target - len(pool[slug]) - len(pending[slug])
            if need <= 0:
                continue
            bol = json.loads(p.read_text())["bolimlar"]
            total = sum(max(1, b["ulush"]) for b in bol)
            have = {}
            for q in pool[slug] + pending[slug]:
                have[q["bolim"]] = have.get(q["bolim"], 0) + 1
            want = []
            for b in bol:
                quota = round(args.target * max(1, b["ulush"]) / total * 1.1)  # 10% zaxira — tekshiruvda tushib qoladi
                want.append((b, max(0, quota - have.get(b["nomi"], 0))))
            stems = [q["savol"] for q in pool[slug] + pending[slug]]
            for b, k in want:
                for c in range(0, k, CHUNK):
                    n = min(CHUNK, k - c)
                    avoid = "\n".join(f"- {s}" for s in random.sample(stems, min(40, len(stems))) if s)
                    gen_req.append((f"gen{rnd}__{slug}__{hashlib.md5((b['nomi'] + str(c)).encode()).hexdigest()[:8]}",
                                    params(SYSTEM, subject_context(f) +
                                           f"\n\nBo'lim: {b['nomi']}\nMavzular: {b['mavzular']}\n\n"
                                           f"Shu bo'lim bo'yicha {n} ta yangi test topshirig'ini tuz. Har biri boshqa "
                                           "mavzu yoki jihatni tekshirsin." +
                                           (f"\nQuyidagi savollarni takrorlama:\n{avoid}" if avoid else ""),
                                           GEN_SCHEMA)))
        gen = B.run(f"gen_round{rnd}", gen_req)
        for cid, res in gen.items():
            _, slug, _ = cid.split("__")
            bolim = _bolim_of(cid, slug)
            for q in res.get("savollar", []):
                q["bolim"] = bolim
                q["manba"] = "ai"
                pending[slug].append(q)

        # mahalliy tekshiruv + uzunlik muvozanati
        rebal_req = []
        for f in fanlar:
            slug = f["slug"]
            seen = {norm(q["savol"]) for q in pool[slug]}
            keep = []
            for q in pending[slug]:
                why = local_check(q, seen)
                if why:
                    continue
                seen.add(norm(q["savol"]))
                q["_id"] = hashlib.md5((slug + q["savol"]).encode()).hexdigest()[:12]
                keep.append(q)
            pending[slug] = keep
            fix = {q["_id"] for q in pending[slug] if not length_ok(q["togri"], q["xato"])}
            fix |= {q["_id"] for q in pick_unbalanced(pool[slug], pending[slug])}
            for q in pending[slug]:
                if q["_id"] not in fix:
                    continue
                L = len(q["togri"])
                rebal_req.append((f"rb{rnd}__{slug}__{q['_id']}", params(SYSTEM,
                    f"Savol: {q['savol']}\nTo'g'ri javob ({L} belgi): {q['togri']}\n"
                    f"Hozirgi noto'g'ri variantlar: {q['xato']}\n\nUchta noto'g'ri variantni qayta yoz. Har biri aniq "
                    f"noto'g'ri, lekin fanni yaxshi bilmagan kishi uchun ishonarli, tuzilishi to'g'ri javobga o'xshash "
                    f"bo'lsin. Uzunliklar: kamida bittasi to'g'ri javobdan uzunroq ({L + 3}–{int(L * 1.25) + 4} belgi), "
                    f"bittasi undan qisqaroq ({int(L * 0.8)}–{max(int(L * 0.8), L - 3)} belgi), qolgani "
                    f"{int(L * 0.9)}–{int(L * 1.15) + 2} belgi.", REBAL_SCHEMA, "low", 4000)))
        rb = B.run(f"rebal_round{rnd}", rebal_req)
        for f in fanlar:
            for q in pending[f["slug"]]:
                r = rb.get(f"rb{rnd}__{f['slug']}__{q['_id']}")
                if r and len(r.get("xato", [])) == 3:
                    q["xato"] = r["xato"]

        # 3) TEKSHIRUV — kalitsiz yechish
        ver_req, keymap = [], {}
        for f in fanlar:
            slug = f["slug"]
            qs = [q for q in pending[slug] if length_ok(q["togri"], q["xato"])]
            # me'yordan ortiq "eng uzun/eng qisqa" qolganlar bu bosqichda tekshiruvga yuborilmaydi
            over = {q["_id"] for q in pick_unbalanced(pool[slug], qs)}
            qs = [q for q in qs if q["_id"] not in over]
            for c in range(0, len(qs), CHUNK):
                part = qs[c:c + CHUNK]
                lines = []
                for i, q in enumerate(part):
                    opts = [q["togri"], *q["xato"]]
                    random.shuffle(opts)
                    keymap[(slug, q["_id"])] = LETTERS[opts.index(q["togri"])]
                    lines.append(f"{i + 1}. {q['savol']}\n" + "\n".join(f"{LETTERS[k]}) {o}" for k, o in enumerate(opts)))
                    q["_n"] = (c // CHUNK, i + 1)
                ver_req.append((f"v{rnd}__{slug}__{c // CHUNK}", params(
                    "Sen qat'iy test ekspertisan. Har bir savolni mustaqil yech va to'g'ri variantni tanla. So'ng "
                    "nuqsonlarni tekshir: bir nechta to'g'ri javob bormi, to'g'ri javob yo'qmi, faktik xato, noaniq "
                    "shart, imlo/til xatosi, javobni oshkor qiluvchi belgi (masalan, to'g'ri javob uzunligi yoki "
                    "batafsilligi bilan ajralib turishi). Nuqson bo'lmasa — bo'sh satr.",
                    f"Fan: {f['nomi']}\n\n" + "\n\n".join(lines), VERIFY_SCHEMA, "medium", 16000)))
        ver = B.run(f"verify_round{rnd}", ver_req)
        for f in fanlar:
            slug = f["slug"]
            still = []
            for q in pending[slug]:
                if "_n" not in q:
                    continue  # uzunlik muvozanati tiklanmadi — tashlanadi
                chunk, n = q["_n"]
                res = ver.get(f"v{rnd}__{slug}__{chunk}")
                if res is None:
                    still.append(q)
                    continue
                a = next((x for x in res.get("javoblar", []) if x["n"] == n), None)
                if a and a["tanlov"] == keymap[(slug, q["_id"])] and not a["nuqson"].strip():
                    pool[slug].append({k: v for k, v in q.items() if not k.startswith("_")})
            pending[slug] = still
            (STATE / f"existing_done_{slug}").touch()
            save_bank(f, meta[slug], pool[slug][:args.target])
            print(f"  {rnd}-bosqich: {f['nomi']}: {min(len(pool[slug]), args.target)}/{args.target}", flush=True)
        if all(len(pool[f["slug"]]) >= args.target for f in fanlar):
            break

    report(fanlar, args.target)
    return 0


def _bolim_of(cid: str, slug: str) -> str:
    h = cid.split("__")[2]
    for b in json.loads((STATE / f"plan__{slug}.json").read_text())["bolimlar"]:
        for c in range(0, 2000, CHUNK):
            if hashlib.md5((b["nomi"] + str(c)).encode()).hexdigest()[:8] == h:
                return b["nomi"]
    return ""


def report(fanlar: list[dict], target: int) -> None:
    tot = longest = 0
    for f in fanlar:
        p = BANK / f"{f['slug']}.json"
        if not p.exists():
            continue
        qs = json.loads(p.read_text())["savollar"]
        for q in qs:
            tot += 1
            longest += len(q["a"][0]) > max(len(x) for x in q["a"][1:])
        print(f"{len(qs):4d}/{target}  {f['nomi']}")
    if tot:
        print(f"\nJami: {tot} ta savol. To'g'ri javob eng uzun bo'lgan savollar: {100 * longest / tot:.0f}% "
              f"(maqsad: ≤{int(MAX_LONGEST * 100)}%, tasodifiy daraja).")


if __name__ == "__main__":
    sys.exit(main())
