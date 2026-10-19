/* ═══════════════════════════════════════════════════════════════
   #/console — 运行台（T10）
   左 340px 运行配置卡（渐进披露，命令预览实时更新）；
   右侧结果列（循环摘要条 + 概览 / Case 列表 / 控制台 页签）。
   轮询 5s /api/loops/{id}/status；SSE 控制台流 openConsoleStream。
   ═══════════════════════════════════════════════════════════════ */
import { apiFetch, openConsoleStream } from "../api.js";
import { mountCasePicker } from "../casepicker.js";

/* ── 视图生命周期：router 直接 innerHTML 替换，本模块自行清理 ── */
let disposers = [];
let renderSeq = 0;
function onDispose(fn) { disposers.push(fn); }
function dispose() {
  disposers.splice(0).forEach((fn) => { try { fn(); } catch { /* ignore */ } });
}

const $ = (s, root = document) => root.querySelector(s);
const $$ = (s, root = document) => Array.from(root.querySelectorAll(s));
const esc = (s) => String(s ?? "").replace(/[&<>"']/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

/* ── 视图状态 ── */
const state = {
  config: { products: [], branches: [], suites: [], tests: [] },
  envs: [],
  uploads: [],
  suitesSaved: [],   // 保存的套件（/api/suites）
  loops: [],          // 最近任务列表（/api/loops，最新在前）
  envId: "",
  form: {
    product: "firebox", source: "repo", gitRef: "HEAD", uploadId: "",
    targetMode: "suite", suite: "", test: "",
    cases: [], savedSuiteId: "",       // 勾选 Case 模式
    repeat: 1, unlimited: false, pauseOnFail: false, headless: false,
    fwBranch: "", fwBuild: "",
  },
  loop: null,
  tab: "overview",
  consoleStream: null,
  pollTimer: null,
};

/* ── 视图专属 CSS 动态注入 ── */
function ensureCss() {
  if (document.getElementById("rc-console-css")) return;
  const link = document.createElement("link");
  link.id = "rc-console-css";
  link.rel = "stylesheet";
  link.href = "css/console.css";
  document.head.appendChild(link);
}

/* ── toast ── */
let toastEl = null, toastTimer = null;
function toast(msg, isErr = false) {
  if (!toastEl) {
    toastEl = document.createElement("div");
    toastEl.className = "rc-toast";
    document.body.appendChild(toastEl);
    onDispose(() => { toastEl?.remove(); toastEl = null; });
  }
  toastEl.textContent = msg;
  toastEl.classList.toggle("err", isErr);
  requestAnimationFrame(() => toastEl.classList.add("on"));
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toastEl?.classList.remove("on"), 2400);
}

/* ── 命令预览 ── */
function buildCommand() {
  const f = state.form;
  const parts = [`python -m runner --product ${f.product}`];
  const notes = [];
  if (f.source === "repo") {
    if (f.targetMode === "suite") f.suite ? parts.push(`--suite ${f.suite}`) : notes.push("未选择 Suite");
    else if (f.targetMode === "test") f.test ? parts.push(`--test ${f.test}`) : notes.push("未选择 Test");
    else if (f.targetMode === "cases") {
      f.cases.length
        ? parts.push(`--suite （勾选 ${f.cases.length} case → 运行时生成临时套件）`)
        : notes.push("未勾选 Case");
    }
  } else {
    const up = state.uploads.find((u) => u.id === f.uploadId);
    if (!up) notes.push("未选择我的测试");
    else if (up.kind === "suite") parts.push(`--suite ${up.name}`);
    else parts.push(`--test ${up.relpath}`);
  }
  if (f.headless) parts.push("--headless true");
  if (f.fwBranch) {
    parts.push(`--branch ${f.fwBranch}`);
    if (f.fwBuild) parts.push(`--build ${f.fwBuild}`);
  }
  notes.push(f.gitRef || "HEAD");
  notes.push(f.unlimited ? "×∞" : `×${Math.max(1, parseInt(f.repeat, 10) || 1)}`);
  if (f.pauseOnFail) notes.push("pause-on-fail");
  return { pure: parts.join(" "), note: notes.join(" · ") };
}

function updatePreview() {
  const el = $("#rc-cmd");
  if (!el) return;
  const { pure, note } = buildCommand();
  el.innerHTML = `${esc(pure)} <span class="rc-cmd-note"># ${esc(note)}</span>`;
}

function runParams() {
  const f = state.form;
  return {
    env_id: state.envId,
    product: f.product,
    source: f.source,
    git_ref: f.gitRef,
    upload_id: f.source === "upload" ? f.uploadId : "",
    suite: f.source === "repo" && f.targetMode === "suite" ? f.suite : "",
    test: f.source === "repo" && f.targetMode === "test" ? f.test : "",
    cases: f.source === "repo" && f.targetMode === "cases" ? f.cases : [],
    headless: f.headless,
    branch: f.fwBranch,
    build: f.fwBuild,
    repeat: f.unlimited ? 0 : Math.max(1, parseInt(f.repeat, 10) || 1),
    pause_on_fail: f.pauseOnFail,
  };
}

/* ── 工具 ── */
function fmtDuration(loop) {
  const jobs = (loop.jobs || []).filter((j) => j.started_at);
  if (!jobs.length) return "—";
  const starts = jobs.map((j) => new Date(j.started_at.replace(" ", "T")).getTime()).filter(Number.isFinite);
  const ends = jobs.map((j) => j.ended_at && new Date(j.ended_at.replace(" ", "T")).getTime()).filter(Number.isFinite);
  if (!starts.length) return "—";
  const end = ends.length ? Math.max(...ends) : Date.now();
  const sec = Math.max(0, Math.round((end - Math.min(...starts)) / 1000));
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  return h ? `${h}h${String(m).padStart(2, "0")}m${String(s).padStart(2, "0")}s`
    : m ? `${m}m${String(s).padStart(2, "0")}s` : `${s}s`;
}

function loopBadge(loop) {
  if (loop.status === "running") return { cls: "running", text: "RUNNING" };
  if (loop.status === "stopped") return { cls: "warn", text: "STOPPED" };
  return { cls: "pass", text: "DONE" };
}

/* ── 页头：环境胶囊 ── */
function envState() {
  if (state.loop && state.loop.status === "running") return "running";
  const env = state.envs.find((e) => e.id === state.envId);
  return env && env.lock && env.lock.held ? "running" : "idle";
}

function updateEnvPill() {
  const pill = $("#rc-env-pill");
  if (!pill) return;
  const env = state.envs.find((e) => e.id === state.envId);
  pill.dataset.state = envState();
  $("#rc-env-name").textContent = env ? env.name : "选择环境";
}

function renderEnvMenu() {
  const menu = $("#rc-env-menu");
  if (!menu) return;
  menu.innerHTML = state.envs.length
    ? state.envs.map((e) => {
        const lockTxt = e.lock && e.lock.held ? (e.lock.stale ? "锁残留" : "占用中") : "空闲";
        return `<button type="button" class="rc-env-item ${e.id === state.envId ? "on" : ""}"
          data-env="${esc(e.id)}" ${e.disabled ? "disabled" : ""}>
          <div class="env-name">${esc(e.name)}</div>
          <div class="env-meta"><span>${esc(e.owner_name || "")}</span><span>${e.disabled ? "已禁用" : esc(lockTxt)}</span></div>
        </button>`;
      }).join("")
    : `<div class="rc-env-item rc-env-none">暂无环境</div>`;
  $$(".rc-env-item[data-env]", menu).forEach((b) =>
    b.addEventListener("click", () => {
      state.envId = b.dataset.env;
      $("#rc-env-menu").hidden = true;
      updateEnvPill();
    }));
}

function wireEnvPill() {
  const pill = $("#rc-env-pill"), menu = $("#rc-env-menu");
  pill.addEventListener("click", (e) => {
    e.stopPropagation();
    menu.hidden = !menu.hidden;
    if (!menu.hidden) renderEnvMenu();
  });
  const close = (e) => { if (!menu.hidden && !menu.contains(e.target)) menu.hidden = true; };
  document.addEventListener("click", close);
  onDispose(() => document.removeEventListener("click", close));
}

/* ── 页头：RUN / STOP ── */
function setRunUI() {
  const btn = $("#rc-btn-run");
  if (!btn) return;
  const running = !!state.loop && state.loop.status === "running";
  btn.textContent = running ? "STOP" : "RUN";
  btn.classList.toggle("btn-primary", !running);
  btn.classList.toggle("btn-danger", running);
}

async function onRun() {
  const f = state.form;
  if (!state.envId) { toast("请先选择环境", true); return; }
  if (f.source === "repo" && f.targetMode === "suite" && !f.suite) { toast("请选择 Suite", true); return; }
  if (f.source === "repo" && f.targetMode === "test" && !f.test) { toast("请选择 Test", true); return; }
  if (f.source === "repo" && f.targetMode === "cases" && !f.cases.length) { toast("请勾选至少一个 Case", true); return; }
  if (f.source === "upload" && !f.uploadId) { toast("请选择我的测试", true); return; }
  const btn = $("#rc-btn-run");
  btn.disabled = true;
  try {
    const res = await apiFetch("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(runParams()),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.error) { toast(data.error || `启动失败（${res.status}）`, true); return; }
    toast(`loop 已启动：${data.loop_id}`);
    await showLoop(data.loop_id);
  } catch (err) {
    toast(err.message || "启动失败", true);
  } finally {
    btn.disabled = false;
    setRunUI();
  }
}

async function onStop() {
  if (!state.loop) return;
  const id = state.loop.id;
  try {
    const res = await apiFetch(`/api/loops/${encodeURIComponent(id)}/stop`, { method: "POST" });
    const data = await res.json().catch(() => ({}));
    toast(data.message || `已请求停止 ${id}`, !res.ok || !!data.error);
  } catch (err) {
    toast(err.message || "停止失败", true);
  }
  await pollOnce();
}

/* ── 轮询 ── */
async function pollOnce() {
  if (!state.loop) return;
  const id = state.loop.id;
  try {
    const data = await (await apiFetch(`/api/loops/${encodeURIComponent(id)}/status`)).json();
    const loop = data && data.loop;
    if (!loop) { state.loop = null; stopPolling(); renderRight(); return; }
    if (!state.loop || state.loop.id !== id) return; // 已切换
    const statusChanged = state.loop.status !== loop.status;
    state.loop = loop;
    updateSummaryCard();
    updateEnvPill();
    setRunUI();
    // 状态变化（如 running → done/stopped）：重建概览区 + 刷新最近任务列表
    // 的徽标（否则列表一直显示旧的 running）；定时重建会销毁用户正在查看的
    // 内嵌 log / 截图 lightbox 并打断滚动，所以数据没变时绝不动 DOM
    if (statusChanged) {
      if (state.tab === "overview") renderTabBody();
      fetchJson("/api/loops", []).then((ls) => {
        if (Array.isArray(ls) && ls.length) { state.loops = ls; renderRecentList(); }
      });
    } else if (state.tab === "overview" && loop.status === "running") {
      updateOverviewLive();
    }
  } catch { /* 瞬时错误忽略 */ }
}

function startPolling() {
  stopPolling();
  state.pollTimer = setInterval(pollOnce, 5000);
  onDispose(stopPolling);
}
function stopPolling() {
  if (state.pollTimer) { clearInterval(state.pollTimer); state.pollTimer = null; }
}

/* ── loop 绑定 ── */
async function bindLoopById(id) {
  try {
    const data = await (await apiFetch(`/api/loops/${encodeURIComponent(id)}/status`)).json();
    state.loop = data && data.loop ? data.loop : { id };
  } catch {
    state.loop = { id };
  }
  state.tab = "overview";
  renderRight();
  startPolling();
  updateEnvPill();
  setRunUI();
}

/* ── 右侧结果列 ── */
function renderRight() {
  const box = $("#rc-right");
  if (!box) return;
  if (!state.loop) {
    box.innerHTML = `
      <div class="card rc-empty">
        <p>在左侧选择环境、配置运行参数后点击 RUN 启动。<br>历史任务见左下「最近任务」。</p>
      </div>`;
    setRunUI();
    return;
  }
  const latest = [...(state.loop.jobs || [])].reverse().find((j) => j.run_id);
  box.innerHTML = `
    <div class="card" id="rc-summary-card"></div>
    <div class="card">
      <div class="rc-tabs">
        <button class="rc-tab ${state.tab === "overview" ? "on" : ""}" data-t="overview" type="button">概览</button>
        <button class="rc-tab ${state.tab === "console" ? "on" : ""}" data-t="console" type="button">控制台</button>
        <span class="rc-spacer"></span>
        ${latest ? `<a class="rc-summary-link" href="/api/runs/${encodeURIComponent(latest.run_id)}/summary.html" target="_blank" rel="noopener">summary.html</a>` : ""}
      </div>
      <div id="rc-tab-body"></div>
    </div>`;
  $$(".rc-tab", box).forEach((b) =>
    b.addEventListener("click", () => switchTab(b.dataset.t)));
  renderSummaryCard();
  renderTabBody();
}

function updateSummaryCard() {
  const card = $("#rc-summary-card");
  if (!card) return;
  renderSummaryCard();
}

let lastSummaryKey = "";
function renderSummaryCard() {
  const card = $("#rc-summary-card");
  if (!card || !state.loop) return;
  const l = state.loop;
  const badge = loopBadge(l);
  // 数据无变化时不重建 DOM（轮询 5s 一次，重建造成可见闪烁并打断交互）
  const key = [l.id, l.status, l.iterations, l.passed_iters, l.fail_iters, badge.text].join("|");
  if (key === lastSummaryKey && card.querySelector(".rc-loop-id")) return;
  lastSummaryKey = key;
  const target = l.suite || l.test || "—";
  const total = l.repeat_total > 0 ? l.repeat_total : (l.iteration_statuses || []).length;
  let blocks = "";
  for (let i = 1; i <= Math.max(total, (l.iteration_statuses || []).length); i++) {
    const it = (l.iteration_statuses || []).find((x) => x.iteration === i);
    blocks += `<span class="rc-it ${it ? esc(it.status) : ""}" title="第 ${i} 轮：${it ? esc(it.status) : "未跑"}"></span>`;
  }
  card.innerHTML = `
    <div class="card-pad">
      <div class="rc-loop-row1">
        <span class="rc-loop-id">${esc(l.id)}</span>
        <span class="badge ${badge.cls}">${badge.text}</span>
        <span class="rc-spacer"></span>
        <button class="btn btn-ghost btn-sm" id="rc-btn-refresh" type="button">刷新</button>
      </div>
      <div class="rc-loop-meta">${esc(l.env_name || "")} · ${esc(target)} · ${esc(l.owner_name || "")} · 耗时 ${esc(fmtDuration(l))}</div>
      <div class="rc-loop-stats">
        <span>已运行 <b>${l.iterations ?? 0}</b></span>
        <span class="rc-stat-pass">Pass <b>${l.passed_iters ?? 0}</b></span>
        <span class="rc-stat-fail">Fail <b>${l.fail_iters ?? 0}</b></span>
      </div>
      <div class="rc-iters">${blocks}</div>
    </div>`;
  $("#rc-btn-refresh", card).addEventListener("click", () => pollOnce());
}

/* ── 页签 ── */
async function switchTab(tab) {
  if (state.tab === tab) return;
  state.tab = tab;
  closeConsoleStream();
  $$(".rc-tab").forEach((b) => b.classList.toggle("on", b.dataset.t === tab));
  renderTabBody();
}

function renderTabBody() {
  const body = $("#rc-tab-body");
  if (!body || !state.loop) return;
  if (state.tab === "overview") renderOverview(body);
  else renderConsole(body);
}

/* 概览 */
function renderOverview(body) {
  const l = state.loop;
  const fw = [l.firmware_branch, l.firmware_build].filter(Boolean).join(" · ") || "—";
  const banners = [];
  if (l.stop_reason) banners.push(`<div class="rc-banner warn">停止原因：${esc(l.stop_reason)}</div>`);
  if (l.failed_reason) banners.push(`<div class="rc-banner fail">失败原因：${esc(l.failed_reason)}</div>`);
  const runs = (l.jobs || []).filter((j) => j.run_id);
  const latest = runs.length ? runs[runs.length - 1] : null;
  body.innerHTML = `
    <div class="rc-tabpad">
      <div class="rc-meta">
        <div class="rc-meta-cell"><div class="k">Product</div><div class="v">${esc(l.product || "—")}</div></div>
        <div class="rc-meta-cell"><div class="k">DUT Model</div><div class="v">${esc(l.dut_model || "—")}</div></div>
        <div class="rc-meta-cell"><div class="k">Firmware</div><div class="v">${esc(fw)}</div></div>
        <div class="rc-meta-cell"><div class="k">Duration</div><div class="v">${esc(fmtDuration(l))}</div></div>
      </div>
      ${banners.join("") || `<div class="rc-note-plain">本次运行无停止 / 失败原因记录。</div>`}
      ${latest ? `
        <div class="rc-cases-head" style="margin-top:16px">
          <div class="rc-cmd-label" style="margin:0">运行结果${l.status === "running" ? ' <span class="badge running">实时</span>' : ""}</div>
          <span class="rc-spacer"></span>
          ${runs.length > 1 ? `<select class="select rc-run-select" id="rc-ov-run" title="loop 多轮时选择要查看的轮次">
            ${runs.map((j) => `<option value="${esc(j.run_id)}" ${j === latest ? "selected" : ""}>第 ${j.iteration} 轮 · ${esc(j.run_id)} · ${esc(j.status)}</option>`).join("")}
          </select>` : `<span class="faint mono" style="font-size:11.5px">run ${esc(latest.run_id)}</span>`}
        </div>
        <table class="table">
          <thead><tr><th>Case</th><th>Result</th><th>Duration</th><th>Message</th></tr></thead>
          <tbody id="rc-cases-body"><tr><td colspan="4"><div class="rc-cases-empty">加载中…</div></td></tr></tbody>
        </table>
        <div class="rc-cmd-label">材料 · Run ${esc(latest.run_id)}${l.status === "running" ? "（实时）" : ""}</div>
        <div id="rc-art-list"><div class="rc-cases-empty">加载中…</div></div>`
      : l.status === "running" ? `
        <div class="rc-cases-head" style="margin-top:16px">
          <div class="rc-cmd-label" style="margin:0">运行结果 <span class="badge running">实时</span></div>
        </div>
        <table class="table">
          <thead><tr><th>Case</th><th>Result</th><th>Duration</th><th>Message</th></tr></thead>
          <tbody id="rc-cases-body"><tr><td colspan="4"><div class="rc-cases-empty">等待第一个 case 开始…</div></td></tr></tbody>
        </table>
        <div class="rc-cmd-label">材料 · 实时</div>
        <div id="rc-art-list"><div class="rc-cases-empty">run 目录创建后实时显示</div></div>`
      : `<div class="rc-note-plain">尚无已完成的 run——iteration 结束后这里会显示 case 结果与材料。</div>`}
    </div>`;
  if (!latest) {
    if (l.status === "running") updateOverviewLive();
    return;
  }
  const sel = $("#rc-ov-run", body);
  if (sel) sel.addEventListener("change", (e) => loadOverviewCases(e.target.value));
  if (l.status === "running") updateOverviewLive();
  else loadOverviewCases(latest.run_id);
  loadArtifacts(latest.run_id);
}

/* 运行中：从 console 解析实时 case 状态 + 扫描当前 run 的材料（5s 轮询调用） */
async function updateOverviewLive() {
  if (state.tab !== "overview" || !state.loop || state.loop.status !== "running") return;
  let d;
  try {
    d = await (await apiFetch(`/api/loops/${encodeURIComponent(state.loop.id)}/live-cases`)).json();
  } catch { return; }
  if (state.tab !== "overview" || !state.loop || state.loop.status !== "running") return;
  const tb = $("#rc-cases-body");
  if (tb && Array.isArray(d.cases) && d.cases.length) renderCasesBody(d.cases);
  const list = $("#rc-art-list");
  if (list && d.run_id && Array.isArray(d.artifacts) && d.artifacts.length) {
    renderArtifactsInto(list, d.run_id, d.artifacts);
  }
}

/* 概览内的 case 结果（loop 多轮时随轮次下拉切换） */
async function loadOverviewCases(runId) {
  const tbody = $("#rc-cases-body");
  if (!tbody) return;
  let cases = [];
  try {
    const data = await (await apiFetch(`/api/runs/${encodeURIComponent(runId)}`)).json();
    if (Array.isArray(data?.cases)) cases = data.cases;
  } catch { cases = []; }
  if (!tbody.isConnected) return; // 已切走
  renderCasesBody(cases);
}

/* 材料清单（概览内联）：
 * - job/case log：点击在运行台内嵌展开（step 行高亮），不跳转
 * - 截图：缩略图网格，点击弹层放大，点遮罩空白处关闭
 * - 汇总页/汇总 JSON：新窗口打开；配置/支持包：直接下载
 */
const ARTIFACT_KIND_LABEL = {
  job_log: "Job 日志", case_log: "Case 日志", screenshot: "截图",
  summary_html: "汇总页", summary_json: "汇总 JSON", run_meta: "运行元数据",
  support_tgz: "支持包", config: "配置", other: "其他",
};
/* 这些 kind 浏览器可直接预览（不带 download）；其余（配置/包）点击即下载 */
const PREVIEW_KINDS = new Set(["job_log", "case_log", "summary_html"]);
const INLINE_LOG_KINDS = new Set(["job_log", "case_log"]);

function fmtSize(bytes) {
  const n = Number(bytes) || 0;
  if (n >= 1024 * 1024) return (n / 1024 / 1024).toFixed(1) + " MB";
  if (n >= 1024) return (n / 1024).toFixed(1) + " KB";
  return n + " B";
}

/* step / 结构 / 错误行高亮（对应 runner 侧 ui_automation.step 的日志格式） */
function logLineClass(line) {
  if (/^\s*File "|^\w+(Error|Exception)\b|^Traceback\b/.test(line)) return "lv-err";
  if (/:\s*FAIL\s{2}/.test(line) || /\[ERROR\]/.test(line)) return "ln-fail";
  if (/:\s*PASS\s{2}/.test(line)) return "ln-pass";
  if (/:\s*START\s/.test(line)) return "lv-step";
  if (/=== .*Step\d|=====.+=====$/.test(line)) return "lv-step";
  if (/:\s*(Saved .*)?[Ss]creenshot|Saved support snapshot/.test(line)) return "lv-shot";
  if (/RESULT |duration=/.test(line)) return "lv-struct";
  return "";
}

function renderLogText(text) {
  const lines = String(text).split(/\r?\n/);
  const MAX = 5000;
  const shown = lines.length > MAX ? lines.slice(0, MAX) : lines;
  let html = "";
  for (const ln of shown) {
    const cls = logLineClass(ln);
    html += cls ? `<div class="${cls}">${esc(ln)}</div>` : `<div>${esc(ln)}</div>`;
  }
  if (lines.length > MAX) {
    html += `<div class="lv-struct">…（其余 ${lines.length - MAX} 行省略，可下载原文件查看）</div>`;
  }
  return html;
}

/* 内嵌 log 查看：同一时间只展开一个，再次点击收起 */
async function toggleLogView(runId, relpath, anchor) {
  const existing = $(".rc-logview");
  if (existing) {
    const same = existing.dataset.key === runId + "|" + relpath;
    existing.remove();
    if (same) return;
  }
  const view = document.createElement("div");
  view.className = "rc-logview";
  view.dataset.key = runId + "|" + relpath;
  view.innerHTML = `<div class="rc-logview-head"><span>${esc(relpath)}</span>
    <button type="button" class="rc-logview-x" title="关闭">×</button></div>
    <pre class="rc-logview-body"><div class="rc-cases-empty">加载中…</div></pre>`;
  anchor.after(view);
  view.querySelector(".rc-logview-x").addEventListener("click", () => view.remove());
  let text = "";
  try {
    const res = await apiFetch(`/runs/${encodeURIComponent(runId)}/${relpath.split("/").map(encodeURIComponent).join("/")}`);
    text = await res.text();
    if (!res.ok) text = `加载失败（${res.status}）`;
  } catch (e) { text = "加载失败：" + (e.message || e); }
  const body = view.querySelector(".rc-logview-body");
  if (!body) return;
  body.innerHTML = renderLogText(text);
  body.scrollTop = 0;
}

/* 截图 lightbox：点击遮罩空白处关闭（点图片本身不关）；底部显示截图名 */
function openLightbox(url, name) {
  const mask = document.createElement("div");
  mask.className = "rc-lightbox";
  mask.innerHTML = `<figure><img src="${url}" alt="${esc(name)}">
    <figcaption class="mono">${esc(name)}</figcaption></figure>`;
  mask.addEventListener("click", (e) => { if (e.target === mask) mask.remove(); });
  document.body.appendChild(mask);
  onDispose(() => mask.remove());
}

/* 截图文件名（由步骤描述命名）：Step3__Unlock_Network_Interfaces → Step3: Unlock Network Interfaces */
function shotLabel(relpath) {
  const base = String(relpath).split("/").pop().replace(/\.(png|jpg|jpeg|webp)$/i, "");
  return base.replace(/_+/g, " ").trim() || base;
}

/* 截图网格：按所属 case 分组，缩略图下方显示步骤名（文件名即步骤描述） */
function renderShotGrid(shots, fileUrl) {
  const byCase = {};
  for (const f of shots) {
    const key = f.case_name || "其它截图";
    (byCase[key] = byCase[key] || []).push(f);
  }
  return Object.entries(byCase).map(([caseName, list]) => `
    <div class="rc-shots-case">
      <div class="rc-shots-case-name">${esc(caseName)} <span class="faint">(${list.length})</span></div>
      <div class="rc-shots">${list.map((f) => `
        <button type="button" class="rc-shot" data-url="${fileUrl(f.relpath)}" data-name="${esc(shotLabel(f.relpath))}"
                title="${esc(shotLabel(f.relpath))}（点击放大）">
          <img src="${fileUrl(f.relpath)}" loading="lazy" alt="${esc(f.relpath)}">
          <span class="rc-shot-name">${esc(shotLabel(f.relpath))}</span>
        </button>`).join("")}</div>
    </div>`).join("");
}

async function loadArtifacts(runId) {
  let files = [];
  try {
    files = await (await apiFetch(`/api/runs/${encodeURIComponent(runId)}/artifacts`)).json();
    if (!Array.isArray(files)) files = [];
  } catch { files = []; }
  const list = $("#rc-art-list");
  if (!list) return; // 视图已切换 / 概览已重渲染
  if (!files.length) {
    list.innerHTML = `<div class="rc-cases-empty">该 run 没有材料记录</div>`;
    return;
  }
  renderArtifactsInto(list, runId, files);
}

function renderArtifactsInto(list, runId, files) {
  const fileUrl = (rel) => `/runs/${encodeURIComponent(runId)}/${rel.split("/").map(encodeURIComponent).join("/")}`;
  const byKind = {};
  for (const f of files) (byKind[f.kind] = byKind[f.kind] || []).push(f);
  // summary.html/json 不在列表中显示（tab 右上角已有 summary.html 入口，JSON 可经下载取得）
  const KIND_ORDER = ["job_log", "run_meta", "case_log", "screenshot", "support_tgz", "config", "other"];
  list.innerHTML = KIND_ORDER.filter((k) => byKind[k]?.length).map((k) => `
    <div class="rc-art-group" data-kind="${esc(k)}">
      <div class="rc-art-kind">${esc(ARTIFACT_KIND_LABEL[k] || k)} <span class="faint">(${byKind[k].length})</span></div>
      ${k === "screenshot"
        ? renderShotGrid(byKind[k], fileUrl)
        : byKind[k].map((f) => {
            const url = fileUrl(f.relpath);
            if (INLINE_LOG_KINDS.has(k)) {
              return `<button type="button" class="rc-art-file rc-art-log" data-run="${esc(runId)}" data-rel="${esc(f.relpath)}">
                <span class="rc-art-name">${esc(f.relpath)}</span>
                <span class="rc-art-size">${fmtSize(f.size_bytes)} · 点击查看</span>
              </button>`;
            }
            const dl = PREVIEW_KINDS.has(k) ? "" : " download";
            return `<a class="rc-art-file" href="${url}" target="_blank" rel="noopener"${dl}>
              <span class="rc-art-name">${esc(f.relpath)}</span>
              <span class="rc-art-size">${fmtSize(f.size_bytes)}${dl ? " · 下载" : " · 打开"}</span>
            </a>`;
          }).join("")}
    </div>`).join("");
  // log 内嵌展开
  $$(".rc-art-log", list).forEach((b) =>
    b.addEventListener("click", () => {
      toggleLogView(b.dataset.run, b.dataset.rel, b.closest(".rc-art-group") || b);
    }));
  // 截图 lightbox
  $$(".rc-shot", list).forEach((b) =>
    b.addEventListener("click", () => openLightbox(b.dataset.url, b.dataset.name)));
}

/* Case 列表 */
function caseBadgeCls(status) {
  return status === "pass" ? "pass" : status === "fail" ? "fail"
    : status === "broken" ? "warn" : status === "running" ? "running" : "";
}

function renderCasesBody(cases) {
  const tbody = $("#rc-cases-body");
  if (!tbody) return;
  if (!cases.length) {
    tbody.innerHTML = `<tr><td colspan="4"><div class="rc-cases-empty">该 run 没有 case 明细</div></td></tr>`;
    return;
  }
  let html = "", lastFeature = null;
  for (const c of cases) {
    const feature = c.name.includes("/") ? c.name.slice(0, c.name.lastIndexOf("/")) : "";
    if (feature && feature !== lastFeature) {
      html += `<tr class="rc-grp"><td colspan="4">${esc(feature)}</td></tr>`;
      lastFeature = feature;
    }
    const indent = feature ? " rc-cname-indent" : "";
    html += `<tr>
      <td class="rc-cname${indent}">${esc(c.name.split("/").pop())}</td>
      <td><span class="badge ${caseBadgeCls(c.status)}">${esc(c.status)}</span></td>
      <td class="mono">${c.duration_s != null ? esc(c.duration_s) + "s" : "—"}</td>
      <td><div class="rc-msg" title="${esc(c.message || "")}">${esc(c.message || "—")}</div></td>
    </tr>`;
  }
  tbody.innerHTML = html;
}

/* 控制台 */
function closeConsoleStream() {
  if (state.consoleStream) { state.consoleStream.close(); state.consoleStream = null; }
}

function appendConsoleLine(pre, text) {
  const pinned = pre.scrollHeight - pre.scrollTop - pre.clientHeight < 32;
  const div = document.createElement("div");
  if (/PASS/.test(text)) div.className = "ln-pass";
  else if (/FAIL/.test(text)) div.className = "ln-fail";
  div.textContent = text;
  pre.appendChild(div);
  if (pinned) pre.scrollTop = pre.scrollHeight;
}

function renderConsole(body) {
  body.innerHTML = `<pre class="rc-console" id="rc-console"></pre>`;
  const pre = $("#rc-console", body);
  closeConsoleStream();
  state.consoleStream = openConsoleStreamFor(pre);
  onDispose(closeConsoleStream);
}

function openConsoleStreamFor(pre) {
  const loopId = state.loop.id;
  return openConsoleStream(loopId, {
    onreset() { pre.textContent = ""; },
    onmessage(msg) { appendConsoleLine(pre, msg.line ?? ""); },
    onend() {
      const end = document.createElement("div");
      end.className = "rc-console-end";
      end.textContent = `— 控制台流结束（loop ${loopId}）—`;
      pre.appendChild(end);
      pre.scrollTop = pre.scrollHeight;
    },
  });
}

/* ── 左侧配置表单 ── */
function optionList(items, selected) {
  return items.map((it) =>
    `<option value="${esc(it.value)}" ${it.value === selected ? "selected" : ""}>${esc(it.label)}</option>`).join("");
}

function applySourceMode() {
  const repo = state.form.source === "repo";
  $("#rc-field-git").hidden = !repo;
  $("#rc-field-upload").hidden = repo;
  $("#rc-field-target").hidden = !repo;
  $("#rc-field-suite").hidden = !repo || state.form.targetMode !== "suite";
  $("#rc-field-test").hidden = !repo || state.form.targetMode !== "test";
  const casesOn = repo && state.form.targetMode === "cases";
  $("#rc-field-cases").hidden = !casesOn;
  if (casesOn && !casePicker) mountCasesPicker();
  else if (!casesOn && casePicker) { casePicker.destroy(); casePicker = null; }
}

/* 勾选 Case 模式：挂载共享勾选器 + 已保存套件联动 */
let casePicker = null;

function mountCasesPicker() {
  const box = $("#rc-cases-picker");
  if (!box) return;
  $("#rc-cases-ref").textContent = state.form.gitRef || "HEAD";
  casePicker = mountCasePicker(box, {
    ref: state.form.gitRef || "HEAD",
    product: state.form.product,
    selected: state.form.cases,
    onChange: (set) => {
      state.form.cases = [...set];
      updatePreview();
    },
  });
  onDispose(() => { casePicker?.destroy(); casePicker = null; });
}

function segWire(id, key, after) {
  $$(`#${id} button`).forEach((b) =>
    b.addEventListener("click", () => {
      $$(/* reuse */`#${id} button`).forEach((x) => x.classList.remove("on"));
      b.classList.add("on");
      state.form[key] = b.dataset.v;
      after && after();
      updatePreview();
    }));
}

function wireConfigForm() {
  // Product 分段
  segWire("rc-seg-product", "product");
  // 来源分段
  segWire("rc-seg-source", "source", applySourceMode);
  // 按 Suite / 按 Test
  segWire("rc-seg-target", "targetMode", applySourceMode);
  // git_ref / 上传下拉
  $("#rc-sel-git").addEventListener("change", (e) => {
    state.form.gitRef = e.target.value;
    casePicker?.setRef(state.form.gitRef);
    const refLabel = $("#rc-cases-ref");
    if (refLabel) refLabel.textContent = state.form.gitRef;
    updatePreview();
  });
  $("#rc-sel-upload").addEventListener("change", (e) => { state.form.uploadId = e.target.value; updatePreview(); });
  $("#rc-sel-suite").addEventListener("change", (e) => { state.form.suite = e.target.value; updatePreview(); });
  $("#rc-sel-test").addEventListener("change", (e) => { state.form.test = e.target.value; updatePreview(); });
  // 已保存套件选用 → 展开为勾选集合
  $("#rc-sel-savedsuite").addEventListener("change", (e) => {
    state.form.savedSuiteId = e.target.value;
    const s = state.suitesSaved.find((x) => x.id === e.target.value);
    state.form.cases = s ? [...s.cases] : [];
    if (casePicker) casePicker.setSelected(state.form.cases);
    updatePreview();
    if (s) toast(`已套用套件「${s.name}」（${s.cases.length} cases）`);
  });
  // 另存为套件
  $("#rc-btn-savesuite").addEventListener("click", async () => {
    if (!state.form.cases.length) { toast("先勾选 case 再保存", true); return; }
    const name = $("#rc-in-suitename").value.trim();
    if (!name) { toast("请输入套件名称", true); return; }
    try {
      const res = await apiFetch("/api/suites", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, product: state.form.product, cases: state.form.cases }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || data.error) { toast(data.error || "保存失败", true); return; }
      state.suitesSaved = await (await apiFetch("/api/suites")).json().catch(() => state.suitesSaved);
      state.form.savedSuiteId = data.suite.id;
      renderConfigForm();
      toast(`已保存套件「${name}」（可在资源页管理）`);
    } catch (err) { toast(err.message || "保存失败", true); }
  });
  // 执行组
  const inRepeat = $("#rc-in-repeat");
  inRepeat.addEventListener("input", () => { state.form.repeat = inRepeat.value; updatePreview(); });
  const chkUnlimited = $("#rc-chk-unlimited");
  chkUnlimited.addEventListener("change", () => {
    state.form.unlimited = chkUnlimited.checked;
    inRepeat.disabled = state.form.unlimited;
    updatePreview();
  });
  const chkPause = $("#rc-chk-pause");
  chkPause.addEventListener("change", () => { state.form.pauseOnFail = chkPause.checked; updatePreview(); });
  const chkHeadless = $("#rc-chk-headless");
  chkHeadless.addEventListener("change", () => { state.form.headless = chkHeadless.checked; updatePreview(); });
  // 高级折叠
  const advBody = $("#rc-adv-body"), advToggle = $("#rc-adv-toggle");
  advToggle.addEventListener("click", () => {
    advBody.hidden = !advBody.hidden;
    advToggle.classList.toggle("open", !advBody.hidden);
  });
  const inFwBranch = $("#rc-in-fwbranch");
  inFwBranch.addEventListener("input", () => {
    state.form.fwBranch = inFwBranch.value.trim();
    $("#rc-in-fwbuild").disabled = !state.form.fwBranch;
    updatePreview();
  });
  const inBuild = $("#rc-in-fwbuild");
  inBuild.addEventListener("input", () => { state.form.fwBuild = inBuild.value.trim(); updatePreview(); });
  // 复制命令（复制纯命令部分）
  $("#rc-btn-copy").addEventListener("click", async () => {
    const { pure } = buildCommand();
    try {
      await navigator.clipboard.writeText(pure);
      toast("已复制命令");
    } catch {
      toast("复制失败", true);
    }
  });
  // RUN / STOP
  $("#rc-btn-run").addEventListener("click", () => {
    if (state.loop && state.loop.status === "running") onStop();
    else onRun();
  });
}

function renderConfigForm() {
  const f = state.form;
  const products = state.config.products || [];
  $("#rc-seg-product").innerHTML = products.map((p) =>
    `<button type="button" data-v="${esc(p)}" class="${p === f.product ? "on" : ""}">${esc(p)}</button>`).join("");
  $("#rc-seg-source").innerHTML = `
    <button type="button" data-v="repo" class="${f.source === "repo" ? "on" : ""}">仓库测试</button>
    <button type="button" data-v="upload" class="${f.source === "upload" ? "on" : ""}">我的测试</button>`;
  $("#rc-seg-target").innerHTML = `
    <button type="button" data-v="suite" class="${f.targetMode === "suite" ? "on" : ""}">按 Suite</button>
    <button type="button" data-v="test" class="${f.targetMode === "test" ? "on" : ""}">按 Test</button>
    <button type="button" data-v="cases" class="${f.targetMode === "cases" ? "on" : ""}">勾选 Case</button>`;
  $("#rc-sel-git").innerHTML = optionList(
    (state.config.branches || []).map((b) => ({ value: b.name, label: b.name + (b.current ? "（当前）" : "") })),
    f.gitRef);
  $("#rc-sel-upload").innerHTML = state.uploads.length
    ? `<option value="">请选择…</option>` + optionList(
        state.uploads.map((u) => ({ value: u.id, label: `[${u.kind === "suite" ? "suite" : "脚本"}] ${u.relpath}` })),
        f.uploadId)
    : `<option value="">还没有上传</option>`;
  $("#rc-sel-suite").innerHTML = optionList(
    (state.config.suites || []).map((s) => ({ value: s.name, label: `${s.name}（${s.cases} cases）` })),
    f.suite);
  $("#rc-sel-test").innerHTML = optionList(
    (state.config.tests || []).map((t) => ({ value: t, label: t })),
    f.test);
  $("#rc-sel-savedsuite").innerHTML = `<option value="">（手动勾选）</option>` + optionList(
    state.suitesSaved.map((s) => ({ value: s.id, label: `[套件] ${s.name}（${s.cases.length} cases）` })),
    f.savedSuiteId);
  applySourceMode();
  updatePreview();
}

/* ── 装配 ── */
async function fetchJson(path, fallback) {
  try {
    return await (await apiFetch(path)).json();
  } catch {
    return fallback;
  }
}

export async function render(el) {
  dispose(); // 清理上一次视图的定时器 / 流 / 监听
  const seq = ++renderSeq; // 防止切视图后迟到的 fetch 继续覆盖 DOM
  ensureCss();

  const [config, envs, uploads, loops, suitesSaved] = await Promise.all([
    fetchJson("/api/config", {}),
    fetchJson("/api/envs", []),
    fetchJson("/api/uploads", []),
    fetchJson("/api/loops", []),
    fetchJson("/api/suites", []),
  ]);
  if (seq !== renderSeq) return;
  state.config = { products: [], branches: [], suites: [], tests: [], ...config };
  state.envs = Array.isArray(envs) ? envs : [];
  state.uploads = Array.isArray(uploads) ? uploads : [];
  state.loops = Array.isArray(loops) ? loops : [];
  state.suitesSaved = Array.isArray(suitesSaved) ? suitesSaved : [];

  // 默认表单值
  const f = state.form;
  f.product = state.config.products[0] || "firebox";
  const cur = (state.config.branches || []).find((b) => b.current);
  f.gitRef = (cur && cur.name) || (state.config.branches || [])[0]?.name || "HEAD";
  f.suite = (state.config.suites || [])[0]?.name || "";
  f.test = (state.config.tests || [])[0] || "";
  f.uploadId = state.uploads[0]?.id || "";

  // 绑定 loop，优先级：
  // 1) URL ?loop=（任务中心「在运行台打开」）
  // 2) 模块级保留的 state.loop（切页签回来不断线）
  // 3) 正在运行的 loop；再退到最近一条任务（右栏直接显示最近详情）
  const urlLoopId = new URLSearchParams(location.hash.split("?")[1] || "").get("loop");
  if (urlLoopId) {
    await bindLoopById(urlLoopId);
  } else if (!state.loop || !state.loops.some((l) => l.id === state.loop.id)) {
    state.loop = state.loops.find((l) => l.status === "running") || state.loops[0] || null;
  }

  el.innerHTML = `
    <div class="rc-head">
      <h1 class="rc-title">运行台</h1>
      <div class="rc-spacer"></div>
      <div class="rc-env-wrap">
        <button class="rc-env-pill" id="rc-env-pill" type="button" data-state="idle">
          <span class="rc-env-dot"></span><span id="rc-env-name">—</span><span class="rc-caret">▼</span>
        </button>
        <div class="rc-env-menu card" id="rc-env-menu" hidden></div>
      </div>
    </div>
    <div class="rc-layout">
      <div class="rc-left">
        <section class="card rc-config">
          <div class="card-head">
            <span class="card-title">运行配置</span>
            <span class="rc-spacer"></span>
            <button class="btn btn-ghost btn-sm" id="rc-btn-copy" type="button">复制命令</button>
          </div>
          <div class="card-pad">
            <div class="rc-group">
              <div class="rc-group-label">目标</div>
              <div class="field"><label>Product</label><div class="rc-seg" id="rc-seg-product"></div></div>
              <div class="field"><label>来源</label><div class="rc-seg" id="rc-seg-source"></div></div>
              <div class="field" id="rc-field-git"><label>分支 / ref</label><select class="select" id="rc-sel-git"></select></div>
              <div class="field" id="rc-field-upload" hidden><label>我的测试</label><select class="select" id="rc-sel-upload"></select></div>
              <div class="field" id="rc-field-target"><label>运行目标</label><div class="rc-seg" id="rc-seg-target"></div></div>
              <div class="field" id="rc-field-suite"><label>Suite</label><select class="select" id="rc-sel-suite"></select></div>
              <div class="field" id="rc-field-test" hidden><label>Test</label><select class="select" id="rc-sel-test"></select></div>
              <div class="field" id="rc-field-cases" hidden>
                <label>勾选 Case <span class="faint" style="font-weight:400">（分支：<span id="rc-cases-ref">HEAD</span>，运行时生成临时套件并在结束后删除）</span></label>
                <select class="select" id="rc-sel-savedsuite"></select>
                <div id="rc-cases-picker"></div>
                <div class="rc-save-suite-row">
                  <input class="input" id="rc-in-suitename" type="text" placeholder="套件名称（另存当前勾选）" autocomplete="off"/>
                  <button class="btn btn-ghost btn-sm" id="rc-btn-savesuite" type="button">另存为套件</button>
                </div>
              </div>
            </div>
            <div class="rc-group">
              <div class="rc-group-label">执行</div>
              <div class="rc-repeat-row">
                <div class="rc-repeat-input"><span class="rc-x">×</span><input id="rc-in-repeat" type="number" min="1" value="${f.repeat}" aria-label="重复次数"></div>
                <label class="rc-switch"><input type="checkbox" id="rc-chk-unlimited"><span class="rc-track"></span><span class="rc-sw-text">无限循环</span></label>
              </div>
              <label class="rc-switch rc-switch-row rc-row-pause"><input type="checkbox" id="rc-chk-pause"><span class="rc-track"></span><span class="rc-sw-text">Pause on fail</span></label>
              <label class="rc-switch rc-switch-row"><input type="checkbox" id="rc-chk-headless"><span class="rc-track"></span><span class="rc-sw-text">跳过 Job setup / teardown</span></label>
            </div>
            <div class="rc-group">
              <button class="rc-adv-toggle" id="rc-adv-toggle" type="button">
                <span>高级 · 固件 Branch / Build</span><span class="rc-adv-caret">›</span>
              </button>
              <div class="rc-adv-body" id="rc-adv-body" hidden>
                <div class="field"><label>固件 branch</label>
                  <input class="input" id="rc-in-fwbranch" placeholder="如 utm-2026_2（留空不指定）" autocomplete="off"></div>
                <div class="field rc-field-last"><label>固件 build</label><input class="input" id="rc-in-fwbuild" placeholder="如 733385" disabled></div>
              </div>
            </div>
            <div class="rc-cmd-label">命令预览</div>
            <div class="rc-cmd" id="rc-cmd"></div>
            <div class="rc-run-row">
              <button class="btn btn-primary btn-block" id="rc-btn-run" type="button">RUN</button>
            </div>
          </div>
        </section>
        <section class="card rc-recent">
          <div class="card-head"><span class="card-title">最近任务</span></div>
          <div id="rc-recent-list"></div>
        </section>
      </div>
      <section class="rc-right" id="rc-right"></section>
    </div>`;

  wireEnvPill();
  renderConfigForm();
  wireConfigForm();
  updateEnvPill();
  renderRecentList();
  renderRight();
  if (state.loop) startPolling();
  setRunUI();
}

/* ── 最近任务列表（左列配置卡下方） ── */
function renderRecentList() {
  const box = $("#rc-recent-list");
  if (!box) return;
  const loops = state.loops.slice(0, 8);
  if (!loops.length) {
    box.innerHTML = `<div class="rc-recent-empty">还没有任务记录，发起一次运行后这里会显示。</div>`;
    return;
  }
  box.innerHTML = loops.map((l) => {
    const b = loopBadge(l);
    const target = l.suite || l.test || "—";
    const on = state.loop && state.loop.id === l.id ? " on" : "";
    return `<button type="button" class="rc-recent-item${on}" data-loop="${esc(l.id)}">
      <div class="rr-row1"><span class="rr-id">${esc(l.id)}</span><span class="badge ${b.cls}">${b.text}</span></div>
      <div class="rr-meta">${esc(l.env_name || "")} · ${esc(target)} · ${esc(l.owner_name || "")}</div>
    </button>`;
  }).join("");
  $$(".rc-recent-item", box).forEach((el) =>
    el.addEventListener("click", () => showLoop(el.dataset.loop)));
}

/* 点击最近任务 / URL 参数：绑定指定 loop 并在右侧显示详情 */
async function showLoop(id) {
  await bindLoopById(id);
  // 最近任务列表可能落后（如刚发起的 loop 不在 render 时拉取的列表里）
  fetchJson("/api/loops", []).then((ls) => {
    if (Array.isArray(ls) && ls.length) { state.loops = ls; renderRecentList(); }
  });
}
