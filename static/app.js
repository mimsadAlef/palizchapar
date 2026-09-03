// -----------------------------------------------------------------------
// نکته: این فایل بر اساس شیء window.Bale.WebApp نوشته شده که با اسکریپت
// https://tapi.bale.ai/miniapp.js ساخته می‌شه و از الگوی WebApp تلگرام
// پیروی می‌کنه. نام دقیق بعضی متدها (مثل requestContact) رو قبل از
// انتشار نهایی با آخرین نسخه‌ی مستندات docs.bale.ai/miniapp چک کن؛
// این فایل چند روش رو به‌صورت fallback امتحان می‌کنه تا مقاوم باشه.
// -----------------------------------------------------------------------

const WebApp = (window.Bale && window.Bale.WebApp) || null;

function getInitData() {
  if (WebApp && WebApp.initData) return WebApp.initData;
  if (window.__DEV_MODE__) {
    // فقط برای تست لوکال بدون اپ واقعی بله
    let id = localStorage.getItem("debug_chat_id");
    if (!id) {
      id = prompt("حالت توسعه: یک chat_id عددی برای تست وارد کن") || "111111";
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
  ["loading", "phone-step", "user-view", "admin-view"].forEach((x) => {
    el(x).classList.toggle("hidden", x !== id);
  });
}

let profile = null;

async function boot() {
  if (WebApp) {
    try { WebApp.ready(); } catch (e) {}
    try { WebApp.expand(); } catch (e) {}
  }

  const auth = await api("/api/auth", {});
  if (!auth.ok) {
    el("loading").textContent = "خطا در احراز هویت. لطفاً دوباره از داخل بله باز کن.";
    return;
  }
  profile = auth;

  // شماره تلفن فقط از کسی که با توکن ادمین وارد شده گرفته می‌شه
  if (profile.is_admin && !profile.phone) {
    showOnly("phone-step");
    return;
  }

  if (profile.is_admin) {
    showOnly("admin-view");
    loadAdminThreads();
  } else {
    showOnly("user-view");
    loadUserMessages();
  }
}

function showJoinAlert(missing) {
  const lines = (missing || []).map((c) => `• ${c.title}: ${c.url}`).join("\n");
  alert("برای ادامه، اول باید توی این کانال‌ها عضو بشی و بعد دوباره تلاش کنی:\n\n" + lines);
}

// ---------------- دریافت شماره تلفن ----------------
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
    alert("نتونستیم شماره رو خودکار بگیریم. لطفاً از چت بات، شماره‌ت رو با دکمه‌ی اشتراک مخاطب بفرست و دوباره مینی‌اپ رو باز کن.");
  } catch (e) {
    console.error(e);
    alert("درخواست لغو شد یا با خطا مواجه شد.");
  }
});

async function submitPhone(phone) {
  const r = await api("/api/phone", { phone });
  if (r.ok) boot();
}

// ---------------- نمای کاربر عادی ----------------
el("nickname-btn").addEventListener("click", async () => {
  const nickname = prompt("نام مستعار جدید (خالی بذار برای ناشناس بودن):", profile.nickname || "");
  if (nickname === null) return;
  const r = await api("/api/nickname", { nickname });
  if (r.ok) profile.nickname = r.nickname;
});

function renderBubble(container, text, isMe) {
  const div = document.createElement("div");
  div.className = "bubble " + (isMe ? "me" : "other");
  div.textContent = text;
  container.appendChild(div);
}

async function loadUserMessages() {
  const r = await api("/api/messages", {});
  if (!r.ok) return;
  const box = el("messages");
  box.innerHTML = "";
  r.messages.forEach((m) => renderBubble(box, m.text, m.direction === "in"));
  box.scrollTop = box.scrollHeight;
}

el("send-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const input = el("text-input");
  const text = input.value.trim();
  if (!text) return;
  input.value = "";
  const r = await api("/api/send", { text });
  if (r.ok) {
    loadUserMessages();
  } else if (r.error === "not_member") {
    showJoinAlert(r.missing);
  }
});

// ---------------- پنل ادمین ----------------
let currentTarget = null;

async function loadAdminThreads() {
  const r = await api("/api/messages", {});
  if (!r.ok) return;
  const box = el("thread-list");
  box.innerHTML = "";
  r.threads.forEach((t) => {
    const div = document.createElement("div");
    div.className = "thread-item";
    div.innerHTML = `<div class="name">${t.nickname ? escapeHtml(t.nickname) : "کاربر ناشناس"}</div>
                      <div class="preview">${escapeHtml(t.last_text || "")}</div>`;
    div.addEventListener("click", () => openThread(t.sender_chat_id, t.nickname));
    box.appendChild(div);
  });
  el("thread-list").classList.remove("hidden");
  el("thread-detail").classList.add("hidden");
}

async function openThread(chatId, nickname) {
  currentTarget = chatId;
  el("thread-list").classList.add("hidden");
  el("thread-detail").classList.remove("hidden");
  await refreshThread();
}

async function refreshThread() {
  const r = await api("/api/thread", { target_chat_id: currentTarget });
  if (!r.ok) return;
  const box = el("admin-messages");
  box.innerHTML = "";
  r.messages.forEach((m) => renderBubble(box, m.text, m.direction === "out"));
  box.scrollTop = box.scrollHeight;
}

el("back-btn").addEventListener("click", () => {
  currentTarget = null;
  loadAdminThreads();
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

function escapeHtml(str) {
  const d = document.createElement("div");
  d.textContent = str;
  return d.innerHTML;
}

boot();
