from flask import Flask, request, jsonify, render_template

import config
import database as db
import bale_api
import bot
from admin_api import admin_api

app = Flask(__name__)
app.register_blueprint(admin_api)

# جدول‌ها/migrationها رو همین‌جا (زمان import شدن ماژول) اجرا می‌کنیم، نه فقط
# داخل if __name__ == "__main__"، چون با gunicorn/uwsgi اون بلوک اجرا نمی‌شه.
db.init_db()


@app.route(f"/webhook/{config.WEBHOOK_SECRET_PATH}", methods=["POST"])
def webhook():
    update = request.get_json(silent=True) or {}
    if "message" in update:
        bot.handle_message(update["message"])
    elif "callback_query" in update:
        bot.handle_callback(update["callback_query"])
    return jsonify({"ok": True})


@app.route("/miniapp")
def miniapp_page():
    return render_template("miniapp.html", dev_mode=config.DEV_MODE)


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
    app.run(host="0.0.0.0", port=config.PORT, debug=config.DEV_MODE)
