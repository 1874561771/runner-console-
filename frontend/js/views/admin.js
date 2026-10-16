/* ═══════════════════════════════════════════════════════════════
   #/admin — 管理（T12 实现，仅 admin 角色）
   页签「用户」：用户表（角色徽标/来源/最近登录）+ 设为 admin/用户 + 重置口令（均带确认）
   页签「保留策略」：retain_count / retain_days 数字输入 + 保存（保存即触发清理）
   页签「审计日志」：时间/操作人/action 徽标/detail，「加载更多」分页
   非 admin 访问：显示「需要管理员权限」空态卡。
   ═══════════════════════════════════════════════════════════════ */
import { apiFetch } from "../api.js";
import { store } from "../store.js";
import { esc, toast, confirmDialog, openModal, skeletonRows, emptyState } from "../ui.js";

let viewEl = null;
let tab = "users";
let users = [];
let audit = { items: [], total: 0 };
const AUDIT_PAGE = 20;

export async function render(el) {
  viewEl = el;
  tab = "users";

  if (store.currentUser?.role !== "admin") {
    el.innerHTML = `
      <h1 class="view-title">管理</h1>
      <div class="card"><div class="admin-denied">
        ${emptyState("需要管理员权限", "此页仅对 admin 角色开放，请联系管理员。")}
      </div></div>`;
    return;
  }

  el.innerHTML = `
    <div class="view-head">
      <div>
        <h1 class="view-title">管理</h1>
        <div class="view-sub">用户 · 保留策略 · 审计日志</div>
      </div>
    </div>
    <div class="rc-tabs" role="tablist">
      <button type="button" class="rc-tab active" data-tab="users">用户</button>
      <button type="button" class="rc-tab" data-tab="retention">保留策略</button>
      <button type="button" class="rc-tab" data-tab="audit">审计日志</button>
    </div>
    <div id="admin-body">${skeletonRows(4, 5)}</div>`;

  el.querySelectorAll(".rc-tab").forEach((b) =>
    b.addEventListener("click", () => switchTab(b.dataset.tab)));

  await loadUsers();
}

function switchTab(next) {
  if (tab === next) return;
  tab = next;
  viewEl.querySelectorAll(".rc-tab").forEach((b) =>
    b.classList.toggle("active", b.dataset.tab === tab));
  ({ users: loadUsers, retention: loadRetention, audit: loadAuditFirst })[tab]();
}

/* ═══ 用户 ═════════════════════════════════════════════════ */

async function loadUsers() {
  const body = viewEl.querySelector("#admin-body");
  if (!body) return;
  body.innerHTML = skeletonRows(4, 5);
  try {
    const res = await apiFetch("/api/admin/users");
    users = await res.json();
    if (!res.ok) throw new Error(users.error || "加载失败");
  } catch (err) {
    body.innerHTML = emptyState("用户加载失败", err.message || "请稍后重试");
    return;
  }
  if (!users.length) {
    body.innerHTML = emptyState("还没有用户");
    return;
  }
  body.innerHTML = `
    <div class="user-toolbar" style="display:flex;justify-content:flex-end;margin-bottom:10px">
      <button type="button" class="btn btn-primary btn-sm" id="btn-user-create">＋ 新建用户</button>
    </div>
    <div class="card"><table class="table">
    <thead><tr>
      <th>用户名</th><th>姓名</th><th>角色</th><th>来源</th><th>最近登录</th><th style="text-align:right">操作</th>
    </tr></thead>
    <tbody>${users.map(userRow).join("")}</tbody></table></div>`;
  body.querySelector("#btn-user-create").addEventListener("click", openCreateUser);
  body.querySelectorAll("[data-act]").forEach((btn) =>
    btn.addEventListener("click", () => {
      const u = users.find((x) => x.id === Number(btn.dataset.id));
      if (!u) return;
      ({ role: changeRole, reset: resetPassword })[btn.dataset.act](u);
    }));
}

/* 新建用户（弹层表单；口令留空由服务端生成一次性随机口令） */
function openCreateUser() {
  const m = openModal({
    title: "新建用户",
    body: `
      <div class="field"><label>用户名 <span class="faint">（字母/数字/. _ -，2-40 位）</span></label>
        <input class="input" id="nu-username" maxlength="40" autocomplete="off"/></div>
      <div class="field"><label>姓名（可选）</label>
        <input class="input" id="nu-name" maxlength="40"/></div>
      <div class="field"><label>初始口令 <span class="faint">（留空则自动生成一次性口令）</span></label>
        <input class="input" id="nu-password" type="text" autocomplete="off" placeholder="至少 6 位"/></div>
      <div class="field"><label>角色</label>
        <select class="input" id="nu-role"><option value="user">user</option><option value="admin">admin</option></select></div>`,
    footer: `<button type="button" class="btn btn-ghost" data-act="cancel">取消</button>
             <button type="button" class="btn btn-primary" data-act="ok">创建</button>`,
    width: 440,
  });
  m.root.querySelector('[data-act="cancel"]').addEventListener("click", m.close);
  m.root.querySelector('[data-act="ok"]').addEventListener("click", async () => {
    const body = {
      username: m.root.querySelector("#nu-username").value.trim(),
      name: m.root.querySelector("#nu-name").value.trim() || null,
      password: m.root.querySelector("#nu-password").value || null,
      role: m.root.querySelector("#nu-role").value,
    };
    if (!body.username) { toast("请输入用户名", "error"); return; }
    try {
      const res = await apiFetch("/api/admin/users", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const d = await res.json();
      if (!res.ok || d.error) throw new Error(d.error || "创建失败");
      m.close();
      toast(d.password
        ? `已创建 ${d.username}，一次性口令：${d.password}`
        : `已创建 ${d.username}`);
      loadUsers();
    } catch (err) { toast(err.message || "创建失败", "error"); }
  });
}

function userRow(u) {
  const me = store.currentUser;
  const roleBadge = u.role === "admin"
    ? `<span class="badge running">admin</span>`
    : `<span class="badge">user</span>`;
  const srcBadge = `<span class="badge">${esc(u.source || "local")}</span>`;
  const roleTarget = u.role === "admin" ? "user" : "admin";
  const ops = [
    `<button type="button" class="btn btn-ghost btn-sm" data-act="role" data-id="${u.id}">设为 ${roleTarget}</button>`,
    `<button type="button" class="btn btn-ghost btn-sm" data-act="reset" data-id="${u.id}">重置口令</button>`,
  ];
  if (me && u.id === me.id) ops.length = 0; // 不能改自己
  return `<tr>
    <td class="mono" style="font-weight:600">${esc(u.username)}</td>
    <td>${esc(u.name || "")}</td>
    <td>${roleBadge}</td>
    <td>${srcBadge}</td>
    <td class="mono faint">${esc(u.last_login || "—")}</td>
    <td><div class="row-actions">${ops.join("") || `<span class="faint" style="font-size:12px">当前账号</span>`}</div></td>
  </tr>`;
}

/* 设为 admin / user（带确认） */
async function changeRole(u) {
  const target = u.role === "admin" ? "user" : "admin";
  const ok = await confirmDialog({
    title: "调整角色",
    message: `确定将用户 <b>${esc(u.username)}</b>（${esc(u.name || "")}）设为 <b>${target}</b>？`,
    okText: "确定",
  });
  if (!ok) return;
  try {
    const res = await apiFetch(`/api/admin/users/${u.id}/role`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ role: target }),
    });
    const d = await res.json();
    if (!res.ok || d.error) throw new Error(d.error || "操作失败");
    toast(`${u.username} → ${target}`);
    loadUsers();
  } catch (err) { toast(err.message || "操作失败", "error"); }
}

/* 重置口令（带确认，成功后展示新口令） */
async function resetPassword(u) {
  const ok = await confirmDialog({
    title: "重置口令",
    message: `确定重置 <b>${esc(u.username)}</b> 的口令？<br/>重置后会生成一个一次性新口令，请转告本人。`,
    okText: "重置",
  });
  if (!ok) return;
  try {
    const res = await apiFetch(`/api/admin/users/${u.id}/reset-password`, { method: "POST" });
    const d = await res.json();
    if (!res.ok || d.error) throw new Error(d.error || "重置失败");
    toast(`${u.username} 新口令：${d.password}`);
  } catch (err) { toast(err.message || "重置失败", "error"); }
}

/* ═══ 保留策略 ═════════════════════════════════════════════ */

async function loadRetention() {
  const body = viewEl.querySelector("#admin-body");
  if (!body) return;
  body.innerHTML = skeletonRows(2, 3);
  let r;
  try {
    const res = await apiFetch("/api/admin/settings");
    r = await res.json();
    if (!res.ok || r.error) throw new Error(r.error || "加载失败");
  } catch (err) {
    body.innerHTML = emptyState("保留策略加载失败", err.message || "请稍后重试");
    return;
  }
  body.innerHTML = `<div class="card card-pad" style="max-width:560px">
    <div class="two-col">
      <div class="field"><label>保留份数（0 = 不限制）</label>
        <input class="input" type="number" id="retain-count" min="0" value="${Number(r.retain_count) || 0}"/></div>
      <div class="field"><label>保留天数（0 = 不限制）</label>
        <input class="input" type="number" id="retain-days" min="0" value="${Number(r.retain_days) || 0}"/></div>
    </div>
    <p class="faint" style="font-size:12px;line-height:1.7;margin:0 0 14px">
      只清理 artifacts 下的 run 目录及对应 Job 记录，正在运行的 Job 不会删。
      两项都大于 0 时需同时满足（既在份数内又未过期）。<b>保存后立即按策略清理一次。</b>
    </p>
    <button type="button" class="btn btn-primary" id="btn-retain-save">保存</button>
  </div>`;

  body.querySelector("#btn-retain-save").addEventListener("click", async () => {
    const count = Number(body.querySelector("#retain-count").value) || 0;
    const days = Number(body.querySelector("#retain-days").value) || 0;
    if (count < 0 || days < 0) { toast("不能为负数", "error"); return; }
    try {
      const res = await apiFetch("/api/admin/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ retain_count: count, retain_days: days }),
      });
      const d = await res.json();
      if (!res.ok || d.error) throw new Error(d.error || "保存失败");
      toast(d.cleaned ? `已保存，清理了 ${d.cleaned} 个 run` : "已保存");
    } catch (err) { toast(err.message || "保存失败", "error"); }
  });
}

/* ═══ 审计日志 ═════════════════════════════════════════════ */

async function loadAuditFirst() {
  audit = { items: [], total: 0 };
  await loadAudit(false);
}

async function loadAudit(append = true) {
  const body = viewEl.querySelector("#admin-body");
  if (!body) return;
  if (!append) body.innerHTML = skeletonRows(4, 5);

  /* 追加模式时只刷新「加载更多」按钮状态 */
  const offset = audit.items.length;
  try {
    const res = await apiFetch(`/api/admin/audit?offset=${offset}&limit=${AUDIT_PAGE}`);
    const d = await res.json();
    if (!res.ok || d.error) throw new Error(d.error || "加载失败");
    audit.items = audit.items.concat(d.items || []);
    audit.total = d.total ?? audit.items.length;
  } catch (err) {
    if (!append) body.innerHTML = emptyState("审计日志加载失败", err.message || "请稍后重试");
    else toast(err.message || "加载失败", "error");
    return;
  }

  const all = audit.items.length >= audit.total;
  body.innerHTML = `<div class="card">
    <table class="table">
      <thead><tr><th>时间</th><th>操作人</th><th>动作</th><th>详情</th></tr></thead>
      <tbody>${audit.items.map(auditRow).join("")}</tbody>
    </table>
    ${all ? "" : `<div style="padding:12px;text-align:center;border-top:1px solid var(--line-soft)">
      <button type="button" class="btn btn-ghost" id="btn-audit-more">加载更多（${audit.total - audit.items.length}）</button>
    </div>`}
  </div>`;

  const more = body.querySelector("#btn-audit-more");
  if (more) more.addEventListener("click", () => loadAudit(true));
}

const AUDIT_BADGE = {
  "user.create": "running", "user.role": "warn", "user.reset": "warn", "retain.save": "warn",
  "env.del": "fail", "upload.del": "fail", "lock.release": "fail",
};

function auditRow(a) {
  return `<tr>
    <td class="mono faint" style="white-space:nowrap">${esc(a.created_at || "")}</td>
    <td class="mono">${esc(a.actor || "")}</td>
    <td><span class="badge ${AUDIT_BADGE[a.action] || ""}">${esc(a.action)}</span></td>
    <td class="muted">${esc(a.detail || "")}</td>
  </tr>`;
}
