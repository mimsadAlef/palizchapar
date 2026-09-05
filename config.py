"""
تنظیمات پروژه - همه چیز از فایل .env یا متغیرهای محیطی خوانده می‌شود.
قبل از اجرا، فایل .env.example را کپی کنید به .env و مقادیر را پر کنید.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# توکن ربات که از @botfather در بله گرفته‌اید
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

# آدرس پایه‌ی API بله (طبق مستندات docs.bale.ai)
API_BASE_URL = os.getenv("API_BASE_URL", "https://tapi.bale.ai/")

# آدرس عمومی (https) سروری که این اپ روی آن دیپلوی شده، بدون / انتهایی
# مثال: https://mybot.example.com
BASE_URL = os.getenv("BASE_URL", "").rstrip("/")

# بخش مخفی مسیر وبهوک، برای جلوگیری از حدس زدن آدرس وبهوک توسط دیگران
WEBHOOK_SECRET_PATH = os.getenv("WEBHOOK_SECRET_PATH", "change-this-secret")

# توکن مخصوص ورود ادمین - وقتی کسی ربات را با
# /start <این توکن>
# استارت کند، به عنوان ادمین ثبت می‌شود. این را محرمانه نگه دارید
# و فقط لینک آن (t.me مانند بله: ble.ir/YOUR_BOT?start=TOKEN) را به ادمین بدهید.
ADMIN_START_TOKEN = os.getenv("ADMIN_START_TOKEN", "change-this-admin-token")

# مسیر فایل دیتابیس (dsn اتصال به PostgreSQL)
# مثال: postgresql://user:password@localhost:5432/dbname
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://bale:bale@localhost:5432/anon_bale_bot")

# پورت اجرای فلَسک (برای اجرای لوکال/توسعه)
PORT = int(os.getenv("PORT", "5000"))

# کانال‌هایی که عضویت در اون‌ها برای استفاده از بات اجباریه (عضویت اجباری)
# username کانال باید دقیقاً همونی باشه که در getChatMember پاس داده می‌شه (با @)
REQUIRED_CHANNELS = [
    {"username": "@sharif_for_iran", "title": "شریف برای ایران"},
    {"username": "@rahbar_ir", "title": "رهبر ایران"},
]
