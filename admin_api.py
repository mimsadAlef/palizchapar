"""
APIهای پنل مدیریت (مینی‌اپ) - جدا از app.py و bot.py.
همه‌ی مسیرهای اینجا با initData مینی‌اپ احراز هویت می‌شن، نه با سشن/کوکی.
"""
from flask import Blueprint, request, jsonify

import config
import database as db
import bale_api
import bot
from miniapp_auth import validate_init_data, dev_bypass, extract_chat_id

admin_api = Blueprint("admin_api", __name__)


# --------------------------------------------------------------------------
# احراز هویت initData
# --------------------------------------------------------------------------
def _auth_chat_id(body: dict) -> int | None:
    parsed = validate_init_data(body.get("initData", ""))
    if parsed is None and config.DEV_MODE:
        parsed = dev_bypass(body.get("initData", ""))
    if parsed is None:
        return None
    return extract_chat_id(parsed)


def _auth_panel(body: dict) -> int | None:
    """دسترسی پنل: مالک یا مدیر تاییدشده."""
    chat_id = _auth_chat_id(body)
    if chat_id is None or not db.has_panel_access(chat_id):
        return None
    return chat_id


def _auth_owner(body: dict) -> int | None:
    chat_id = _auth_chat_id(body)
    if chat_id is None or not db.is_owner(chat_id):
        return None
    return chat_id


def _visible_unit_ids(user: dict) -> list[int] | None:
    """None یعنی بدون فیلتر (مالک همه‌چیز رو می‌بینه)."""
    if user["is_owner"]:
        return None
    return [u["id"] for u in db.get_units_for_admin(user["chat_id"])]


# --------------------------------------------------------------------------
# احراز هویت و پروفایل
# --------------------------------------------------------------------------
@admin_api.route("/api/auth", methods=["POST"])
def api_auth():
    body = request.get_json(silent=True) or {}
    chat_id = _auth_chat_id(body)
    if chat_id is None:
        return jsonify({"ok": False, "error": "invalid_init_data"}), 401

    user = db.get_or_create_user(chat_id)
    if not (user["is_admin"] or user["is_owner"]):
        return jsonify({"ok": False, "error": "admin_only"}), 403

    my_units = db.list_units() if user["is_owner"] else db.get_units_for_admin(chat_id)
    return jsonify({
        "ok": True,
        "chat_id": chat_id,
        "phone": user["phone"],
        "is_owner": bool(user["is_owner"]),
        "is_admin": bool(user["is_admin"]),
        "units": my_units,
    })


@admin_api.route("/api/phone", methods=["POST"])
def api_phone():
    body = request.get_json(silent=True) or {}
    chat_id = _auth_panel(body)
    if chat_id is None:
        return jsonify({"ok": False, "error": "forbidden"}), 403

    phone = (body.get("phone") or "").strip()
    if not phone:
        return jsonify({"ok": False, "error": "phone_required"}), 400
    db.set_phone(chat_id, phone)
    return jsonify({"ok": True})


@admin_api.route("/api/resign", methods=["POST"])
def api_resign():
    """مدیر (نه مالک) از مدیریت انصراف می‌ده؛ دوباره مدیر شدنش نیازمند تایید مالکه."""
    body = request.get_json(silent=True) or {}
    chat_id = _auth_chat_id(body)
    if chat_id is None:
        return jsonify({"ok": False, "error": "forbidden"}), 403
    user = db.get_or_create_user(chat_id)
    if not user["is_admin"]:
        return jsonify({"ok": False, "error": "not_admin"}), 403

    db.set_admin(chat_id, False)
    db.clear_admin_units(chat_id)
    return jsonify({"ok": True})


# --------------------------------------------------------------------------
# گفتگوها
# --------------------------------------------------------------------------
@admin_api.route("/api/messages", methods=["POST"])
def api_messages():
    body = request.get_json(silent=True) or {}
    chat_id = _auth_panel(body)
    if chat_id is None:
        return jsonify({"ok": False, "error": "forbidden"}), 403

    user = db.get_or_create_user(chat_id)
    unit_ids = _visible_unit_ids(user)
    my_unit_count = len(db.list_units()) if unit_ids is None else len(unit_ids)
    threads = db.list_threads(unit_ids)
    return jsonify({"ok": True, "threads": threads, "my_unit_count": my_unit_count})


def _can_access_unit(user: dict, unit_id: int) -> bool:
    if user["is_owner"]:
        return True
    return any(u["id"] == unit_id for u in db.get_units_for_admin(user["chat_id"]))


@admin_api.route("/api/thread", methods=["POST"])
def api_thread():
    body = request.get_json(silent=True) or {}
    chat_id = _auth_panel(body)
    if chat_id is None:
        return jsonify({"ok": False, "error": "forbidden"}), 403

    target = body.get("target_chat_id")
    unit_id = body.get("unit_id")
    if target is None or unit_id is None:
        return jsonify({"ok": False, "error": "target_and_unit_required"}), 400

    user = db.get_or_create_user(chat_id)
    unit_id = int(unit_id)
    if not _can_access_unit(user, unit_id):
        return jsonify({"ok": False, "error": "forbidden"}), 403

    thread = db.get_thread(int(target), unit_id)
    return jsonify({"ok": True, "messages": thread})


@admin_api.route("/api/send", methods=["POST"])
def api_send():
    body = request.get_json(silent=True) or {}
    chat_id = _auth_panel(body)
    if chat_id is None:
        return jsonify({"ok": False, "error": "forbidden"}), 403

    missing = bot.get_missing_channels(chat_id)
    if missing:
        return jsonify({
            "ok": False,
            "error": "not_member",
            "missing": [{"username": c["username"], "title": c["title"], "url": bot.channel_url(c)} for c in missing],
        }), 403

    text = (body.get("text") or "").strip()
    target = body.get("target_chat_id")
    unit_id = body.get("unit_id")
    if not text or target is None or unit_id is None:
        return jsonify({"ok": False, "error": "text_target_and_unit_required"}), 400
    target = int(target)
    unit_id = int(unit_id)

    user = db.get_or_create_user(chat_id)
    if not _can_access_unit(user, unit_id):
        return jsonify({"ok": False, "error": "forbidden"}), 403

    unit = db.get_unit(unit_id)
    if unit is None:
        return jsonify({"ok": False, "error": "unit_not_found"}), 404

    reply_to_message = None
    reply_to_id = body.get("reply_to_id")
    if reply_to_id is not None:
        reply_to_message = db.get_message(int(reply_to_id))
        if reply_to_message is None or reply_to_message["sender_chat_id"] != target or reply_to_message["unit_id"] != unit_id:
            return jsonify({"ok": False, "error": "invalid_reply_target"}), 400

    bot.send_reply_to_user(unit, target, chat_id, text, reply_to_message)
    return jsonify({"ok": True})


@admin_api.route("/api/block", methods=["POST"])
def api_block():
    body = request.get_json(silent=True) or {}
    chat_id = _auth_panel(body)
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


@admin_api.route("/api/delete_thread", methods=["POST"])
def api_delete_thread():
    body = request.get_json(silent=True) or {}
    chat_id = _auth_panel(body)
    if chat_id is None:
        return jsonify({"ok": False, "error": "forbidden"}), 403

    target = body.get("target_chat_id")
    unit_id = body.get("unit_id")
    if target is None or unit_id is None:
        return jsonify({"ok": False, "error": "target_and_unit_required"}), 400
    unit_id = int(unit_id)

    user = db.get_or_create_user(chat_id)
    if not _can_access_unit(user, unit_id):
        return jsonify({"ok": False, "error": "forbidden"}), 403

    db.delete_thread(int(target), unit_id)
    return jsonify({"ok": True})


# --------------------------------------------------------------------------
# بخش‌های ویژه‌ی مالک: واحدها، مدیریت مدیرها، تایید درخواست‌ها
# --------------------------------------------------------------------------
@admin_api.route("/api/units/list", methods=["POST"])
def api_units_list():
    body = request.get_json(silent=True) or {}
    chat_id = _auth_owner(body)
    if chat_id is None:
        return jsonify({"ok": False, "error": "forbidden"}), 403
    return jsonify({"ok": True, "units": db.list_units()})


@admin_api.route("/api/units/create", methods=["POST"])
def api_units_create():
    body = request.get_json(silent=True) or {}
    chat_id = _auth_owner(body)
    if chat_id is None:
        return jsonify({"ok": False, "error": "forbidden"}), 403

    name = (body.get("name") or "").strip()[:64]
    if not name:
        return jsonify({"ok": False, "error": "name_required"}), 400
    try:
        unit = db.create_unit(name)
    except Exception:
        return jsonify({"ok": False, "error": "duplicate_name"}), 409
    return jsonify({"ok": True, "unit": unit})


@admin_api.route("/api/units/delete", methods=["POST"])
def api_units_delete():
    body = request.get_json(silent=True) or {}
    chat_id = _auth_owner(body)
    if chat_id is None:
        return jsonify({"ok": False, "error": "forbidden"}), 403

    unit_id = body.get("unit_id")
    if unit_id is None:
        return jsonify({"ok": False, "error": "unit_id_required"}), 400
    ok, error = db.delete_unit(int(unit_id))
    if not ok:
        return jsonify({"ok": False, "error": "has_messages", "message": error}), 409
    return jsonify({"ok": True})


@admin_api.route("/api/admins/list", methods=["POST"])
def api_admins_list():
    body = request.get_json(silent=True) or {}
    chat_id = _auth_owner(body)
    if chat_id is None:
        return jsonify({"ok": False, "error": "forbidden"}), 403
    return jsonify({"ok": True, "admins": db.list_admins_with_units(), "units": db.list_units()})


@admin_api.route("/api/admins/set_units", methods=["POST"])
def api_admins_set_units():
    body = request.get_json(silent=True) or {}
    chat_id = _auth_owner(body)
    if chat_id is None:
        return jsonify({"ok": False, "error": "forbidden"}), 403

    target = body.get("chat_id")
    unit_ids = body.get("unit_ids")
    if target is None or not isinstance(unit_ids, list):
        return jsonify({"ok": False, "error": "chat_id_and_unit_ids_required"}), 400
    if not db.is_admin(int(target)):
        return jsonify({"ok": False, "error": "not_an_admin"}), 400

    db.set_admin_units(int(target), [int(u) for u in unit_ids])
    return jsonify({"ok": True})


@admin_api.route("/api/admins/remove", methods=["POST"])
def api_admins_remove():
    body = request.get_json(silent=True) or {}
    chat_id = _auth_owner(body)
    if chat_id is None:
        return jsonify({"ok": False, "error": "forbidden"}), 403

    target = body.get("chat_id")
    if target is None:
        return jsonify({"ok": False, "error": "chat_id_required"}), 400
    target = int(target)
    db.set_admin(target, False)
    db.clear_admin_units(target)
    bale_api.send_message(target, "دسترسی مدیریتت توسط مالک لغو شد.")
    return jsonify({"ok": True})


@admin_api.route("/api/admin_requests/list", methods=["POST"])
def api_admin_requests_list():
    body = request.get_json(silent=True) or {}
    chat_id = _auth_owner(body)
    if chat_id is None:
        return jsonify({"ok": False, "error": "forbidden"}), 403
    return jsonify({"ok": True, "requests": db.list_pending_requests()})


@admin_api.route("/api/admin_requests/decide", methods=["POST"])
def api_admin_requests_decide():
    body = request.get_json(silent=True) or {}
    chat_id = _auth_owner(body)
    if chat_id is None:
        return jsonify({"ok": False, "error": "forbidden"}), 403

    request_id = body.get("request_id")
    approve = bool(body.get("approve"))
    if request_id is None:
        return jsonify({"ok": False, "error": "request_id_required"}), 400

    req = db.decide_request(int(request_id), approve, chat_id)
    if req is None:
        return jsonify({"ok": False, "error": "request_not_found_or_decided"}), 404

    if approve:
        bale_api.send_message(req["chat_id"], "✅ درخواست مدیر شدنت توسط مالک تایید شد.",
                               reply_markup=bot.open_miniapp_keyboard())
    else:
        bale_api.send_message(req["chat_id"], "❌ درخواست مدیر شدنت توسط مالک رد شد.")
    return jsonify({"ok": True})
