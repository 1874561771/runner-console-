/* ═══════════════════════════════════════════════════════════════
   tasks.js — #/tasks 任务中心（T11）
   循环与 Job 的统一列表：筛选栏 + 左密表 + 右 360px Inspector。
   依赖 API（契约权威 = api.js / mock-data.js）：
     GET /api/loops?days=&env_id=&status=   列表过滤
     GET /api/loops/:id                     全量详情
     GET /api/loops/:id/status              轻量轮询
     GET /api/runs?loop_id=                 某 loop 的 run 列表
     GET /api/runs/:id                      run 详情（含 cases）
     openConsoleStream(loopId, handlers)    控制台 SSE（mock 定时逐行）
   跳转运行台：#/console?loop=<loop_id>（router 剥离 query，T10 解析 hash）。
   卸载清理：MutationObserver 感知视图被替换，关停全部 timer / SSE。
   ═══════════════════════════════════════════════════════════════ */
import { apiFetch, openConsoleStream } from "../api.js";

/* ── 工具 ── */
const esc = (s) => String(s ?? "").replace(/[&<>"']/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function fmtDur(s) {
  if (s == null || s === "") return "—";
  s = Math.round(Number(s));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60), r = s % 60;
  if (m < 60) return `${m}m${String(r).padStart(2, "0")}s`;
  return `${Math.floor(m / 60)}h${String(m % 60).padStart(2, "0")}m`;
}

/* loop 状态 → 徽标 class / 文案（failed 为 T7 预留终态） */
function loopBadge(loop) {
  switch (loop.status) {
    case "running": return { cls: "running", text: "RUNNING" };
    case "done":    return { cls: "pass",    text: "DONE" };
    case "failed":  return { cls: "fail",    text: "FAIL" };
    default:        return { cls: "",        text: "STOPPED" };
  }
}
const itCls = (s) =>
  ({ pass: "pass", fail: "fail", setup_fail: "setup_fail", running: "running" }[s] || "pending");

const LOCK_DOT = {
  held:  "var(--running)",
  stale: "var(--warn)",
  free:  "var(--idle-dot)",
};

export function render(el) {
  /* ══ 局部状态（每次 render 独立，防跨视图残留）══ */
  const st = {
    days: "14", env: "", status: "",        // 筛选
    loops: [], runsTotal: 0,                // 列表
    selId: null, selLoop: null,             // 选中 loop
    runs: [], openRunId: null, runDetail: null, msgCase: null, // run 展开
    consoleBuf: [], stream: null, consoleStick: true, consoleEnd: null, // 控制台流
  };
  const timers = new Set();

  /* ══ 骨架 ══ */
  const root = document.createElement("div");
  root.className = "tasks-view";
  root.innerHTML = `
    <div class="tasks-head">
      <h1 class="view-title">任务中心</h1>
      <span class="tasks-sub">循环与 Job 的统一列表 · 行点击查看详情</span>
    </div>

    <div class="card tasks-filterbar">
      <select class="select" id="tf-days" title="时间范围">
        <option value="today">今天</option>
        <option value="7">近 7 天</option>
        <option value="14" selected>近 14 天</option>
        <option value="30">近 30 天</option>
        <option value="all">全部</option>
      </select>
      <select class="select" id="tf-env" title="环境">
        <option value="">全部环境</option>
      </select>
      <div class="tasks-seg" id="tf-status">
        <button type="button" data-s="" class="active">全部</button>
        <button type="button" data-s="running">运行中</button>
        <button type="button" data-s="failed">失败</button>
      </div>
      <span class="tasks-count mono" id="tf-count"></span>
    </div>

    <div class="tasks-main">
      <div class="card tasks-listcard">
        <table class="tasks-table">
          <thead><tr>
            <th>Loop</th><th>目标</th><th>状态</th><th>轮次</th>
          </tr></thead>
          <tbody id="loop-rows"></tbody>
        </table>
        <div class="tasks-empty" id="loop-empty" hidden></div>
      </div>
      <div class="card tasks-inspector" id="inspector"></div>
    </div>
  `;
  el.appendChild(root);

  const $ = (sel) => root.querySelector(sel);
  const rowsEl = $("#loop-rows");
  const emptyEl = $("#loop-empty");
  const countEl = $("#tf-count");
  const inspEl = $("#inspector");

  /* ══ 列表 ══ */
  async function refreshList() {
    try {
      const qs = new URLSearchParams();
      if (st.days !== "all") qs.set("days", st.days);
      if (st.env) qs.set("env_id", st.env);
      if (st.status) qs.set("status", st.status);
      const [loops, runs] = await Promise.all([
        apiFetch(`/api/loops?${qs}`).then((r) => r.json()),
        apiFetch("/api/runs").then((r) => r.json()),
      ]);
      st.loops = Array.isArray(loops) ? loops : [];
      st.runsTotal = Array.isArray(runs) ? runs.length : 0;
      renderRows();
    } catch { /* 静默：轮询失败不打断界面 */ }
  }

  function renderRows() {
    countEl.textContent = `${st.loops.length} loops · ${st.runsTotal} runs`;
    emptyEl.hidden = st.loops.length > 0;
    emptyEl.textContent =
      "无符合条件的循环。当前筛选：" +
      `${$("#tf-days").selectedOptions[0].textContent} · ` +
      `${st.env || "全部环境"} · ` +
      `${st.status === "running" ? "运行中" : st.status === "failed" ? "失败" : "全部状态"}。`;
    rowsEl.innerHTML = st.loops.map((l) => {
      const b = loopBadge(l);
      const done = l.passed_iters + l.fail_iters;
      const totalTxt = l.repeat_total > 0 ? l.repeat_total : "∞";
      const blocks = (l.iteration_statuses || [])
        .map((it) => `<i class="${itCls(it.status)}"></i>`).join("");
      const pending = l.repeat_total > 0
        ? `<i class="pending"></i>`.repeat(Math.max(0, l.repeat_total - (l.iteration_statuses || []).length))
        : "";
      return `
      <tr data-id="${esc(l.id)}" class="${l.id === st.selId ? "selected" : ""}">
        <td>
          <div class="t-loopid">${esc(l.id)}</div>
          <div class="t-loopsub">${esc(l.owner_name)} · ${esc(l.env_name)}</div>
        </td>
        <td><span class="t-target">${esc(l.suite || l.test || "—")}</span></td>
        <td><span class="badge ${b.cls}">${b.text}</span></td>
        <td>
          <div class="t-iters">
            <span class="t-iterbar">${blocks}${pending}</span>
            <span class="t-itertext">${done}/${totalTxt}</span>
          </div>
        </td>
      </tr>`;
    }).join("");
  }

  /* ══ Inspector ══ */
  function renderInspectorEmpty() {
    inspEl.innerHTML = `<div class="insp-empty">点击列表行查看详情</div>`;
  }

  async function selectLoop(id) {
    st.selId = id;
    st.openRunId = null;
    st.runDetail = null;
    st.msgCase = null;
    st.consoleBuf = [];
    st.consoleEnd = null;
    st._lastSig = null;
    closeStream();                       // 切换选中：先关旧流，防串写缓冲
    rowsEl.querySelectorAll("tr.selected").forEach((tr) =>
      tr.classList.toggle("selected", tr.dataset.id === id));
    try {
      const data = await apiFetch(`/api/loops/${encodeURIComponent(id)}`).then((r) => r.json());
      if (data.error) { renderInspectorEmpty(); return; }
      st.selLoop = data;
      renderInspector();
      startStatusPoll();
      syncConsole();
      refreshRuns();
    } catch { renderInspectorEmpty(); }
  }

  function closeInspector() {
    st.selId = null;
    st.selLoop = null;
    stopStatusPoll();
    closeStream();
    renderInspectorEmpty();
    rowsEl.querySelectorAll("tr.selected").forEach((tr) => tr.classList.remove("selected"));
  }

  function renderInspector() {
    const l = st.selLoop;
    if (!l) { renderInspectorEmpty(); return; }
    const b = loopBadge(l);
    const dur = (l.jobs || []).reduce((s, j) => s + (j.job_duration_s || 0), 0);

    /* 失败原因横幅：优先 stop_reason（warn），否则最近失败轮次的 failed_reason（fail） */
    let banner = "";
    if (l.stop_reason) {
      banner = `<div class="banner warn">已停止：${esc(l.stop_reason)}</div>`;
    } else if (l.fail_iters > 0 || l.status === "failed") {
      const failJob = [...(l.jobs || [])].reverse().find((j) => j.status === "fail" || j.status === "setup_fail");
      const reason = failJob?.failed_reason || "存在失败轮次";
      banner = `<div class="banner fail">失败原因：${esc(reason)}</div>`;
    }

    inspEl.innerHTML = `
      <div class="insp-head">
        <span class="insp-title">循环详情</span>
        <button type="button" class="insp-close" id="insp-close" title="关闭">
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
            <path d="M2 2l10 10M12 2L2 12" stroke="#8A8F96" stroke-width="1.6" stroke-linecap="round"/>
          </svg>
        </button>
      </div>
      <div class="insp-body">
        <div class="insp-idrow">
          <span class="insp-id">${esc(l.id)}</span>
          <span class="badge ${b.cls}">${b.text}</span>
        </div>

        <div class="insp-stats">
          <div class="insp-stat"><div class="k">计划</div><div class="v">${l.repeat_total > 0 ? l.repeat_total : "∞"}</div></div>
          <div class="insp-stat"><div class="k">PASS</div><div class="v pass">${l.passed_iters}</div></div>
          <div class="insp-stat"><div class="k">FAIL</div><div class="v fail">${l.fail_iters}</div></div>
          <div class="insp-stat"><div class="k">时长</div><div class="v">${esc(fmtDur(dur))}</div></div>
        </div>

        <div class="insp-meta">
          <div class="insp-meta-row">
            <span class="k">环境</span>
            <span class="v"><i class="lock-dot" style="background:${LOCK_DOT[lockState(l)]}"></i>${esc(l.env_name)}</span>
          </div>
          <div class="insp-meta-row">
            <span class="k">Git</span>
            <span class="v">${esc(l.git_ref)}${l.firmware_build ? ` · ${esc(l.firmware_branch || "")} ${esc(l.firmware_build)}` : ""}</span>
          </div>
          <div class="insp-meta-row">
            <span class="k">开始于</span>
            <span class="v">${esc(l.created_at || "—")}</span>
          </div>
        </div>

        ${banner}
        <button type="button" class="btn btn-ghost insp-open" id="insp-open">在运行台中打开</button>

        <div id="insp-console"></div>

        <div id="insp-runs"></div>
      </div>
    `;
    $("#insp-close").addEventListener("click", closeInspector);
    $("#insp-open").addEventListener("click", () => {
      location.hash = `#/console?loop=${encodeURIComponent(l.id)}`;
    });
    renderConsoleBlock();
    renderRuns();
  }

  function lockState(l) {
    const env = l.env_lock || {};
    if (env.stale) return "stale";
    if (env.held) return "held";
    return "free";
  }

  /* ══ run 迷你表 + case 子表 ══ */
  async function refreshRuns() {
    if (!st.selId) return;
    try {
      const runs = await apiFetch(`/api/runs?loop_id=${encodeURIComponent(st.selId)}`).then((r) => r.json());
      st.runs = Array.isArray(runs) ? runs : [];
      renderRuns();
    } catch { /* 静默 */ }
  }

  function renderRuns() {
    const box = $("#insp-runs");
    if (!box) return;
    if (!st.runs.length) {
      box.innerHTML = `
        <div class="runs-mini">
          <div class="runs-mini-head"><span class="insp-title">Runs</span></div>
          <div class="tasks-empty" style="padding:20px 0">暂无 run 记录</div>
        </div>`;
      return;
    }
    const sorted = [...st.runs].sort((a, b) => (a.iteration || 0) - (b.iteration || 0));
    const rows = sorted.map((r) => {
      const b = runBadge(r.status);
      const open = r.run_id === st.openRunId;
      return `
      <tr class="rrow ${open ? "open" : ""}" data-run="${esc(r.run_id)}">
        <td class="mono">#${esc(r.iteration ?? "—")}</td>
        <td class="rid-mono">${esc(r.run_id)}</td>
        <td><span class="badge ${b.cls}">${b.text}</span></td>
        <td class="mono">${r.status === "running" ? "—" : `${r.passed ?? "—"}/${r.total ?? "—"}`}</td>
        <td class="mono">${esc(fmtDur(r.job_duration_s))}</td>
      </tr>
      ${open ? renderRunDetail() : ""}`;
    }).join("");
    box.innerHTML = `
      <div class="runs-mini">
        <div class="runs-mini-head"><span class="insp-title">Runs</span></div>
        <table class="runs-table">
          <thead><tr><th>#</th><th>Run ID</th><th>状态</th><th>Pass</th><th>时长</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>`;
    box.querySelectorAll("tr.rrow").forEach((tr) => {
      tr.addEventListener("click", () => toggleRun(tr.dataset.run));
    });
    /* 失败 case 行点击 → message 全文（委托） */
    box.querySelectorAll("tr.cfail").forEach((tr) => {
      tr.addEventListener("click", () => {
        st.msgCase = st.msgCase === tr.dataset.case ? null : tr.dataset.case;
        renderRuns();
      });
    });
  }

  const runBadge = (s) =>
    ({ pass: { cls: "pass", text: "PASS" }, fail: { cls: "fail", text: "FAIL" },
       setup_fail: { cls: "warn", text: "SETUP" }, running: { cls: "running", text: "RUN" } }[s]
      || { cls: "", text: String(s || "—").toUpperCase() });

  function renderRunDetail() {
    const d = st.runDetail;
    if (!d) return `<tr><td colspan="5" class="run-detail">加载 case 明细…</td></tr>`;
    if (!d.cases?.length) {
      return `<tr><td colspan="5" class="run-detail">暂无 case 明细${d.has_summary === false ? "（summary 未生成）" : ""}</td></tr>`;
    }
    const rows = d.cases.map((c, i) => {
      const isFail = c.status === "fail" || c.status === "broken";
      const b = runBadge(c.status === "pass" ? "pass" : c.status === "broken" ? "setup_fail" : "fail");
      return `
      <tr class="${isFail ? "cfail" : ""}" ${isFail ? `data-case="${i}"` : ""}>
        <td class="rid-mono">${esc(c.name)}</td>
        <td><span class="badge ${b.cls}">${b.text}</span></td>
        <td class="mono">${esc(fmtDur(c.duration_s))}</td>
        <td>${c.message ? `<span class="case-msg-cut">${esc(c.message)}</span>` : ""}</td>
      </tr>
      ${isFail && st.msgCase === String(i)
        ? `<tr><td colspan="4" style="padding:0 8px 6px"><div class="case-msg-full">${esc(c.message)}</div></td></tr>`
        : ""}`;
    }).join("");
    return `
      <tr><td colspan="5" class="run-detail">
        <table class="case-table">
          <thead><tr><th>Case</th><th>结果</th><th>耗时</th><th>Message</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </td></tr>`;
  }

  async function toggleRun(runId) {
    if (st.openRunId === runId) {          // 再点收起
      st.openRunId = null;
      st.runDetail = null;
      st.msgCase = null;
      renderRuns();
      return;
    }
    st.openRunId = runId;
    st.runDetail = null;
    st.msgCase = null;
    renderRuns();
    try {
      const d = await apiFetch(`/api/runs/${encodeURIComponent(runId)}`).then((r) => r.json());
      if (d.error) return;
      if (st.openRunId !== runId) return;  // 期间已切换
      st.runDetail = d;
      renderRuns();
    } catch { /* 静默 */ }
  }

  /* ══ 控制台实时（选中 running loop 时）══ */
  function renderConsoleBlock() {
    const box = $("#insp-console");
    if (!box) return;
    const running = st.selLoop?.status === "running";
    if (!running && !st.consoleBuf.length) { box.innerHTML = ""; return; }
    const ended = st.consoleEnd;
    box.innerHTML = `
      <div class="console-block">
        <div class="console-head">控制台<span class="faint mono" style="font-weight:400;margin-left:auto">${running ? "live" : "ended"}</span></div>
        <pre class="console-pre" id="console-pre"></pre>
        ${ended ? `<div class="console-end-banner ${ended}">${ended === "failed" ? "LOOP FAILED" : "LOOP DONE"}</div>` : ""}
      </div>`;
    const pre = $("#console-pre");
    pre.textContent = st.consoleBuf.join("\n");
    if (st.consoleStick) pre.scrollTop = pre.scrollHeight;
    pre.addEventListener("scroll", () => {
      st.consoleStick = pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 24;
    });
  }

  function syncConsole() {
    const running = st.selLoop?.status === "running";
    if (running) startStream();
    else closeStream();
    renderConsoleBlock();
  }

  function startStream() {
    if (st.stream || !st.selId) return;
    st.consoleEnd = null;
    st.consoleStick = true;
    st.stream = openConsoleStream(st.selId, {
      onreset() {
        st.consoleBuf = [];
        const pre = $("#console-pre");
        if (pre) pre.textContent = "";
      },
      onmessage(msg) {
        st.consoleBuf.push(msg.line ?? "");
        const pre = $("#console-pre");
        if (pre) {
          const stick = st.consoleStick;
          pre.textContent = st.consoleBuf.join("\n");
          if (stick) pre.scrollTop = pre.scrollHeight;
        }
      },
      async onend() {
        st.stream = null;
        /* 终态横幅：以最新状态为准（done→绿 / failed→红） */
        try {
          const { loop } = await apiFetch(`/api/loops/${encodeURIComponent(st.selId)}/status`).then((r) => r.json());
          st.consoleEnd = loop?.status === "failed" ? "failed" : "done";
        } catch { st.consoleEnd = "done"; }
        renderConsoleBlock();
        refreshList();
      },
      onerror() { /* EventSource 自动重连；mock 流不触发 */ },
    });
  }

  function closeStream() {
    st.stream?.close();
    st.stream = null;
  }

  /* ══ 轮询 ══ */
  let statusTimer = null;
  function startStatusPoll() {
    stopStatusPoll();
    statusTimer = setInterval(pollStatus, 3000);   // Inspector 打开时 3s
    timers.add(statusTimer);
  }
  function stopStatusPoll() {
    if (statusTimer) { clearInterval(statusTimer); timers.delete(statusTimer); statusTimer = null; }
  }

  async function pollStatus() {
    if (!st.selId) return;
    try {
      const { loop } = await apiFetch(`/api/loops/${encodeURIComponent(st.selId)}/status`).then((r) => r.json());
      if (!loop || !st.selLoop) return;
      const sig = JSON.stringify([loop.status, loop.passed_iters, loop.fail_iters, loop.iterations, loop.iteration_statuses]);
      if (sig === st._lastSig) return;
      st._lastSig = sig;
      const wasRunning = st.selLoop.status === "running";
      Object.assign(st.selLoop, loop);
      renderInspector();
      if (wasRunning && loop.status !== "running") {
        /* 运行结束：刷新列表，控制台交给 onend 收尾 */
        refreshList();
      } else {
        syncConsole();
      }
    } catch { /* 静默 */ }
  }

  /* ══ 事件绑定 ══ */
  $("#tf-days").addEventListener("change", (e) => { st.days = e.target.value; refreshList(); });
  $("#tf-env").addEventListener("change", (e) => { st.env = e.target.value; refreshList(); });
  $("#tf-status").addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-s]");
    if (!btn) return;
    st.status = btn.dataset.s;
    $("#tf-status").querySelectorAll("button").forEach((b) => b.classList.toggle("active", b === btn));
    refreshList();
  });
  rowsEl.addEventListener("click", (e) => {
    const tr = e.target.closest("tr[data-id]");
    if (tr && tr.dataset.id !== st.selId) selectLoop(tr.dataset.id);
  });

  /* 环境下拉 */
  apiFetch("/api/envs").then((r) => r.json()).then((envs) => {
    const sel = $("#tf-env");
    (Array.isArray(envs) ? envs : []).forEach((e) => {
      const opt = document.createElement("option");
      opt.value = e.id;
      opt.textContent = e.name + (e.disabled ? "（停用）" : "");
      sel.appendChild(opt);
    });
  }).catch(() => {});

  /* ══ 启动 + 卸载清理 ══ */
  renderInspectorEmpty();
  refreshList();
  timers.add(setInterval(refreshList, 5000));      // 列表 5s

  const cleanup = () => {
    timers.forEach((t) => clearInterval(t));
    timers.clear();
    stopStatusPoll();
    closeStream();
  };
  /* 视图被替换（路由切换 / 登出重渲染）时自动清理全部 timer 与 SSE */
  const mo = new MutationObserver(() => {
    if (!root.isConnected) { cleanup(); mo.disconnect(); }
  });
  mo.observe(el, { childList: true });
}
