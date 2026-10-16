/* ═══════════════════════════════════════════════════════════════
   main.js — 装配入口
   启动：GET /api/me（mock 直接注入假用户）→ 初始化 router
   ═══════════════════════════════════════════════════════════════ */
import { MOCK, apiFetch } from "./api.js";
import { store, emit } from "./store.js";
import { initRouter, rerender, isLoggedIn } from "./router.js";

const $ = (s) => document.querySelector(s);
const viewEl = $("#view");
const overlay = $("#login-overlay");

/* ── 顶栏状态胶囊 / 用户名 / workdir ── */
function renderTopbar() {
  $("#topbar-user").textContent = store.currentUser
    ? store.currentUser.username + (store.currentUser.role === "admin" ? " · admin" : "")
    : "—";
  const pill = $("#status-pill");
  pill.dataset.state = store.status;
  pill.querySelector(".pill-text").textContent = store.status;
  $("#workdir-path").textContent = store.workdir || "…";
}

/* ── 登录浮层 ── */
let loginMode = "local";

function showLogin() {
  overlay.hidden = false;
}

function hideLogin() {
  overlay.hidden = true;
}

function setLoginMode(mode) {
  loginMode = mode;
  document.querySelectorAll(".login-tab").forEach((b) =>
    b.classList.toggle("active", b.dataset.mode === mode));
  const local = mode === "local";
  $("#login-field-user").hidden = !local;
  $("#login-token-label").textContent = local ? "访问口令" : "GitLab PAT";
  $("#login-token").placeholder = local ? "自己设定，至少 6 位" : "glpat-…";
  $("#login-field-pass").hidden = !local;
  $("#login-intro").textContent = local
    ? "内网工具：使用管理员分配的账号和口令登录。"
    : "使用 GitLab Personal Access Token（至少 read_api）。令牌仅用于校验。";
}

document.querySelectorAll(".login-tab").forEach((b) =>
  b.addEventListener("click", () => setLoginMode(b.dataset.mode)));

async function doLogin(e) {
  e.preventDefault();
  const errEl = $("#login-err");
  errEl.textContent = "";
  const local = loginMode === "local";
  const body = {
    mode: loginMode,
    username: local ? $("#login-user").value.trim() : "",
    token: $("#login-token").value.trim(),
    password: local ? $("#login-pass").value : "",
  };
  if (local && !body.username) { errEl.textContent = "请输入用户名"; return; }
  if (!body.token && !body.password) { errEl.textContent = local ? "请输入口令" : "请输入 token"; return; }
  try {
    const res = await apiFetch("/api/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok || data.error) { errEl.textContent = data.error || "登录失败"; return; }
    // 兼容两种响应形状：mock {session, user} / 真实后端 UserOut 直接返回
    store.currentUser = data.user || (data.username ? data : null)
      || body.username && { username: body.username, role: "user" };
    hideLogin();
    emit("auth:login", store.currentUser);
    rerender();
  } catch (err) {
    errEl.textContent = err.message || "登录失败";
  }
}

$("#login-form").addEventListener("submit", doLogin);

/* ── 全局登出事件（api.js 401 时 dispatch window CustomEvent）── */
window.addEventListener("rc:logout", () => {
  store.currentUser = null;
  showLogin();
});

/* ── 轮询 /api/status 刷新顶栏胶囊（真实模式）── */
async function pollStatus() {
  if (!isLoggedIn() || MOCK) return;
  try {
    const st = await (await apiFetch("/api/status")).json();
    store.status = (st.jobs || []).length ? "running" : "idle";
    renderTopbar();
  } catch { /* 忽略瞬时错误 */ }
}

/* ── 启动 ── */
async function boot() {
  initRouter(viewEl);
  try {
    const res = await apiFetch("/api/me");
    const data = await res.json();
    if (data.user) {
      store.currentUser = data.user;
      store.authMode = data.auth_mode || "local";
    }
  } catch { /* 401 已由 apiFetch 处理 */ }
  if (isLoggedIn()) {
    try {
      const cfg = await (await apiFetch("/api/config")).json();
      store.workdir = cfg.workdir || "";
    } catch { /* ignore */ }
    hideLogin();
  } else {
    showLogin();
  }
  renderTopbar();
  rerender();
  setInterval(pollStatus, 2000);
}

boot();
