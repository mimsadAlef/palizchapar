"""
لایه‌ی دیتابیس - PostgreSQL از طریق psycopg3 با یک connection pool.
همه‌ی توابع dict برمی‌گردونن (row_factory=dict_row) تا کد بالادستی
با row["field"] کار کنه.
"""
import time
import contextlib

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

import config
import migrations

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
    migrations.apply_migrations(get_db)


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
            # uuid به‌صورت متوالی از خود دیتابیس گرفته می‌شه: ۰۰۰۱، ۰۰۰۲، ...
            conn.execute(
                "INSERT INTO users (chat_id, uuid, nickname, phone, is_admin, is_blocked, awaiting_nick, created_at) "
                "VALUES (%s, lpad(nextval('user_uuid_seq')::text, 4, '0'), NULL, NULL, FALSE, FALSE, FALSE, %s)",
                (chat_id, time.time()),
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


def set_awaiting_owner_verify(chat_id: int, value: bool):
    with get_db() as conn:
        conn.execute("UPDATE users SET awaiting_owner_verify=%s WHERE chat_id=%s", (value, chat_id))


def set_phone(chat_id: int, phone: str):
    with get_db() as conn:
        conn.execute("UPDATE users SET phone=%s WHERE chat_id=%s", (phone, chat_id))


def set_admin(chat_id: int, value: bool):
    with get_db() as conn:
        conn.execute("UPDATE users SET is_admin=%s WHERE chat_id=%s", (value, chat_id))


def set_owner(chat_id: int, value: bool):
    with get_db() as conn:
        conn.execute("UPDATE users SET is_owner=%s WHERE chat_id=%s", (value, chat_id))


def set_blocked(chat_id: int, blocked: bool):
    with get_db() as conn:
        conn.execute("UPDATE users SET is_blocked=%s WHERE chat_id=%s", (blocked, chat_id))


def set_active_unit(chat_id: int, unit_id: int | None):
    with get_db() as conn:
        conn.execute("UPDATE users SET active_unit_id=%s WHERE chat_id=%s", (unit_id, chat_id))


def is_admin(chat_id: int) -> bool:
    with get_db() as conn:
        row = conn.execute("SELECT is_admin FROM users WHERE chat_id=%s", (chat_id,)).fetchone()
        return bool(row and row["is_admin"])


def is_owner(chat_id: int) -> bool:
    with get_db() as conn:
        row = conn.execute("SELECT is_owner FROM users WHERE chat_id=%s", (chat_id,)).fetchone()
        return bool(row and row["is_owner"])


def has_panel_access(chat_id: int) -> bool:
    """دسترسی به پنل مینی‌اپ: مالک یا مدیر تاییدشده."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT is_admin, is_owner FROM users WHERE chat_id=%s", (chat_id,)
        ).fetchone()
        return bool(row and (row["is_admin"] or row["is_owner"]))


def is_blocked(chat_id: int) -> bool:
    with get_db() as conn:
        row = conn.execute("SELECT is_blocked FROM users WHERE chat_id=%s", (chat_id,)).fetchone()
        return bool(row and row["is_blocked"])


def list_owner_chat_ids() -> list[int]:
    with get_db() as conn:
        rows = conn.execute("SELECT chat_id FROM users WHERE is_owner=TRUE").fetchall()
        return [r["chat_id"] for r in rows]


def list_admin_chat_ids_for_unit(unit_id: int) -> list[int]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT au.chat_id FROM admin_units au "
            "JOIN users u ON u.chat_id = au.chat_id "
            "WHERE au.unit_id=%s AND u.is_admin=TRUE",
            (unit_id,),
        ).fetchall()
        return [r["chat_id"] for r in rows]


# --------------------------------------------------------------------------
# واحدها (دپارتمان‌ها)
# --------------------------------------------------------------------------
def list_units() -> list[dict]:
    with get_db() as conn:
        return conn.execute("SELECT * FROM units ORDER BY name ASC").fetchall()


def get_unit(unit_id: int) -> dict | None:
    with get_db() as conn:
        return conn.execute("SELECT * FROM units WHERE id=%s", (unit_id,)).fetchone()


def create_unit(name: str) -> dict:
    with get_db() as conn:
        row = conn.execute(
            "INSERT INTO units (name, created_at) VALUES (%s, %s) RETURNING *",
            (name, time.time()),
        ).fetchone()
        return row


def delete_unit(unit_id: int) -> tuple[bool, str | None]:
    """اگه واحد دارای گفتگوی ثبت‌شده باشه (FK RESTRICT)، حذف نمی‌شه و پیام خطا برمی‌گرده."""
    try:
        with get_db() as conn:
            conn.execute("DELETE FROM units WHERE id=%s", (unit_id,))
        return True, None
    except Exception:
        return False, "این واحد دارای گفتگوی ثبت‌شده است و قابل حذف نیست."


def get_units_for_admin(chat_id: int) -> list[dict]:
    with get_db() as conn:
        return conn.execute(
            "SELECT un.* FROM admin_units au JOIN units un ON un.id = au.unit_id "
            "WHERE au.chat_id=%s ORDER BY un.name ASC",
            (chat_id,),
        ).fetchall()


def set_admin_units(chat_id: int, unit_ids: list[int]):
    """کل عضویت‌های یک مدیر توی واحدها رو با این لیست جایگزین می‌کنه."""
    with get_db() as conn:
        conn.execute("DELETE FROM admin_units WHERE chat_id=%s", (chat_id,))
        for unit_id in unit_ids:
            conn.execute(
                "INSERT INTO admin_units (chat_id, unit_id) VALUES (%s,%s) ON CONFLICT DO NOTHING",
                (chat_id, unit_id),
            )


def clear_admin_units(chat_id: int):
    with get_db() as conn:
        conn.execute("DELETE FROM admin_units WHERE chat_id=%s", (chat_id,))


def list_admins_with_units() -> list[dict]:
    """برای پنل مالک: همه‌ی مدیرهای تاییدشده + لیست واحدهاشون."""
    with get_db() as conn:
        admins = conn.execute(
            "SELECT chat_id, uuid, nickname, phone FROM users WHERE is_admin=TRUE ORDER BY created_at ASC"
        ).fetchall()
        for a in admins:
            a["units"] = conn.execute(
                "SELECT un.id, un.name FROM admin_units au JOIN units un ON un.id = au.unit_id "
                "WHERE au.chat_id=%s ORDER BY un.name ASC",
                (a["chat_id"],),
            ).fetchall()
        return admins


# --------------------------------------------------------------------------
# درخواست‌های مدیر شدن
# --------------------------------------------------------------------------
def create_admin_request(chat_id: int) -> int:
    with get_db() as conn:
        row = conn.execute(
            "INSERT INTO admin_requests (chat_id, status, created_at) VALUES (%s, 'pending', %s) RETURNING id",
            (chat_id, time.time()),
        ).fetchone()
        return row["id"]


def has_pending_request(chat_id: int) -> bool:
    with get_db() as conn:
        row = conn.execute(
            "SELECT id FROM admin_requests WHERE chat_id=%s AND status='pending' LIMIT 1",
            (chat_id,),
        ).fetchone()
        return row is not None


def list_pending_requests() -> list[dict]:
    with get_db() as conn:
        return conn.execute(
            """
            SELECT r.id, r.chat_id, r.created_at, u.uuid, u.nickname, u.phone
            FROM admin_requests r
            JOIN users u ON u.chat_id = r.chat_id
            WHERE r.status='pending'
            ORDER BY r.created_at ASC
            """
        ).fetchall()


def get_request(request_id: int) -> dict | None:
    with get_db() as conn:
        return conn.execute("SELECT * FROM admin_requests WHERE id=%s", (request_id,)).fetchone()


def decide_request(request_id: int, approve: bool, decided_by: int) -> dict | None:
    """درخواست رو تایید/رد می‌کنه و در صورت تایید، is_admin رو ست می‌کنه. رکورد درخواست رو برمی‌گردونه."""
    with get_db() as conn:
        req = conn.execute("SELECT * FROM admin_requests WHERE id=%s AND status='pending'", (request_id,)).fetchone()
        if req is None:
            return None
        status = "approved" if approve else "rejected"
        conn.execute(
            "UPDATE admin_requests SET status=%s, decided_at=%s, decided_by=%s WHERE id=%s",
            (status, time.time(), decided_by, request_id),
        )
        if approve:
            conn.execute("UPDATE users SET is_admin=TRUE WHERE chat_id=%s", (req["chat_id"],))
        return req


# --------------------------------------------------------------------------
# پیام‌ها
# --------------------------------------------------------------------------
def add_message(sender_chat_id: int, unit_id: int, nickname_snapshot: str | None, text: str,
                 direction: str, admin_chat_id: int | None = None,
                 origin_message_id: int | None = None, reply_to_id: int | None = None,
                 reply_preview: str | None = None) -> int:
    with get_db() as conn:
        row = conn.execute(
            "INSERT INTO messages (sender_chat_id, unit_id, nickname_snapshot, text, direction, "
            "admin_chat_id, origin_message_id, reply_to_id, reply_preview, created_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
            (sender_chat_id, unit_id, nickname_snapshot, text, direction, admin_chat_id,
             origin_message_id, reply_to_id, reply_preview, time.time()),
        ).fetchone()
        return row["id"]


def set_message_origin_id(message_id: int, origin_message_id: int):
    with get_db() as conn:
        conn.execute("UPDATE messages SET origin_message_id=%s WHERE id=%s", (origin_message_id, message_id))


def get_message(message_id: int) -> dict | None:
    with get_db() as conn:
        return conn.execute("SELECT * FROM messages WHERE id=%s", (message_id,)).fetchone()


def get_thread(sender_chat_id: int, unit_id: int) -> list[dict]:
    with get_db() as conn:
        return conn.execute(
            "SELECT * FROM messages WHERE sender_chat_id=%s AND unit_id=%s ORDER BY created_at ASC",
            (sender_chat_id, unit_id),
        ).fetchall()


def list_threads(unit_ids: list[int] | None) -> list[dict]:
    """لیست خلاصه‌ی گفتگوها. unit_ids=None یعنی بدون فیلتر (برای مالک/دید کلی)."""
    query = """
        SELECT m.sender_chat_id,
               m.unit_id,
               un.name AS unit_name,
               u.nickname,
               u.uuid,
               u.is_blocked,
               (SELECT text FROM messages m2
                    WHERE m2.sender_chat_id = m.sender_chat_id AND m2.unit_id = m.unit_id
                          AND m2.direction <> 'system'
                    ORDER BY m2.created_at DESC LIMIT 1) AS last_text,
               MAX(m.created_at) AS last_at
        FROM messages m
        JOIN users u ON u.chat_id = m.sender_chat_id
        JOIN units un ON un.id = m.unit_id
    """
    params: tuple = ()
    if unit_ids is not None:
        if not unit_ids:
            return []
        query += " WHERE m.unit_id = ANY(%s)"
        params = (list(unit_ids),)
    query += " GROUP BY m.sender_chat_id, m.unit_id, un.name, u.nickname, u.uuid, u.is_blocked ORDER BY last_at DESC"
    with get_db() as conn:
        return conn.execute(query, params).fetchall()


def delete_thread(sender_chat_id: int, unit_id: int):
    """گفتگوی یک کاربر با یک واحد خاص (پیام‌ها + نگاشت پاسخ‌ها) رو حذف می‌کنه."""
    with get_db() as conn:
        conn.execute(
            "DELETE FROM reply_map WHERE sender_chat_id=%s AND message_id IN "
            "(SELECT id FROM messages WHERE sender_chat_id=%s AND unit_id=%s)",
            (sender_chat_id, sender_chat_id, unit_id),
        )
        conn.execute(
            "DELETE FROM messages WHERE sender_chat_id=%s AND unit_id=%s",
            (sender_chat_id, unit_id),
        )


def save_reply_map(admin_chat_id: int, forwarded_message_id: int, sender_chat_id: int, message_id: int):
    with get_db() as conn:
        conn.execute(
            "INSERT INTO reply_map (admin_chat_id, forwarded_message_id, sender_chat_id, message_id) "
            "VALUES (%s,%s,%s,%s) ON CONFLICT (admin_chat_id, forwarded_message_id) DO UPDATE SET "
            "sender_chat_id = EXCLUDED.sender_chat_id, message_id = EXCLUDED.message_id",
            (admin_chat_id, forwarded_message_id, sender_chat_id, message_id),
        )


def get_reply_target(admin_chat_id: int, forwarded_message_id: int) -> dict | None:
    with get_db() as conn:
        return conn.execute(
            "SELECT sender_chat_id, message_id FROM reply_map WHERE admin_chat_id=%s AND forwarded_message_id=%s",
            (admin_chat_id, forwarded_message_id),
        ).fetchone()
