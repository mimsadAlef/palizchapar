import os
from flask import Flask, request, jsonify, render_template

import config
import database as db
import bale_api
from miniapp_auth import validate_init_data, dev_bypass, extract_chat_id

app = Flask(__name__)
DEV_MODE = os.getenv("DEV_MODE", "0") == "1"

# جدول‌های دیتابیس رو همین‌جا (زمان import شدن ماژول) می‌سازیم، نه فقط
# داخل if __name__ == "__main__"، چون با gunicorn/uwsgi اون بلوک اجرا نمی‌شه
# و در نتیجه جدول‌ها هیچ‌وقت ساخته نمی‌شدن (خطای "no such table: users").
db.init_db()

ANONYMOUS_LABEL = "کاربر ناشناس"

WELCOME_TEXT = (
    "سلام! 👋\n"
    "به بات پیام ناشناس خوش اومدی.\n\n"
    "هر پیامی که برام بفرستی، کاملاً ناشناس برای ادمین ارسال می‌شه.\n"
    "اگه دوست داری، می‌تونی یه نام مستعار برای خودت انتخاب کنی (اختیاریه) "
    "یا از دکمه‌ی زیر رد بشی.\n\n"
    "همچنین می‌تونی از طریق مینی‌اپ هم مثل یه چت پیام‌هات رو بفرستی و ببینی."
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
    return bale_api.mini_app_button("💬 باز کردن مینی‌اپ", miniapp_url())


def handle_message(message: dict):
    chat = message.get("chat", {})
    chat_id = chat.get("id")
    if chat_id is None:
        return
    text = (message.get("text") or "").strip()

    # اگر کاربر شماره تلفنش رو از طریق دکمه‌ی اشتراک مخاطب فرستاده باشه
    contact = message.get("contact")
    if contact and contact.get("phone_number"):
        db.get_or_create_user(chat_id)
        db.set_phone(chat_id, contact["phone_number"])
        bale_api.send_message(chat_id, "شماره‌ت با موفقیت ثبت شد ✅", reply_markup=bale_api.remove_keyboard())
        return

    if text.startswith("/start"):
        parts = text.split(maxsplit=1)
        payload = parts[1].strip() if len(parts) > 1 else ""
        return handle_start(chat_id, payload)

    if text == "/nickname":
        db.get_or_create_user(chat_id)
        db.set_awaiting_nick(chat_id, True)
        bale_api.send_message(chat_id, "اسم مستعار جدیدت رو بفرست:")
        return

    user = db.get_or_create_user(chat_id)

    if user["awaiting_nick"]:
        nickname = text[:32] if text else None
        db.set_nickname(chat_id, nickname)
        bale_api.send_message(chat_id, f"نام مستعارت ثبت شد: «{nickname}» ✅")
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
    forward_to_admins(chat_id, user["nickname"], text)


def forward_to_admins(sender_chat_id: int, nickname: str | None, text: str):
    db.add_message(sender_chat_id, nickname, text, direction="in")
    display_name = nickname or ANONYMOUS_LABEL
    admin_ids = db.list_admin_chat_ids()
    if not admin_ids:
        bale_api.send_message(sender_chat_id, "پیامت دریافت شد، ولی فعلاً ادمینی برای پاسخ ثبت نشده.")
        return
    for admin_id in admin_ids:
        result = bale_api.send_message(
            admin_id,
            f"📨 پیام جدید از «{display_name}»:\n\n{text}\n\n"
            f"برای پاسخ ناشناس، روی همین پیام ریپلای بزن.",
        )
        forwarded_msg = (result.get("result") or {})
        forwarded_id = forwarded_msg.get("message_id")
        if forwarded_id:
            db.save_reply_map(forwarded_id, admin_id, sender_chat_id)
    bale_api.send_message(sender_chat_id, "پیامت ارسال شد ✅")


def handle_start(chat_id: int, payload: str):
    db.get_or_create_user(chat_id)

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
    bale_api.send_message(chat_id, "همچنین می‌تونی مینی‌اپ رو باز کنی:", reply_markup=open_miniapp_keyboard())


def handle_callback(callback_query: dict):
    cq_id = callback_query.get("id")
    data = callback_query.get("data")
    message = callback_query.get("message", {})
    chat_id = (message.get("chat") or {}).get("id")
    if chat_id is None:
        return

    db.get_or_create_user(chat_id)

    if data == "set_nick":
        db.set_awaiting_nick(chat_id, True)
        bale_api.send_message(chat_id, "اسم مستعارت رو بفرست:")
    elif data == "skip_nick":
        db.set_nickname(chat_id, None)
        bale_api.send_message(chat_id, "باشه، پیام‌هات به صورت «کاربر ناشناس» ارسال می‌شن.")

    bale_api.answer_callback_query(cq_id)


# --------------------------------------------------------------------------
# مینی‌اپ: صفحه‌ی وب + API
# --------------------------------------------------------------------------
@app.route("/miniapp")
def miniapp_page():
    return render_template("miniapp.html", dev_mode=DEV_MODE)


def _auth(init_data: str):
    parsed = validate_init_data(init_data)
    if parsed is None and DEV_MODE:
        parsed = dev_bypass(init_data)
    if parsed is None:
        return None
    chat_id = extract_chat_id(parsed)
    if chat_id is None:
        return None
    return chat_id


@app.route("/api/auth", methods=["POST"])
def api_auth():
    body = request.get_json(silent=True) or {}
    chat_id = _auth(body.get("initData", ""))
    if chat_id is None:
        return jsonify({"ok": False, "error": "invalid_init_data"}), 401

    user = db.get_or_create_user(chat_id)
    return jsonify({
        "ok": True,
        "chat_id": chat_id,
        "nickname": user["nickname"],
        "phone": user["phone"],
        "is_admin": bool(user["is_admin"]),
    })


@app.route("/api/phone", methods=["POST"])
def api_phone():
    body = request.get_json(silent=True) or {}
    chat_id = _auth(body.get("initData", ""))
    if chat_id is None:
        return jsonify({"ok": False, "error": "invalid_init_data"}), 401
    phone = (body.get("phone") or "").strip()
    if not phone:
        return jsonify({"ok": False, "error": "phone_required"}), 400
    db.get_or_create_user(chat_id)
    db.set_phone(chat_id, phone)
    return jsonify({"ok": True})


@app.route("/api/nickname", methods=["POST"])
def api_nickname():
    body = request.get_json(silent=True) or {}
    chat_id = _auth(body.get("initData", ""))
    if chat_id is None:
        return jsonify({"ok": False, "error": "invalid_init_data"}), 401
    nickname = (body.get("nickname") or "").strip()[:32] or None
    db.get_or_create_user(chat_id)
    db.set_nickname(chat_id, nickname)
    return jsonify({"ok": True, "nickname": nickname})


@app.route("/api/messages", methods=["POST"])
def api_messages():
    """برای کاربر عادی: کل نخ پیام‌های خودش.
    برای ادمین: لیست تمام نخ‌های کاربران (خلاصه)."""
    body = request.get_json(silent=True) or {}
    chat_id = _auth(body.get("initData", ""))
    if chat_id is None:
        return jsonify({"ok": False, "error": "invalid_init_data"}), 401

    user = db.get_or_create_user(chat_id)

    if user["is_admin"]:
        threads = db.list_threads_for_admin()
        return jsonify({"ok": True, "is_admin": True, "threads": [dict(t) for t in threads]})

    thread = db.get_thread(chat_id)
    return jsonify({"ok": True, "is_admin": False, "messages": [dict(m) for m in thread]})


@app.route("/api/thread", methods=["POST"])
def api_thread():
    """فقط برای ادمین: مشاهده‌ی کامل گفتگو با یک کاربر خاص."""
    body = request.get_json(silent=True) or {}
    chat_id = _auth(body.get("initData", ""))
    if chat_id is None:
        return jsonify({"ok": False, "error": "invalid_init_data"}), 401
    if not db.is_admin(chat_id):
        return jsonify({"ok": False, "error": "forbidden"}), 403

    target = body.get("target_chat_id")
    if target is None:
        return jsonify({"ok": False, "error": "target_chat_id_required"}), 400
    thread = db.get_thread(int(target))
    return jsonify({"ok": True, "messages": [dict(m) for m in thread]})


@app.route("/api/send", methods=["POST"])
def api_send():
    body = request.get_json(silent=True) or {}
    chat_id = _auth(body.get("initData", ""))
    if chat_id is None:
        return jsonify({"ok": False, "error": "invalid_init_data"}), 401

    text = (body.get("text") or "").strip()
    if not text:
        return jsonify({"ok": False, "error": "text_required"}), 400

    user = db.get_or_create_user(chat_id)

    if user["is_admin"]:
        target = body.get("target_chat_id")
        if target is None:
            return jsonify({"ok": False, "error": "target_chat_id_required"}), 400
        target = int(target)
        db.add_message(target, None, text, direction="out", admin_chat_id=chat_id)
        bale_api.send_message(target, f"📩 پاسخ ادمین:\n{text}")
        return jsonify({"ok": True})

    forward_to_admins(chat_id, user["nickname"], text)
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
