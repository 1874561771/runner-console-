<script setup>
/* 任务中心（P4）：统计卡 + 过滤条 + 任务列表 + 右侧 Inspector（:key 切换重建） */
import { ref, computed, onMounted } from "vue";
import { NCard, NButton, NSelect, NEmpty, NPopconfirm, NSpin, useMessage } from "naive-ui";
import { apiFetch, asJson } from "../api/client.js";
import Inspector from "../components/tasks/Inspector.vue";
import { useAuthStore } from "../stores/auth.js";
import StatusTag from "../components/common/StatusTag.vue";

const $msg = useMessage();
const auth = useAuthStore();

const rows = ref([]);
const loading = ref(true);
const selectedId = ref("");
const stats = ref(null);
const queue = ref([]);

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
const queueDisplay = computed(() => [...queue.value].sort((a, b) => {
  if (a.status === "queued" && b.status !== "queued") return -1;
  if (a.status !== "queued" && b.status === "queued") return 1;
  return a.status === "queued"
    ? String(a.created_at).localeCompare(String(b.created_at))
    : String(b.created_at).localeCompare(String(a.created_at));
}));

onMounted(async () => {
  envs.value = await apiFetch("/api/envs").then(asJson).catch(() => []);
  if (!Array.isArray(envs.value)) envs.value = [];
  envOptions.value = [{ value: "", label: "全部环境" },
    ...envs.value.map((e) => ({ value: e.id, label: e.name }))];
  stats.value = auth.user
    ? await apiFetch("/api/stats").then(asJson).catch(() => null)
    : null;
  await load();
  if (auth.user) await loadQueue();
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

async function loadQueue() {
  try {
    const d = await apiFetch("/api/run-queue").then(asJson);
    queue.value = Array.isArray(d) ? d : [];
  } catch (err) { $msg.error(err.message || "加载队列失败"); }
}

async function cancelQueue(item) {
  try {
    await apiFetch(`/api/run-queue/${item.id}`, { method: "DELETE" });
    $msg.success("队列任务已取消");
    loadQueue();
  } catch (err) { $msg.error(err.message || "取消失败"); }
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

  <n-card v-if="auth.user && queue.length" title="任务队列" size="small" class="queue-card">
    <div v-for="item in queueDisplay.slice(0, 10)" :key="item.id" class="queue-item">
      <span v-if="item.status === 'queued'" class="mono queue-pos">#{{ queueDisplay.filter((x) => x.status === "queued").indexOf(item) + 1 }}</span>
      <StatusTag :status="item.status" />
      <span class="mono">{{ item.id }}</span>
      <span>{{ item.env_name }}</span>
      <span class="faint">{{ item.params?.suite || item.params?.test || `${item.params?.cases?.length || 0} cases` }}</span>
      <span class="spacer"></span>
      <span v-if="item.note" class="faint queue-note">{{ item.note }}</span>
      <router-link v-if="item.loop_id" :to="`/console?loop=${item.loop_id}`" class="mono link">{{ item.loop_id }}</router-link>
      <n-popconfirm v-if="['queued', 'failed'].includes(item.status)" @positive-click="cancelQueue(item)">
        <template #trigger><n-button size="tiny" type="error" secondary>取消</n-button></template>
        确定取消该队列任务？
      </n-popconfirm>
    </div>
  </n-card>

  <div class="tk-layout">
    <n-spin :show="loading">
      <n-card size="small" class="tk-list">
        <n-empty v-if="!rows.length && !loading" description="没有符合筛选条件的任务" style="padding: 24px 0" />
        <div
          v-for="l in rows" :key="l.id" role="button" tabindex="0"
          class="tk-item" :class="{ on: selectedId === l.id }"
          @click="selectedId = l.id"
          @keydown.enter.prevent="selectedId = l.id"
          @keydown.space.prevent="selectedId = l.id"
        >
          <StatusTag :status="l.status" />
          <span class="mono rid">{{ l.id }}</span>
          <span class="faint" style="font-size: 11.5px">{{ l.env_name || "" }} · {{ l.suite || l.test || "" }}</span>
          <span class="spacer"></span>
          <n-popconfirm v-if="auth.user && l.status === 'running'" @positive-click="onStop(l)">
            <template #trigger>
              <n-button size="tiny" type="error" secondary @click.stop>停止</n-button>
            </template>
            确定停止「{{ l.id }}」？
          </n-popconfirm>
          <span class="faint mono" style="font-size: 11px">{{ l.created_at || "" }}</span>
        </div>
      </n-card>
    </n-spin>

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
.queue-card { margin-bottom: 14px; }
.queue-item { display: flex; align-items: center; gap: 8px; min-height: 30px; font-size: 12px; }
.queue-item .spacer { flex: 1; }
.queue-pos { width: 28px; color: var(--accent); }
.queue-note { max-width: 260px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.link { color: var(--accent); }
.tk-layout { display: grid; grid-template-columns: 380px minmax(0, 1fr); gap: 16px; align-items: start; }
.tk-layout > :deep(.n-spin-container) { min-width: 0; }
@media (max-width: 1080px) { .tk-layout { grid-template-columns: 1fr; } }
.tk-item {
  display: flex; align-items: center; gap: 8px; padding: 7px 10px;
  border-radius: 6px; cursor: pointer;
}
.tk-item:hover { background: var(--surface-sub); }
.tk-item.on { background: var(--accent-soft); }
.tk-item:focus-visible { outline: 2px solid var(--accent); outline-offset: 1px; }
.tk-item .spacer { flex: 1; }
.rid { font-size: 12px; }
@media (max-width: 768px) {
  .stat-row { grid-template-columns: repeat(2, 1fr); }
  .filter-row { flex-wrap: wrap; }
  .filter-row :deep(.n-select) { flex: 1 1 130px; width: auto !important; }
}
</style>
