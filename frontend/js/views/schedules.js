/* ═══════════════════════════════════════════════════════════════
   #/schedules — 定时任务（T16）
   列表：规则 / 下次运行 / 上次结果；新建&编辑弹层（配置表单简化版，
   目标支持 Suite / 保存的套件 / 勾选 Case）；启停 / 立即运行 / 删除。
   时间口径：服务器本机时间。
   ═══════════════════════════════════════════════════════════════ */
import { apiFetch } from "../api.js";
import { mountCasePicker } from "../casepicker.js";
import { esc, toast, confirmDialog, openModal, emptyState, skeletonRows } from "../ui.js";

const $ = (s, root = document) => root.querySelector(s);
const $$ = (s, root = document) => Array.from(root.querySelectorAll(s));

let disposers = [];
function onDispose(fn) { disposers.push(fn); }
function dispose() { disposers.splice(0).forEach((fn) => { try { fn(); } catch { /* ignore */ } }); }

const RULE_TXT = { daily: "每天", once: "单次" };
const STATUS_BADGE = {
  started: ["running", "已发起"], start_error: ["fail", "发起失败"],
  missed: ["warn", "已错过"], ok: ["pass", "完成"], failed: ["fail", "失败"],
  stopped: ["warn", "已停止"],
};

export async function render(el) {
  dispose();
  if (!document.getElementById("rc-console-css")) {
    const link = document.createElement("link");
    link.id = "rc-console-css";
    link.rel = "stylesheet";
    link.href = "css/console.css";
    document.head.appendChild(link);
  }
  el.innerHTML = `
    <div class="view-head">
      <h1 class="view-title">定时任务</h1>
      <div class="view-spacer"></div>
      <button class="btn btn-primary" id="sch-btn-new" type="button">＋ 新建定时任务</button>
    </div>
    <div id="sch-list">${skeletonRows(5, 5)}</div>`;
  $("#sch-btn-new").addEventListener("click", () => openEditor(null));
  await refresh();
  onDispose(dispose);
}

async function refresh() {
  const box = $("#sch-list");
  if (!box) return;
  let rows = [];
  try {
    rows = await (await apiFetch("/api/schedules")).json();
    if (!Array.isArray(rows)) rows = [];
  } catch { rows = []; }
  if (!box) return;
  if (!rows.length) {
    box.innerHTML = `<div class="card"><div class="card-pad">${emptyState(
      "还没有定时任务", "点击右上角「新建定时任务」：每天固定时间自动运行，或指定时间运行一次")}</div></div>`;
    return;
  }
  box.innerHTML = `<div class="card"><table class="table">
    <thead><tr>
      <th>名称</th><th>运行配置</th><th>规则</th><th>下次运行</th><th>上次运行</th><th style="text-align:right">操作</th>
    </tr></thead>
    <tbody>${rows.map(rowHtml).join("")}</tbody></table></div>`;

  $$("[data-act]", box).forEach((btn) => btn.addEventListener("click", async () => {
    const s = rows.find((x) => x.id === btn.dataset.id);
    if (!s) return;
    const act = btn.dataset.act;
    if (act === "toggle") await patch(s.id, { enabled: !s.enabled });
    else if (act === "run") await runNow(s);
    else if (act === "del") await remove(s);
    else if (act === "edit") openEditor(s);
    else if (act === "loop") location.hash = `#/console?loop=${encodeURIComponent(s.last_loop_id)}`;
  }));
}

function rowHtml(s) {
  const p = s.params || {};
  const target = p.cases?.length
    ? `勾选 ${p.cases.length} case`
    : p.suite ? `suite ${p.suite}` : "—";
  const cfg = `${esc(s.env_name || p.env_id)} · ${esc(p.product || "firebox")} · ${esc(target)}`
    + ` · ${p.repeat === 0 ? "∞" : "×" + (p.repeat || 1)}`
    + (p.git_ref ? ` · ${esc(p.git_ref)}` : "");
  const rule = s.rule_type === "daily"
    ? `${RULE_TXT.daily} <b class="mono">${esc(s.time || "")}</b>`
    : `${RULE_TXT.once} <b class="mono">${esc(s.run_at || "")}</b>`;
  const badge = STATUS_BADGE[s.last_status] || ["faint", s.last_status || "—"];
  const last = s.last_loop_id
    ? `<a href="javascript:void(0)" data-act="loop" data-id="${esc(s.id)}" class="mono" style="font-size:11.5px">${esc(s.last_loop_id)}</a>`
    : `<span class="faint">—</span>`;
  return `<tr>
    <td><b>${esc(s.name)}</b>${s.enabled ? "" : ` <span class="badge faint">已停用</span>`}
      ${s.last_note ? `<div class="faint" style="font-size:11.5px;margin-top:2px">${esc(s.last_note)}</div>` : ""}</td>
    <td style="font-size:12px">${cfg}</td>
    <td style="font-size:12px">${rule}</td>
    <td class="mono" style="font-size:12px">${s.enabled ? esc(s.next_run_at || "—") : "—"}</td>
    <td style="font-size:12px"><span class="badge ${badge[0]}">${badge[1]}</span> ${last}</td>
    <td><div class="row-actions">
      <button type="button" class="btn btn-ghost btn-sm" data-act="toggle" data-id="${esc(s.id)}">${s.enabled ? "停用" : "启用"}</button>
      <button type="button" class="btn btn-ghost btn-sm" data-act="run" data-id="${esc(s.id)}">立即运行</button>
      <button type="button" class="btn btn-ghost btn-sm" data-act="edit" data-id="${esc(s.id)}">编辑</button>
      <button type="button" class="btn btn-danger btn-sm" data-act="del" data-id="${esc(s.id)}">删除</button>
    </div></td>
  </tr>`;
}

async function patch(id, body) {
  try {
    const res = await apiFetch(`/api/schedules/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.error) { toast(data.error || "操作失败", "error"); return; }
    toast("已更新");
    refresh();
  } catch (err) { toast(err.message || "操作失败", "error"); }
}

async function runNow(s) {
  try {
    const res = await apiFetch(`/api/schedules/${s.id}/run-now`, { method: "POST" });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.error) { toast(data.error || "触发失败", "error"); return; }
    toast(`已发起 loop：${data.loop_id}`);
    location.hash = `#/console?loop=${encodeURIComponent(data.loop_id)}`;
  } catch (err) { toast(err.message || "触发失败", "error"); }
}

async function remove(s) {
  const ok = await confirmDialog({
    title: "删除定时任务",
    message: `确定删除 <b>${esc(s.name)}</b>？${s.rule_type === "daily" ? "之后不会再自动运行。" : ""}`,
    danger: true, okText: "删除",
  });
  if (!ok) return;
  try {
    const res = await apiFetch(`/api/schedules/${s.id}`, { method: "DELETE" });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.error) { toast(data.error || "删除失败", "error"); return; }
    toast("已删除");
    refresh();
  } catch (err) { toast(err.message || "删除失败", "error"); }
}

/* ── 新建 / 编辑弹层 ── */
async function openEditor(existing) {
  let envs = [], config = {}, suites = [];
  try {
    [envs, config, suites] = await Promise.all([
      apiFetch("/api/envs").then((r) => r.json()),
      apiFetch("/api/config").then((r) => r.json()),
      apiFetch("/api/suites").then((r) => r.json()),
    ]);
    if (!Array.isArray(envs)) envs = [];
    if (!Array.isArray(suites)) suites = [];
  } catch { /* 保持默认空值 */ }
  const p = existing?.params || {};
  const isEdit = !!existing;

  const envOpts = envs.map((e) =>
    `<option value="${esc(e.id)}" ${e.id === (p.env_id || "") ? "selected" : ""} ${e.disabled ? "disabled" : ""}>${esc(e.name)}</option>`).join("");
  const branchOpts = (config.branches || []).map((b) =>
    `<option value="${esc(b.name)}" ${b.name === (p.git_ref || "") ? "selected" : ""}>${esc(b.name)}${b.current ? "（当前）" : ""}</option>`).join("");
  const suiteOpts = (config.suites || []).map((x) =>
    `<option value="${esc(x.name)}" ${x.name === (p.suite || "") ? "selected" : ""}>${esc(x.name)}（${x.cases} cases）</option>`).join("");
  const savedOpts = suites.map((x) =>
    `<option value="${esc(x.id)}">${esc(x.name)}（${x.cases.length}）</option>`).join("");

  const targetMode = p.cases?.length ? "cases" : "suite";
  const modal = openModal({
    title: isEdit ? `编辑定时任务：${existing.name}` : "新建定时任务",
    width: 620,
    body: `
      <div class="field"><label>名称</label>
        <input class="input" id="sch-name" type="text" value="${esc(existing?.name || "")}" placeholder="如：每晚报关回归" autocomplete="off"/></div>
      <div class="field"><label>触发规则（服务器本机时间）</label>
        <div class="sch-rule-row">
          <label class="rc-switch"><input type="radio" name="sch-rule" value="daily" ${existing?.rule_type !== "once" ? "checked" : ""}/><span class="rc-track"></span><span class="rc-sw-text">每天</span></label>
          <input class="input" id="sch-time" type="time" value="${esc(existing?.time || "08:30")}" style="width:120px"/>
          <label class="rc-switch"><input type="radio" name="sch-rule" value="once" ${existing?.rule_type === "once" ? "checked" : ""}/><span class="rc-track"></span><span class="rc-sw-text">单次</span></label>
          <input class="input" id="sch-runat" type="datetime-local" value="${esc((existing?.run_at || "").replace(" ", "T"))}" style="width:200px"/>
        </div></div>
      <div class="field"><label>环境</label>
        <select class="select" id="sch-env">${envOpts || `<option value="">（无可用环境）</option>`}</select></div>
      <div class="field"><label>分支（每次运行取该分支当时最新）</label>
        <select class="select" id="sch-branch">${branchOpts}</select></div>
      <div class="field"><label>运行目标</label>
        <div class="rc-seg" id="sch-seg-target">
          <button type="button" data-v="suite" class="${targetMode === "suite" ? "on" : ""}">按 Suite</button>
          <button type="button" data-v="cases" class="${targetMode === "cases" ? "on" : ""}">勾选 Case</button>
        </div></div>
      <div class="field" id="sch-field-suite">
        <select class="select" id="sch-suite">${suiteOpts}</select></div>
      <div class="field" id="sch-field-cases" hidden>
        <select class="select" id="sch-saved" style="margin-bottom:8px">
          <option value="">（手动勾选）</option>${savedOpts}</select>
        <div id="sch-picker"></div></div>
      <div class="field"><label>重复次数（0 = 无限循环）</label>
        <input class="input" id="sch-repeat" type="number" min="0" value="${p.repeat ?? 1}" style="width:110px"/></div>
      <label class="rc-switch rc-switch-row" style="margin-bottom:4px"><input type="checkbox" id="sch-headless" ${p.headless ? "checked" : ""}/><span class="rc-track"></span><span class="rc-sw-text">跳过 Job setup / teardown</span></label>
    `,
    footer: `<button type="button" class="btn btn-ghost" data-act="cancel">取消</button>
             <button type="button" class="btn btn-primary" data-act="save">${isEdit ? "保存" : "创建"}</button>`,
  });

  let mode = targetMode;
  let picker = null;
  let cases = [...(p.cases || [])];
  const seg = modal.root.querySelector("#sch-seg-target");
  const suiteField = modal.root.querySelector("#sch-field-suite");
  const casesField = modal.root.querySelector("#sch-field-cases");
  function applyMode() {
    suiteField.hidden = mode !== "suite";
    casesField.hidden = mode !== "cases";
    if (mode === "cases" && !picker) {
      picker = mountCasePicker(modal.root.querySelector("#sch-picker"), {
        ref: modal.root.querySelector("#sch-branch").value,
        product: "firebox",
        selected: cases,
        onChange: (set) => { cases = [...set]; },
        height: 220,
      });
    }
  }
  seg.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => {
    seg.querySelectorAll("button").forEach((x) => x.classList.remove("on"));
    b.classList.add("on");
    mode = b.dataset.v;
    applyMode();
  }));
  modal.root.querySelector("#sch-saved")?.addEventListener("change", (e) => {
    const s = suites.find((x) => x.id === e.target.value);
    cases = s ? [...s.cases] : [];
    picker?.setSelected(cases);
  });
  applyMode();

  modal.root.querySelector('[data-act="cancel"]').addEventListener("click", modal.close);
  modal.root.querySelector('[data-act="save"]').addEventListener("click", async () => {
    const name = modal.root.querySelector("#sch-name").value.trim();
    if (!name) { toast("请输入名称", "error"); return; }
    const ruleType = modal.root.querySelector('input[name=sch-rule]:checked').value;
    const time = modal.root.querySelector("#sch-time").value;
    const runAt = modal.root.querySelector("#sch-runat").value.replace("T", " ");
    if (ruleType === "daily" && !time) { toast("请选择每天运行的时间", "error"); return; }
    if (ruleType === "once" && !runAt) { toast("请选择单次运行时间", "error"); return; }
    const envId = modal.root.querySelector("#sch-env").value;
    if (!envId) { toast("请选择环境", "error"); return; }
    const repeat = parseInt(modal.root.querySelector("#sch-repeat").value, 10);
    const run = {
      env_id: envId,
      product: "firebox",
      source: "repo",
      git_ref: modal.root.querySelector("#sch-branch").value || "HEAD",
      suite: mode === "suite" ? modal.root.querySelector("#sch-suite").value : "",
      cases: mode === "cases" ? cases : [],
      repeat: Number.isFinite(repeat) ? Math.max(0, repeat) : 1,
      headless: modal.root.querySelector("#sch-headless").checked,
    };
    if (mode === "suite" && !run.suite) { toast("请选择 Suite", "error"); return; }
    if (mode === "cases" && !run.cases.length) { toast("请勾选至少一个 Case", "error"); return; }
    const body = { name, rule_type: ruleType, time, run_at: runAt, enabled: true, run };
    try {
      const res = await apiFetch(
        isEdit ? `/api/schedules/${existing.id}` : "/api/schedules",
        { method: isEdit ? "PATCH" : "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || data.error) { toast(data.error || "保存失败", "error"); return; }
      toast(isEdit ? "已保存" : "定时任务已创建");
      modal.close();
      refresh();
    } catch (err) { toast(err.message || "保存失败", "error"); }
  });
}
