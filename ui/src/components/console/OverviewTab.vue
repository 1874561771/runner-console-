<script setup>
/* 概览页签：meta / 停止原因 / 运行结果（轮次选择 + case 表，运行中实时） / 材料区 */
import { ref, computed, watch, onUnmounted } from "vue";
import { NSelect, NTag, NTable } from "naive-ui";
import { apiFetch, asJson } from "../../api/client.js";
import { fmtDuration, caseBadge } from "../../utils/format.js";
import MaterialsList from "./MaterialsList.vue";

const props = defineProps({
  loop: { type: Object, required: true },   // loop 视图（含 jobs）
});
const LIVE_INTERVAL = 5000;

const jobs = computed(() => (props.loop.jobs || []).filter((j) => j.run_id));
const latest = computed(() => [...jobs.value].reverse().find((j) => j.run_id) || null);
const running = computed(() => props.loop.status === "running");

const runOptions = computed(() => jobs.value.map((j) => ({
  value: j.run_id,
  label: `第 ${j.iteration} 轮 · ${j.run_id} · ${j.status}`,
})));
const selectedRun = ref("");

/* 已入库的 case 明细 */
const runCases = ref([]);
/* 运行中实时解析 */
const live = ref(null); // {run_id, cases, artifacts}
let liveTimer = null;

const showLive = computed(() => running.value && live.value && live.value.run_id);
const activeRunId = computed(() => showLive.value?.run_id || selectedRun.value || latest.value?.run_id || "");
const displayCases = computed(() => {
  if (showLive.value) return live.value.cases || [];
  return runCases.value;
});
const materialsFiles = computed(() => (showLive.value ? live.value?.artifacts : null) || null);

const materialsEl = ref(null);
/* case 表行点击 → 定位到材料区对应的 case 块（跨组件经 expose 方法） */
function goToCase(i) {
  materialsEl.value?.scrollToCase(i);
}

const fw = computed(() => [props.loop.firmware_branch, props.loop.firmware_build]
  .filter(Boolean).join(" · ") || "—");

watch(latest, (j) => { if (j && !selectedRun.value) selectedRun.value = j.run_id; }, { immediate: true });
watch([selectedRun, running], loadRunData, { immediate: true });

async function loadRunData() {
  stopLive();
  if (!selectedRun.value) return;
  try {
    const d = await asJson(await apiFetch(`/api/runs/${encodeURIComponent(selectedRun.value)}`));
    runCases.value = Array.isArray(d?.cases) ? d.cases : [];
  } catch { runCases.value = []; }
  if (running.value) startLive();
}

async function pollLive() {
  if (!props.loop?.id) return;
  try {
    live.value = await asJson(await apiFetch(`/api/loops/${encodeURIComponent(props.loop.id)}/live-cases`));
  } catch { /* 瞬时错误忽略 */ }
}
function startLive() {
  if (liveTimer) return;
  pollLive();
  liveTimer = setInterval(pollLive, LIVE_INTERVAL);
}
function stopLive() {
  if (liveTimer) { clearInterval(liveTimer); liveTimer = null; }
  live.value = null;
}
onUnmounted(stopLive);
</script>

<template>
  <div class="ov">
    <div class="meta-grid">
      <div><div class="k">Product</div><div class="v">{{ loop.product || "—" }}</div></div>
      <div><div class="k">DUT Model</div><div class="v">{{ loop.dut_model || "—" }}</div></div>
      <div><div class="k">Firmware</div><div class="v">{{ fw }}</div></div>
      <div><div class="k">Duration</div><div class="v mono">{{ fmtDuration(loop) }}</div></div>
    </div>

    <div v-if="loop.stop_reason" class="banner warn">停止原因：{{ loop.stop_reason }}</div>
    <div v-if="loop.failed_reason" class="banner fail">失败原因：{{ loop.failed_reason }}</div>

    <div class="sec-head">
      <span class="sec-label">运行结果</span>
      <n-tag v-if="running" type="info" size="small" round>实时</n-tag>
      <span class="spacer"></span>
      <n-select
        v-if="jobs.length > 1" v-model:value="selectedRun"
        :options="runOptions" size="tiny" style="width: 260px"
      />
      <span v-else-if="latest" class="faint mono" style="font-size: 11.5px">run {{ latest.run_id }}</span>
    </div>

    <n-table size="small" :single-line="false" class="cases-table">
      <thead>
        <tr><th>Case</th><th>Result</th><th>Duration</th><th>Message</th></tr>
      </thead>
      <tbody>
        <tr v-if="!displayCases.length">
          <td colspan="4" class="faint" style="text-align:center">
            {{ running ? "等待第一个 case 开始…" : "该 run 没有 case 明细" }}
          </td>
        </tr>
        <tr v-for="(c, i) in displayCases" :key="c.name" class="case-row" :title="'点击查看该 case 的日志与截图'"
          @click="goToCase(i)">
          <td class="mono cname">{{ c.name.split("/").pop() }}</td>
          <td><n-tag size="small" :type="caseBadge(c.status).tag" :bordered="false">{{ caseBadge(c.status).text }}</n-tag></td>
          <td class="mono">{{ c.duration_s != null ? c.duration_s + "s" : "—" }}</td>
          <td class="msg faint">{{ c.message || "—" }}</td>
        </tr>
      </tbody>
    </n-table>

    <div class="sec-head" style="margin-top: 14px">
      <span class="sec-label">材料</span>
      <span v-if="activeRunId" class="faint mono" style="font-size: 11.5px">Run {{ activeRunId }}</span>
    </div>
    <MaterialsList
      v-if="activeRunId" ref="materialsEl" :run-id="activeRunId"
      :files="materialsFiles" :cases="displayCases"
    />
  </div>
</template>

<style scoped>
.meta-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-bottom: 12px; }
.meta-grid .k { font-size: 11.5px; color: var(--ink-3); }
.meta-grid .v { font-size: 13px; font-weight: 600; word-break: break-all; }
.banner { padding: 8px 10px; border-radius: 6px; font-size: 12.5px; margin-bottom: 10px; }
.banner.warn { background: #fdf6ec; color: #b8860b; }
.banner.fail { background: #fdeef0; color: #c0392b; }
.sec-head { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.sec-label { font-size: 13px; font-weight: 700; }
.sec-head .spacer { flex: 1; }
.cases-table :deep(td) { font-size: 12.5px; }
.cases-table :deep(th) { font-size: 12px; }
.cases-table :deep(.case-row) { cursor: pointer; }
.cases-table :deep(.case-row:hover td) { background: var(--accent-soft); }
.cname { word-break: break-all; }
.msg { max-width: 320px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
