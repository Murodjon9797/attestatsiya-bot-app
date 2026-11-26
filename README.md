# Texnikum o'qituvchilari attestatsiyasi — Telegram bot

Bot [edu.profedu.uz](https://edu.profedu.uz/meyorlar) saytidagi **2026-yilgi** texnikum (o'rta maxsus
professional ta'lim) yo'nalishlari, mutaxassisliklari va fanlari asosida attestatsiya testini o'tkazadi.
Test savollarini sun'iy intellekt (Claude) har safar yangidan tuzadi.

**Oqim:** Bilim sohasi → Yo'nalish → Mutaxassislik → Fan → Savollar soni (10/20/30) → Test → Natija

## Premium va to'lov

- Bepul: `FREE_QUESTIONS` ta savol (standart 5). Keyin premium kerak.
- Tariflar: 1 oy — `PRICE_1M` (40 000 so'm), 3 oy — `PRICE_3M` (60 000 so'm).
- To'lov: foydalanuvchi `CARD_NUMBER` kartaga (egasi `CARD_OWNER`) pul o'tkazadi va chek rasmini
  ilovada yoki chatda yuboradi. Chek adminga **[✅ 1 oylik kod] [✅ 3 oylik kod] [❌ Rad etish]**
  tugmalari bilan keladi. Admin tasdiqlasa, bot foydalanuvchiga faollashtirish kodini yuboradi.
- Foydalanuvchi kodni `/kod ABCD-EFGH-JKLM` yoki ilovadagi Premium bo'limida kiritadi.
- Admin bo'lish: botga `/admin <ADMIN_CLAIM_CODE>` yozing (kod bir martalik). Yoki `ADMIN_IDS` ga Telegram ID.
- Admin buyruqlari: `/kod1`, `/kod3` — qo'lda kod yaratish (naqd to'lov va h.k.), `/statistika`.
- **Muhim:** `DATABASE_URL` (PostgreSQL, masalan Neon bepul) bo'lmasa, Render'da server qayta ishga
  tushganda obunalar va natijalar o'chadi.

Premium imkoniyatlari: cheksiz mashq, sinov imtihoni (vaqtli, javoblar oxirida), xatolar ustida ishlash,
fanlar va bo'limlar kesimida tahlil.

Bot ikki ko'rinishda ishlaydi:
- **Mini App** (Telegram ichida ochiladigan ilova): tahlil (tayyorlik darajasi, fanlar va zaif mavzular,
  dinamika), test (mashq, sinov imtihoni, xatolar ustida ishlash), premium. Fayllar: `webapp/index.html`, `bot/web.py`.
- **Chat rejimi**: tugmalar orqali xuddi shu test (Mini App ochilmaydigan qurilmalar uchun).

## Tuzilma

| Fayl | Vazifasi |
|---|---|
| `scrape.py` | Saytdan 2026-yil ma'lumotlarini yig'ib, `data/fanlar_2026.json` yaratadi |
| `scraper/profedu.py` | Sayt bilan ishlash: ochiq API, login, "O'quv dasturi" faylini yuklash |
| `scraper/local_parse.py` | O'quv dasturi PDF'idan fanlar, ularning mazmuni va o'qitish natijalarini API kalitisiz ajratish |
| `scraper/extract.py` | Zaxira: mahalliy usul o'qiy olmagan fayldan (DOCX/XLSX/ZIP, boshqa format) fanlarni Claude orqali ajratish |
| `data/qolda_fanlar.json` | Skanerlangan (matnsiz) hujjatlardan qo'lda ko'chirilgan fanlar |
| `bot/main.py` | Telegram bot (aiogram 3) + Mini App serverini ishga tushirish |
| `bot/web.py` | Mini App API: katalog, test, javoblarni tekshirish, XP, check-in, reyting (Telegram initData imzosi tekshiriladi) |
| `webapp/index.html` | Mini App sahifasi |
| `deploy/` | Serverga joylash: Caddy (HTTPS) va systemd xizmati |
| `bot/quiz.py` | Test savollarini tuzish |
| `bot/db.py` | Natijalarni SQLite'da saqlash |
| `data/fanlar_2026.json` | Tayyor ma'lumot: 9 bilim sohasi, 76 yo'nalish, 149 mutaxassislik, ulardan 117 tasida fanlar ro'yxati |

## O'rnatish

```bash
pip install -r requirements.txt
```

```bash
cp .env.example .env
```

`.env` faylini to'ldiring:

- `BOT_TOKEN` — [@BotFather](https://t.me/BotFather) dan olingan token
- `ANTHROPIC_API_KEY` — [console.anthropic.com](https://console.anthropic.com) dan olingan kalit
- `PROFEDU_PHONE`, `PROFEDU_PASSWORD` — edu.profedu.uz dagi akkauntingiz (faqat `scrape.py` uchun kerak)

## 1-qadam: fanlarni yig'ish

Fanlar ro'yxati har bir mutaxassislikning "O'quv dasturi" faylida turadi. Saytda bu fayl faqat
tizimga kirgandan keyin ochiladi. Shuning uchun skript sizning akkauntingiz bilan kiradi:

```bash
python scrape.py
```

Avval bitta mutaxassislikda sinab ko'rish uchun:

```bash
python scrape.py --only 50610203
```

- Yuklangan fayllar `data/raw/`, ajratilgan fanlar esa `data/cache/` papkasida saqlanadi. Qayta ishga
  tushirganda faqat yangi fayllar qayta ishlanadi.
- Fanlar PDF'dagi modul dasturlaridan (nomi, kodi, soati, mazmuni, o'qitish natijalari) yoki
  o'quv reja jadvalidan ajratiladi. Buning uchun API kaliti kerak emas. Claude faqat bu usul o'qiy olmagan
  fayllar uchun ishlatiladi.
- Login o'rniga brauzerdagi `sessionid` cookie'ni `PROFEDU_SESSIONID` ga qo'yish ham mumkin. Lekin
  sayt sessiyani qurilmaga bog'laydi, shuning uchun bu usul faqat o'sha kompyuterda ishlaydi.
- Fayllarni qo'lda ham berish mumkin: o'quv dasturini `data/raw/<kod>_nom.pdf` qilib saqlang
  (masalan `data/raw/50610203_dastur.pdf`), so'ng `python scrape.py --no-login` ni ishga tushiring.
- `--no-login` — saytga kirmaydi: faqat ochiq ma'lumot (yo'nalish va mutaxassisliklar) va `data/raw/` dagi fayllar ishlatiladi.

Fanlar ro'yxati hali yuklanmagan mutaxassisliklarda ham bot ishlaydi: o'qituvchi fan nomini o'zi yozadi.
2026-yil holatiga ko'ra 32 ta mutaxassislikka saytda o'quv dasturi umuman yuklanmagan. Keyinroq
`python scrape.py` ni qayta ishga tushirsangiz, yangi qo'shilgan dasturlar ham olinadi.

Ochiq (public) repozitoriyda `data/fanlar_2026.json` faqat fan nomlarini saqlaydi: o'quv dasturlaridagi
mazmun parchalari Institut mulki bo'lgani uchun olib tashlangan. `python scrape.py` ni o'zingiz ishga
tushirsangiz, fayl mazmun va o'qitish natijalari bilan to'liq yaratiladi. Shunda testlar aynan rasmiy
dastur mazmuni asosida tuziladi. Bunday faylni ochiq repozitoriyga yuklamang.

## 2-qadam: botni ishga tushirish

**Bepul 24/7 hosting (Render.com):** qadamma-qadam yo'riqnoma `deploy/RENDER.md` da. Ommaviy manzil bo'lsa
(`RENDER_EXTERNAL_URL` yoki `PUBLIC_URL`), bot o'zi webhook rejimiga o'tadi va Mini App tugmasini ulaydi.

**O'z serveringizda:**

Mini App uchun Telegram **HTTPS** manzil talab qiladi. Shuning uchun bot domenli serverda ishlashi kerak
(eng arzon VPS yetadi). Serverda:

```bash
sudo useradd -r -m -d /opt/attestatsiya_bot attestatsiya
```

Loyihani `/opt/attestatsiya_bot` ga ko'chiring, so'ng:

```bash
cd /opt/attestatsiya_bot && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

`.env` da `WEBAPP_URL=https://bot.sizning-domen.uz/` ni yozing (oxiridagi `/` bilan). Keyin
`deploy/Caddyfile` dagi domenni o'zingiznikiga almashtirib, Caddy'ni o'rnating va xizmatni yoqing:

```bash
sudo cp deploy/attestatsiya-bot.service /etc/systemd/system/ && sudo systemctl enable --now attestatsiya-bot
```

Bot ishga tushganda menyu tugmasi ("Ilova") avtomatik o'rnatiladi, `/start` da esa "📱 Ilovani ochish"
tugmasi chiqadi. Lokal kompyuterda sinash uchun (Telegram'siz, brauzerda) `.env` ga `WEBAPP_DEV_USER=1`
qo'shib, http://localhost:8080 ni oching. Serverda bu o'zgaruvchini **qo'ymang**.

```bash
python run_bot.py
```

Buyruqlar: `/start` — bosh menyu, `/natijalar` — oxirgi natijalar, `/help` — yordam.

## Sozlamalar (`.env`)

| O'zgaruvchi | Standart qiymat | Izoh |
|---|---|---|
| `CLAUDE_MODEL` | `claude-opus-5-5` | Test tuzadigan model |
| `PASS_PERCENT` | `60` | O'tish bali (%) |
| `DATA_FILE` | `data/fanlar_2026.json` | Ma'lumotlar fayli |
| `DB_FILE` | `data/natijalar.sqlite3` | Natijalar bazasi |

## Eslatmalar

- Saytdagi materiallar Kasbiy ta'limni rivojlantirish institutining intellektual mulki hisoblanadi.
  Skript faqat fan nomlarini oladi, fayllar esa sizning kompyuteringizda (`data/raw/`) qoladi.
  Ularni tarqatmang.
- Yo'nalish nomlari saytdagi bog'lanish bo'yicha olingan. Ba'zi mutaxassisliklar saytning o'zida
  boshqa yo'nalishga biriktirilgan bo'lishi mumkin.
- Savollarni sun'iy intellekt tuzadi. Ulardan tayyorgarlik uchun foydalaning, rasmiy test sifatida emas.
