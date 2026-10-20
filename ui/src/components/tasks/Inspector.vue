<script setup>
/* 任务中心 Inspector：选中 loop 的详情（摘要 + jobs + 概览 + SSE 控制台）。
 * 自管理轮询与流实例——不与运行台共享绑定，互不干扰 */
import { ref, computed, onMounted, onUnmounted, watch } from "vue";
import { NCard, NTag, NTabs, NTabPane, NButton, NTable, useMessage } from "naive-ui";
import { apiFetch, asJson } from "../../api/client.js";
import { createConsoleStream } from "../../composables/useConsoleStream.js";
import { fmtDuration } from "../../utils/format.js";
import OverviewTab from "../console/OverviewTab.vue";
import ConsoleStream from "../console/ConsoleStream.vue";

const props = defineProps({
  loopId: { type: String, required: true },
});
const emit = defineEmits(["changed"]);
const $msg = useMessage();

const loop = ref(null);
const missing = ref(false);
const stream = createConsoleStream();
let timer = null;

const STATUS_TAG = {
  running: { type: "info", text: "RUNNING" },
  stopped: { type: "warning", text: "STOPPED" },
  failed: { type: "error", text: "FAILED" },
  done: { type: "success", text: "DONE" },
};

async function load() {
  try {
    const d = await asJson(await apiFetch(`/api/loops/${encodeURIComponent(props.loopId)}/status`));
    if (!d?.loop) { missing.value = true; return; }
    const prev = loop.value?.status;
    loop.value = d.loop;
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
          <n-tag :type="(STATUS_TAG[loop.status] || {}).type || 'default'" :bordered="false">
            {{ (STATUS_TAG[loop.status] || {}).text || loop.status }}
          </n-tag>
        </template>
        <div class="meta-line faint">
          {{ loop.env_name || loop.env_id || "—" }} · {{ loop.product || "—" }} ·
          {{ loop.suite || loop.test || "—" }} · {{ loop.owner_name || "" }}
        </div>
        <div class="meta-line">
          耗时 <b class="mono">{{ fmtDuration(loop) }}</b>
          <span class="faint" style="margin-left: 10px">轮次 {{ loop.iterations ?? 0 }} / {{ loop.repeat_total || "∞" }}</span>
          <n-button v-if="running" size="tiny" type="error" secondary style="margin-left: 12px" @click="onStop">
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
                  <td><n-tag size="small" :type="j.status === 'pass' ? 'success' : j.status === 'fail' ? 'error' : 'warning'" :bordered="false">{{ j.status }}</n-tag></td>
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
</style>
