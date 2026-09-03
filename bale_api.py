"""
یک لایه‌ی نازک برای صدا زدن متدهای Bot API بله.
مطابق مستندات docs.bale.ai هر متد با یک POST به آدرس زیر صدا زده می‌شود:
https://tapi.bale.ai/bot<TOKEN>/<METHOD_NAME>
"""
import requests
import config


def _url(method: str) -> str:
    return f"{config.API_BASE_URL}bot{config.BOT_TOKEN}/{method}"


def call(method: str, payload: dict | None = None, timeout: int = 15) -> dict:
    """یک متد دلخواه از Bot API بله را صدا می‌زند و JSON پاسخ را برمی‌گرداند."""
    try:
        resp = requests.post(_url(method), json=payload or {}, timeout=timeout)
        data = resp.json()
    except Exception as e:
        return {"ok": False, "error": str(e)}
    if not data.get("ok"):
        # خطا را در لاگ چاپ می‌کنیم تا در توسعه راحت دیباگ شود
        print(f"[bale_api] خطا در متد {method}: {data}")
    return data


def send_message(chat_id: int, text: str, reply_markup: dict | None = None,
                  reply_to_message_id: int | None = None) -> dict:
    payload = {"chat_id": chat_id, "text": text}
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    if reply_to_message_id is not None:
        payload["reply_to_message_id"] = reply_to_message_id
    return call("sendMessage", payload)


def answer_callback_query(callback_query_id: str, text: str | None = None) -> dict:
    payload = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text
    return call("answerCallbackQuery", payload)


def set_webhook(url: str) -> dict:
    return call("setWebhook", {"url": url})


def delete_webhook() -> dict:
    return call("deleteWebhook", {})


def get_me() -> dict:
    return call("getMe", {})


# --- کیبوردهای پرکاربرد ---

def inline_keyboard(rows: list[list[dict]]) -> dict:
    """rows: لیستی از ردیف‌ها، هر ردیف لیستی از دکمه‌هاست.
    هر دکمه یکی از این دو شکل را دارد:
      {"text": "...", "callback_data": "..."}
      {"text": "...", "web_app": {"url": "..."}}
    """
    return {"inline_keyboard": rows}


def contact_request_keyboard(button_text: str = "📱 ارسال شماره تلفن") -> dict:
    """کیبورد پایین صفحه برای درخواست اشتراک‌گذاری شماره تلفن کاربر
    (روش استاندارد و تضمین‌شده در Bot APIهای سبک تلگرام/بله)."""
    return {
        "keyboard": [[{"text": button_text, "request_contact": True}]],
        "resize_keyboard": True,
        "one_time_keyboard": True,
    }


def remove_keyboard() -> dict:
    return {"remove_keyboard": True}


def mini_app_button(text: str, url: str) -> dict:
    return inline_keyboard([[{"text": text, "web_app": {"url": url}}]])
