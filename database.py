"""
لایه‌ی دیتابیس - PostgreSQL از طریق psycopg3 با یک connection pool.
همه‌ی توابع dict برمی‌گردونن (row_factory=dict_row) تا کد بالادستی
دقیقاً مثل قبل با row["field"] کار کنه.
"""
import time
import uuid
import contextlib

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

import config

SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS users (
        chat_id         BIGINT PRIMARY KEY,
        uuid            TEXT NOT NULL UNIQUE,
        nickname        TEXT,
        phone           TEXT,
        is_admin        BOOLEAN NOT NULL DEFAULT FALSE,
        is_blocked      BOOLEAN NOT NULL DEFAULT FALSE,
        awaiting_nick   BOOLEAN NOT NULL DEFAULT FALSE,
        created_at      DOUBLE PRECISION NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS messages (
        id                  BIGSERIAL PRIMARY KEY,
        sender_chat_id      BIGINT NOT NULL,   -- کاربری که این نخ پیام به او تعلق دارد
        nickname_snapshot   TEXT,
        text                TEXT NOT NULL,
        direction           TEXT NOT NULL,     -- 'in' (کاربر->ادمین) | 'out' (ادمین->کاربر) | 'system' (رویداد سیستمی، مثل تغییر نام)
        admin_chat_id       BIGINT,
        created_at          DOUBLE PRECISION NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_messages_sender ON messages (sender_chat_id, created_at)",
    """
    CREATE TABLE IF NOT EXISTS reply_map (
        forwarded_message_id  BIGINT PRIMARY KEY,  -- آی‌دی پیام فوروارد شده در چت ادمین
        admin_chat_id         BIGINT NOT NULL,
        sender_chat_id        BIGINT NOT NULL
    )
    """,
]

_pool: ConnectionPool | None = None


def _get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            conninfo=config.DATABASE_URL,
            min_size=1,
            max_size=10,
            kwargs={"row_factory": dict_row},
            open=True,
        )
    return _pool


@contextlib.contextmanager
def get_db():
    """یک کانکشن از pool می‌گیره. در صورت موفقیت commit و در صورت خطا rollback می‌شه."""
    with _get_pool().connection() as conn:
        yield conn


def init_db():
    with get_db() as conn:
        for stmt in SCHEMA_STATEMENTS:
            conn.execute(stmt)


# --------------------------------------------------------------------------
# کاربران
# --------------------------------------------------------------------------
def get_user(chat_id: int) -> dict | None:
    with get_db() as conn:
        return conn.execute("SELECT * FROM users WHERE chat_id=%s", (chat_id,)).fetchone()


def get_or_create_user(chat_id: int) -> dict:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM users WHERE chat_id=%s", (chat_id,)).fetchone()
        if row is None:
            new_uuid = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO users (chat_id, uuid, nickname, phone, is_admin, is_blocked, awaiting_nick, created_at) "
                "VALUES (%s, %s, NULL, NULL, FALSE, FALSE, FALSE, %s)",
                (chat_id, new_uuid, time.time()),
            )
            row = conn.execute("SELECT * FROM users WHERE chat_id=%s", (chat_id,)).fetchone()
        return row


def default_nickname(user: dict) -> str:
    """اگه کاربر نام مستعار نذاشته باشه، این شکل رو برمی‌گردونه: «ناشناس <uuid>»."""
    return f"ناشناس {user['uuid']}"


def display_name(user: dict) -> str:
    return user["nickname"] or default_nickname(user)


def set_nickname(chat_id: int, nickname: str | None) -> str | None:
    """نام مستعار رو ست می‌کنه و نام قبلی (خام، ممکنه None باشه) رو برمی‌گردونه."""
    with get_db() as conn:
        row = conn.execute("SELECT nickname FROM users WHERE chat_id=%s", (chat_id,)).fetchone()
        old_nickname = row["nickname"] if row else None
        conn.execute(
            "UPDATE users SET nickname=%s, awaiting_nick=FALSE WHERE chat_id=%s",
            (nickname, chat_id),
        )
        return old_nickname


def set_awaiting_nick(chat_id: int, value: bool):
    with get_db() as conn:
        conn.execute("UPDATE users SET awaiting_nick=%s WHERE chat_id=%s", (value, chat_id))


def set_phone(chat_id: int, phone: str):
    with get_db() as conn:
        conn.execute("UPDATE users SET phone=%s WHERE chat_id=%s", (phone, chat_id))


def mark_admin(chat_id: int):
    with get_db() as conn:
        conn.execute("UPDATE users SET is_admin=TRUE WHERE chat_id=%s", (chat_id,))


def set_blocked(chat_id: int, blocked: bool):
    with get_db() as conn:
        conn.execute("UPDATE users SET is_blocked=%s WHERE chat_id=%s", (blocked, chat_id))


def is_admin(chat_id: int) -> bool:
    with get_db() as conn:
        row = conn.execute("SELECT is_admin FROM users WHERE chat_id=%s", (chat_id,)).fetchone()
        return bool(row and row["is_admin"])


def is_blocked(chat_id: int) -> bool:
    with get_db() as conn:
        row = conn.execute("SELECT is_blocked FROM users WHERE chat_id=%s", (chat_id,)).fetchone()
        return bool(row and row["is_blocked"])


def list_admin_chat_ids() -> list[int]:
    with get_db() as conn:
        rows = conn.execute("SELECT chat_id FROM users WHERE is_admin=TRUE").fetchall()
        return [r["chat_id"] for r in rows]


# --------------------------------------------------------------------------
# پیام‌ها
# --------------------------------------------------------------------------
def add_message(sender_chat_id: int, nickname_snapshot: str | None, text: str,
                 direction: str, admin_chat_id: int | None = None) -> int:
    with get_db() as conn:
        row = conn.execute(
            "INSERT INTO messages (sender_chat_id, nickname_snapshot, text, direction, admin_chat_id, created_at) "
            "VALUES (%s,%s,%s,%s,%s,%s) RETURNING id",
            (sender_chat_id, nickname_snapshot, text, direction, admin_chat_id, time.time()),
        ).fetchone()
        return row["id"]


def get_thread(sender_chat_id: int) -> list[dict]:
    with get_db() as conn:
        return conn.execute(
            "SELECT * FROM messages WHERE sender_chat_id=%s ORDER BY created_at ASC",
            (sender_chat_id,),
        ).fetchall()


def list_threads_for_admin() -> list[dict]:
    """برای پنل ادمین: آخرین پیام (غیرسیستمی) هر کاربر، نام مستعار، uuid و وضعیت مسدودی."""
    with get_db() as conn:
        return conn.execute(
            """
            SELECT m.sender_chat_id,
                   u.nickname,
                   u.uuid,
                   u.is_blocked,
                   (SELECT text FROM messages m2
                        WHERE m2.sender_chat_id = m.sender_chat_id AND m2.direction <> 'system'
                        ORDER BY m2.created_at DESC LIMIT 1) AS last_text,
                   MAX(m.created_at) AS last_at
            FROM messages m
            JOIN users u ON u.chat_id = m.sender_chat_id
            GROUP BY m.sender_chat_id, u.nickname, u.uuid, u.is_blocked
            ORDER BY last_at DESC
            """
        ).fetchall()


def delete_thread(sender_chat_id: int):
    """کل گفتگوی یک کاربر (پیام‌ها + نگاشت پاسخ‌ها) رو حذف می‌کنه."""
    with get_db() as conn:
        conn.execute("DELETE FROM messages WHERE sender_chat_id=%s", (sender_chat_id,))
        conn.execute("DELETE FROM reply_map WHERE sender_chat_id=%s", (sender_chat_id,))


def save_reply_map(forwarded_message_id: int, admin_chat_id: int, sender_chat_id: int):
    with get_db() as conn:
        conn.execute(
            "INSERT INTO reply_map (forwarded_message_id, admin_chat_id, sender_chat_id) VALUES (%s,%s,%s) "
            "ON CONFLICT (forwarded_message_id) DO UPDATE SET "
            "admin_chat_id = EXCLUDED.admin_chat_id, sender_chat_id = EXCLUDED.sender_chat_id",
            (forwarded_message_id, admin_chat_id, sender_chat_id),
        )


def get_sender_by_forwarded_id(forwarded_message_id: int) -> int | None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT sender_chat_id FROM reply_map WHERE forwarded_message_id=%s",
            (forwarded_message_id,),
        ).fetchone()
        return row["sender_chat_id"] if row else None
