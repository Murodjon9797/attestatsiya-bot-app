"""Natijalar, foydalanuvchi XP'si, kunlik check-in va reyting (SQLite)."""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

# Darajalar: (nomi, kerakli XP)
LEVELS = [
    ("Boshlovchi", 0),
    ("Izlanuvchi", 300),
    ("Malakali", 1000),
    ("Ekspert", 3000),
    ("Ustoz", 7000),
]
XP_PER_CORRECT = 10
XP_PASS_BONUS = 50
CHECKIN_XP = [5, 5, 10, 10, 15, 15, 30]  # 1..7-kun


def level_info(xp: int) -> dict:
    idx = max(i for i, (_, need) in enumerate(LEVELS) if xp >= need)
    name, need = LEVELS[idx]
    nxt = LEVELS[idx + 1] if idx + 1 < len(LEVELS) else None
    return {"level": idx + 1, "name": name, "from": need,
            "to": nxt[1] if nxt else None, "next_name": nxt[0] if nxt else None}


class ResultsDB:
    def __init__(self, path: str | Path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS natijalar (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                fio TEXT,
                mutaxassislik TEXT,
                fan TEXT NOT NULL,
                togri INTEGER NOT NULL,
                jami INTEGER NOT NULL,
                foiz REAL NOT NULL,
                vaqt TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                name TEXT,
                username TEXT,
                photo TEXT,
                xp INTEGER NOT NULL DEFAULT 0,
                streak INTEGER NOT NULL DEFAULT 0,
                last_checkin TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_nat_user ON natijalar(user_id);
        """)
        self.conn.commit()

    # ---------- foydalanuvchi ----------
    def touch_user(self, user_id: int, name: str, username: str = "", photo: str = "") -> None:
        self.conn.execute(
            "INSERT INTO users (user_id, name, username, photo) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET name=excluded.name, username=excluded.username, "
            "photo=COALESCE(NULLIF(excluded.photo, ''), users.photo)",
            (user_id, name, username, photo))
        self.conn.commit()

    def add_xp(self, user_id: int, xp: int) -> int:
        self.conn.execute("UPDATE users SET xp = xp + ? WHERE user_id = ?", (xp, user_id))
        self.conn.commit()
        return self.conn.execute("SELECT xp FROM users WHERE user_id = ?", (user_id,)).fetchone()[0]

    def profile(self, user_id: int) -> dict:
        row = self.conn.execute("SELECT name, xp, streak, last_checkin FROM users WHERE user_id = ?",
                                (user_id,)).fetchone() or ("", 0, 0, None)
        name, xp, streak, last = row
        today = date.today().isoformat()
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        if last not in (today, yesterday):
            streak = 0  # ketma-ketlik uzilgan
        st = self.conn.execute(
            "SELECT COUNT(*), COALESCE(AVG(foiz), 0), COALESCE(SUM(togri), 0) FROM natijalar WHERE user_id = ?",
            (user_id,)).fetchone()
        rank = self.conn.execute("SELECT COUNT(*) + 1 FROM users WHERE xp > ?", (xp,)).fetchone()[0]
        return {
            "name": name, "xp": xp, "level": level_info(xp), "rank": rank,
            "streak": streak, "checked_today": last == today, "checkin_xp": CHECKIN_XP,
            "tests": st[0], "avg": round(st[1], 1), "correct": st[2],
            "history": self.last(user_id, 10),
        }

    def checkin(self, user_id: int) -> dict:
        row = self.conn.execute("SELECT streak, last_checkin FROM users WHERE user_id = ?", (user_id,)).fetchone()
        streak, last = row if row else (0, None)
        today = date.today().isoformat()
        if last == today:
            return {"ok": False, "xp_gained": 0}
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        streak = streak + 1 if last == yesterday and streak < 7 else 1
        gained = CHECKIN_XP[streak - 1]
        self.conn.execute("UPDATE users SET streak = ?, last_checkin = ?, xp = xp + ? WHERE user_id = ?",
                          (streak, today, gained, user_id))
        self.conn.commit()
        return {"ok": True, "xp_gained": gained}

    def leaderboard(self, limit: int = 50) -> list[dict]:
        rows = self.conn.execute(
            "SELECT user_id, name, photo, xp FROM users WHERE xp > 0 ORDER BY xp DESC, user_id LIMIT ?",
            (limit,)).fetchall()
        return [{"user_id": u, "name": n or "Foydalanuvchi", "photo": p or "", "xp": x,
                 "level": level_info(x)["level"]} for u, n, p, x in rows]

    # ---------- natijalar ----------
    def save(self, user_id: int, fio: str, mutaxassislik: str, fan: str, togri: int, jami: int) -> None:
        self.conn.execute(
            "INSERT INTO natijalar (user_id, fio, mutaxassislik, fan, togri, jami, foiz, vaqt) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, fio, mutaxassislik, fan, togri, jami, round(100 * togri / jami, 1),
             datetime.now().strftime("%Y-%m-%d %H:%M")))
        self.conn.commit()

    def last(self, user_id: int, limit: int = 10) -> list[tuple]:
        return self.conn.execute(
            "SELECT vaqt, fan, togri, jami, foiz FROM natijalar WHERE user_id = ? "
            "ORDER BY id DESC LIMIT ?", (user_id, limit)).fetchall()
