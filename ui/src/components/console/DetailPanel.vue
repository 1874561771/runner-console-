<script setup>
/* 右侧详情：摘要卡 + 页签（概览 / 控制台） */
import { computed } from "vue";
import { NCard, NTag, NTabs, NTabPane } from "naive-ui";
import { useConsoleStore } from "../../stores/consoleStore.js";
import { fmtDuration } from "../../utils/format.js";
import OverviewTab from "./OverviewTab.vue";
import ConsoleStream from "./ConsoleStream.vue";

const store = useConsoleStore();
const bound = computed(() => store.loop?.loop || null);
const running = computed(() => bound.value?.status === "running");
const STATUS_TAG = {
  running: { type: "info", text: "RUNNING" },
  stopped: { type: "warning", text: "STOPPED" },
  failed: { type: "error", text: "FAILED" },
  done: { type: "success", text: "DONE" },
};
const latestRun = computed(() => [...(bound.value?.jobs || [])]
  .reverse().find((j) => j.run_id && j.has_summary));
const target = computed(() => {
  const l = bound.value || {};
  return l.suite || l.test || (l.cases_count ? `${l.cases_count} cases` : "—");
});
</script>

<template>
  <div class="detail">
    <n-card size="small" class="summary">
      <template #header>
        <span class="mono" style="font-size: 14px">{{ bound.id }}</span>
      </template>
      <template #header-extra>
        <n-tag :type="(STATUS_TAG[bound.status] || {}).type || 'default'" :bordered="false">
          {{ (STATUS_TAG[bound.status] || {}).text || bound.status }}
        </n-tag>
      </template>
      <div class="meta-line faint">
        {{ bound.env_name || bound.env_id || "—" }} · {{ bound.product || "—" }} ·
        {{ target }} · {{ bound.owner_name || "" }}
      </div>
      <div class="meta-line">耗时 <b class="mono">{{ fmtDuration(bound) }}</b>
        <span class="faint" style="margin-left: 10px">轮次 {{ bound.iterations ?? 0 }} / {{ bound.repeat_total || "∞" }}</span>
      </div>
    </n-card>

    <n-card size="small" :content-style="{ padding: 0 }">
      <n-tabs type="line" size="small" animated default-value="overview" style="padding: 0 12px">
        <n-tab-pane name="overview" tab="概览">
          <OverviewTab :loop="bound" />
        </n-tab-pane>
        <n-tab-pane name="console" tab="控制台" display-directive="show">
          <ConsoleStream />
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
  </div>
</template>

<style scoped>
.detail { display: flex; flex-direction: column; gap: 14px; min-width: 0; }
.meta-line { font-size: 12.5px; color: var(--ink-2); margin-bottom: 4px; }
.meta-line b { font-size: 13px; color: var(--ink); }
</style>
