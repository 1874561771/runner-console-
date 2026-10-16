/* ═══════════════════════════════════════════════════════════════
   #/dashboard — 数据看板（T12 实现）
   页头（时间范围下拉）+ KPI 6 卡 + 通过率趋势（纯 SVG，chart-lite）
   + 失败 Case Top 横条 + 循环 iteration 色条。
   数据：GET /api/stats?days=N（7/14/30）；30s 轮询，路由切换时 destroy 清理 timer。
   ═══════════════════════════════════════════════════════════════ */
import { apiFetch } from "../api.js";
import { esc, skeletonRows, emptyState } from "../ui.js";
import { renderLineChart } from "../chart-lite.js";

let viewEl = null;
let timer = null;
let days = 14;

/* 视图卸载：清理轮询 timer（router.js 在切路由前调用） */
export function destroy() {
  if (timer) { clearInterval(timer); timer = null; }
}

export async function render(el) {
  destroy();
  viewEl = el;
  el.innerHTML = `
    <div class="view-head">
      <div>
        <h1 class="view-title">数据看板</h1>
        <div class="view-sub" id="dash-sub">近 ${days} 天 · 全部环境</div>
      </div>
      <select class="select" id="dash-range" style="width:130px" aria-label="时间范围">
        <option value="7">近 7 天</option>
        <option value="14">近 14 天</option>
        <option value="30">近 30 天</option>
      </select>
    </div>
    <div id="dash-body">${skeletonRows(3, 5)}</div>`;

  const range = el.querySelector("#dash-range");
  range.value = String(days);
  range.addEventListener("change", () => {
    days = Number(range.value) || 14;
    load();
  });

  await load();
  timer = setInterval(load, 30000);
}

async function load() {
  const body = viewEl.querySelector("#dash-body");
  const sub = viewEl.querySelector("#dash-sub");
  if (!body) return destroy();
  if (sub) sub.textContent = `近 ${days} 天 · 全部环境`;

  let s;
  try {
    const res = await apiFetch(`/api/stats?days=${days}`);
    s = await res.json();
    if (!res.ok || s.error) throw new Error(s.error || "加载失败");
  } catch (err) {
    body.innerHTML = emptyState("看板加载失败", err.message || "请稍后重试");
    return;
  }
  body.innerHTML = renderKpis(s) + renderCharts(s) + renderLoopBars(s);
  /* trend 契约：{date, pass_rate} → chart-lite {date, value} */
  renderLineChart(body.querySelector("#trend-chart"),
    (s.trend || []).map((t) => ({ date: t.date, value: t.pass_rate })));
}

/* ── KPI 6 卡：JOBS / LOOPS / 通过率 / 进行中 / 失败 / BROKEN ── */
function renderKpis(s) {
  const rate = typeof s.pass_rate === "number" ? (s.pass_rate * 100).toFixed(1) + "%" : "—";
  const items = [
    { k: "JOBS",      v: s.jobs ?? "—" },
    { k: "LOOPS",     v: s.loops ?? "—" },
    { k: "通过率",    v: rate },
    { k: "进行中",    v: s.running ?? "—",     cls: "v-accent" },
    { k: "失败 JOBS", v: s.failed_jobs ?? "—", cls: "v-fail" },
    { k: "BROKEN",    v: s.broken_jobs ?? "—", cls: "v-warn" },
  ];
  return `<div class="kpi dash-kpis">
    ${items.map((i) => `<div class="card kpi-item">
      <div class="kpi-key">${esc(i.k)}</div>
      <div class="kpi-val ${i.cls || ""}">${esc(String(i.v))}</div>
    </div>`).join("")}
  </div>`;
}

/* ── 图表行：左通过率趋势（自适应）+ 右失败 Case Top（480px）── */
function renderCharts(s) {
  const fails = s.fail_cases || [];
  const max = Math.max(1, ...fails.map((f) => f.count));
  const bars = fails.length
    ? fails.map((f) => `
        <div class="failbar-row">
          <span class="failbar-name" title="${esc(f.name)}">${esc(f.name)}</span>
          <span class="failbar-track"><span class="failbar-fill" style="width:${Math.round((f.count / max) * 100)}%"></span></span>
          <span class="failbar-count">×${f.count}</span>
        </div>`).join("")
    : emptyState("近期没有失败 Case");
  return `<div class="chart-row">
    <div class="card chart-card">
      <div class="card-head">
        <span class="card-title">通过率趋势</span>
        <span class="faint" style="margin-left:auto;font-size:11px">%</span>
      </div>
      <div class="chart-wrap" id="trend-chart"></div>
    </div>
    <div class="card chart-card">
      <div class="card-head"><span class="card-title">失败 Case Top</span></div>
      <div class="chart-wrap">${bars}</div>
    </div>
  </div>`;
}

/* ── 循环 iteration 色条：日期 · suite + 12×12 轮次色块 ─────── */
function renderLoopBars(s) {
  const rows = s.loop_bars || [];
  const body = rows.length
    ? rows.map((r) => `
        <div class="loopbar-row">
          <span class="loopbar-meta" title="${esc(r.created_at)} · ${esc(r.suite)}">${esc(r.created_at)} · ${esc(r.suite)}</span>
          <span class="iterbar">${(r.iterations || []).map((it) =>
            `<i class="${esc(it.status)}" title="第 ${it.iteration} 轮 · ${esc(it.status)}"></i>`).join("")}</span>
        </div>`).join("")
    : emptyState("暂无循环任务");
  return `<div class="card" style="margin-top:16px">
    <div class="card-head"><span class="card-title">循环 iteration</span></div>
    <div class="card-pad">${body}</div>
  </div>`;
}
