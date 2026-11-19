<script setup>
/* 任务中心 Inspector：选中 loop 的详情（摘要 + jobs + 概览 + SSE 控制台）。
 * 自管理轮询与流实例——不与运行台共享绑定，互不干扰 */
import { ref, computed, onMounted, onUnmounted, watch } from "vue";
import { NCard, NTabs, NTabPane, NButton, NTable, NSelect, NEmpty, useMessage } from "naive-ui";
import { apiFetch, asJson } from "../../api/client.js";
import { createConsoleStream } from "../../composables/useConsoleStream.js";
import { fmtDuration } from "../../utils/format.js";
import OverviewTab from "../console/OverviewTab.vue";
import ConsoleStream from "../console/ConsoleStream.vue";
import { useAuthStore } from "../../stores/auth.js";
import StatusTag from "../common/StatusTag.vue";

const props = defineProps({
  loopId: { type: String, required: true },
});
const emit = defineEmits(["changed"]);
const $msg = useMessage();
const auth = useAuthStore();

const loop = ref(null);
const missing = ref(false);
const stream = createConsoleStream();
const comparison = ref(null);
const comparing = ref(false);
const baseRunId = ref("");
const targetRunId = ref("");
let timer = null;

async function load() {
  try {
    const d = await asJson(await apiFetch(`/api/loops/${encodeURIComponent(props.loopId)}/status`));
    if (!d?.loop) { missing.value = true; return; }
    const prev = loop.value?.status;
    loop.value = d.loop;
    const runIds = (d.loop.jobs || []).filter((j) => j.run_id).map((j) => j.run_id);
    if (!targetRunId.value && runIds.length) targetRunId.value = runIds[runIds.length - 1];
    if (!baseRunId.value && runIds.length > 1) baseRunId.value = runIds[runIds.length - 2];
    if (d.loop.status !== prev) emit("changed");
  } catch (err) { $msg.error(err.message || "加载失败"); }
}

onMounted(async () => {
  await load();
  stream.open(props.loopId);
  timer = setInterval(load, 5000);
});
onUnmounted(() => { if (timer) clearInterval(timer); stream.close(); });
watch(() => props.loopId, () => { /* 外部切换 loopId 时整组件重建（:key） */ });

const running = computed(() => loop.value?.status === "running");
const jobs = computed(() => loop.value?.jobs || []);
const latestRun = computed(() => [...jobs.value].reverse().find((j) => j.run_id && j.has_summary));
const runOptions = computed(() => jobs.value.filter((j) => j.run_id).map((j) => ({
  value: j.run_id, label: `#${j.iteration} · ${j.run_id} · ${j.status}`,
})));

async function compareRuns() {
  if (!baseRunId.value || !targetRunId.value) return;
  comparing.value = true;
  try {
    const q = new URLSearchParams({ base_run_id: baseRunId.value, target_run_id: targetRunId.value });
    comparison.value = await asJson(await apiFetch(`/api/run-comparisons?${q}`));
  } catch (err) { $msg.error(err.message || "对比失败"); }
  finally { comparing.value = false; }
}

async function onStop() {
  try {
    const d = await apiFetch(`/api/loops/${encodeURIComponent(props.loopId)}/stop`, { method: "POST" });
    $msg.info(d.message || "已请求停止");
    load();
  } catch (err) { $msg.error(err.message || "停止失败"); }
}
</script>

<template>
  <div class="insp">
    <div v-if="missing" class="faint" style="padding: 20px; text-align: center">该任务不存在或已被清理</div>
    <template v-else-if="loop">
      <n-card size="small">
        <template #header><span class="mono" style="font-size: 14px">{{ loop.id }}</span></template>
        <template #header-extra>
          <StatusTag :status="loop.status" />
        </template>
        <div class="meta-line faint">
          {{ loop.env_name || loop.env_id || "—" }} · {{ loop.product || "—" }} ·
          {{ loop.suite || loop.test || "—" }} · {{ loop.owner_name || "" }}
        </div>
        <div class="meta-line">
          耗时 <b class="mono">{{ fmtDuration(loop) }}</b>
          <span class="faint" style="margin-left: 10px">轮次 {{ loop.iterations ?? 0 }} / {{ loop.repeat_total || "∞" }}</span>
          <n-button v-if="auth.user && running" size="tiny" type="error" secondary style="margin-left: 12px" @click="onStop">
            停止
          </n-button>
        </div>
      </n-card>

      <n-card size="small" :content-style="{ padding: 0 }">
        <n-tabs type="line" size="small" animated default-value="overview" style="padding: 0 12px">
          <n-tab-pane name="overview" tab="概览">
            <OverviewTab :loop="loop" />
          </n-tab-pane>
          <n-tab-pane name="jobs" tab="轮次记录">
            <n-table size="small" :single-line="false">
              <thead><tr><th>轮次</th><th>状态</th><th>run</th><th>开始</th><th>结束</th></tr></thead>
              <tbody>
                <tr v-if="!jobs.length"><td colspan="5" class="faint" style="text-align:center">暂无轮次</td></tr>
                <tr v-for="j in [...jobs].reverse()" :key="j.id">
                  <td>#{{ j.iteration }}</td>
                  <td><StatusTag :status="j.status" /></td>
                  <td class="mono">{{ j.run_id || "—" }}</td>
                  <td class="mono faint">{{ j.started_at || "—" }}</td>
                  <td class="mono faint">{{ j.ended_at || "—" }}</td>
                </tr>
              </tbody>
            </n-table>
          </n-tab-pane>
          <n-tab-pane name="console" tab="控制台" display-directive="show">
            <ConsoleStream :stream="stream" />
          </n-tab-pane>
          <n-tab-pane name="compare" tab="Run 对比">
            <div class="compare-controls">
              <n-select v-model:value="baseRunId" :options="runOptions" placeholder="基准 Run" />
              <span>→</span>
              <n-select v-model:value="targetRunId" :options="runOptions" placeholder="目标 Run" />
              <n-button type="primary" :loading="comparing" :disabled="!baseRunId || !targetRunId || baseRunId === targetRunId" @click="compareRuns">对比</n-button>
            </div>
            <n-empty v-if="runOptions.length < 2" description="至少需要两个已生成结果的 Run" style="padding: 24px" />
            <template v-else-if="comparison">
              <div class="delta-grid">
                <div><b>{{ comparison.delta.pass_rate > 0 ? "+" : "" }}{{ comparison.delta.pass_rate }}%</b><span>通过率变化</span></div>
                <div><b>{{ comparison.delta.duration_s > 0 ? "+" : "" }}{{ comparison.delta.duration_s }}s</b><span>耗时变化</span></div>
                <div><b>{{ comparison.delta.failed > 0 ? "+" : "" }}{{ comparison.delta.failed }}</b><span>失败变化</span></div>
                <div><b>{{ comparison.changes.regressions.length }}</b><span>新增失败</span></div>
              </div>
              <div v-for="group in [
                ['regressions', '新增失败'],
                ['fixed', '已修复'],
                ['unchanged_failures', '持续失败'],
                ['added', '新增用例'],
                ['removed', '移除用例'],
              ]" :key="group[0]" class="change-group">
                <h4>{{ group[1] }}（{{ comparison.changes[group[0]].length }}）</h4>
                <div v-if="!comparison.changes[group[0]].length" class="faint">无</div>
                <div v-for="item in comparison.changes[group[0]]" :key="`${item.name}-${item.seq}`" class="case-change">
                  <span class="mono">{{ item.name }}</span><span class="spacer"></span>
                  <StatusTag v-if="item.base_status" :status="item.base_status" /><span>→</span>
                  <StatusTag v-if="item.target_status" :status="item.target_status" />
                </div>
              </div>
            </template>
          </n-tab-pane>
          <template #suffix>
            <a
              v-if="latestRun"
              class="mono faint" style="font-size: 12px"
              :href="`/runs/${encodeURIComponent(latestRun.run_id)}/summary.html`"
              target="_blank" rel="noopener"
            >summary.html</a>
          </template>
        </n-tabs>
      </n-card>
    </template>
    <div v-else class="faint" style="padding: 30px; text-align: center">加载中…</div>
  </div>
</template>

<style scoped>
.insp { display: flex; flex-direction: column; gap: 14px; min-width: 0; }
.meta-line { font-size: 12.5px; color: var(--ink-2); margin-bottom: 4px; }
.meta-line b { font-size: 13px; color: var(--ink); }
.compare-controls { display: grid; grid-template-columns: 1fr auto 1fr auto; gap: 8px; align-items: center; margin: 12px 0; }
.delta-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin: 12px 0; }
.delta-grid > div { padding: 10px; border-radius: 6px; background: var(--surface-sub); display: flex; flex-direction: column; }
.delta-grid b { font-size: 17px; }
.delta-grid span { font-size: 11px; color: var(--ink-3); }
.change-group h4 { margin: 14px 0 6px; }
.case-change { display: flex; align-items: center; gap: 6px; padding: 4px 6px; border-bottom: 1px solid var(--line-soft); font-size: 12px; }
.case-change .spacer { flex: 1; }
@media (max-width: 700px) {
  .compare-controls { grid-template-columns: 1fr; }
  .delta-grid { grid-template-columns: repeat(2, 1fr); }
}
</style>
