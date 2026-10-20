<script setup>
/* 数据看板（P5）：时间范围 + KPI 卡 + 通过率趋势（SVG）+ 失败 Case Top + 循环 iteration */
import { ref, computed, onMounted, onUnmounted } from "vue";
import { NCard, NSelect } from "naive-ui";
import { apiFetch, asJson } from "../api/client.js";
import { lineChartSvg, iterColor } from "../utils/chart.js";

const days = ref(14);
const stats = ref(null);
let timer = null;

const daysOptions = [
  { value: 7, label: "近 7 天" },
  { value: 14, label: "近 14 天" },
  { value: 30, label: "近 30 天" },
];

async function load() {
  try {
    stats.value = await asJson(await apiFetch(`/api/stats?days=${days.value}`));
  } catch { /* 瞬时错误忽略 */ }
}
function onRangeChange(v) { days.value = v; load(); }

onMounted(() => { load(); timer = setInterval(load, 30000); });
onUnmounted(() => { if (timer) clearInterval(timer); });

const kpis = computed(() => {
  const s = stats.value;
  if (!s) return [];
  const pr = s.pass_rate != null ? Math.round(s.pass_rate * 100) + "%" : "—";
  return [
    { label: "jobs 总数", value: s.jobs ?? "—" },
    { label: "loops", value: s.loops ?? "—" },
    { label: "运行中", value: s.running ?? 0 },
    { label: "pass 率", value: pr },
    { label: "失败 jobs", value: s.failed_jobs ?? 0 },
    { label: "broken jobs", value: s.broken_jobs ?? 0 },
  ];
});
const trendSvg = computed(() => lineChartSvg((stats.value?.trend || []).map((t) => ({ date: t.date, value: t.pass_rate }))));
const fails = computed(() => {
  const list = stats.value?.fail_cases || [];
  const max = Math.max(1, ...list.map((f) => f.count));
  return list.map((f) => ({ ...f, pct: Math.round((f.count / max) * 100) }));
});
const loopBars = computed(() => stats.value?.loop_bars || []);
</script>

<template>
  <div class="view-head">
    <h1 class="view-title">数据看板</h1>
    <span class="faint" style="font-size: 12.5px">近 {{ days }} 天 · 全部环境（30s 自动刷新）</span>
    <span class="spacer"></span>
    <n-select :value="days" :options="daysOptions" size="small" style="width: 130px" @update:value="onRangeChange" />
  </div>

  <div class="kpi-row">
    <n-card v-for="k in kpis" :key="k.label" size="small" class="kpi">
      <div class="kpi-v mono">{{ k.value }}</div>
      <div class="kpi-k faint">{{ k.label }}</div>
    </n-card>
  </div>

  <div class="chart-row">
    <n-card size="small" class="chart-card">
      <template #header><span style="font-size: 13.5px; font-weight: 600">通过率趋势</span></template>
      <div v-html="trendSvg"></div>
    </n-card>
    <n-card size="small" class="chart-card">
      <template #header><span style="font-size: 13.5px; font-weight: 600">失败 Case Top</span></template>
      <div v-if="!fails.length" class="faint" style="padding: 24px 0; text-align: center; font-size: 12.5px">暂无失败记录</div>
      <div v-for="f in fails" :key="f.name" class="fail-row">
        <span class="fail-name" :title="f.name">{{ f.name }}</span>
        <div class="fail-bar-wrap"><div class="fail-bar" :style="{ width: f.pct + '%' }"></div></div>
        <span class="fail-count mono">{{ f.count }}</span>
      </div>
    </n-card>
  </div>

  <n-card size="small" style="margin-top: 14px">
    <template #header><span style="font-size: 13.5px; font-weight: 600">循环 iteration</span></template>
    <div v-if="!loopBars.length" class="faint" style="padding: 12px 0; font-size: 12.5px">暂无循环记录</div>
    <div v-for="(r, i) in loopBars" :key="i" class="lb-row">
      <span class="lb-meta faint" :title="`${r.created_at} · ${r.suite}`">{{ r.created_at }} · {{ r.suite }}</span>
      <span class="lb-dots">
        <i
          v-for="(it, j) in r.iterations || []" :key="j"
          :style="{ background: iterColor(it.status) }"
          :title="`第 ${it.iteration} 轮 · ${it.status}`"
        ></i>
      </span>
    </div>
  </n-card>
</template>

<style scoped>
.kpi-row { display: grid; grid-template-columns: repeat(6, 1fr); gap: 12px; margin-bottom: 14px; }
@media (max-width: 1200px) { .kpi-row { grid-template-columns: repeat(3, 1fr); } }
.kpi :deep(.n-card__content) { text-align: center; padding: 12px 8px; }
.kpi-v { font-size: 19px; font-weight: 700; }
.kpi-k { font-size: 11.5px; }
.chart-row { display: grid; grid-template-columns: 3fr 2fr; gap: 14px; }
@media (max-width: 1080px) { .chart-row { grid-template-columns: 1fr; } }
.fail-row { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; font-size: 12.5px; }
.fail-name { width: 42%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.fail-bar-wrap { flex: 1; height: 10px; background: var(--surface-sub); border-radius: 5px; overflow: hidden; }
.fail-bar { height: 100%; background: var(--accent); border-radius: 5px; }
.fail-count { flex: none; color: var(--ink-2); }
.lb-row { display: flex; align-items: center; gap: 12px; padding: 6px 0; border-bottom: 1px solid var(--line-soft); font-size: 12.5px; }
.lb-row:last-child { border-bottom: none; }
.lb-meta { width: 300px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.lb-dots { display: flex; gap: 5px; }
.lb-dots i { width: 11px; height: 11px; border-radius: 3px; display: inline-block; }
</style>
