"""
اعتبارسنجی initData ارسالی از مینی‌اپ بله.

⚠️ نکته‌ی مهم:
مینی‌اپ‌های بله (window.Bale.WebApp که با اسکریپت
https://tapi.bale.ai/miniapp.js ساخته می‌شود) از همان معماریِ WebApp
تلگرام الگو گرفته‌اند. مطابق مستندات docs.bale.ai/miniapp، initData یک
query-string امضا شده است که برای اعتبارسنجی آن (طبق همان الگوریتم
استاندارد WebApp) باید:
  1) secret_key = HMAC_SHA256(key="WebAppData", msg=BOT_TOKEN)
  2) data_check_string = تمام فیلدها (به جز hash) به شکل key=value ،
     مرتب‌شده بر اساس نام کلید، جدا شده با کاراکتر \n
  3) hash محاسبه‌شده = HMAC_SHA256(key=secret_key, msg=data_check_string)
  4) اگر با hash ارسالی برابر بود، داده معتبر است.

پیش از دیپلوی نهایی حتماً این بخش را با آخرین نسخه‌ی مستندات
docs.bale.ai/miniapp مطابقت بدهید، چون ممکن است جزئیات (مثلاً نام دقیق
متدهای JS برای گرفتن initData یا شماره تلفن) در نسخه‌های بعدی تغییر کند.
"""
import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

import config

MAX_AGE_SECONDS = 24 * 60 * 60  # اعتبار initData را حداکثر ۲۴ ساعت در نظر می‌گیریم


def validate_init_data(init_data: str) -> dict | None:
    """اگر initData معتبر بود، دیکشنری پارس‌شده (شامل user) را برمی‌گرداند، وگرنه None."""
    if not init_data:
        return None

    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = pairs.pop("hash", None)
    if not received_hash:
        return None

    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))

    secret_key = hmac.new(b"WebAppData", config.BOT_TOKEN.encode(), hashlib.sha256).digest()
    computed_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(computed_hash, received_hash):
        return None

    auth_date = pairs.get("auth_date")
    if auth_date and (time.time() - int(auth_date)) > MAX_AGE_SECONDS:
        return None

    result = dict(pairs)
    if "user" in result:
        try:
            result["user"] = json.loads(result["user"])
        except (json.JSONDecodeError, TypeError):
            result["user"] = None
    return result


def extract_chat_id(parsed_init_data: dict) -> int | None:
    user = parsed_init_data.get("user")
    if not user:
        return None
    uid = user.get("id")
    return int(uid) if uid is not None else None


# --- حالت توسعه/دیباگ بدون امضای واقعی ---
# در محیط توسعه (وقتی DEV_MODE=1 باشد)، اگر initData به‌جای رشته‌ی امضاشده
# چیزی مثل "debug:123456789" باشد، همان chat_id را برمی‌گرداند تا بتوانید
# مینی‌اپ را بدون نیاز به اپلیکیشن واقعی بله تست کنید.
def dev_bypass(init_data: str) -> dict | None:
    if init_data and init_data.startswith("debug:"):
        chat_id = init_data.split(":", 1)[1]
        return {"user": {"id": int(chat_id)}}
    return None
