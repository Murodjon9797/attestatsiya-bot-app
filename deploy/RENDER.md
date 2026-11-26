# Botni bepul 24/7 serverga joylash (Render.com)

Taxminan 15 daqiqa vaqt oladi. Kerak bo'ladi: GitHub akkaunti (bepul), Render akkaunti (bepul,
GitHub orqali kiriladi), bot tokeni va Anthropic API kaliti.

## 1. Kodni GitHub'ga yuklash

1. https://github.com/new da yangi repozitoriy oching: nomi `attestatsiya-bot`, turi **Private**.
2. "uploading an existing file" havolasini bosing.
3. `attestatsiya_bot.zip` ni kompyuteringizda oching va **ichidagi barcha fayl va papkalarni**
   brauzerga sudrab tashlang (`bot`, `data`, `webapp`, `scraper`, `deploy`, `render.yaml`, `run_bot.py` va boshqalar).
4. Pastdagi **Commit changes** tugmasini bosing.

`.env` fayli arxivda yo'q va uni GitHub'ga yuklamang: token Render sozlamalarida saqlanadi.

## 2. Render'da server yaratish

1. https://dashboard.render.com ga GitHub orqali kiring.
2. **New → Blueprint** ni tanlang va `attestatsiya-bot` repozitoriysini ulang.
3. Render `render.yaml` ni o'qiydi va ikkita qiymatni so'raydi:
   - `BOT_TOKEN`: @BotFather bergan token
   - `ANTHROPIC_API_KEY`: https://console.anthropic.com dagi kalit
4. **Apply** ni bosing. 3–5 daqiqadan keyin server `https://attestatsiya-bot-xxxx.onrender.com`
   manzilida ishga tushadi.

Bot ishga tushganda o'zi:
- Telegram webhook'ini shu manzilga ulaydi;
- chatdagi menyu tugmasini ("Ilova") Mini App'ga ulaydi.

Telegram'da botga `/start` yozib tekshiring.

## 3. Server uxlab qolmasligi uchun

Render bepul serverni 15 daqiqa so'rov kelmasa uxlatadi. Telegram xabari kelsa, server o'zi uyg'onadi,
lekin birinchi javob 30–60 soniya kechikadi. Doim tez javob berishi uchun:

1. https://uptimerobot.com da bepul ro'yxatdan o'ting.
2. **Add New Monitor → HTTP(s)**, URL: `https://<sizning-manzilingiz>.onrender.com/health`,
   interval: **5 minutes**.

Render har oy 750 soat bepul beradi. Bu bitta serverning oy bo'yi 24/7 ishlashiga yetadi.

## Bilib qo'yish kerak

- **Bepul Render'da disk doimiy emas.** Server qayta ishga tushganda yoki yangilanganda foydalanuvchilarning
  XP'si, reytingi va natijalar tarixi nolga tushadi. Fanlar bazasi esa kod ichida, u yo'qolmaydi.
  Ma'lumot doimiy saqlanishi kerak bo'lsa, Render'da pullik disk ($1/oy dan) qo'shing va
  `DB_FILE=/var/data/natijalar.sqlite3` qiling, yoki pastdagi Oracle variantidan foydalaning.
- Test savollarini tuzish Anthropic API orqali ishlaydi va bu **pullik** (har bir test uchun bir necha sent).
  Hosting bepul, API emas.

## To'liq bepul va doimiy variant: Oracle Cloud "Always Free"

Oracle umrbod bepul virtual server beradi (1 GB RAM, disk doimiy). Ro'yxatdan o'tishda bank kartasi
faqat tekshiruv uchun so'raladi, pul yechilmaydi. Server ochilgach, `README.md` dagi
"2-qadam: botni ishga tushirish" bo'yicha Caddy va systemd bilan o'rnatiladi. Domen bo'lmasa,
bepul `sizning-nom.duckdns.org` domenidan foydalanish mumkin.
