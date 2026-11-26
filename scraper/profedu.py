"""edu.profedu.uz saytidan ma'lumot olish.

Ochiq qism (login kerak emas):
  /meyor-year/?year=2026             -> bilim sohalari ro'yxati
  /meyorlar?selected=<soha>&year=2026 -> yo'nalishlar (yun) va kasb/mutaxassisliklar (kasb)

Yopiq qism (login kerak):
  /kasb va mutaxasislik/<id>  sahifasidagi "O'quv dasturi" fayli (fanlar shu faylda).
"""
from __future__ import annotations

import html
import re
import time
from dataclasses import dataclass, field
from urllib.parse import unquote, urljoin

import requests

BASE = "https://edu.profedu.uz/"
TEXNIKUM_PREFIX = "5"  # 5xxxxxxx — o'rta-maxsus professional ta'lim (texnikum)

_YEAR_SUFFIX = re.compile(r"\s*\(?\s*20\d\d\s*[-/–]\s*20\d\d\s*\)?\s*$")


def clean_name(name: str) -> str:
    """'Dasturiy injiniring 2026-2027' -> 'Dasturiy injiniring'."""
    return _YEAR_SUFFIX.sub("", " ".join(name.split())).strip()


@dataclass
class Mutaxassislik:
    id: int  # saytdagi ichki id (sahifa manzili uchun)
    kod: str  # 50610203
    nomi: str
    url: str
    fanlar: list[dict] = field(default_factory=list)
    fanlar_manba: str = ""  # fanlar qaysi fayldan olingani


class ProfEduClient:
    def __init__(self, delay: float = 0.5, timeout: int = 60):
        self.s = requests.Session()
        self.s.headers.update({
            "User-Agent": "Mozilla/5.0 (attestatsiya-bot scraper)",
            "Accept-Language": "uz,ru;q=0.8,en;q=0.5",
        })
        self.delay = delay
        self.timeout = timeout
        self.logged_in = False

    # ---------- past darajadagi so'rovlar ----------
    def _get(self, path: str, ajax: bool = False, **params) -> requests.Response:
        headers = {"X-Requested-With": "XMLHttpRequest", "Accept": "application/json"} if ajax else {}
        for attempt in range(4):
            try:
                r = self.s.get(urljoin(BASE, path), params=params or None, headers=headers,
                               timeout=self.timeout)
                if r.status_code >= 500 and attempt < 3:
                    raise requests.HTTPError(f"{r.status_code}")
                r.raise_for_status()
                time.sleep(self.delay)
                return r
            except (requests.ConnectionError, requests.Timeout, requests.HTTPError):
                if attempt == 3:
                    raise
                time.sleep(2 ** attempt)
        raise RuntimeError("unreachable")

    def _json(self, path: str, **params):
        return self._get(path, ajax=True, **params).json()

    # ---------- ochiq ma'lumotlar ----------
    def texnikum_tree(self, year: int = 2026) -> list[dict]:
        """Bilim sohasi -> yo'nalish -> mutaxassislik daraxti (faqat texnikum, 5xxxxxxx)."""
        tree = []
        for b in self._json("meyor-year/", year=year)["bilim_soxa"]:
            r = self._json("meyorlar", selected=b["name"], year=year)
            yun = {u["id"]: u for u in r.get("yun", [])}
            yunalishlar: dict[int, dict] = {}
            for k in r.get("kasb", []):
                if not str(k["_id"]).startswith(TEXNIKUM_PREFIX):
                    continue
                u = yun.get(k["tYunalish_id_id"], {"id": 0, "_id": "", "name": "Boshqa"})
                y = yunalishlar.setdefault(u["id"], {
                    "kod": str(u.get("_id", "")),
                    "nomi": clean_name(u["name"]),
                    "mutaxassisliklar": [],
                })
                y["mutaxassisliklar"].append(Mutaxassislik(
                    id=k["id"], kod=str(k["_id"]), nomi=clean_name(k["name"]),
                    url=f"{BASE}kasb%20va%20mutaxasislik/{k['id']}",
                ))
            if yunalishlar:
                ys = sorted(yunalishlar.values(), key=lambda y: y["kod"])
                for y in ys:
                    y["mutaxassisliklar"].sort(key=lambda m: m.kod)
                tree.append({"nomi": b["name"], "yunalishlar": ys})
        return tree

    # ---------- login ----------
    @staticmethod
    def _phone_variants(phone: str) -> list[str]:
        digits = re.sub(r"\D", "", phone)
        if len(digits) == 9:
            digits = "998" + digits
        out = [phone.strip()]
        if len(digits) == 12:
            d = digits[3:]
            out += [f"+998 ({d[:2]}) {d[2:5]}-{d[5:7]}-{d[7:]}", "+" + digits, digits]
        return list(dict.fromkeys(out))

    def login(self, phone: str, password: str) -> bool:
        self._get("")  # sessiya/CSRF cookie
        for p in self._phone_variants(phone):
            try:
                data = self._json("user/my-login", phone=p, password=password)
            except (requests.RequestException, ValueError):
                continue
            if data.get("is_auth"):
                self.logged_in = True
                return True
        return False

    def use_session_cookie(self, sessionid: str, probe: "Mutaxassislik | None" = None) -> bool:
        """Brauzerda kirilgandan keyingi `sessionid` cookie bilan ishlash (parolsiz)."""
        self.s.cookies.set("sessionid", sessionid.strip(), domain="edu.profedu.uz", path="/")
        if probe is None:
            self.logged_in = True
            return True
        page = self._get(probe.url).text
        # kirilmagan bo'lsa "O'quv dasturi" tugmasi "Ro'yxatdan o'tish" (class user-kirish) bo'ladi
        mm = re.search(r"<h3>\s*O\S{1,2}quv dasturi\s*</h3>", page)
        card = page[mm.start():mm.start() + 800] if mm else ""
        self.logged_in = bool(card) and "user-kirish" not in card
        return self.logged_in

    # ---------- o'quv dasturi fayli ----------
    def program_file_urls(self, m: Mutaxassislik) -> list[str]:
        """Mutaxassislik sahifasidagi 'O'quv dasturi' kartochkasidan fayl havolalarini topadi."""
        page = self._get(m.url).text
        urls: list[str] = []
        # 1) "O‘quv dasturi" sarlavhali kartochka ichidagi havolalar
        for card in re.findall(r'<div class="card9">(.*?)</div>\s*</div>', page, flags=re.S):
            title = html.unescape(re.sub(r"<[^>]+>", " ", card))
            if re.search(r"quv\s+dasturi", title, flags=re.I) and "dual" not in title.lower():
                urls += re.findall(r'href="([^"#][^"]*)"', card)
                urls += re.findall(r"""(?:window\.open|location\.href)\s*\(?\s*['"]([^'"]+)['"]""", card)
        # 2) zaxira: sahifadagi /media/ ostidagi hujjat havolalari
        if not urls:
            urls = re.findall(r'href="([^"]*/media/[^"]+\.(?:pdf|docx?|xlsx?|zip))"', page, flags=re.I)
        return [urljoin(m.url, html.unescape(u)) for u in dict.fromkeys(urls)]

    def download(self, url: str) -> tuple[bytes, str]:
        r = self._get(url)
        name = unquote(url.rstrip("/").rsplit("/", 1)[-1])
        cd = r.headers.get("Content-Disposition", "")
        mm = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)', cd)
        if mm:
            name = unquote(mm.group(1))
        if r.headers.get("Content-Type", "").startswith("text/html"):
            raise ValueError(f"Fayl o'rniga HTML sahifa qaytdi (login talab qilinyaptimi?): {url}")
        return r.content, name
