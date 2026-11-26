"""O'quv dasturi faylidan (PDF/DOCX/XLSX/ZIP) fanlar ro'yxatini ajratib olish.

PDF to'g'ridan-to'g'ri Claude'ga hujjat sifatida yuboriladi (skanerlangan PDF ham o'qiladi),
DOCX/XLSX esa avval matnga aylantiriladi.
"""
from __future__ import annotations

import base64
import io
import zipfile

import anthropic

from claude_json import ask_json

SYSTEM = (
    "Sen O'zbekiston kasbiy ta'lim (texnikum) o'quv rejalari va o'quv dasturlarini tahlil "
    "qiluvchi mutaxassissan. Hujjatdan o'quvchilarga o'qitiladigan barcha fanlar va modullarni "
    "aniq hujjatdagi nomi bilan (lotin yozuvida) ajratib ol. Amaliyotlar, attestatsiya/imtihonlar, "
    "konsultatsiyalar, 'Jami' kabi yig'indi qatorlarini fan sifatida olma. Bir xil fanni takrorlama."
)

SCHEMA = {
    "type": "object",
    "properties": {
        "fanlar": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "nomi": {"type": "string", "description": "Fan yoki modul nomi"},
                    "blok": {
                        "type": "string",
                        "description": "Fan bloki: 'Umumta'lim', 'Umumkasbiy', 'Maxsus', 'Tanlov' "
                                       "yoki hujjatda ko'rsatilgan boshqa nom; noma'lum bo'lsa ''",
                    },
                    "soat": {"type": "string", "description": "Jami soat (bo'lsa), aks holda ''"},
                },
                "required": ["nomi", "blok", "soat"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["fanlar"],
    "additionalProperties": False,
}

MAX_TEXT_CHARS = 400_000


def _docx_text(data: bytes) -> str:
    import docx

    d = docx.Document(io.BytesIO(data))
    parts = [p.text for p in d.paragraphs if p.text.strip()]
    for t in d.tables:
        for row in t.rows:
            cells = []
            for c in row.cells:
                txt = c.text.strip()
                if txt and (not cells or cells[-1] != txt):
                    cells.append(txt)
            if cells:
                parts.append(" | ".join(cells))
    return "\n".join(parts)


def _xlsx_text(data: bytes) -> str:
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    parts = []
    for ws in wb.worksheets:
        parts.append(f"## {ws.title}")
        for row in ws.iter_rows(values_only=True):
            vals = [str(v).strip() for v in row if v is not None and str(v).strip()]
            if vals:
                parts.append(" | ".join(vals))
    return "\n".join(parts)


def to_content_blocks(data: bytes, filename: str) -> list[dict]:
    """Faylni Claude'ga yuboriladigan content bloklariga aylantiradi."""
    name = filename.lower()
    if name.endswith(".zip") or (data[:4] == b"PK\x03\x04" and not name.endswith((".docx", ".xlsx"))):
        blocks: list[dict] = []
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for info in z.infolist():
                if info.is_dir() or "__MACOSX" in info.filename:
                    continue
                if info.filename.lower().endswith((".pdf", ".docx", ".xlsx")):
                    blocks += to_content_blocks(z.read(info), info.filename)
        return blocks
    if name.endswith(".pdf") or data[:5] == b"%PDF-":
        return [{
            "type": "document",
            "source": {"type": "base64", "media_type": "application/pdf",
                       "data": base64.standard_b64encode(data).decode()},
            "title": filename,
        }]
    if name.endswith(".docx"):
        text = _docx_text(data)
    elif name.endswith(".xlsx"):
        text = _xlsx_text(data)
    else:
        raise ValueError(f"Qo'llab-quvvatlanmaydigan fayl turi: {filename} (.doc/.xls bo'lsa, "
                         f".docx/.xlsx/.pdf ga o'girib, data/raw/ ga qo'ying)")
    if len(text) > MAX_TEXT_CHARS:
        raise ValueError(f"{filename}: matn juda katta ({len(text)} belgi)")
    return [{"type": "text", "text": f"<hujjat nomi=\"{filename}\">\n{text}\n</hujjat>"}]


async def extract_fanlar(client: anthropic.AsyncAnthropic, data: bytes, filename: str,
                         mutaxassislik: str) -> list[dict]:
    blocks = to_content_blocks(data, filename)
    if not blocks:
        raise ValueError(f"{filename}: ichida o'qiladigan hujjat topilmadi")
    blocks.append({
        "type": "text",
        "text": f"Bu '{mutaxassislik}' mutaxassisligining 2026-yilgi o'quv dasturi. "
                "Undagi barcha fanlar va modullar ro'yxatini qaytar.",
    })
    res = await ask_json(client, system=SYSTEM, content=blocks, schema=SCHEMA, effort="low")
    seen, out = set(), []
    for f in res["fanlar"]:
        nomi = " ".join(f["nomi"].split())
        if nomi and nomi.lower() not in seen:
            seen.add(nomi.lower())
            out.append({"nomi": nomi, "blok": f["blok"].strip(), "soat": f["soat"].strip()})
    return out
