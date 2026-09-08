"""
منطق چت‌بات (سمت وبهوک بله) - جدا از app.py تا فایل اصلی سبک بمونه.
همه‌چیزی که به «پیام گرفتن از کاربر توی چت بله» مربوطه اینجاست؛ APIهای
مینی‌اپ توی admin_api.py هستن.
"""
import re

import config
import database as db
import bale_api

WELCOME_TEXT = (
    "سلام! 👋\n"
    "به بات پیام ناشناس بنیاد شهید پالیزوانی(ره) خوش اومدی.\n\n"
    "هر پیامی که برام بفرستی، کاملاً ناشناس برای مدیران کانال ارسال می‌شه.\n"
    "توی بخش زیر میتونی برای خودت نام مستعار انتخاب کنی "
    "و اگر مایل نیستی میتونی «ناشناس بمونم» رو انتخاب کنی."
)


def normalize_phone(phone: str) -> str:
    """فقط رقم‌ها رو نگه می‌داره و ۱۰ رقم آخر رو برمی‌گردونه، تا فرمت‌های
    مختلف یک شماره (+98912...، 0098912...، 0912...) با هم برابر مقایسه بشن."""
    digits = re.sub(r"\D", "", phone or "")
    return digits[-10:] if len(digits) >= 10 else digits


def miniapp_url() -> str:
    return f"{config.BASE_URL}/miniapp"


def open_miniapp_keyboard():
    return bale_api.mini_app_button("🛠 باز کردن پنل مدیریت", miniapp_url())


def nickname_choice_keyboard():
    return bale_api.inline_keyboard([
        [{"text": "✏️ انتخاب نام مستعار", "callback_data": "set_nick"}],
        [{"text": "👤 ناشناس بمونم", "callback_data": "skip_nick"}],
    ])


def ready_to_send_text(label: str) -> str:
    """پیامی که بعد از انتخاب/رد نام مستعار و مشخص‌شدن واحد نشون داده می‌شه."""
    return f"{label} عزیز حالا می‌تونی پیامت رو برام ارسال کنی تا من به‌صورت ناشناس به مدیران کانال منتقلش کنم."


def change_unit_keyboard():
    return bale_api.inline_keyboard([[{"text": "🔄 تغییر واحد", "callback_data": "change_unit"}]])


def maybe_change_unit_keyboard() -> dict | None:
    """دکمه‌ی «تغییر واحد» فقط وقتی معنا داره که بیش از یک واحد وجود داشته باشه."""
    if len(db.list_units()) > 1:
        return change_unit_keyboard()
    return None


# --------------------------------------------------------------------------
# عضویت اجباری در کانال‌ها - قبل از پردازش هر پیام (چه کاربر عادی چه ادمین)
# --------------------------------------------------------------------------
def get_missing_channels(user_id: int) -> list[dict]:
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
# پیام‌های سیستمی (مثل تغییر نام مستعار) که در گفتگوی کاربر برای مدیر ثبت می‌شن
# --------------------------------------------------------------------------
def log_nickname_change(chat_id: int, unit_id: int, user_before: dict,
                         old_nickname: str | None, new_nickname: str | None):
    old_label = old_nickname or db.default_nickname(user_before)
    new_label = new_nickname or db.default_nickname(user_before)
    if old_label == new_label:
        return
    db.add_message(
        chat_id, unit_id, None,
        f"🔄 کاربر نام مستعارش رو از «{old_label}» به «{new_label}» تغییر داد.",
        direction="system",
    )


# --------------------------------------------------------------------------
# انتخاب واحد - قبل از اینکه کاربر عادی بتونه پیام بده باید یه واحد انتخاب کنه
# --------------------------------------------------------------------------
def unit_choice_keyboard(units: list[dict]) -> dict:
    rows = [[{"text": u["name"], "callback_data": f"unit:{u['id']}"}] for u in units]
    return bale_api.inline_keyboard(rows)


def prompt_unit_selection_or_ready(chat_id: int, user: dict):
    """بعد از حل‌شدن نام مستعار صدا زده می‌شه: اگه کاربر واحد فعال داره،
    پیام آماده‌ی ارسال رو نشون می‌ده؛ وگرنه لیست واحدها رو برای انتخاب می‌فرسته
    (مگر اینکه فقط یک واحد وجود داشته باشه که در اون صورت خودکار انتخاب می‌شه)."""
    if user["active_unit_id"] is not None:
        unit = db.get_unit(user["active_unit_id"])
        if unit is not None:
            label = db.display_name(user)
            bale_api.send_message(
                chat_id, ready_to_send_text(label) + f"\n\n(واحد فعلی: {unit['name']})",
                reply_markup=maybe_change_unit_keyboard(),
            )
            return

    units = db.list_units()
    if not units:
        bale_api.send_message(chat_id, "فعلاً واحدی برای گفتگو تعریف نشده. لطفاً بعداً دوباره امتحان کن.")
        return
    if len(units) == 1:
        handle_unit_selected(chat_id, user, units[0]["id"])
        return
    bale_api.send_message(chat_id, "لطفاً واحد مورد نظرت رو انتخاب کن:", reply_markup=unit_choice_keyboard(units))


def handle_unit_selected(chat_id: int, user: dict, unit_id: int):
    unit = db.get_unit(unit_id)
    if unit is None:
        bale_api.send_message(chat_id, "این واحد دیگه در دسترس نیست، یکی دیگه رو انتخاب کن:",
                               reply_markup=unit_choice_keyboard(db.list_units()))
        return
    db.set_active_unit(chat_id, unit_id)
    label = db.display_name(user)
    bale_api.send_message(
        chat_id,
        f"به واحد «{unit['name']}» وصل شدی.\n" + ready_to_send_text(label),
        reply_markup=maybe_change_unit_keyboard(),
    )


# --------------------------------------------------------------------------
# فوروارد پیام کاربر عادی به مدیرهای واحد + مالک‌ها
# --------------------------------------------------------------------------
def forward_to_unit(sender_chat_id: int, user: dict, unit: dict, text: str, origin_message_id: int | None):
    db_message_id = db.add_message(
        sender_chat_id, unit["id"], user["nickname"], text,
        direction="in", origin_message_id=origin_message_id,
    )
    display = db.display_name(user)
    recipients = set(db.list_admin_chat_ids_for_unit(unit["id"])) | set(db.list_owner_chat_ids())
    if not recipients:
        bale_api.send_message(sender_chat_id, "پیامت دریافت شد، ولی فعلاً مدیری برای این واحد ثبت نشده.")
        return
    for admin_id in recipients:
        result = bale_api.send_message(
            admin_id,
            f"📨 پیام جدید از «{display}» (واحد: {unit['name']}):\n\n{text}\n\n"
            f"برای پاسخ ناشناس، روی همین پیام ریپلای بزن.",
        )
        forwarded_msg = (result.get("result") or {})
        forwarded_id = forwarded_msg.get("message_id")
        if forwarded_id:
            db.save_reply_map(admin_id, forwarded_id, sender_chat_id, db_message_id)
    bale_api.send_message(sender_chat_id, "پیامت ارسال شد ✅")


def send_reply_to_user(unit: dict, target_chat_id: int, admin_chat_id: int, text: str,
                        reply_to_message: dict | None) -> int:
    """پاسخ مدیر/مالک رو به کاربر می‌فرسته (به‌صورت ریپلای واقعی روی پیام اصلی، اگه
    مشخص شده باشه)، و رکورد پیام رو در دیتابیس ثبت می‌کنه. آی‌دی پیام جدید رو برمی‌گردونه."""
    reply_to_id = reply_to_message["id"] if reply_to_message else None
    reply_preview = (reply_to_message["text"][:80] if reply_to_message else None)
    origin_reply_to = reply_to_message["origin_message_id"] if reply_to_message else None

    full_text = f"📩 پاسخ از واحد {unit['name']}:\n{text}"
    result = bale_api.send_message(target_chat_id, full_text, reply_to_message_id=origin_reply_to)
    origin_message_id = (result.get("result") or {}).get("message_id")

    return db.add_message(
        target_chat_id, unit["id"], None, text, direction="out",
        admin_chat_id=admin_chat_id, origin_message_id=origin_message_id,
        reply_to_id=reply_to_id, reply_preview=reply_preview,
    )


# --------------------------------------------------------------------------
# پردازش پیام‌های ورودی از وبهوک
# --------------------------------------------------------------------------
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

    # عضویت اجباری: قبل از پردازش هر پیام چک می‌شه
    missing = get_missing_channels(chat_id)
    if missing:
        send_join_prompt(chat_id, missing)
        return

    # اشتراک‌گذاری مخاطب (شماره تلفن) - هم برای احراز مالک، هم ثبت شماره‌ی مدیر
    contact = message.get("contact")
    if contact and contact.get("phone_number"):
        return handle_contact_shared(chat_id, user, contact["phone_number"])

    if text.startswith("/start"):
        parts = text.split(maxsplit=1)
        payload = parts[1].strip() if len(parts) > 1 else ""
        return handle_start(chat_id, user, payload)

    if text == "/owner":
        return handle_owner_command(chat_id, user)

    if text == "/unit":
        if user["is_admin"] or user["is_owner"]:
            return  # واحد فقط برای کاربر عادی معناداره
        if len(db.list_units()) <= 1:
            bale_api.send_message(chat_id, "فعلاً فقط یک واحد تعریف شده، امکان تغییر واحد وجود نداره.")
            return
        db.set_active_unit(chat_id, None)
        return prompt_unit_selection_or_ready(chat_id, db.get_or_create_user(chat_id))

    if text == "/nickname":
        db.set_awaiting_nick(chat_id, True)
        bale_api.send_message(chat_id, "نام مستعار جدیدت رو بنویس:")
        return

    if user["awaiting_nick"]:
        nickname = text[:32] if text else None
        old_nickname = db.set_nickname(chat_id, nickname)
        user = db.get_or_create_user(chat_id)
        if user["active_unit_id"]:
            log_nickname_change(chat_id, user["active_unit_id"], user, old_nickname, nickname)
        label = nickname or db.default_nickname(user)
        bale_api.send_message(chat_id, f"نام مستعارت ثبت شد: «{label}» ✅")
        prompt_unit_selection_or_ready(chat_id, user)
        return

    if not text:
        return  # فعلاً فقط پیام متنی رو پشتیبانی می‌کنیم

    # مدیر/مالک: اگر داره به یه پیام فورواردشده ریپلای می‌کنه => پاسخ ناشناس به فرستنده
    reply_to = message.get("reply_to_message")
    if (user["is_admin"] or user["is_owner"]) and reply_to:
        return handle_admin_reply_in_chat(chat_id, reply_to, text)

    if user["is_admin"] or user["is_owner"]:
        # پیام معمولی (بدون ریپلای) از مدیر/مالک - به‌عنوان پیام ناشناس کاربر تلقی نمی‌شه
        bale_api.send_message(
            chat_id,
            "برای پاسخ به یک پیام، روی همون پیام ریپلای بزن، یا از پنل مدیریت استفاده کن.",
            reply_markup=open_miniapp_keyboard(),
        )
        return

    # کاربر عادی: باید قبلاً یه واحد انتخاب کرده باشه
    if user["active_unit_id"] is None:
        prompt_unit_selection_or_ready(chat_id, user)
        return
    unit = db.get_unit(user["active_unit_id"])
    if unit is None:
        prompt_unit_selection_or_ready(chat_id, user)
        return

    forward_to_unit(chat_id, user, unit, text, message.get("message_id"))


def handle_contact_shared(chat_id: int, user: dict, phone: str):
    if user["awaiting_owner_verify"]:
        db.set_awaiting_owner_verify(chat_id, False)
        if config.OWNER_PHONE and normalize_phone(phone) == normalize_phone(config.OWNER_PHONE):
            db.set_owner(chat_id, True)
            db.set_phone(chat_id, phone)
            bale_api.send_message(chat_id, "✅ مالکیت تایید شد. خوش اومدی!", reply_markup=bale_api.remove_keyboard())
            bale_api.send_message(chat_id, "پنل مدیریت:", reply_markup=open_miniapp_keyboard())
        else:
            bale_api.send_message(
                chat_id, "❌ این شماره با شماره‌ی ثبت‌شده‌ی مالک مطابقت نداره.",
                reply_markup=bale_api.remove_keyboard(),
            )
        return

    if user["awaiting_admin_request"]:
        db.set_awaiting_admin_request(chat_id, False)
        db.set_phone(chat_id, phone)
        register_admin_request(chat_id, db.get_or_create_user(chat_id))
        return

    db.set_phone(chat_id, phone)
    bale_api.send_message(chat_id, "شماره‌ت با موفقیت ثبت شد ✅", reply_markup=bale_api.remove_keyboard())


def handle_admin_reply_in_chat(admin_chat_id: int, reply_to: dict, text: str):
    forwarded_id = reply_to.get("message_id")
    target = db.get_reply_target(admin_chat_id, forwarded_id) if forwarded_id else None
    if not target:
        bale_api.send_message(admin_chat_id, "برای پاسخ، لطفاً روی همون پیام فوروارد شده ریپلای بزن.")
        return

    original = db.get_message(target["message_id"])
    if original is None:
        bale_api.send_message(admin_chat_id, "این پیام دیگه در دسترس نیست (احتمالاً حذف شده).")
        return
    unit = db.get_unit(original["unit_id"])
    if unit is None:
        bale_api.send_message(admin_chat_id, "واحد مربوط به این گفتگو دیگه وجود نداره.")
        return

    send_reply_to_user(unit, target["sender_chat_id"], admin_chat_id, text, reply_to_message=original)
    bale_api.send_message(admin_chat_id, "پاسخت ارسال شد ✅")


def handle_start(chat_id: int, user: dict, payload: str):
    if payload and payload == config.ADMIN_START_TOKEN:
        return handle_admin_request(chat_id, user)

    bale_api.send_message(chat_id, WELCOME_TEXT, reply_markup=nickname_choice_keyboard())


def handle_admin_request(chat_id: int, user: dict):
    if user["is_admin"] or user["is_owner"]:
        bale_api.send_message(chat_id, "شما همین الان هم به پنل مدیریت دسترسی دارید.",
                               reply_markup=open_miniapp_keyboard())
        return
    if db.has_pending_request(chat_id):
        bale_api.send_message(chat_id, "درخواست مدیر شدنت قبلاً ثبت شده و منتظر تایید مالکه.")
        return

    db.set_awaiting_admin_request(chat_id, True)
    bale_api.send_message(
        chat_id,
        "برای ثبت درخواست مدیر شدن، لطفاً اول شماره تلفنت رو با دکمه‌ی زیر بفرست:",
        reply_markup=bale_api.contact_request_keyboard("📱 ارسال شماره و ثبت درخواست"),
    )


def register_admin_request(chat_id: int, user: dict):
    """بعد از دریافت شماره تلفن صدا زده می‌شه: همین‌جا درخواست واقعاً ثبت و به مالک اطلاع داده می‌شه."""
    db.create_admin_request(chat_id)
    bale_api.send_message(chat_id, "✅ درخواستت برای مدیر شدن ثبت شد و برای مالک ارسال شد. به‌محض تایید بهت خبر می‌دیم.",
                           reply_markup=bale_api.remove_keyboard())

    display = db.display_name(user)
    for owner_id in db.list_owner_chat_ids():
        bale_api.send_message(
            owner_id,
            f"🙋 درخواست مدیر شدن جدید از «{display}».\nبرای بررسی، پنل مدیریت رو باز کن.",
            reply_markup=open_miniapp_keyboard(),
        )


def handle_owner_command(chat_id: int, user: dict):
    if user["is_owner"]:
        bale_api.send_message(chat_id, "شما همین الان هم مالک هستید.", reply_markup=open_miniapp_keyboard())
        return
    if not config.OWNER_PHONE:
        bale_api.send_message(chat_id, "شماره‌ی مالک در تنظیمات سرور مشخص نشده.")
        return
    db.set_awaiting_owner_verify(chat_id, True)
    bale_api.send_message(
        chat_id, "برای تایید مالکیت، شماره‌ت رو با دکمه‌ی زیر بفرست:",
        reply_markup=bale_api.contact_request_keyboard("📱 تایید مالکیت با شماره تلفن"),
    )


# --------------------------------------------------------------------------
# پردازش کال‌بک‌های دکمه‌های شیشه‌ای
# --------------------------------------------------------------------------
def handle_callback(callback_query: dict):
    cq_id = callback_query.get("id")
    data = callback_query.get("data") or ""
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

    # از اینجا به بعد هم عضویت رو چک می‌کنیم
    missing = get_missing_channels(chat_id)
    if missing:
        bale_api.answer_callback_query(cq_id)
        send_join_prompt(chat_id, missing)
        return

    if data == "set_nick":
        db.set_awaiting_nick(chat_id, True)
        bale_api.send_message(chat_id, "نام مستعارت رو بنویس:")

    elif data == "skip_nick":
        old_nickname = db.set_nickname(chat_id, None)
        user = db.get_or_create_user(chat_id)
        if user["active_unit_id"]:
            log_nickname_change(chat_id, user["active_unit_id"], user, old_nickname, None)
        label = db.default_nickname(user)
        bale_api.send_message(chat_id, f"باشه، پیام‌هات به‌صورت «{label}» ارسال می‌شن.")
        prompt_unit_selection_or_ready(chat_id, user)

    elif data == "change_unit":
        if len(db.list_units()) <= 1:
            bale_api.send_message(chat_id, "فعلاً فقط یک واحد تعریف شده، امکان تغییر واحد وجود نداره.")
        else:
            db.set_active_unit(chat_id, None)
            prompt_unit_selection_or_ready(chat_id, db.get_or_create_user(chat_id))

    elif data.startswith("unit:"):
        try:
            unit_id = int(data.split(":", 1)[1])
        except ValueError:
            unit_id = None
        if unit_id is not None:
            handle_unit_selected(chat_id, user, unit_id)

    bale_api.answer_callback_query(cq_id)
