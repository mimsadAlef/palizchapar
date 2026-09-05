// -----------------------------------------------------------------------
// نکته: این فایل بر اساس شیء window.Bale.WebApp نوشته شده که با اسکریپت
// https://tapi.bale.ai/miniapp.js ساخته می‌شه و از الگوی WebApp تلگرام
// پیروی می‌کنه. نام دقیق بعضی متدها (مثل requestContact) رو قبل از
// انتشار نهایی با آخرین نسخه‌ی مستندات docs.bale.ai/miniapp چک کن.
//
// این مینی‌اپ فقط برای ادمین بات قابل استفاده‌ست؛ اگه کاربر عادی بازش کنه
// پیام "فقط برای مدیر" رو می‌بینه (سمت بک‌اند هم همین رو enforce می‌کنه).
// -----------------------------------------------------------------------

const WebApp = (window.Bale && window.Bale.WebApp) || null;

function getInitData() {
  if (WebApp && WebApp.initData) return WebApp.initData;
  if (window.__DEV_MODE__) {
    // فقط برای تست لوکال بدون اپ واقعی بله
    let id = localStorage.getItem("debug_chat_id");
    if (!id) {
      id = prompt("حالت توسعه: chat_id عددیِ یک ادمین رو وارد کن") || "111111";
      localStorage.setItem("debug_chat_id", id);
    }
    return `debug:${id}`;
  }
  return "";
}

async function api(path, body) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ initData: getInitData(), ...body }),
  });
  return res.json();
}

const el = (id) => document.getElementById(id);

function showOnly(id) {
  ["loading", "unauthorized", "phone-step", "admin-view"].forEach((x) => {
    el(x).classList.toggle("hidden", x !== id);
  });
}

function showJoinAlert(missing) {
  const lines = (missing || []).map((c) => `• ${c.title}: ${c.url}`).join("\n");
  alert("برای ادامه، اول باید توی این کانال‌ها عضو بشی و بعد دوباره تلاش کنی:\n\n" + lines);
}

let profile = null;

async function boot() {
  if (WebApp) {
    try { WebApp.ready(); } catch (e) {}
    try { WebApp.expand(); } catch (e) {}
  }

  const auth = await api("/api/auth", {});
  if (!auth.ok) {
    if (auth.error === "admin_only") {
      showOnly("unauthorized");
    } else {
      el("loading").textContent = "خطا در احراز هویت. لطفاً دوباره از داخل بله باز کن.";
    }
    return;
  }
  profile = auth;

  if (!profile.phone) {
    showOnly("phone-step");
    return;
  }

  showOnly("admin-view");
  loadAdminThreads();
}

// ---------------- دریافت شماره تلفن ادمین ----------------
el("share-phone-btn").addEventListener("click", async () => {
  if (!WebApp) {
    alert("این دکمه فقط داخل اپلیکیشن بله کار می‌کنه.");
    return;
  }
  try {
    if (typeof WebApp.requestContact === "function") {
      const result = await WebApp.requestContact();
      const phone = result?.contact?.phone_number || result?.phone_number;
      if (phone) return submitPhone(phone);
    }
    if (typeof WebApp.requestPhoneNumber === "function") {
      const result = await WebApp.requestPhoneNumber();
      const phone = result?.phone_number || result;
      if (phone) return submitPhone(phone);
    }
    alert("نتونستیم شماره رو خودکار بگیریم. لطفاً از چت بات، شماره‌ت رو با دکمه‌ی اشتراک مخاطب بفرست و دوباره پنل رو باز کن.");
  } catch (e) {
    console.error(e);
    alert("درخواست لغو شد یا با خطا مواجه شد.");
  }
});

async function submitPhone(phone) {
  const r = await api("/api/phone", { phone });
  if (r.ok) boot();
}

// ---------------- پنل ادمین ----------------
let currentTarget = null;
let currentBlocked = false;

function renderMessage(container, m) {
  if (m.direction === "system") {
    const div = document.createElement("div");
    div.className = "system-note";
    div.textContent = m.text;
    container.appendChild(div);
    return;
  }
  const div = document.createElement("div");
  div.className = "bubble " + (m.direction === "out" ? "me" : "other");
  div.textContent = m.text;
  container.appendChild(div);
}

function escapeHtml(str) {
  const d = document.createElement("div");
  d.textContent = str;
  return d.innerHTML;
}

async function loadAdminThreads() {
  const r = await api("/api/messages", {});
  if (!r.ok) return;
  const box = el("thread-list");
  box.innerHTML = "";
  r.threads.forEach((t) => {
    const label = t.nickname ? escapeHtml(t.nickname) : `ناشناس ${escapeHtml(t.uuid)}`;
    const div = document.createElement("div");
    div.className = "thread-item";
    div.innerHTML = `<div class="name">${label} ${t.is_blocked ? '<span class="blocked-badge">مسدود</span>' : ""}</div>
                      <div class="preview">${escapeHtml(t.last_text || "")}</div>`;
    div.addEventListener("click", () => openThread(t.sender_chat_id, label, t.is_blocked));
    box.appendChild(div);
  });
  el("thread-list").classList.remove("hidden");
  el("thread-detail").classList.add("hidden");
}

function updateBlockBtn() {
  const btn = el("block-btn");
  btn.textContent = currentBlocked ? "رفع مسدودی" : "مسدود کردن";
  btn.classList.toggle("active", currentBlocked);
}

async function openThread(chatId, label, isBlocked) {
  currentTarget = chatId;
  currentBlocked = !!isBlocked;
  el("thread-title").textContent = label;
  updateBlockBtn();
  el("thread-list").classList.add("hidden");
  el("thread-detail").classList.remove("hidden");
  await refreshThread();
}

async function refreshThread() {
  const r = await api("/api/thread", { target_chat_id: currentTarget });
  if (!r.ok) return;
  const box = el("admin-messages");
  box.innerHTML = "";
  r.messages.forEach((m) => renderMessage(box, m));
  box.scrollTop = box.scrollHeight;
}

el("back-btn").addEventListener("click", () => {
  currentTarget = null;
  loadAdminThreads();
});

el("block-btn").addEventListener("click", async () => {
  if (!currentTarget) return;
  const newState = !currentBlocked;
  const r = await api("/api/block", { target_chat_id: currentTarget, blocked: newState });
  if (r.ok) {
    currentBlocked = r.blocked;
    updateBlockBtn();
  }
});

el("delete-btn").addEventListener("click", async () => {
  if (!currentTarget) return;
  if (!confirm("مطمئنی می‌خوای کل گفتگوی این کاربر حذف بشه؟ این کار قابل بازگشت نیست.")) return;
  const r = await api("/api/delete_thread", { target_chat_id: currentTarget });
  if (r.ok) {
    currentTarget = null;
    loadAdminThreads();
  }
});

el("admin-send-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const input = el("admin-text-input");
  const text = input.value.trim();
  if (!text || !currentTarget) return;
  input.value = "";
  const r = await api("/api/send", { text, target_chat_id: currentTarget });
  if (r.ok) {
    refreshThread();
  } else if (r.error === "not_member") {
    showJoinAlert(r.missing);
  }
});

boot();
