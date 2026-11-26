"""edu.profedu.uz dan 2026-yilgi texnikum mutaxassisliklari va fanlarini yig'ish.

Ishlatish:
    python scrape.py                 # .env dagi login bilan to'liq yig'ish
    python scrape.py --no-login      # faqat ochiq ma'lumot (yo'nalish va mutaxassisliklar)
    python scrape.py --only 50610203 # faqat bitta mutaxassislik (sinash uchun)

Natija: data/fanlar_2026.json

Qo'lda fayl berish: agar biror mutaxassislik o'quv dasturini o'zingiz yuklab olsangiz,
uni data/raw/<kod>_<istalgan_nom>.pdf (yoki .docx/.xlsx/.zip) qilib qo'ying —
skript uni ham o'qiydi.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import sys
from dataclasses import asdict
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

from scraper.profedu import ProfEduClient, Mutaxassislik

ROOT = Path(__file__).parent
RAW = ROOT / "data" / "raw"
CACHE = ROOT / "data" / "cache"
log = logging.getLogger("scrape")


def safe(name: str) -> str:
    return re.sub(r"[^\w.\-]+", "_", name)[:120]


def local_files(kod: str) -> list[Path]:
    return sorted(p for p in RAW.glob(f"{kod}_*") if p.is_file())


def fetch_files(pe: ProfEduClient, m: Mutaxassislik) -> list[Path]:
    """Mutaxassislik o'quv dasturi fayllarini data/raw/ ga yuklab oladi (agar hali yo'q bo'lsa)."""
    have = local_files(m.kod)
    if have or not pe.logged_in:
        return have
    urls = pe.program_file_urls(m)
    if not urls:
        log.warning("%s: 'O'quv dasturi' havolasi topilmadi (%s)", m.kod, m.url)
        return []
    out = []
    for u in urls:
        try:
            data, name = pe.download(u)
        except Exception as e:  # noqa: BLE001
            log.warning("%s: yuklab bo'lmadi %s: %s", m.kod, u, e)
            continue
        p = RAW / f"{m.kod}_{safe(name)}"
        p.write_bytes(data)
        out.append(p)
        log.info("%s: yuklandi %s (%d KB)", m.kod, p.name, len(data) // 1024)
    return out


MIN_LOCAL = 3  # mahalliy ajratgich shundan kam modul topsa, Claude'ga yuboriladi


async def extract_all(todo: list[tuple[Mutaxassislik, list[Path]]], parallel: int) -> None:
    from scraper.local_parse import name_key, parse_file

    has_key = bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"))
    client = None
    if has_key:
        import anthropic

        client = anthropic.AsyncAnthropic()
    sem = asyncio.Semaphore(parallel)
    from concurrent.futures import ProcessPoolExecutor

    pool = ProcessPoolExecutor(max_workers=os.cpu_count() or 4)
    loop = asyncio.get_running_loop()

    async def one(m: Mutaxassislik, files: list[Path]):
        cache = CACHE / f"{m.kod}.json"
        sig = [f"{p.name}:{p.stat().st_size}" for p in files]
        if cache.exists():
            c = json.loads(cache.read_text())
            if c.get("sig") == sig:
                m.fanlar, m.fanlar_manba = c["fanlar"], c["manba"]
                return
        fanlar: list[dict] = []
        for p in files:
            data = p.read_bytes()
            try:
                got = await loop.run_in_executor(pool, parse_file, data, p.name)
            except Exception as e:  # noqa: BLE001
                log.warning("%s: %s ni o'qib bo'lmadi: %s", m.kod, p.name, e)
                got = []
            if len(got) < MIN_LOCAL:
                if client is None:
                    log.warning("%s: %s dan modullar topilmadi (Claude kaliti yo'q).", m.kod, p.name)
                    continue
                from scraper.extract import extract_fanlar

                async with sem:
                    try:
                        got = await extract_fanlar(client, data, p.name, m.nomi)
                    except Exception as e:  # noqa: BLE001
                        log.warning("%s: %s dan fan ajratib bo'lmadi: %s", m.kod, p.name, e)
                        continue
            names = {name_key(f["nomi"]) for f in fanlar}
            fanlar += [f for f in got if name_key(f["nomi"]) not in names]
        if fanlar:
            m.fanlar, m.fanlar_manba = fanlar, ", ".join(p.name for p in files)
            cache.write_text(json.dumps({"sig": sig, "fanlar": fanlar, "manba": m.fanlar_manba},
                                        ensure_ascii=False, indent=1))
            log.info("%s %s: %d ta fan", m.kod, m.nomi, len(fanlar))

    try:
        await asyncio.gather(*(one(m, f) for m, f in todo))
    finally:
        pool.shutdown()


def main() -> int:
    load_dotenv(ROOT / ".env")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--year", type=int, default=2026)
    ap.add_argument("--no-login", action="store_true", help="saytga kirmasdan, faqat ochiq ma'lumot")
    ap.add_argument("--only", nargs="*", default=[], help="faqat shu kodli mutaxassisliklar")
    ap.add_argument("--parallel", type=int, default=4, help="bir vaqtda Claude so'rovlari soni")
    ap.add_argument("--out", default=os.getenv("DATA_FILE", "data/fanlar_2026.json"))
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    RAW.mkdir(parents=True, exist_ok=True)
    CACHE.mkdir(parents=True, exist_ok=True)
    pe = ProfEduClient()

    log.info("%d-yil texnikum mutaxassisliklari yuklanmoqda...", args.year)
    tree = pe.texnikum_tree(args.year)
    all_m = [m for b in tree for y in b["yunalishlar"] for m in y["mutaxassisliklar"]]
    log.info("%d ta bilim sohasi, %d ta mutaxassislik topildi", len(tree), len(all_m))

    sessionid = os.getenv("PROFEDU_SESSIONID", "")
    if not args.no_login and sessionid:
        if not pe.use_session_cookie(sessionid, probe=all_m[0]):
            log.error("PROFEDU_SESSIONID bilan kirib bo'lmadi (cookie eskirgan yoki xato). "
                      "Saytga qayta kiring va yangi sessionid ni oling.")
            return 1
        log.info("sessionid cookie bilan saytga kirildi.")
    elif not args.no_login:
        phone, pw = os.getenv("PROFEDU_PHONE", ""), os.getenv("PROFEDU_PASSWORD", "")
        if not (phone and pw):
            log.error(".env da PROFEDU_PHONE va PROFEDU_PASSWORD yo'q. --no-login bilan ishga tushiring "
                      "yoki ularni kiriting.")
            return 1
        if not pe.login(phone, pw):
            log.error("edu.profedu.uz ga kirib bo'lmadi: telefon yoki parol xato.")
            return 1
        log.info("Saytga muvaffaqiyatli kirildi.")

    targets = [m for m in all_m if not args.only or m.kod in args.only]
    todo = []
    for i, m in enumerate(targets, 1):
        files = fetch_files(pe, m)
        if files:
            todo.append((m, files))
        if i % 20 == 0:
            log.info("... %d/%d sahifa ko'rildi", i, len(targets))

    if todo:
        log.info("%d ta o'quv dasturidan fanlar ajratilmoqda...", len(todo))
        asyncio.run(extract_all(todo, args.parallel))
    # --only bilan ishlaganda qolgan mutaxassisliklar uchun oldingi keshni ishlatamiz
    for m in all_m:
        c = CACHE / f"{m.kod}.json"
        if not m.fanlar and c.exists():
            d = json.loads(c.read_text())
            m.fanlar, m.fanlar_manba = d["fanlar"], d["manba"]
    qolda_path = ROOT / "data" / "qolda_fanlar.json"
    if qolda_path.exists():
        qolda = json.loads(qolda_path.read_text())
        for m in all_m:
            if not m.fanlar and m.kod in qolda:
                m.fanlar, m.fanlar_manba = qolda[m.kod]["fanlar"], qolda[m.kod]["manba"]
    missing = [m.kod for m in all_m if not m.fanlar]
    if missing:
        log.warning("Fanlari topilmagan mutaxassisliklar (%d): %s", len(missing), " ".join(missing))

    out = {
        "manba": "https://edu.profedu.uz/meyorlar",
        "yil": args.year,
        "yangilangan": date.today().isoformat(),
        "bilim_sohalari": [
            {"nomi": b["nomi"], "yunalishlar": [
                {**{k: v for k, v in y.items() if k != "mutaxassisliklar"},
                 "mutaxassisliklar": [asdict(m) for m in y["mutaxassisliklar"]]}
                for y in b["yunalishlar"]]}
            for b in tree
        ],
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=1))
    with_f = sum(1 for m in all_m if m.fanlar)
    log.info("Saqlandi: %s — %d ta mutaxassislik, ulardan %d tasida fanlar bor.", args.out, len(all_m), with_f)
    return 0


if __name__ == "__main__":
    sys.exit(main())
