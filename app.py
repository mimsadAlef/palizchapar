import os
from flask import Flask, request, jsonify, render_template

import config
import database as db
import bale_api
from miniapp_auth import validate_init_data, dev_bypass, extract_chat_id

app = Flask(__name__)
DEV_MODE = os.getenv("DEV_MODE", "0") == "1"

# جدول‌های دیتابیس رو همین‌جا (زمان import شدن ماژول) می‌سازیم، نه فقط
# داخل if __name__ == "__main__"، چون با gunicorn/uwsgi اون بلوک اجرا نمی‌شه.
db.init_db()

WELCOME_TEXT = (
    "سلام! 👋\n"
    "به بات پیام ناشناس خوش اومدی.\n\n"
    "هر پیامی که برام بفرستی، کاملاً ناشناس برای ادمین ارسال می‌شه.\n"
    "اگه دوست داری، می‌تونی یه نام مستعار برای خودت انتخاب کنی (اختیاریه) "
    "یا از دکمه‌ی زیر رد بشی."
)


# --------------------------------------------------------------------------
# مسیر وبهوک - بله برای هر پیام/کال‌بک جدید یک POST به این آدرس می‌فرستد
# --------------------------------------------------------------------------
@app.route(f"/webhook/{config.WEBHOOK_SECRET_PATH}", methods=["POST"])
def webhook():
    update = request.get_json(silent=True) or {}

    if "message" in update:
        handle_message(update["message"])
    elif "callback_query" in update:
        handle_callback(update["callback_query"])

    return jsonify({"ok": True})


def miniapp_url() -> str:
    return f"{config.BASE_URL}/miniapp"


def nickname_choice_keyboard():
    return bale_api.inline_keyboard([
        [{"text": "✏️ انتخاب نام مستعار", "callback_data": "set_nick"}],
        [{"text": "⏭ رد کردن (ناشناس بمونم)", "callback_data": "skip_nick"}],
    ])


def open_miniapp_keyboard():
    return bale_api.mini_app_button("🛠 باز کردن پنل ادمین", miniapp_url())


# --------------------------------------------------------------------------
# عضویت اجباری در کانال‌ها - قبل از پردازش هر پیام (چه کاربر عادی چه ادمین)
# --------------------------------------------------------------------------
def get_missing_channels(user_id: int) -> list[dict]:
    """لیست کانال‌هایی که کاربر هنوز عضوشون نشده رو برمی‌گردونه (خالی یعنی همه رو داره)."""
    return [ch for ch in config.REQUIRED_CHANNELS if not bale_api.is_channel_member(ch["username"], user_id)]


def channel_url(channel: dict) -> str:
    return f"https://ble.ir/{channel['username'].lstrip('@')}"


def join_prompt_keyboard(missing: list[dict]) -> dict:
    rows = [[{"text": f"عضویت در {ch['title']}", "url": channel_url(ch)}] for ch in missing]
    rows.append([{"text": "✅ عضو شدم، بررسی کن", "callback_data": "check_membership"}])
    return bale_api.inline_keyboard(rows)


def send_join_prompt(chat_id: int, missing: list[dict]):
    bale_api.send_message(
        chat_id,
        "برای استفاده از بات، اول باید توی کانال‌های زیر عضو بشی:",
        reply_markup=join_prompt_keyboard(missing),
    )


# --------------------------------------------------------------------------
# پیام‌های سیستمی (مثل تغییر نام مستعار) که در گفتگوی کاربر برای ادمین ثبت می‌شن
# --------------------------------------------------------------------------
def log_nickname_change(chat_id: int, user_before: dict, old_nickname: str | None, new_nickname: str | None):
    old_label = old_nickname or db.default_nickname(user_before)
    new_label = new_nickname or db.default_nickname(user_before)
    if old_label == new_label:
        return
    db.add_message(
        chat_id, None,
        f"🔄 کاربر نام مستعارش رو از «{old_label}» به «{new_label}» تغییر داد.",
        direction="system",
    )


def handle_message(message: dict):
    chat = message.get("chat", {})
    chat_id = chat.get("id")
    if chat_id is None:
        return
    text = (message.get("text") or "").strip()

    user = db.get_or_create_user(chat_id)

    if user["is_blocked"]:
        bale_api.send_message(chat_id, "🚫 شما توسط مدیر مسدود شده‌اید و امکان استفاده از این بات رو ندارید.")
        return

    # عضویت اجباری: قبل از پردازش هر پیام (چه از ادمین چه از کاربر عادی) چک می‌شه
    missing = get_missing_channels(chat_id)
    if missing:
        send_join_prompt(chat_id, missing)
        return

    # اگر کاربر شماره تلفنش رو از طریق دکمه‌ی اشتراک مخاطب فرستاده باشه
    contact = message.get("contact")
    if contact and contact.get("phone_number"):
        db.set_phone(chat_id, contact["phone_number"])
        bale_api.send_message(chat_id, "شماره‌ت با موفقیت ثبت شد ✅", reply_markup=bale_api.remove_keyboard())
        return

    if text.startswith("/start"):
        parts = text.split(maxsplit=1)
        payload = parts[1].strip() if len(parts) > 1 else ""
        return handle_start(chat_id, payload)

    if text == "/nickname":
        db.set_awaiting_nick(chat_id, True)
        bale_api.send_message(chat_id, "اسم مستعار جدیدت رو بفرست:")
        return

    if user["awaiting_nick"]:
        nickname = text[:32] if text else None
        old_nickname = db.set_nickname(chat_id, nickname)
        log_nickname_change(chat_id, user, old_nickname, nickname)
        bale_api.send_message(chat_id, f"نام مستعارت ثبت شد: «{nickname or db.default_nickname(user)}» ✅")
        return

    if not text:
        return  # فعلاً فقط پیام متنی رو پشتیبانی می‌کنیم

    # ادمین: اگر داره به یه پیام فورواردشده ریپلای می‌کنه => پاسخ ناشناس به فرستنده
    reply_to = message.get("reply_to_message")
    if user["is_admin"] and reply_to:
        forwarded_id = reply_to.get("message_id")
        sender_chat_id = db.get_sender_by_forwarded_id(forwarded_id) if forwarded_id else None
        if sender_chat_id:
            db.add_message(sender_chat_id, None, text, direction="out", admin_chat_id=chat_id)
            bale_api.send_message(sender_chat_id, f"📩 پاسخ ادمین:\n{text}")
            bale_api.send_message(chat_id, "پاسخت ارسال شد ✅")
            return
        else:
            bale_api.send_message(chat_id, "برای پاسخ، لطفاً روی همون پیام فوروارد شده ریپلای بزن.")
            return

    # حالت عادی: پیام ناشناس کاربر به سمت ادمین(ها)
    forward_to_admins(chat_id, user, text)


def forward_to_admins(sender_chat_id: int, user: dict, text: str):
    db.add_message(sender_chat_id, user["nickname"], text, direction="in")
    display = db.display_name(user)
    admin_ids = db.list_admin_chat_ids()
    if not admin_ids:
        bale_api.send_message(sender_chat_id, "پیامت دریافت شد، ولی فعلاً ادمینی برای پاسخ ثبت نشده.")
        return
    for admin_id in admin_ids:
        result = bale_api.send_message(
            admin_id,
            f"📨 پیام جدید از «{display}»:\n\n{text}\n\n"
            f"برای پاسخ ناشناس، روی همین پیام ریپلای بزن.",
        )
        forwarded_msg = (result.get("result") or {})
        forwarded_id = forwarded_msg.get("message_id")
        if forwarded_id:
            db.save_reply_map(forwarded_id, admin_id, sender_chat_id)
    bale_api.send_message(sender_chat_id, "پیامت ارسال شد ✅")


def handle_start(chat_id: int, payload: str):
    if payload and payload == config.ADMIN_START_TOKEN:
        db.mark_admin(chat_id)
        bale_api.send_message(
            chat_id,
            "✅ به عنوان ادمین ثبت شدی.\n"
            "لطفاً شماره‌ت رو با دکمه‌ی زیر برام بفرست:",
            reply_markup=bale_api.contact_request_keyboard(),
        )
        bale_api.send_message(
            chat_id,
            "برای دیدن پیام‌ها و پاسخ دادن، پنل ادمین رو باز کن:",
            reply_markup=open_miniapp_keyboard(),
        )
        return

    bale_api.send_message(chat_id, WELCOME_TEXT, reply_markup=nickname_choice_keyboard())


def handle_callback(callback_query: dict):
    cq_id = callback_query.get("id")
    data = callback_query.get("data")
    message = callback_query.get("message", {})
    chat_id = (message.get("chat") or {}).get("id")
    if chat_id is None:
        return

    user = db.get_or_create_user(chat_id)

    if user["is_blocked"]:
        bale_api.answer_callback_query(cq_id, "🚫 شما مسدود شده‌اید.")
        return

    if data == "check_membership":
        missing = get_missing_channels(chat_id)
        if missing:
            bale_api.answer_callback_query(cq_id, "هنوز توی همه‌ی کانال‌ها عضو نشدی ❌")
            send_join_prompt(chat_id, missing)
        else:
            bale_api.answer_callback_query(cq_id, "عضویت تأیید شد ✅")
            bale_api.send_message(chat_id, "عضویتت تأیید شد ✅ حالا می‌تونی از بات استفاده کنی. /start رو بزن.")
        return

    # از اینجا به بعد هم عضویت رو چک می‌کنیم (کال‌بک‌های مربوط به نام مستعار و ...)
    missing = get_missing_channels(chat_id)
    if missing:
        bale_api.answer_callback_query(cq_id)
        send_join_prompt(chat_id, missing)
        return

    if data == "set_nick":
        db.set_awaiting_nick(chat_id, True)
        bale_api.send_message(chat_id, "اسم مستعارت رو بفرست:")
    elif data == "skip_nick":
        old_nickname = db.set_nickname(chat_id, None)
        log_nickname_change(chat_id, user, old_nickname, None)
        bale_api.send_message(chat_id, f"باشه، پیام‌هات به‌صورت «{db.default_nickname(user)}» ارسال می‌شن.")

    bale_api.answer_callback_query(cq_id)


# --------------------------------------------------------------------------
# مینی‌اپ: فقط پنل ادمین (کاربر عادی به این بخش دسترسی نداره)
# --------------------------------------------------------------------------
@app.route("/miniapp")
def miniapp_page():
    return render_template("miniapp.html", dev_mode=DEV_MODE)


def _auth_chat_id(body: dict) -> int | None:
    """initData رو اعتبارسنجی می‌کنه و chat_id رو برمی‌گردونه (بدون چک نقش)."""
    parsed = validate_init_data(body.get("initData", ""))
    if parsed is None and DEV_MODE:
        parsed = dev_bypass(body.get("initData", ""))
    if parsed is None:
        return None
    return extract_chat_id(parsed)


def _auth_admin(body: dict) -> int | None:
    """مینی‌اپ فقط برای ادمینه؛ اگه کاربر ادمین نباشه None برمی‌گردونه."""
    chat_id = _auth_chat_id(body)
    if chat_id is None:
        return None
    if not db.is_admin(chat_id):
        return None
    return chat_id


@app.route("/api/auth", methods=["POST"])
def api_auth():
    body = request.get_json(silent=True) or {}
    chat_id = _auth_chat_id(body)
    if chat_id is None:
        return jsonify({"ok": False, "error": "invalid_init_data"}), 401

    user = db.get_or_create_user(chat_id)
    if not user["is_admin"]:
        return jsonify({"ok": False, "error": "admin_only"}), 403

    return jsonify({"ok": True, "chat_id": chat_id, "phone": user["phone"]})


@app.route("/api/phone", methods=["POST"])
def api_phone():
    body = request.get_json(silent=True) or {}
    chat_id = _auth_admin(body)
    if chat_id is None:
        return jsonify({"ok": False, "error": "forbidden"}), 403

    phone = (body.get("phone") or "").strip()
    if not phone:
        return jsonify({"ok": False, "error": "phone_required"}), 400
    db.set_phone(chat_id, phone)
    return jsonify({"ok": True})


@app.route("/api/messages", methods=["POST"])
def api_messages():
    """لیست خلاصه‌ی گفتگوها برای پنل ادمین."""
    body = request.get_json(silent=True) or {}
    chat_id = _auth_admin(body)
    if chat_id is None:
        return jsonify({"ok": False, "error": "forbidden"}), 403

    threads = db.list_threads_for_admin()
    return jsonify({"ok": True, "threads": threads})


@app.route("/api/thread", methods=["POST"])
def api_thread():
    """مشاهده‌ی کامل گفتگو با یک کاربر خاص."""
    body = request.get_json(silent=True) or {}
    chat_id = _auth_admin(body)
    if chat_id is None:
        return jsonify({"ok": False, "error": "forbidden"}), 403

    target = body.get("target_chat_id")
    if target is None:
        return jsonify({"ok": False, "error": "target_chat_id_required"}), 400
    thread = db.get_thread(int(target))
    return jsonify({"ok": True, "messages": thread})


@app.route("/api/send", methods=["POST"])
def api_send():
    """ارسال پاسخ ناشناس ادمین به یک کاربر."""
    body = request.get_json(silent=True) or {}
    chat_id = _auth_admin(body)
    if chat_id is None:
        return jsonify({"ok": False, "error": "forbidden"}), 403

    # عضویت اجباری برای ادمین هم برقراره
    missing = get_missing_channels(chat_id)
    if missing:
        return jsonify({
            "ok": False,
            "error": "not_member",
            "missing": [{"username": c["username"], "title": c["title"], "url": channel_url(c)} for c in missing],
        }), 403

    text = (body.get("text") or "").strip()
    target = body.get("target_chat_id")
    if not text or target is None:
        return jsonify({"ok": False, "error": "text_and_target_required"}), 400
    target = int(target)

    db.add_message(target, None, text, direction="out", admin_chat_id=chat_id)
    bale_api.send_message(target, f"📩 پاسخ ادمین:\n{text}")
    return jsonify({"ok": True})


@app.route("/api/block", methods=["POST"])
def api_block():
    """مسدود/رفع مسدودی یک کاربر توسط ادمین."""
    body = request.get_json(silent=True) or {}
    chat_id = _auth_admin(body)
    if chat_id is None:
        return jsonify({"ok": False, "error": "forbidden"}), 403

    target = body.get("target_chat_id")
    if target is None:
        return jsonify({"ok": False, "error": "target_chat_id_required"}), 400
    target = int(target)
    if target == chat_id:
        return jsonify({"ok": False, "error": "cannot_block_self"}), 400

    blocked = bool(body.get("blocked"))
    db.set_blocked(target, blocked)
    return jsonify({"ok": True, "blocked": blocked})


@app.route("/api/delete_thread", methods=["POST"])
def api_delete_thread():
    """حذف کامل گفتگوی یک کاربر توسط ادمین."""
    body = request.get_json(silent=True) or {}
    chat_id = _auth_admin(body)
    if chat_id is None:
        return jsonify({"ok": False, "error": "forbidden"}), 403

    target = body.get("target_chat_id")
    if target is None:
        return jsonify({"ok": False, "error": "target_chat_id_required"}), 400
    db.delete_thread(int(target))
    return jsonify({"ok": True})


# --------------------------------------------------------------------------
# راه‌اندازی وبهوک (یک‌بار موقع دیپلوی صدا زده می‌شه)
# --------------------------------------------------------------------------
@app.route("/setup-webhook")
def setup_webhook():
    """این مسیر رو بعد از دیپلوی، یک‌بار توی مرورگر باز کن تا وبهوک ثبت بشه.
    (بهتره بعد از اولین اجرا این مسیر رو غیرفعال/حذف کنی یا پشت یک رمز بذاری)"""
    if not config.BASE_URL:
        return "BASE_URL در تنظیمات خالیه.", 400
    url = f"{config.BASE_URL}/webhook/{config.WEBHOOK_SECRET_PATH}"
    result = bale_api.set_webhook(url)
    return jsonify(result)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=config.PORT, debug=DEV_MODE)
