// -----------------------------------------------------------------------
// نکته: بر اساس window.Bale.WebApp (اسکریپت https://tapi.bale.ai/miniapp.js)
// که از الگوی WebApp تلگرام پیروی می‌کنه. نام دقیق متد گرفتن شماره تلفن
// (requestContact) رو قبل از انتشار نهایی با آخرین مستندات docs.bale.ai/miniapp چک کن.
// -----------------------------------------------------------------------

const WebApp = (window.Bale && window.Bale.WebApp) || null;

function getInitData() {
  if (WebApp && WebApp.initData) return WebApp.initData;
  if (window.__DEV_MODE__) {
    let id = localStorage.getItem("debug_chat_id");
    if (!id) {
      id = prompt("حالت توسعه: chat_id عددیِ یک مدیر/مالک رو وارد کن") || "111111";
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
    body: JSON.stringify({ initData: getInitData(), ...(body || {}) }),
  });
  return res.json();
}

const el = (id) => document.getElementById(id);

function escapeHtml(str) {
  const d = document.createElement("div");
  d.textContent = str == null ? "" : String(str);
  return d.innerHTML;
}

function showJoinAlert(missing) {
  const lines = (missing || []).map((c) => `• ${c.title}: ${c.url}`).join("\n");
  alert("برای ادامه، اول باید توی این کانال‌ها عضو بشی و بعد دوباره تلاش کنی:\n\n" + lines);
}

// window.confirm() داخل وب‌ویوی مینی‌اپ‌های شبیه بله/تلگرام معمولاً غیرفعاله یا
// همیشه false برمی‌گردونه (بدون نمایش هیچ دیالوگی)، که باعث می‌شه هر اکشنی که
// پشت "if (!confirm(...)) return" باشه عملاً هیچ‌وقت اجرا نشه. به‌جاش این تابع
// اول WebApp.showConfirm (اگه موجود بود) و در غیر این صورت یک دیالوگ داخلیِ
// خودمون رو نشون می‌ده.
function showConfirm(message) {
  return new Promise((resolve) => {
    if (WebApp && typeof WebApp.showConfirm === "function") {
      try {
        WebApp.showConfirm(message, (result) => resolve(!!result));
        return;
      } catch (e) {
        // اگه پرتاب خطا کرد، به دیالوگ داخلی برمی‌گردیم
      }
    }
    const overlay = el("confirm-overlay");
    const yesBtn = el("confirm-yes");
    const noBtn = el("confirm-no");
    el("confirm-message").textContent = message;
    overlay.classList.remove("hidden");

    function cleanup(result) {
      overlay.classList.add("hidden");
      yesBtn.removeEventListener("click", onYes);
      noBtn.removeEventListener("click", onNo);
      resolve(result);
    }
    function onYes() { cleanup(true); }
    function onNo() { cleanup(false); }
    yesBtn.addEventListener("click", onYes);
    noBtn.addEventListener("click", onNo);
  });
}

function showOnly(id) {
  ["loading", "unauthorized", "phone-step", "main-view"].forEach((x) => {
    el(x).classList.toggle("hidden", x !== id);
  });
}

let profile = null;

// --------------------------------------------------------------------------
// بوت
// --------------------------------------------------------------------------
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

  showOnly("main-view");
  setupMainView();
}

// --------------------------------------------------------------------------
// دریافت شماره تلفن
// --------------------------------------------------------------------------
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
    alert("نتونستیم شماره رو خودکار بگیریم. از چت بات، شماره‌ت رو با دکمه‌ی اشتراک مخاطب بفرست و دوباره پنل رو باز کن.");
  } catch (e) {
    console.error(e);
    alert("درخواست لغو شد یا با خطا مواجه شد.");
  }
});

async function submitPhone(phone) {
  const r = await api("/api/phone", { phone });
  if (r.ok) boot();
}

// --------------------------------------------------------------------------
// تب‌ها
// --------------------------------------------------------------------------
const TAB_DEFS = [
  { id: "threads", label: "گفتگوها", ownerOnly: false },
  { id: "requests", label: "درخواست‌ها", ownerOnly: true },
  { id: "admins", label: "مدیران", ownerOnly: true },
  { id: "units", label: "واحدها", ownerOnly: true },
];

let activeTab = "threads";

function setupMainView() {
  el("role-badge").textContent = profile.is_owner ? "👑 مالک" : "🛠 مدیر";
  el("resign-btn").classList.toggle("hidden", !(profile.is_admin && !profile.is_owner));

  const tabsBox = el("tabs");
  tabsBox.innerHTML = "";
  TAB_DEFS.forEach((t) => {
    if (t.ownerOnly && !profile.is_owner) return;
    const btn = document.createElement("button");
    btn.className = "tab-btn" + (t.id === activeTab ? " active" : "");
    btn.textContent = t.label;
    btn.addEventListener("click", () => switchTab(t.id));
    tabsBox.appendChild(btn);
  });

  switchTab("threads");
}

function switchTab(tabId) {
  activeTab = tabId;
  TAB_DEFS.forEach((t) => {
    el(`tab-${t.id}`).classList.toggle("hidden", t.id !== tabId);
  });
  const visibleTabs = TAB_DEFS.filter((t) => !t.ownerOnly || profile.is_owner);
  [...el("tabs").children].forEach((btn, i) => {
    btn.classList.toggle("active", visibleTabs[i] && visibleTabs[i].id === tabId);
  });

  if (tabId === "threads") loadThreads();
  else if (tabId === "requests") loadRequests();
  else if (tabId === "admins") loadAdmins();
  else if (tabId === "units") loadUnits();
}

el("resign-btn").addEventListener("click", async () => {
  if (!(await showConfirm("مطمئنی می‌خوای از مدیریت انصراف بدی؟ برای مدیر شدن دوباره، نیاز به تایید مجدد مالک داری."))) return;
  const r = await api("/api/resign", {});
  if (r.ok) location.reload();
});

// --------------------------------------------------------------------------
// تب گفتگوها
// --------------------------------------------------------------------------
let currentTarget = null;
let currentUnitId = null;
let currentBlocked = false;
let currentReplyTo = null; // {id, preview}
let myUnitCount = 1;

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
  if (m.reply_preview) {
    const q = document.createElement("span");
    q.className = "quote";
    q.textContent = m.reply_preview;
    div.appendChild(q);
  }
  const body = document.createElement("span");
  body.textContent = m.text;
  div.appendChild(body);
  div.addEventListener("click", () => setReplyTarget(m));
  container.appendChild(div);
}

function setReplyTarget(m) {
  if (m.direction === "system") return;
  currentReplyTo = { id: m.id, preview: m.text.slice(0, 80) };
  el("reply-preview-text").textContent = "پاسخ به: " + currentReplyTo.preview;
  el("reply-preview-bar").classList.remove("hidden");
  el("admin-text-input").focus();
}

el("cancel-reply-btn").addEventListener("click", () => {
  currentReplyTo = null;
  el("reply-preview-bar").classList.add("hidden");
});

async function loadThreads() {
  const r = await api("/api/messages", {});
  if (!r.ok) return;
  myUnitCount = r.my_unit_count || 1;
  const box = el("thread-list");
  box.innerHTML = "";
  if (r.threads.length === 0) {
    box.innerHTML = '<div class="empty-hint">هنوز گفتگویی ثبت نشده.</div>';
  }
  r.threads.forEach((t) => {
    const label = t.nickname ? escapeHtml(t.nickname) : `ناشناس ${escapeHtml(t.uuid)}`;
    const unitBadge = myUnitCount > 1 ? `<span class="unit-badge">${escapeHtml(t.unit_name)}</span>` : "";
    const div = document.createElement("div");
    div.className = "thread-item";
    div.innerHTML = `<div class="name">${label} ${unitBadge} ${t.is_blocked ? '<span class="blocked-badge">مسدود</span>' : ""}</div>
                      <div class="preview">${escapeHtml(t.last_text || "")}</div>`;
    div.addEventListener("click", () => openThread(t.sender_chat_id, t.unit_id, label, t.is_blocked, t.unit_name));
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

async function openThread(chatId, unitId, label, isBlocked, unitName) {
  currentTarget = chatId;
  currentUnitId = unitId;
  currentBlocked = !!isBlocked;
  currentReplyTo = null;
  el("reply-preview-bar").classList.add("hidden");
  el("thread-title").textContent = myUnitCount > 1 ? `${label} — ${unitName}` : label;
  updateBlockBtn();
  el("thread-list").classList.add("hidden");
  el("thread-detail").classList.remove("hidden");
  await refreshThread();
}

async function refreshThread() {
  const r = await api("/api/thread", { target_chat_id: currentTarget, unit_id: currentUnitId });
  if (!r.ok) return;
  const box = el("admin-messages");
  box.innerHTML = "";
  r.messages.forEach((m) => renderMessage(box, m));
  box.scrollTop = box.scrollHeight;
}

el("back-btn").addEventListener("click", () => {
  currentTarget = null;
  currentUnitId = null;
  loadThreads();
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
  if (!(await showConfirm("مطمئنی می‌خوای این گفتگو حذف بشه؟ این کار قابل بازگشت نیست."))) return;
  const r = await api("/api/delete_thread", { target_chat_id: currentTarget, unit_id: currentUnitId });
  if (r.ok) {
    currentTarget = null;
    currentUnitId = null;
    loadThreads();
  } else {
    alert(r.message || "حذف گفتگو با خطا مواجه شد.");
  }
});

el("admin-send-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const input = el("admin-text-input");
  const text = input.value.trim();
  if (!text || !currentTarget) return;
  input.value = "";
  const payload = { text, target_chat_id: currentTarget, unit_id: currentUnitId };
  if (currentReplyTo) payload.reply_to_id = currentReplyTo.id;
  const r = await api("/api/send", payload);
  if (r.ok) {
    currentReplyTo = null;
    el("reply-preview-bar").classList.add("hidden");
    refreshThread();
  } else if (r.error === "not_member") {
    showJoinAlert(r.missing);
  }
});

// --------------------------------------------------------------------------
// تب درخواست‌های مدیریت (فقط مالک)
// --------------------------------------------------------------------------
async function loadRequests() {
  const r = await api("/api/admin_requests/list", {});
  if (!r.ok) return;
  const box = el("requests-list");
  box.innerHTML = "";
  if (r.requests.length === 0) {
    box.innerHTML = '<div class="empty-hint">درخواست در انتظاری وجود نداره.</div>';
    return;
  }
  r.requests.forEach((req) => {
    const label = req.nickname ? escapeHtml(req.nickname) : `ناشناس ${escapeHtml(req.uuid)}`;
    const card = document.createElement("div");
    card.className = "card";
    card.innerHTML = `
      <div class="row"><span class="title">${label}</span></div>
      <div class="meta">${req.phone ? escapeHtml(req.phone) : "بدون شماره"}</div>
      <div class="actions">
        <button class="ok-btn" data-act="approve">✅ تایید</button>
        <button class="danger-btn" data-act="reject">❌ رد</button>
      </div>`;
    card.querySelector('[data-act="approve"]').addEventListener("click", () => decideRequest(req.id, true));
    card.querySelector('[data-act="reject"]').addEventListener("click", () => decideRequest(req.id, false));
    box.appendChild(card);
  });
}

async function decideRequest(requestId, approve) {
  const r = await api("/api/admin_requests/decide", { request_id: requestId, approve });
  if (r.ok) loadRequests();
}

// --------------------------------------------------------------------------
// تب مدیران (فقط مالک)
// --------------------------------------------------------------------------
async function loadAdmins() {
  const r = await api("/api/admins/list", {});
  if (!r.ok) return;
  const box = el("admins-list");
  box.innerHTML = "";
  const units = r.units;
  if (r.admins.length === 0) {
    box.innerHTML = '<div class="empty-hint">هنوز مدیری تایید نشده.</div>';
    return;
  }
  r.admins.forEach((admin) => {
    const label = admin.nickname ? escapeHtml(admin.nickname) : `ناشناس ${escapeHtml(admin.uuid)}`;
    const selected = new Set(admin.units.map((u) => u.id));
    const card = document.createElement("div");
    card.className = "card";
    card.innerHTML = `
      <div class="row"><span class="title">${label}</span></div>
      <div class="meta">${admin.phone ? escapeHtml(admin.phone) : "بدون شماره"}</div>
      <div class="unit-chip-list"></div>
      <div class="actions">
        <button class="primary-btn small-btn" data-act="save">ذخیره واحدها</button>
        <button class="danger-btn" data-act="remove">حذف مدیر</button>
      </div>`;
    const chipList = card.querySelector(".unit-chip-list");
    units.forEach((u) => {
      const chip = document.createElement("span");
      chip.className = "unit-chip" + (selected.has(u.id) ? " selected" : "");
      chip.textContent = u.name;
      chip.dataset.unitId = u.id;
      chip.addEventListener("click", () => chip.classList.toggle("selected"));
      chipList.appendChild(chip);
    });
    card.querySelector('[data-act="save"]').addEventListener("click", async () => {
      const unitIds = [...chipList.querySelectorAll(".unit-chip.selected")].map((c) => parseInt(c.dataset.unitId, 10));
      const res = await api("/api/admins/set_units", { chat_id: admin.chat_id, unit_ids: unitIds });
      if (res.ok) alert("ذخیره شد ✅");
    });
    card.querySelector('[data-act="remove"]').addEventListener("click", async () => {
      if (!(await showConfirm(`مطمئنی می‌خوای «${label}» رو از مدیریت حذف کنی؟`))) return;
      const res = await api("/api/admins/remove", { chat_id: admin.chat_id });
      if (res.ok) loadAdmins();
      else alert("حذف مدیر با خطا مواجه شد.");
    });
    box.appendChild(card);
  });
}

// --------------------------------------------------------------------------
// تب واحدها (فقط مالک)
// --------------------------------------------------------------------------
async function loadUnits() {
  const r = await api("/api/units/list", {});
  if (!r.ok) return;
  const box = el("units-list");
  box.innerHTML = "";
  if (r.units.length === 0) {
    box.innerHTML = '<div class="empty-hint">هنوز واحدی تعریف نشده.</div>';
    return;
  }
  r.units.forEach((u) => {
    const card = document.createElement("div");
    card.className = "card";
    card.innerHTML = `
      <div class="row">
        <span class="title">${escapeHtml(u.name)}</span>
        <button class="danger-btn small-btn" data-act="delete">حذف</button>
      </div>`;
    card.querySelector('[data-act="delete"]').addEventListener("click", async () => {
      if (!(await showConfirm(`مطمئنی می‌خوای واحد «${u.name}» حذف بشه؟`))) return;
      const res = await api("/api/units/delete", { unit_id: u.id });
      if (res.ok) loadUnits();
      else alert(res.message || "این واحد قابل حذف نیست.");
    });
    box.appendChild(card);
  });
}

el("unit-create-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const input = el("unit-name-input");
  const name = input.value.trim();
  if (!name) return;
  const r = await api("/api/units/create", { name });
  if (r.ok) {
    input.value = "";
    loadUnits();
  } else if (r.error === "duplicate_name") {
    alert("واحدی با این نام از قبل وجود داره.");
  }
});

boot();
