<script setup>
/* 任务中心（P4）：统计卡 + 过滤条 + 任务列表 + 右侧 Inspector（:key 切换重建） */
import { ref, computed, onMounted } from "vue";
import { NCard, NButton, NTag, NSelect, NEmpty, NPopconfirm, useMessage } from "naive-ui";
import { apiFetch, asJson } from "../api/client.js";
import Inspector from "../components/tasks/Inspector.vue";

const $msg = useMessage();

const rows = ref([]);
const loading = ref(true);
const selectedId = ref("");
const stats = ref(null);

const days = ref("7");
const status = ref("");
const envId = ref("");
const envs = ref([]);

const daysOptions = [
  { value: "today", label: "今天" },
  { value: "7", label: "近 7 天" },
  { value: "14", label: "近 14 天" },
  { value: "30", label: "近 30 天" },
  { value: "all", label: "全部" },
];
const statusOptions = [
  { value: "", label: "全部状态" },
  { value: "running", label: "运行中" },
  { value: "done", label: "已完成" },
  { value: "failed", label: "失败" },
  { value: "stopped", label: "已停止" },
];
const envOptions = ref([]);

const STATUS_TAG = {
  running: { type: "info", text: "RUNNING" },
  stopped: { type: "warning", text: "STOPPED" },
  failed: { type: "error", text: "FAILED" },
  done: { type: "success", text: "DONE" },
};

onMounted(async () => {
  envs.value = await apiFetch("/api/envs").then(asJson).catch(() => []);
  if (!Array.isArray(envs.value)) envs.value = [];
  envOptions.value = [{ value: "", label: "全部环境" },
    ...envs.value.map((e) => ({ value: e.id, label: e.name }))];
  stats.value = await apiFetch("/api/stats").then(asJson).catch(() => null);
  await load();
  // 深链 /tasks?loop=<id>
  const q = new URLSearchParams(location.hash.split("?")[1] || "").get("loop");
  if (q) selectedId.value = q;
  else if (rows.value.length) selectedId.value = rows.value[0].id;
});

async function load() {
  loading.value = true;
  try {
    const q = new URLSearchParams();
    if (days.value) q.set("days", days.value);
    if (status.value) q.set("status", status.value);
    if (envId.value) q.set("env_id", envId.value);
    const d = await asJson(await apiFetch(`/api/loops?${q}`));
    rows.value = Array.isArray(d) ? d : [];
    if (selectedId.value && !rows.value.some((l) => l.id === selectedId.value)) {
      selectedId.value = rows.value[0]?.id || "";
    }
  } catch (err) { $msg.error(err.message || "加载失败"); }
  loading.value = false;
}

function onFilterChange() { load(); }

async function onStop(l) {
  try {
    const d = await apiFetch(`/api/loops/${encodeURIComponent(l.id)}/stop`, { method: "POST" });
    $msg.info(d.message || "已请求停止");
    load();
  } catch (err) { $msg.error(err.message || "停止失败"); }
}

const statCards = computed(() => {
  const s = stats.value;
  if (!s) return [];
  return [
    { label: "近 14 天 loops", value: s.loops ?? "—" },
    { label: "jobs", value: s.jobs ?? "—" },
    { label: "运行中", value: s.running ?? 0 },
    { label: "pass 率", value: s.pass_rate != null ? Math.round(s.pass_rate * 100) + "%" : "—" },
  ];
});
</script>

<template>
  <div class="view-head">
    <h1 class="view-title">任务中心</h1>
    <span class="spacer"></span>
  </div>

  <!-- 统计卡 -->
  <div v-if="statCards.length" class="stat-row">
    <n-card v-for="c in statCards" :key="c.label" size="small" class="stat-card">
      <div class="stat-v mono">{{ c.value }}</div>
      <div class="stat-k faint">{{ c.label }}</div>
    </n-card>
  </div>

  <!-- 过滤条 -->
  <div class="filter-row">
    <n-select v-model:value="days" :options="daysOptions" size="small" style="width: 130px" @update:value="onFilterChange" />
    <n-select v-model:value="status" :options="statusOptions" size="small" style="width: 140px" @update:value="onFilterChange" />
    <n-select v-model:value="envId" :options="envOptions" size="small" style="width: 180px" @update:value="onFilterChange" />
    <span class="spacer"></span>
  </div>

  <div class="tk-layout">
    <n-card size="small" class="tk-list">
      <n-empty v-if="!rows.length && !loading" description="没有符合筛选条件的任务" style="padding: 24px 0" />
      <div
        v-for="l in rows" :key="l.id"
        class="tk-item" :class="{ on: selectedId === l.id }"
        @click="selectedId = l.id"
      >
        <n-tag size="small" :type="(STATUS_TAG[l.status] || {}).type || 'default'" :bordered="false">
          {{ (STATUS_TAG[l.status] || {}).text || l.status }}
        </n-tag>
        <span class="mono rid">{{ l.id }}</span>
        <span class="faint" style="font-size: 11.5px">{{ l.env_name || "" }} · {{ l.suite || l.test || "" }}</span>
        <span class="spacer"></span>
        <n-popconfirm v-if="l.status === 'running'" @positive-click="onStop(l)">
          <template #trigger>
            <n-button size="tiny" type="error" secondary @click.stop>停止</n-button>
          </template>
          确定停止「{{ l.id }}」？
        </n-popconfirm>
        <span class="faint mono" style="font-size: 11px">{{ l.created_at || "" }}</span>
      </div>
    </n-card>

    <div class="tk-right">
      <Inspector v-if="selectedId" :key="selectedId" :loop-id="selectedId" @changed="load" />
      <n-card v-else size="small">
        <n-empty description="点击左侧任务查看详情" style="padding: 30px 0" />
      </n-card>
    </div>
  </div>
</template>

<style scoped>
.stat-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 14px; }
.stat-card :deep(.n-card__content) { text-align: center; }
.stat-v { font-size: 20px; font-weight: 700; }
.stat-k { font-size: 12px; }
.filter-row { display: flex; gap: 10px; margin-bottom: 14px; }
.filter-row .spacer { flex: 1; }
.tk-layout { display: grid; grid-template-columns: 380px minmax(0, 1fr); gap: 16px; align-items: start; }
@media (max-width: 1080px) { .tk-layout { grid-template-columns: 1fr; } }
.tk-item {
  display: flex; align-items: center; gap: 8px; padding: 7px 10px;
  border-radius: 6px; cursor: pointer;
}
.tk-item:hover { background: var(--surface-sub); }
.tk-item.on { background: var(--accent-soft); }
.tk-item .spacer { flex: 1; }
.rid { font-size: 12px; }
</style>
