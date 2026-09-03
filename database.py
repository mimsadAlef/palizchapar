"""
لایه‌ی دیتابیس - از sqlite3 استفاده می‌کند (ساده، بدون نیاز به سرور جدا).
برای بار همزمانی بالا می‌توانید بعداً به PostgreSQL مهاجرت کنید.
"""
import sqlite3
import time
import contextlib
import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    chat_id         INTEGER PRIMARY KEY,
    nickname        TEXT,
    phone           TEXT,
    is_admin        INTEGER NOT NULL DEFAULT 0,
    awaiting_nick   INTEGER NOT NULL DEFAULT 0,
    created_at      REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    sender_chat_id      INTEGER NOT NULL,   -- کاربری که این نخ پیام به او تعلق دارد
    nickname_snapshot   TEXT,
    text                TEXT NOT NULL,
    direction           TEXT NOT NULL,      -- 'in' = کاربر به ادمین , 'out' = ادمین به کاربر
    admin_chat_id       INTEGER,
    created_at          REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS reply_map (
    forwarded_message_id  INTEGER PRIMARY KEY,  -- آی‌دی پیام فوروارد شده در چت ادمین
    admin_chat_id         INTEGER NOT NULL,
    sender_chat_id         INTEGER NOT NULL
);
"""


@contextlib.contextmanager
def get_db():
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_db() as conn:
        conn.executescript(SCHEMA)


def get_or_create_user(chat_id: int) -> sqlite3.Row:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM users WHERE chat_id=?", (chat_id,)).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO users (chat_id, nickname, phone, is_admin, awaiting_nick, created_at) "
                "VALUES (?, NULL, NULL, 0, 0, ?)",
                (chat_id, time.time()),
            )
            row = conn.execute("SELECT * FROM users WHERE chat_id=?", (chat_id,)).fetchone()
        return row


def set_nickname(chat_id: int, nickname: str | None):
    with get_db() as conn:
        conn.execute("UPDATE users SET nickname=?, awaiting_nick=0 WHERE chat_id=?", (nickname, chat_id))


def set_awaiting_nick(chat_id: int, value: bool):
    with get_db() as conn:
        conn.execute("UPDATE users SET awaiting_nick=? WHERE chat_id=?", (1 if value else 0, chat_id))


def set_phone(chat_id: int, phone: str):
    with get_db() as conn:
        conn.execute("UPDATE users SET phone=? WHERE chat_id=?", (phone, chat_id))


def mark_admin(chat_id: int):
    with get_db() as conn:
        conn.execute("UPDATE users SET is_admin=1 WHERE chat_id=?", (chat_id,))


def is_admin(chat_id: int) -> bool:
    with get_db() as conn:
        row = conn.execute("SELECT is_admin FROM users WHERE chat_id=?", (chat_id,)).fetchone()
        return bool(row and row["is_admin"])


def list_admin_chat_ids() -> list[int]:
    with get_db() as conn:
        rows = conn.execute("SELECT chat_id FROM users WHERE is_admin=1").fetchall()
        return [r["chat_id"] for r in rows]


def add_message(sender_chat_id: int, nickname_snapshot: str | None, text: str,
                 direction: str, admin_chat_id: int | None = None) -> int:
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO messages (sender_chat_id, nickname_snapshot, text, direction, admin_chat_id, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (sender_chat_id, nickname_snapshot, text, direction, admin_chat_id, time.time()),
        )
        return cur.lastrowid


def get_thread(sender_chat_id: int) -> list[sqlite3.Row]:
    with get_db() as conn:
        return conn.execute(
            "SELECT * FROM messages WHERE sender_chat_id=? ORDER BY created_at ASC",
            (sender_chat_id,),
        ).fetchall()


def list_threads_for_admin() -> list[sqlite3.Row]:
    """برای پنل ادمین: آخرین پیام هر کاربر به همراه نام مستعارش."""
    with get_db() as conn:
        return conn.execute(
            """
            SELECT m.sender_chat_id,
                   u.nickname,
                   (SELECT text FROM messages m2
                       WHERE m2.sender_chat_id = m.sender_chat_id
                       ORDER BY m2.created_at DESC LIMIT 1) AS last_text,
                   MAX(m.created_at) AS last_at
            FROM messages m
            JOIN users u ON u.chat_id = m.sender_chat_id
            GROUP BY m.sender_chat_id
            ORDER BY last_at DESC
            """
        ).fetchall()


def save_reply_map(forwarded_message_id: int, admin_chat_id: int, sender_chat_id: int):
    with get_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO reply_map (forwarded_message_id, admin_chat_id, sender_chat_id) "
            "VALUES (?,?,?)",
            (forwarded_message_id, admin_chat_id, sender_chat_id),
        )


def get_sender_by_forwarded_id(forwarded_message_id: int) -> int | None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT sender_chat_id FROM reply_map WHERE forwarded_message_id=?",
            (forwarded_message_id,),
        ).fetchone()
        return row["sender_chat_id"] if row else None
