<script setup>
/* 运行台（P1a）：左 = 配置卡 + 最近任务；右 = 绑定 loop 摘要（1b 迁移完整详情） */
import { onMounted, ref, computed } from "vue";
import { NCard, NButton, NTag, NEmpty, NPopconfirm, useMessage } from "naive-ui";
import { useConsoleStore } from "../stores/consoleStore.js";
import { apiFetch } from "../api/client.js";
import ConfigCard from "../components/console/ConfigCard.vue";

const store = useConsoleStore();
const message = useMessage();
const busy = ref(false);

onMounted(async () => {
  await store.loadAll();
  if (!store.loop) {
    const running = store.loops.find((l) => l.status === "running")
      || store.loops[0];
    if (running) await store.bindLoop(running.id).catch(() => {});
  }
});

const bound = computed(() => store.loop?.loop || null);
const recent = computed(() => store.loops.slice(0, 8));

const STATUS_TAG = {
  running: { type: "info", text: "RUNNING" },
  stopped: { type: "warning", text: "STOPPED" },
  failed: { type: "error", text: "FAILED" },
  done: { type: "success", text: "DONE" },
};

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
  <div class="rc-layout">
    <div class="rc-left">
      <ConfigCard @run="onRun" @stop="onStop" />
      <n-card title="最近任务" size="small">
        <template v-if="recent.length">
          <div
            v-for="l in recent" :key="l.id"
            class="recent-item" :class="{ on: bound?.id === l.id }"
            @click="pickLoop(l.id)"
          >
            <n-tag size="small" :type="(STATUS_TAG[l.status] || {}).type || 'default'" :bordered="false">
              {{ (STATUS_TAG[l.status] || {}).text || l.status }}
            </n-tag>
            <span class="mono rid">{{ l.id }}</span>
            <span class="faint" style="font-size: 11.5px">{{ l.created_at || "" }}</span>
          </div>
        </template>
        <n-empty v-else description="还没有任务" style="padding: 20px 0" />
      </n-card>
    </div>

    <div class="rc-right">
      <n-card v-if="bound" size="small">
        <template #header>
          <span class="mono">{{ bound.id }}</span>
        </template>
        <template #header-extra>
          <n-tag :type="(STATUS_TAG[bound.status] || {}).type || 'default'" :bordered="false">
            {{ (STATUS_TAG[bound.status] || {}).text || bound.status }}
          </n-tag>
        </template>
        <div class="meta-grid">
          <div><div class="k">环境</div><div class="v">{{ bound.env_name || bound.env_id || "—" }}</div></div>
          <div><div class="k">Product</div><div class="v">{{ bound.product || "—" }}</div></div>
          <div><div class="k">分支 / ref</div><div class="v mono">{{ bound.git_ref || "HEAD" }}</div></div>
          <div><div class="k">轮次</div><div class="v">{{ bound.iterations ?? 0 }} / {{ bound.repeat_total || "∞" }}</div></div>
        </div>
        <div v-if="bound.stop_reason" class="stop-note">停止原因：{{ bound.stop_reason }}</div>
        <div v-if="bound.status === 'running'" style="margin-top: 10px">
          <n-popconfirm @positive-click="onStop">
            <template #trigger>
              <n-button size="small" type="error" secondary>停止该循环</n-button>
            </template>
            确定停止当前循环？
          </n-popconfirm>
        </div>
        <p class="faint" style="font-size: 12px; margin: 12px 0 0">
          概览详情 / case 结果 / 材料区 / SSE 控制台将在 P1 下一阶段（1b/1c）迁移。
        </p>
      </n-card>
      <n-card v-else size="small">
        <n-empty description="暂无进行中的循环任务——左侧配置后点击 RUN 启动">
          <template #extra>
            <n-button size="small" quaternary @click="pickLoop(store.loops[0]?.id)" :disabled="!store.loops.length">
              查看最近一次运行
            </n-button>
          </template>
        </n-empty>
      </n-card>
    </div>
  </div>
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
.rid { font-size: 12px; }
.meta-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; }
.meta-grid .k { font-size: 11.5px; color: var(--ink-3); }
.meta-grid .v { font-size: 13px; font-weight: 600; word-break: break-all; }
.stop-note {
  margin-top: 10px; padding: 8px 10px; border-radius: 6px;
  background: #fdf6ec; color: #b8860b; font-size: 12.5px;
}
</style>
