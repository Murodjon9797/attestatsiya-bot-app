"""O'quv dasturi PDF'idan fanlar (modullar)ni API kalitisiz ajratish.

2026-yilgi ta'lim dasturlarida modul (fan) dasturlari ikki xil sarlavha bilan uchraydi:

  1-format (yangi "Ta'lim dasturi"):
      Modul turi: Umumkasbiy modul
      Modul nomi va kodi: TGM.1 Oʻzbekistonning eng yangi tarixi
      Davomiyligi: 120 soat
      Oʻqitish natijalari: ...   Modul mazmuni: ...

  2-format ("Namunaviy o'quv dasturi"):
      Fan nomi Amaliy matematika          (yoki: Modul nomi ...)
      Fan kodi 5PM0059                     (yoki: Modul kodi ...)
      Fanga ajratilgan soat Jami yuklama: 150 soat
      Modul mazmuni ...   Bilimlar ...   Koʻnikmalar ...

Shu sarlavhalardan fan nomi, kodi, bloki, soati, o'qitish natijalari va mazmuni olinadi.
Mazmun va natijalar test savollarini aynan rasmiy dastur bo'yicha tuzish uchun ishlatiladi.
"""
from __future__ import annotations

import io
import re

APOS = "ʻʼ‘’`'"
A = f"[{APOS}]?"  # ixtiyoriy apostrof
OQ = rf"O{A}\s?qitish"

# 1-format
_HEAD1 = re.compile(r"Modul\s+nomi\s+va\s+kodi\s*:?\s*(?P<body>.*?)\s*Davomiyligi\s*:?\s*(?P<soat>[^\n]*)",
                    re.S | re.I)
_TUR1 = re.compile(r"Modul\s+turi\s*:?\s*(?P<tur>[^\n]+)", re.I)
_CODE = re.compile(r"^(?P<kod>[A-ZА-ЯЎҚҒҲ]{1,5}\s?\.?\s?\d+(?:\s?\.\s?\d+)*\.?)\s+(?P<nomi>.+)$", re.S)

# 2-format
_HEAD2 = re.compile(
    r"(?:Fan|Modul)\s+nomi(?!\s+va\s+kodi)\s*:?\s*(?P<body>.{2,250}?)\s*(?:Fan|Modul)\s+kodi\s*:?\s*(?P<kod>\S+)"
    r"(?P<rest>.{0,400})", re.S)
_TUR2 = re.compile(r"(?:Fan|Modul)\s+turi\s*\(majburiy/tanlov\)\s*(?P<tur>\w+)", re.I)
_SOAT2 = re.compile(r"Jami\s+yuklama\s*:?\s*(?P<soat>\d+)", re.I)

_STOP = (rf"{OQ}\s+shakllari|{OQ}\s+usullari|{OQ}\s+natijasini\s+baholash|{OQ}ni\s+tashkiliy|"
         rf"Egallanadigan|Axborot\s+manbalari|Baholash\s+tartibi|Modul\s+nomi\s+va\s+kodi")
_NATIJA1 = re.compile(rf"{OQ}\s+natijalari\s*:?(?P<t>.*?)(?=Modul\s+mazmuni|{_STOP}|$)", re.S | re.I)
_NATIJA2 = re.compile(rf"\bBilimlar\b(?P<t>.*?)(?={_STOP}|$)", re.S)
_MAZMUN = re.compile(rf"Modul\s+mazmuni\s*:?(?P<t>.*?)(?=\bBilimlar\b|{_STOP}|$)", re.S | re.I)
_MAQSAD = re.compile(rf"Modulning\s+maqsadi\s*:?(?P<t>.*?)(?=O{A}\s?zlashtirish|Modul\s+mazmuni|{_STOP}|$)",
                     re.S | re.I)


def normalize(text: str) -> str:
    # pypdf apostrofdan oldin bo'sh joy qo'yib yuboradi: "O ʻzbekiston" -> "Oʻzbekiston"
    text = re.sub(rf"(\w) ([{APOS}])(?=\w)", r"\1\2", text)
    text = re.sub(r"[ \t ]+", " ", text)
    text = re.sub(r" ?- ?\n", "-", text)
    return text


def pdf_text(data: bytes) -> str:
    from pypdf import PdfReader

    r = PdfReader(io.BytesIO(data))
    return normalize("\n".join((p.extract_text() or "") for p in r.pages))


def _one_line(s: str) -> str:
    return " ".join(s.split()).strip(" .;:-")


def _heads(text: str) -> list[dict]:
    heads = []
    for h in _HEAD1.finditer(text):
        body = _one_line(h.group("body"))
        m = _CODE.match(body)
        kod, nomi = (_one_line(m.group("kod")).replace(" ", ""), _one_line(m.group("nomi"))) if m else ("", body)
        turs = list(_TUR1.finditer(text[max(0, h.start() - 300):h.start()]))
        soat = re.search(r"\d+", h.group("soat"))
        heads.append({"start": h.start(), "end": h.end(), "kod": kod, "nomi": nomi,
                      "blok": _one_line(turs[-1].group("tur")) if turs else "",
                      "soat": soat.group(0) if soat else ""})
    for h in _HEAD2.finditer(text):
        rest = h.group("rest")
        tur = _TUR2.search(text[h.end():h.end() + 600])
        soat = _SOAT2.search(rest)
        heads.append({"start": h.start(), "end": h.end() - len(rest),
                      "kod": _one_line(h.group("kod")), "nomi": _one_line(h.group("body")),
                      "blok": tur.group("tur").capitalize() if tur else "",
                      "soat": soat.group("soat") if soat else ""})
    heads.sort(key=lambda x: x["start"])
    return heads


_MOD_CODE = r"(?:TGM|UTM|UKM|MM|KM|TM)\s?\.?\s?\d+(?:\.\d+)*"


def name_key(nomi: str) -> str:
    """Takrorlarni aniqlash uchun kalit: apostrof turlari, bo'shliq va registrdan qat'i nazar."""
    k = re.sub(rf"[{APOS}]", "", nomi.lower())
    return re.sub(r"[^0-9a-zа-яёўқғҳ]+", "", k)


def clean(kod: str, nomi: str) -> tuple[str, str]:
    """Hujjatdagi yozuv xatolarini tozalaydi: '– Fizika', 'MM1-Muhandislik', 'Dasturlash - MM.4' va h.k."""
    if not re.search(r"\d", kod):  # 'Modulga', 'Fanga' kabi so'zlar kod emas
        kod = ""
    m = re.match(rf"^({_MOD_CODE})\s*[-–—.]?\s*(.+)$", nomi)
    if m:
        kod, nomi = kod or m.group(1).replace(" ", ""), m.group(2)
    m = re.match(rf"^(.+?)\s*[-–—]\s*({_MOD_CODE})$", nomi)
    if m:
        nomi, kod = m.group(1), kod or m.group(2).replace(" ", "")
    nomi = re.sub(rf"(\s+{_MOD_CODE})+\s*$", "", nomi)  # oxiridagi 'MM.1 MM.2 KM.1' ro'yxati
    nomi = re.split(r"\s+Modul\s+mazmuni\b", nomi)[0]
    nomi = nomi.strip(" -–—.;:\"“”«»")
    nomi = re.sub(r"(\D)(\d(?:,\d)*)$", r"\1 \2", nomi)  # 'Fizika1,2' -> 'Fizika 1,2'
    return kod.strip(" -–—"), nomi


def parse_modules(text: str, max_chars: int = 2500) -> list[dict]:
    """Matndan modullar ro'yxatini qaytaradi: [{kod, nomi, blok, soat, natijalar, mazmun}]."""
    heads = _heads(text)
    out, seen = [], set()
    for i, h in enumerate(heads):
        h["kod"], nomi = clean(h["kod"], h["nomi"])
        if (not nomi or len(nomi) > 200 or name_key(nomi) in seen
                or not re.search(r"[a-zа-яʻʼ‘’]{3}", nomi)):  # nom o'rniga kod tushib qolgan
            continue
        seen.add(name_key(nomi))
        end = heads[i + 1]["start"] if i + 1 < len(heads) else len(text)
        section = text[h["end"]:end]
        nat = _NATIJA1.search(section) or _NATIJA2.search(section)
        maz = _MAZMUN.search(section)
        maq = _MAQSAD.search(section)
        mazmun = _one_line(maz.group("t")) if maz else ""
        if maq and len(mazmun) < 300:
            mazmun = (_one_line(maq.group("t")) + " " + mazmun).strip()
        out.append({
            "kod": h["kod"],
            "nomi": nomi,
            "blok": h["blok"],
            "soat": h["soat"],
            "natijalar": _one_line(nat.group("t"))[:max_chars] if nat else "",
            "mazmun": mazmun[:max_chars],
        })
    return out


_ROW = re.compile(r"^\s*(?P<idx>\d{1,2}\.\d{1,2}(?:\.\d{1,2})?)\.?\s+(?P<rest>.*)$")
_NUM = re.compile(r"^\d+(?:[.,]\d+)?$")
_SKIP = re.compile(r"amaliyot|attestatsiya|^jami|imtihon|^KA\b|^YDA\b", re.I)
_BLOK_WORDS = re.compile(r"(modul|fan)lari?\b|bo.?yicha|bloki|kvalifikatsiya", re.I)


def parse_table(text: str) -> list[dict]:
    """O'quv reja jadvalidan fanlarni ajratadi (modul dasturlari bo'lmagan qisqa hujjatlar uchun).

    Jadval qatorlari: '1.1 5PM0649 O‘zbek (rus) tili 4 120 30 ...' — nom ko'p qatorga bo'linishi mumkin.
    """
    # matnni "Jami:" qatorlari bo'yicha bo'laklarga ajratib, eng ko'p fan chiqqan bo'lakni olamiz
    best: list[dict] = []
    prev = 0
    for m in list(re.finditer(r"Jami\s*:", text)) + [None]:
        end = m.start() if m else len(text)
        got = _parse_rows(text[max(prev, end - 20000):end])
        if len(got) > len(best):
            best = got
        prev = m.end() if m else end
    return best


def _parse_rows(region: str) -> list[dict]:
    rows: list[list[str]] = []
    for line in region.splitlines():
        m = _ROW.match(line)
        if m:
            rows.append([m.group("idx"), m.group("rest")])
        elif rows:
            rows[-1][1] += " " + line
    out, blok, seen = [], "", set()
    for idx, rest in rows:
        toks = rest.split()
        kod = ""
        if toks and re.search(r"\d", toks[0]) and re.search(r"[A-Za-z]", toks[0]):
            kod = toks.pop(0)
            # kod ikki qatorga bo'lingan: '5TGM0' + '649'
            if len(toks) > 1 and toks[0].isdigit() and len(toks[0]) <= 4 and not _NUM.match(toks[1]):
                kod += toks.pop(0)
        name_toks = []
        for t in toks:
            if _NUM.match(t):
                break
            name_toks.append(t)
        nomi = _one_line(" ".join(name_toks))
        if not nomi:
            continue
        if not kod and (re.search(r"\.0+$", idx) or _BLOK_WORDS.search(nomi)):
            blok = re.sub(r"^\d+\.\s*", "", nomi)
            continue
        if _SKIP.search(nomi) or not re.search(r"[a-zа-я]{3}", nomi):
            continue
        kod, nomi = clean(kod, nomi)
        if name_key(nomi) in seen:
            continue
        seen.add(name_key(nomi))
        nums = [t for t in toks[len(name_toks):] if _NUM.match(t)]
        out.append({"kod": kod, "nomi": nomi, "blok": blok,
                    "soat": nums[1] if len(nums) > 1 else "", "natijalar": "", "mazmun": ""})
    return out


BLOK_BY_PREFIX = {
    "TGM": "Tabiiy va gumanitar modullar",
    "UTM": "Umumta'lim modullari",
    "UKM": "Umumkasbiy modullar",
    "MM": "Mutaxassislik modullari",
    "KM": "Kasbiy modullar",
    "TM": "Tanlov modullari",
}


def fix_blok(modules: list[dict]) -> list[dict]:
    for m in modules:
        pref = re.match(r"[A-ZА-Я]+(?=\.)", m["kod"])
        if pref and pref.group(0) in BLOK_BY_PREFIX:
            m["blok"] = BLOK_BY_PREFIX[pref.group(0)]
    return modules


def parse_file(data: bytes, filename: str) -> list[dict]:
    if not (filename.lower().endswith(".pdf") or data[:5] == b"%PDF-"):
        return []
    text = pdf_text(data)
    modules = parse_modules(text)
    if len(modules) < 3:  # modul dasturlari yo'q — o'quv reja jadvalidan olamiz
        modules = parse_table(text)
    return fix_blok(modules)
