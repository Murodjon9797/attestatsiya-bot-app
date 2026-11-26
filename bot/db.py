"""Foydalanuvchilar, javoblar tahlili, natijalar, premium va faollashtirish kodlari.

DATABASE_URL (postgresql://...) berilsa PostgreSQL ishlatiladi — ma'lumotlar server qayta
ishga tushganda yo'qolmaydi (bepul Render uchun shart). Aks holda SQLite fayli ishlatiladi.
"""
from __future__ import annotations

import secrets
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

TZ = timezone(timedelta(hours=5))  # Toshkent vaqti

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id BIGINT PRIMARY KEY,
    name TEXT,
    username TEXT,
    premium_until TEXT,
    created TEXT
);
CREATE TABLE IF NOT EXISTS answers (
    id {serial},
    user_id BIGINT NOT NULL,
    sid TEXT NOT NULL,
    qid TEXT NOT NULL,
    bolim TEXT,
    correct INTEGER NOT NULL,
    vaqt TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_answers_user ON answers(user_id);
CREATE TABLE IF NOT EXISTS results (
    id {serial},
    user_id BIGINT NOT NULL,
    sid TEXT,
    fan TEXT NOT NULL,
    rejim TEXT,
    togri INTEGER NOT NULL,
    jami INTEGER NOT NULL,
    foiz REAL NOT NULL,
    vaqt TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_results_user ON results(user_id);
CREATE TABLE IF NOT EXISTS codes (
    code TEXT PRIMARY KEY,
    days INTEGER NOT NULL,
    created_by BIGINT,
    created TEXT,
    for_user BIGINT,
    used_by BIGINT,
    used_at TEXT
);
CREATE TABLE IF NOT EXISTS admins (
    user_id BIGINT PRIMARY KEY,
    added TEXT
);
CREATE TABLE IF NOT EXISTS payments (
    id {serial},
    user_id BIGINT NOT NULL,
    tarif TEXT,
    file_id TEXT,
    status TEXT NOT NULL,
    created TEXT NOT NULL,
    decided_by BIGINT,
    code TEXT
);
"""


def now() -> datetime:
    return datetime.now(TZ)


def ts() -> str:
    return now().strftime("%Y-%m-%d %H:%M:%S")


class ResultsDB:
    def __init__(self, path: str | Path, database_url: str = ""):
        self.lock = threading.Lock()
        self.pg = database_url.startswith(("postgres://", "postgresql://"))
        self.url = database_url
        if self.pg:
            import psycopg

            self.conn = psycopg.connect(database_url, autocommit=True)
            serial = "BIGSERIAL PRIMARY KEY"
        else:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            self.conn = sqlite3.connect(path, check_same_thread=False)
            serial = "INTEGER PRIMARY KEY AUTOINCREMENT"
        for stmt in SCHEMA.format(serial=serial).split(";"):
            if stmt.strip():
                self._exec(stmt)

    # ---------- past daraja ----------
    def _exec(self, sql: str, args: tuple = ()):
        if self.pg:
            sql = sql.replace("?", "%s")
        with self.lock:
            try:
                cur = self.conn.execute(sql, args)
            except Exception:
                if self.pg and getattr(self.conn, "closed", False):  # uzilgan ulanishni tiklash
                    import psycopg

                    self.conn = psycopg.connect(self.url, autocommit=True)
                    cur = self.conn.execute(sql, args)
                else:
                    raise
            if not self.pg:
                self.conn.commit()
            return cur

    def _all(self, sql: str, args: tuple = ()) -> list[tuple]:
        return list(self._exec(sql, args).fetchall())

    def _one(self, sql: str, args: tuple = ()):
        return self._exec(sql, args).fetchone()

    # ---------- foydalanuvchi ----------
    def touch_user(self, user_id: int, name: str, username: str = "") -> None:
        self._exec("INSERT INTO users (user_id, name, username, created) VALUES (?, ?, ?, ?) "
                   "ON CONFLICT(user_id) DO UPDATE SET name=excluded.name, username=excluded.username",
                   (user_id, name, username, ts()))

    def premium_until(self, user_id: int) -> datetime | None:
        row = self._one("SELECT premium_until FROM users WHERE user_id = ?", (user_id,))
        if not row or not row[0]:
            return None
        until = datetime.fromisoformat(row[0])
        return until if until > now() else None

    def answered_count(self, user_id: int) -> int:
        return self._one("SELECT COUNT(*) FROM answers WHERE user_id = ?", (user_id,))[0]

    def grant_premium(self, user_id: int, days: int) -> datetime:
        start = self.premium_until(user_id) or now()
        until = start + timedelta(days=days)
        self._exec("UPDATE users SET premium_until = ? WHERE user_id = ?", (until.isoformat(timespec="seconds"), user_id))
        return until

    # ---------- kodlar ----------
    def create_code(self, days: int, created_by: int, for_user: int | None = None) -> str:
        alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # chalkash belgilarsiz (0/O, 1/I)
        code = "-".join("".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(3))
        self._exec("INSERT INTO codes (code, days, created_by, created, for_user) VALUES (?, ?, ?, ?, ?)",
                   (code, days, created_by, ts(), for_user))
        return code

    def redeem_code(self, user_id: int, code: str) -> tuple[bool, str, datetime | None]:
        code = code.strip().upper().replace(" ", "")
        if len(code) == 12 and "-" not in code:
            code = f"{code[:4]}-{code[4:8]}-{code[8:]}"
        row = self._one("SELECT days, used_by, for_user FROM codes WHERE code = ?", (code,))
        if not row:
            return False, "Kod topilmadi. Uni to'g'ri kiritganingizni tekshiring.", None
        days, used_by, for_user = row
        if used_by:
            return False, "Bu kod allaqachon ishlatilgan.", None
        if for_user and int(for_user) != int(user_id):
            return False, "Bu kod boshqa foydalanuvchi uchun berilgan.", None
        self._exec("UPDATE codes SET used_by = ?, used_at = ? WHERE code = ? AND used_by IS NULL", (user_id, ts(), code))
        return True, f"{days} kunlik premium faollashtirildi.", self.grant_premium(user_id, days)

    def codes_stats(self) -> dict:
        r = self._one("SELECT COUNT(*), SUM(CASE WHEN used_by IS NOT NULL THEN 1 ELSE 0 END) FROM codes")
        p = self._one("SELECT COUNT(*) FROM users WHERE premium_until > ?", (now().isoformat(timespec="seconds"),))
        u = self._one("SELECT COUNT(*) FROM users")
        return {"kodlar": r[0] or 0, "ishlatilgan": r[1] or 0, "premium": p[0] or 0, "foydalanuvchilar": u[0] or 0}

    # ---------- adminlar ----------
    def admin_ids(self) -> list[int]:
        return [int(r[0]) for r in self._all("SELECT user_id FROM admins")]

    def add_admin(self, user_id: int) -> None:
        self._exec("INSERT INTO admins (user_id, added) VALUES (?, ?) ON CONFLICT(user_id) DO NOTHING", (user_id, ts()))

    # ---------- to'lovlar ----------
    def create_payment(self, user_id: int, tarif: str, file_id: str) -> int:
        if self.pg:
            return self._one("INSERT INTO payments (user_id, tarif, file_id, status, created) "
                             "VALUES (?, ?, ?, 'kutilmoqda', ?) RETURNING id", (user_id, tarif, file_id, ts()))[0]
        return self._exec("INSERT INTO payments (user_id, tarif, file_id, status, created) "
                          "VALUES (?, ?, ?, 'kutilmoqda', ?)", (user_id, tarif, file_id, ts())).lastrowid

    def payment(self, pid: int) -> dict | None:
        r = self._one("SELECT id, user_id, tarif, status FROM payments WHERE id = ?", (pid,))
        return {"id": r[0], "user_id": r[1], "tarif": r[2], "status": r[3]} if r else None

    def decide_payment(self, pid: int, status: str, admin_id: int, code: str = "") -> None:
        self._exec("UPDATE payments SET status = ?, decided_by = ?, code = ? WHERE id = ?", (status, admin_id, code, pid))

    def pending_payment(self, user_id: int) -> bool:
        return bool(self._one("SELECT 1 FROM payments WHERE user_id = ? AND status = 'kutilmoqda'", (user_id,)))

    # ---------- javoblar va natijalar ----------
    def record_answer(self, user_id: int, sid: str, qid: str, bolim: str, correct: bool) -> None:
        self._exec("INSERT INTO answers (user_id, sid, qid, bolim, correct, vaqt) VALUES (?, ?, ?, ?, ?, ?)",
                   (user_id, sid or "", qid or "", bolim or "", int(correct), ts()))

    def save(self, user_id: int, fan: str, togri: int, jami: int, sid: str = "", rejim: str = "mashq") -> None:
        self._exec("INSERT INTO results (user_id, sid, fan, rejim, togri, jami, foiz, vaqt) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                   (user_id, sid, fan, rejim, togri, jami, round(100 * togri / jami, 1), ts()))

    def last(self, user_id: int, limit: int = 10) -> list[tuple]:
        return self._all("SELECT vaqt, fan, togri, jami, foiz, rejim FROM results WHERE user_id = ? "
                         "ORDER BY id DESC LIMIT ?", (user_id, limit))

    def wrong_qids(self, user_id: int, sid: str) -> list[str]:
        """Oxirgi urinishda noto'g'ri javob berilgan savollar."""
        rows = self._all("SELECT qid, correct FROM answers WHERE user_id = ? AND sid = ? ORDER BY id", (user_id, sid))
        last: dict[str, int] = {}
        for qid, c in rows:
            last[qid] = c
        return [q for q, c in last.items() if not c]

    def analytics(self, user_id: int) -> dict:
        tot = self._one("SELECT COUNT(*), COALESCE(SUM(correct), 0) FROM answers WHERE user_id = ?", (user_id,))
        fanlar = self._all("SELECT sid, COUNT(*), SUM(correct), COUNT(DISTINCT qid) FROM answers "
                           "WHERE user_id = ? AND sid <> '' GROUP BY sid", (user_id,))
        bolimlar = self._all("SELECT sid, bolim, COUNT(*), SUM(correct) FROM answers "
                             "WHERE user_id = ? AND sid <> '' AND bolim <> '' GROUP BY sid, bolim", (user_id,))
        trend = self._all("SELECT vaqt, fan, foiz, rejim FROM results WHERE user_id = ? ORDER BY id DESC LIMIT 12", (user_id,))
        return {
            "jami": tot[0], "togri": tot[1] or 0,
            "fanlar": [{"sid": s, "jami": n, "togri": c or 0, "korilgan": d} for s, n, c, d in fanlar],
            "bolimlar": [{"sid": s, "bolim": b, "jami": n, "togri": c or 0} for s, b, n, c in bolimlar],
            "trend": [{"vaqt": v, "fan": f, "foiz": p, "rejim": r} for v, f, p, r in reversed(trend)],
        }
