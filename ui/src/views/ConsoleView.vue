<script setup>
/* 运行台（P1a/P1b）：左 = 配置卡 + 最近任务；右 = 详情面板（概览/控制台） */
import { onMounted, onUnmounted, ref, computed } from "vue";
import { NCard, NButton, NEmpty, NSpin, useMessage } from "naive-ui";
import { useConsoleStore } from "../stores/consoleStore.js";
import { apiFetch, asJson } from "../api/client.js";
import ConfigCard from "../components/console/ConfigCard.vue";
import DetailPanel from "../components/console/DetailPanel.vue";
import { useAuthStore } from "../stores/auth.js";
import StatusTag from "../components/common/StatusTag.vue";

const store = useConsoleStore();
const auth = useAuthStore();
const message = useMessage();
const busy = ref(false);
const loading = ref(true);
let pollTimer = null;

onMounted(async () => {
  try {
    await store.loadAll();
    // 深链：/console?loop=<id>（定时任务页/任务中心跳转）
    const urlLoop = new URLSearchParams(location.hash.split("?")[1] || "").get("loop");
    if (!store.loop) {
      const target = (urlLoop && { id: urlLoop }) || store.loops.find((l) => l.status === "running") || store.loops[0];
      if (target) await store.bindLoop(target.id).catch(() => {});
    }
    pollTimer = setInterval(pollLoop, 5000);
  } finally {
    loading.value = false;
  }
});
onUnmounted(() => { if (pollTimer) clearInterval(pollTimer); });

const bound = computed(() => store.loop?.loop || null);
const recent = computed(() => store.loops.slice(0, 8));

/* 5s 轮询绑定 loop 状态；状态变化时刷新最近任务列表 */
async function pollLoop() {
  if (!store.loop) return;
  const id = store.loop.loop.id;
  try {
    const d = await asJson(await apiFetch(`/api/loops/${encodeURIComponent(id)}/status`));
    if (!d?.loop) return;
    const prev = store.loop?.loop?.status;
    store.loop = d;
    if (d.loop.status !== prev) store.refreshLoops();
  } catch { /* 瞬时错误忽略 */ }
}

async function onRun() {
  busy.value = true;
  try {
    const d = await apiFetch("/api/run", { method: "POST", body: store.runParams });
    message.success(`loop 已启动：${d.loop_id}`);
    await store.bindLoop(d.loop_id);
    await store.refreshLoops();
  } catch (err) {
    message.error(err.message || "启动失败");
  } finally { busy.value = false; }
}

async function onStop() {
  if (!bound.value) return;
  try {
    const d = await apiFetch(`/api/loops/${encodeURIComponent(bound.value.id)}/stop`, { method: "POST" });
    message.info(d.message || "已请求停止");
  } catch (err) { message.error(err.message || "停止失败"); }
}

async function pickLoop(id) {
  try { await store.bindLoop(id); } catch (err) { message.error(err.message || "加载失败"); }
}
</script>

<template>
  <div class="view-head">
    <h1 class="view-title">运行台</h1>
    <span class="faint">配置并启动测试，或查看最近任务的实时状态</span>
  </div>
  <n-spin :show="loading">
    <div class="rc-layout">
    <div class="rc-left">
      <ConfigCard v-if="auth.user" @run="onRun" @stop="onStop" />
      <n-card v-else title="游客只读模式" size="small">
        <div class="faint" style="font-size: 12.5px; margin-bottom: 10px">
          可查看公开环境的任务、完整控制台日志和测试产物。登录后可提交任务。
        </div>
        <n-button type="primary" size="small" @click="$router.push({ name: 'login', query: { redirect: $route.fullPath } })">
          登录
        </n-button>
      </n-card>
      <n-card title="最近任务" size="small">
        <template v-if="recent.length">
          <div
            v-for="l in recent" :key="l.id"
            role="button" tabindex="0"
            class="recent-item" :class="{ on: bound?.id === l.id }"
            @click="pickLoop(l.id)"
            @keydown.enter.prevent="pickLoop(l.id)"
            @keydown.space.prevent="pickLoop(l.id)"
          >
            <StatusTag :status="l.status" />
            <span class="mono rid">{{ l.id }}</span>
            <span class="faint" style="font-size: 11.5px">{{ l.created_at || "" }}</span>
          </div>
        </template>
        <n-empty v-else description="还没有任务" style="padding: 20px 0" />
      </n-card>
    </div>

    <div class="rc-right">
      <DetailPanel v-if="bound" />
      <n-card v-else size="small">
        <n-empty description="暂无进行中的循环任务——左侧配置后点击 RUN 启动">
          <template #extra>
            <n-button size="small" quaternary :disabled="!store.loops.length" @click="pickLoop(store.loops[0]?.id)">
              查看最近一次运行
            </n-button>
          </template>
        </n-empty>
      </n-card>
    </div>
    </div>
  </n-spin>
</template>

<style scoped>
.rc-layout { display: grid; grid-template-columns: 340px minmax(0, 1fr); gap: 16px; align-items: start; }
@media (max-width: 1080px) { .rc-layout { grid-template-columns: 1fr; } }
.rc-left { display: flex; flex-direction: column; gap: 16px; min-width: 0; }
.rc-right { min-width: 0; }
.recent-item {
  display: flex; align-items: center; gap: 8px; padding: 6px 8px;
  border-radius: 6px; cursor: pointer;
}
.recent-item:hover { background: var(--surface-sub); }
.recent-item.on { background: var(--accent-soft); }
.recent-item:focus-visible { outline: 2px solid var(--accent); outline-offset: 1px; }
.rid { font-size: 12px; }
</style>
