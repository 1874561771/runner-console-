/* ═══════════════════════════════════════════════════════════════
   #/resources — 资源（T12 实现）：环境 + 我的上传 合并页
   页签「环境」：环境表（名称/属主/状态/更新时间/操作）+ 新建/编辑弹层
     + 停用/启用（admin）+ 删除（danger 确认）+ 强制释放锁（admin，danger ghost 确认）
   页签「我的上传」：拖拽/选择文件上传（POST /api/uploads，form-data）+ 列表删除
   ═══════════════════════════════════════════════════════════════ */
import { apiFetch } from "../api.js";
import { store } from "../store.js";
import { mountCasePicker } from "../casepicker.js";
import { esc, toast, openModal, confirmDialog, skeletonRows, emptyState } from "../ui.js";

let viewEl = null;
let tab = "envs";
let envs = [];
let uploads = [];
let suites = [];

/* 勾选器 / 套件样式在 console.css 内，本页也注入 */
function ensureCss() {
  if (document.getElementById("rc-console-css")) return;
  const link = document.createElement("link");
  link.id = "rc-console-css";
  link.rel = "stylesheet";
  link.href = "css/console.css";
  document.head.appendChild(link);
}

export async function render(el) {
  viewEl = el;
  tab = "envs";
  ensureCss();
  el.innerHTML = `
    <div class="view-head">
      <div>
        <h1 class="view-title">资源</h1>
        <div class="view-sub">环境、上传的 suite / 脚本、保存的套件</div>
      </div>
      <button type="button" class="btn btn-primary" id="btn-new-env">+ 新建环境</button>
    </div>
    <div class="rc-tabs" role="tablist">
      <button type="button" class="rc-tab active" data-tab="envs">环境</button>
      <button type="button" class="rc-tab" data-tab="uploads">我的上传</button>
      <button type="button" class="rc-tab" data-tab="suites">我的套件</button>
    </div>
    <div id="res-body">${skeletonRows(4, 5)}</div>`;

  el.querySelector("#btn-new-env").addEventListener("click", () => openEnvModal(null));
  el.querySelectorAll(".rc-tab").forEach((b) =>
    b.addEventListener("click", () => switchTab(b.dataset.tab)));

  await loadEnvs();
}

function switchTab(next) {
  if (tab === next) return;
  tab = next;
  viewEl.querySelectorAll(".rc-tab").forEach((b) =>
    b.classList.toggle("active", b.dataset.tab === tab));
  if (tab === "envs") loadEnvs();
  else if (tab === "uploads") loadUploads();
  else loadSuites();
}

/* ═══ 环境 ═════════════════════════════════════════════════ */

async function loadEnvs() {
  const body = viewEl.querySelector("#res-body");
  if (!body) return;
  body.innerHTML = skeletonRows(4, 5);
  try {
    const res = await apiFetch("/api/envs");
    envs = await res.json();
    if (!res.ok) throw new Error(envs.error || "加载失败");
  } catch (err) {
    body.innerHTML = emptyState("环境加载失败", err.message || "请稍后重试");
    return;
  }
  if (!envs.length) {
    body.innerHTML = emptyState("还没有环境", "点击右上角「新建环境」创建第一个环境");
    return;
  }
  body.innerHTML = `<div class="card"><table class="table">
    <thead><tr>
      <th>名称</th><th>属主</th><th>状态</th><th>更新时间</th><th style="text-align:right">操作</th>
    </tr></thead>
    <tbody>${envs.map(envRow).join("")}</tbody></table></div>`;
  wireEnvActions();
}

function envRow(e) {
  const isAdmin = store.currentUser?.role === "admin";
  const locked = e.lock && e.lock.held;
  let status;
  if (e.disabled)      status = `<span class="dot off"></span>停用`;
  else if (locked)     status = `<span class="dot busy"></span>占用`;
  else                 status = `<span class="dot idle"></span>空闲`;

  const lockHint = locked
    ? `<div class="lock-hint">锁 ${esc(e.lock.run_id || "")} · ${esc(e.lock.owner_name || "未知属主")}${e.lock.stale ? " · 残留" : ""}</div>`
    : "";

  const ops = [`<button type="button" class="btn btn-ghost btn-sm" data-act="edit" data-id="${e.id}">编辑</button>`];
  if (isAdmin) ops.push(`<button type="button" class="btn btn-ghost btn-sm" data-act="toggle" data-id="${e.id}">${e.disabled ? "启用" : "停用"}</button>`);
  if (isAdmin && locked) ops.push(`<button type="button" class="btn btn-danger btn-sm" data-act="release" data-id="${e.id}">强制释放</button>`);
  ops.push(`<button type="button" class="btn btn-danger btn-sm" data-act="del" data-id="${e.id}">删除</button>`);

  return `<tr>
    <td><div class="mono" style="font-weight:600">${esc(e.name)}</div>${lockHint}</td>
    <td class="mono">${esc(e.owner_name || "")}</td>
    <td>${status}</td>
    <td class="mono faint">${esc(e.updated_at || "")}</td>
    <td><div class="row-actions">${ops.join("")}</div></td>
  </tr>`;
}

function wireEnvActions() {
  const body = viewEl.querySelector("#res-body");
  body.querySelectorAll('[data-act]').forEach((btn) =>
    btn.addEventListener("click", () => {
      const env = envs.find((x) => x.id === btn.dataset.id);
      if (!env) return;
      ({ edit: openEnvModal, toggle: toggleEnv, release: releaseEnv, del: deleteEnv })[btn.dataset.act](env);
    }));
}

/* 新建 / 编辑弹层 */
function openEnvModal(env) {
  const isEdit = !!env;
  const m = openModal({
    title: isEdit ? "编辑环境" : "新建环境",
    body: `
      <div class="field"><label>名称</label>
        <input class="input mono" id="env-name" value="${isEdit ? esc(env.name) : ""}" placeholder="lab-fbox-12"/></div>
      <div class="field"><label>.firebox_env 内容</label>
        <textarea class="input" id="env-content" placeholder="FIREBOX1_WEBUI_URL=..."></textarea></div>
      <p class="faint" style="font-size:12px;margin:0">密钥按文件保存；编辑时已有密钥会脱敏显示，需修改请整份覆盖粘贴。</p>`,
    footer: `<button type="button" class="btn btn-ghost" data-act="cancel">取消</button>
             <button type="button" class="btn btn-primary" data-act="save">保存</button>`,
  });

  if (isEdit) {
    (async () => {
      try {
        const res = await apiFetch(`/api/envs/${env.id}`);
        const d = await res.json();
        const ta = m.root.querySelector("#env-content");
        if (d.redacted && ta) {
          ta.value = Object.entries(d.redacted).map(([k, v]) => `${k}=${v}`).join("\n")
            + "\n# 上面密钥已脱敏；要改密钥请整份覆盖粘贴";
        }
      } catch { /* 忽略，留空由用户填写 */ }
    })();
  }

  m.root.querySelector('[data-act="cancel"]').addEventListener("click", m.close);
  m.root.querySelector('[data-act="save"]').addEventListener("click", async () => {
    const name = m.root.querySelector("#env-name").value.trim();
    const content = m.root.querySelector("#env-content").value;
    if (!name || !content) { toast("请填写名称与内容", "error"); return; }
    if (content.includes("••••••")) { toast("脱敏内容不能直接保存，请整份覆盖粘贴", "error"); return; }
    try {
      const res = await apiFetch(isEdit ? `/api/envs/${env.id}` : "/api/envs", {
        method: isEdit ? "PATCH" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, content }),
      });
      const d = await res.json();
      if (!res.ok || d.error) throw new Error(d.error || "保存失败");
      m.close();
      toast(isEdit ? "环境已更新" : "环境已创建");
      loadEnvs();
    } catch (err) { toast(err.message || "保存失败", "error"); }
  });
}

/* 停用 / 启用（admin） */
async function toggleEnv(e) {
  try {
    const res = await apiFetch(`/api/envs/${e.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ disabled: !e.disabled }),
    });
    const d = await res.json();
    if (!res.ok || d.error) throw new Error(d.error || "操作失败");
    toast(e.disabled ? "已启用" : "已停用");
    loadEnvs();
  } catch (err) { toast(err.message || "操作失败", "error"); }
}

/* 删除（danger + 确认弹层） */
async function deleteEnv(e) {
  const ok = await confirmDialog({
    title: "删除环境",
    message: `确定删除环境 <b>${esc(e.name)}</b>？<br/>删除环境将不可恢复。`,
    danger: true,
    okText: "删除",
  });
  if (!ok) return;
  try {
    const res = await apiFetch(`/api/envs/${e.id}`, { method: "DELETE" });
    const d = await res.json();
    if (!res.ok || d.error) throw new Error(d.error || "删除失败");
    toast("环境已删除");
    loadEnvs();
  } catch (err) { toast(err.message || "删除失败", "error"); }
}

/* 强制释放锁（admin，danger ghost + 确认弹层） */
async function releaseEnv(e) {
  const ok = await confirmDialog({
    title: "强制释放",
    message: `确定强制释放 <b>${esc(e.name)}</b> 的锁？<br/><span class="mono faint">run ${esc(e.lock.run_id || "")} · ${esc(e.lock.owner_name || "未知属主")}</span><br/>正在使用该环境的任务可能受影响。`,
    danger: true,
    okText: "强制释放",
  });
  if (!ok) return;
  try {
    const res = await apiFetch("/api/lock/force-release", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ env_id: e.id }),
    });
    const d = await res.json();
    if (!res.ok || d.error) throw new Error(d.error || "释放失败");
    toast(d.message || "锁已释放");
    loadEnvs();
  } catch (err) { toast(err.message || "释放失败", "error"); }
}

/* ═══ 我的上传 ═════════════════════════════════════════════ */

async function loadUploads() {
  const body = viewEl.querySelector("#res-body");
  if (!body) return;
  body.innerHTML = skeletonRows(3, 4);
  try {
    const res = await apiFetch("/api/uploads");
    uploads = await res.json();
    if (!res.ok) throw new Error(uploads.error || "加载失败");
  } catch (err) {
    body.innerHTML = emptyState("上传列表加载失败", err.message || "请稍后重试");
    return;
  }
  body.innerHTML = `
    <div class="upload-drop" id="up-drop">
      将 suite / 脚本文件拖到这里，或<b>点击选择文件</b><br/>
      <span class="faint" style="font-size:11.5px">.py 识别为脚本（script），其余识别为 suite；可多选</span>
    </div>
    <input type="file" id="up-file" multiple hidden/>
    <div style="margin:10px 0">
      <button type="button" class="btn btn-ghost btn-sm" id="up-new">＋ 新建文件</button>
    </div>
    <div id="up-list"></div>`;

  /* 上传区交互：点击 / 拖拽 */
  const drop = body.querySelector("#up-drop");
  const file = body.querySelector("#up-file");
  drop.addEventListener("click", () => file.click());
  file.addEventListener("change", () => { uploadFiles(file.files); file.value = ""; });
  drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("drag"); });
  drop.addEventListener("dragleave", () => drop.classList.remove("drag"));
  drop.addEventListener("drop", (e) => {
    e.preventDefault();
    drop.classList.remove("drag");
    uploadFiles(e.dataTransfer.files);
  });

  /* 列表 */
  const list = body.querySelector("#up-list");
  list.innerHTML = uploads.length
    ? `<div class="card"><table class="table">
        <thead><tr>
          <th>名称</th><th>类型</th><th>上传时间</th><th style="text-align:right">操作</th>
        </tr></thead>
        <tbody>${uploads.map((u) => `<tr>
          <td class="mono" style="font-weight:600">${esc(u.name)}</td>
          <td><span class="badge ${u.kind === "script" ? "warn" : "running"}">${esc(u.kind)}</span></td>
          <td class="mono faint">${esc(u.uploaded_at || "")}</td>
          <td><div class="row-actions">
            <button type="button" class="btn btn-ghost btn-sm" data-edit="${u.id}">编辑</button>
            <button type="button" class="btn btn-danger btn-sm" data-del="${u.id}">删除</button>
          </div></td>
        </tr>`).join("")}</tbody></table></div>`
    : emptyState("还没有上传", "suite / 脚本上传后，可在运行台选择「我的测试」运行");

  list.querySelectorAll("[data-del]").forEach((btn) =>
    btn.addEventListener("click", async () => {
      const u = uploads.find((x) => x.id === btn.dataset.del);
      if (!u) return;
      const ok = await confirmDialog({
        title: "删除上传",
        message: `确定删除 <b>${esc(u.name)}</b>（${esc(u.kind)}）？`,
        danger: true,
        okText: "删除",
      });
      if (!ok) return;
      try {
        const res = await apiFetch(`/api/uploads/${u.id}`, { method: "DELETE" });
        const d = await res.json();
        if (!res.ok || d.error) throw new Error(d.error || "删除失败");
        toast("已删除");
        loadUploads();
      } catch (err) { toast(err.message || "删除失败", "error"); }
    }));

  /* 在线编辑已有文件 */
  list.querySelectorAll("[data-edit]").forEach((btn) =>
    btn.addEventListener("click", () => {
      const u = uploads.find((x) => x.id === btn.dataset.edit);
      if (u) openUploadEditor(u);
    }));

  body.querySelector("#up-new").addEventListener("click", () => openUploadEditor(null));
}

/* 在线新建 / 编辑上传文件（suite / script 均为 UTF-8 文本） */
function openUploadEditor(u) {
  const isEdit = !!u;
  const m = openModal({
    title: isEdit ? `编辑文件 · ${u.name}` : "新建文件",
    body: `
      ${isEdit ? "" : `<div class="field"><label>文件名 <span class="faint">（.py 识别为脚本，其余为 suite）</span></label>
        <input class="input mono" id="ue-name" placeholder="regression-test.txt"/></div>`}
      <div class="field"><label>内容</label>
        <textarea class="input mono" id="ue-content" rows="14" spellcheck="false"
          style="font-size:12px;line-height:1.6" placeholder="每行一个 case 脚本路径（suite）；# 开头为注释"></textarea></div>`,
    footer: `<button type="button" class="btn btn-ghost" data-act="cancel">取消</button>
             <button type="button" class="btn btn-primary" data-act="save">保存</button>`,
    width: 640,
  });

  if (isEdit) {
    (async () => {
      try {
        const res = await apiFetch(`/api/uploads/${u.id}/content`);
        if (!res.ok) {
          const d = await res.json().catch(() => ({}));
          throw new Error(d.error || d.detail || "加载失败");
        }
        const ta = m.root.querySelector("#ue-content");
        ta.value = await res.text();
      } catch (err) { toast(err.message || "内容加载失败", "error"); }
    })();
  }

  m.root.querySelector('[data-act="cancel"]').addEventListener("click", m.close);
  m.root.querySelector('[data-act="save"]').addEventListener("click", async () => {
    const content = m.root.querySelector("#ue-content").value;
    try {
      const res = await apiFetch(isEdit ? `/api/uploads/${u.id}/content` : "/api/uploads/text", {
        method: isEdit ? "PUT" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(isEdit ? { content } : {
          name: m.root.querySelector("#ue-name").value.trim(),
          content,
        }),
      });
      const d = await res.json();
      if (!res.ok || d.error) throw new Error(d.error || "保存失败");
      m.close();
      toast(isEdit ? "已保存" : `已创建 ${d.name}`);
      loadUploads();
    } catch (err) { toast(err.message || "保存失败", "error"); }
  });
}

/* form-data 上传（.py → script，其余 → suite） */
async function uploadFiles(files) {
  if (!files || !files.length) return;
  let ok = 0;
  for (const f of files) {
    try {
      const fd = new FormData();
      fd.append("file", f, f.name);
      const res = await apiFetch("/api/uploads", { method: "POST", body: fd });
      if (res.ok) ok++;
    } catch { /* 单个失败不中断整体 */ }
  }
  toast(ok === files.length ? `已上传 ${ok} 个文件` : `已上传 ${ok}/${files.length} 个文件`,
    ok === files.length ? "" : "error");
  loadUploads();
}

/* ═══ 我的套件（勾选 Case 集合的命名保存）═══════════════════ */

async function loadSuites() {
  const body = viewEl.querySelector("#res-body");
  if (!body) return;
  body.innerHTML = skeletonRows(3, 4);
  try {
    const res = await apiFetch("/api/suites");
    suites = await res.json();
    if (!res.ok) throw new Error(suites.error || "加载失败");
    if (!Array.isArray(suites)) suites = [];
  } catch (err) {
    body.innerHTML = emptyState("套件加载失败", err.message || "请稍后重试");
    return;
  }
  body.innerHTML = `
    <div style="margin:0 0 10px">
      <button type="button" class="btn btn-primary btn-sm" id="suite-new">＋ 新建套件</button>
      <span class="faint" style="font-size:11.5px;margin-left:10px">套件 = 勾选的 case 集合；运行时按所选分支当时的内容生成临时 suite，任务结束后删除</span>
    </div>
    ${suites.length ? `<div class="card"><table class="table">
      <thead><tr>
        <th>名称</th><th>Case 数</th><th>更新时间</th><th style="text-align:right">操作</th>
      </tr></thead>
      <tbody>${suites.map((s) => `<tr>
        <td><div class="mono" style="font-weight:600">${esc(s.name)}</div></td>
        <td class="mono">${s.cases.length}</td>
        <td class="mono faint">${esc(s.updated_at || "")}</td>
        <td><div class="row-actions">
          <button type="button" class="btn btn-ghost btn-sm" data-edit="${esc(s.id)}">编辑</button>
          <button type="button" class="btn btn-danger btn-sm" data-del="${esc(s.id)}">删除</button>
        </div></td>
      </tr>`).join("")}</tbody></table></div>`
      : emptyState("还没有套件", "在运行台选「勾选 Case」模式勾选后「另存为套件」，或点上面「新建套件」")}`;

  body.querySelector("#suite-new").addEventListener("click", () => openSuiteModal(null));
  body.querySelectorAll("[data-edit]").forEach((btn) =>
    btn.addEventListener("click", () => {
      const s = suites.find((x) => x.id === btn.dataset.edit);
      if (s) openSuiteModal(s);
    }));
  body.querySelectorAll("[data-del]").forEach((btn) =>
    btn.addEventListener("click", async () => {
      const s = suites.find((x) => x.id === btn.dataset.del);
      if (!s) return;
      const ok = await confirmDialog({
        title: "删除套件",
        message: `确定删除套件 <b>${esc(s.name)}</b>（${s.cases.length} cases）？`,
        danger: true, okText: "删除",
      });
      if (!ok) return;
      try {
        const res = await apiFetch(`/api/suites/${s.id}`, { method: "DELETE" });
        const d = await res.json();
        if (!res.ok || d.error) throw new Error(d.error || "删除失败");
        toast("已删除");
        loadSuites();
      } catch (err) { toast(err.message || "删除失败", "error"); }
    }));
}

/* 新建 / 编辑套件（勾选器选 case） */
function openSuiteModal(s) {
  const isEdit = !!s;
  const m = openModal({
    title: isEdit ? `编辑套件 · ${s.name}` : "新建套件",
    width: 640,
    body: `
      <div class="field"><label>名称</label>
        <input class="input" id="su-name" value="${isEdit ? esc(s.name) : ""}" placeholder="如：报关冒烟集" autocomplete="off"/></div>
      <div class="field"><label>勾选 Case <span class="faint">（基于当前 HEAD 分支展示，运行时按所选分支解析）</span></label>
        <div id="su-picker"></div></div>`,
    footer: `<button type="button" class="btn btn-ghost" data-act="cancel">取消</button>
             <button type="button" class="btn btn-primary" data-act="save">${isEdit ? "保存" : "创建"}</button>`,
  });
  let cases = isEdit ? [...s.cases] : [];
  const picker = mountCasePicker(m.root.querySelector("#su-picker"), {
    ref: "HEAD",
    product: "firebox",
    selected: cases,
    onChange: (set) => { cases = [...set]; },
    height: 240,
  });
  m.root.querySelector('[data-act="cancel"]').addEventListener("click", () => { picker.destroy(); m.close(); });
  m.root.querySelector('[data-act="save"]').addEventListener("click", async () => {
    const name = m.root.querySelector("#su-name").value.trim();
    if (!name) { toast("请输入套件名称", "error"); return; }
    if (!cases.length) { toast("请勾选至少一个 case", "error"); return; }
    try {
      const res = await apiFetch(isEdit ? `/api/suites/${s.id}` : "/api/suites", {
        method: isEdit ? "PUT" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, product: "firebox", cases }),
      });
      const d = await res.json();
      if (!res.ok || d.error) throw new Error(d.error || "保存失败");
      toast(isEdit ? "套件已更新" : `已创建套件「${name}」`);
      picker.destroy();
      m.close();
      loadSuites();
    } catch (err) { toast(err.message || "保存失败", "error"); }
  });
}
