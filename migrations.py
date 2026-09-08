"""
مدیریت نسخه‌ی schema دیتابیس (migration ساده و idempotent).

هر migration دقیقاً یک بار روی هر دیتابیس اجرا می‌شه؛ نسخه‌های اجراشده در
جدول schema_migrations ثبت می‌شن. این ماژول هیچ وابستگی‌ای به database.py
نداره (get_db از بیرون تزریق می‌شه) تا import چرخه‌ای پیش نیاد.

چرا این روش؟ چون نسخه‌ی قبلی این پروژه روی production در حال اجراست و
داده‌ی واقعی (کاربران، گفتگوها) داره. نمی‌تونیم جدول‌ها رو drop-and-recreate
کنیم؛ باید schema رو با ALTER/INSERT های backward-compatible و idempotent
جلو ببریم. هر migration جدید فقط باید به این لیست اضافه بشه، نه اینکه
migration های قبلی رو ویرایش کنه.
"""
import time

MIGRATIONS: list[tuple[str, list[str]]] = [
    (
        "0001_baseline",
        [
            # شماره‌ی uuid کاربران از این sequence گرفته می‌شه: ۰۰۰۱، ۰۰۰۲، ...
            "CREATE SEQUENCE IF NOT EXISTS user_uuid_seq START 1",
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
                sender_chat_id      BIGINT NOT NULL,
                nickname_snapshot   TEXT,
                text                TEXT NOT NULL,
                direction           TEXT NOT NULL,
                admin_chat_id       BIGINT,
                created_at          DOUBLE PRECISION NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_messages_sender ON messages (sender_chat_id, created_at)",
            """
            CREATE TABLE IF NOT EXISTS reply_map (
                forwarded_message_id  BIGINT PRIMARY KEY,
                admin_chat_id         BIGINT NOT NULL,
                sender_chat_id        BIGINT NOT NULL
            )
            """,
        ],
    ),
    (
        "0002_owner_units_and_reply_threading",
        [
            # --- نقش مالک ---
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_owner BOOLEAN NOT NULL DEFAULT FALSE",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS awaiting_owner_verify BOOLEAN NOT NULL DEFAULT FALSE",

            # --- واحدها (دپارتمان‌ها) ---
            """
            CREATE TABLE IF NOT EXISTS units (
                id          BIGSERIAL PRIMARY KEY,
                name        TEXT NOT NULL UNIQUE,
                created_at  DOUBLE PRECISION NOT NULL
            )
            """,
            # یک واحد پیش‌فرض می‌سازیم تا گفتگوهای قبل از این migration یه
            # واحد معتبر برای نسبت‌دادن داشته باشن (چون unit_id روی messages
            # در ادامه‌ی همین migration NOT NULL می‌شه).
            """
            INSERT INTO units (name, created_at)
            SELECT 'عمومی', extract(epoch from now())
            WHERE NOT EXISTS (SELECT 1 FROM units)
            """,

            "ALTER TABLE users ADD COLUMN IF NOT EXISTS active_unit_id BIGINT REFERENCES units(id) ON DELETE SET NULL",

            # --- عضویت مدیر در واحدها (یک مدیر می‌تونه عضو چند واحد باشه) ---
            """
            CREATE TABLE IF NOT EXISTS admin_units (
                chat_id  BIGINT NOT NULL,
                unit_id  BIGINT NOT NULL REFERENCES units(id) ON DELETE CASCADE,
                PRIMARY KEY (chat_id, unit_id)
            )
            """,
            # مدیرهای فعلی (قبل از این migration) رو عضو همون واحد پیش‌فرض
            # می‌کنیم تا گفتگوهای قدیمی‌شون رو در پنل از دست ندن.
            """
            INSERT INTO admin_units (chat_id, unit_id)
            SELECT u.chat_id, (SELECT id FROM units ORDER BY id LIMIT 1)
            FROM users u
            WHERE u.is_admin = TRUE
            ON CONFLICT DO NOTHING
            """,

            # --- درخواست‌های مدیر شدن (نیازمند تایید مالک) ---
            """
            CREATE TABLE IF NOT EXISTS admin_requests (
                id          BIGSERIAL PRIMARY KEY,
                chat_id     BIGINT NOT NULL,
                status      TEXT NOT NULL DEFAULT 'pending',
                created_at  DOUBLE PRECISION NOT NULL,
                decided_at  DOUBLE PRECISION,
                decided_by  BIGINT
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_admin_requests_status ON admin_requests (status, created_at)",

            # --- پیام‌ها: افزودن واحد + زیرساخت ریپلای واقعی به یک پیام خاص ---
            "ALTER TABLE messages ADD COLUMN IF NOT EXISTS unit_id BIGINT REFERENCES units(id) ON DELETE RESTRICT",
            "UPDATE messages SET unit_id = (SELECT id FROM units ORDER BY id LIMIT 1) WHERE unit_id IS NULL",
            "ALTER TABLE messages ALTER COLUMN unit_id SET NOT NULL",
            "CREATE INDEX IF NOT EXISTS idx_messages_unit ON messages (unit_id, created_at)",

            # message_id همون پیام در چتِ خودِ کاربر (برای ریپلای واقعیِ بله)
            "ALTER TABLE messages ADD COLUMN IF NOT EXISTS origin_message_id BIGINT",
            "ALTER TABLE messages ADD COLUMN IF NOT EXISTS reply_to_id BIGINT REFERENCES messages(id) ON DELETE SET NULL",
            "ALTER TABLE messages ADD COLUMN IF NOT EXISTS reply_preview TEXT",

            # --- بازسازی reply_map ---
            # کلید قدیمی (فقط forwarded_message_id) باگ داشت: این عدد فقط
            # داخل یک چت یکتاست، نه سراسری؛ بین چت‌های مختلف مدیرها می‌تونست
            # تصادفی تکرار بشه. چون این جدول صرفاً یک نگاشت کوتاه‌مدت برای
            # پاسخ سریع به آخرین پیام‌های فوروواردشده‌ست (نه یک آرشیو)، و
            # داده‌ی قدیمیش برای ریپلای دقیق به یک پیام خاص کافی نبود،
            # بازسازیش می‌کنیم. اثر جانبی: پیام‌های فوروواردشده‌ی قبل از این
            # migration که هنوز پاسخ داده نشدن، دیگه با ریپلای مستقیم قابل
            # پاسخ نیستن (پیام fallback مربوطه راهنماییشون می‌کنه).
            "DROP TABLE IF EXISTS reply_map",
            """
            CREATE TABLE reply_map (
                admin_chat_id         BIGINT NOT NULL,
                forwarded_message_id  BIGINT NOT NULL,
                sender_chat_id        BIGINT NOT NULL,
                message_id            BIGINT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
                PRIMARY KEY (admin_chat_id, forwarded_message_id)
            )
            """,
        ],
    ),
    (
        "0003_admin_request_after_phone",
        [
            # درخواست مدیر شدن دیگه فوری (با زدن لینک توکن) ثبت نمی‌شه؛ اول باید
            # شماره تلفن گرفته بشه، بعد درخواست ساخته بشه. این پرچم وضعیت
            # «منتظر شماره برای ثبت درخواست» رو نگه می‌داره.
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS awaiting_admin_request BOOLEAN NOT NULL DEFAULT FALSE",
        ],
    ),
]


def apply_migrations(get_db):
    """get_db: همون context-manager تولیدکننده‌ی کانکشن از database.py (تزریق‌شده
    تا این ماژول به database.py وابسته نباشه)."""
    with get_db() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "version TEXT PRIMARY KEY, applied_at DOUBLE PRECISION NOT NULL)"
        )
        applied = {r["version"] for r in conn.execute("SELECT version FROM schema_migrations").fetchall()}

    for version, statements in MIGRATIONS:
        if version in applied:
            continue
        with get_db() as conn:
            for stmt in statements:
                conn.execute(stmt)
            conn.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (%s, %s)",
                (version, time.time()),
            )
