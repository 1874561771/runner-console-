<script setup>
/* 材料清单：job/case log 内嵌查看、截图缩略图（点击放大）、配置下载。
 * files 传入（live 模式）或按 runId 自行拉取（已入库模式） */
import { ref, computed, watch } from "vue";
import { NImage, NButton, NSpin } from "naive-ui";
import { apiFetch, asJson } from "../../api/client.js";
import { fmtSize } from "../../utils/format.js";
import LogViewer from "./LogViewer.vue";

const props = defineProps({
  runId: { type: String, required: true },
  files: { type: Array, default: null },   // live 模式直接传
});

const KIND_ORDER = ["job_log", "run_meta", "case_log", "screenshot", "support_tgz", "config", "other"];
const KIND_LABEL = {
  job_log: "Job 日志", case_log: "Case 日志", screenshot: "截图",
  run_meta: "运行元数据", support_tgz: "支持包", config: "配置", other: "其他",
};

const fetched = ref([]);
const loading = ref(false);
const openLog = ref(""); // "runId|relpath"（同时只展开一个）

watch(() => [props.runId, props.files], load, { immediate: true });

const byKind = computed(() => {
  const src = props.files || fetched.value;
  const m = {};
  for (const f of src) (m[f.kind] = m[f.kind] || []).push(f);
  return m;
});
const kinds = computed(() => KIND_ORDER.filter((k) => byKind.value[k]?.length));

function fileUrl(runId, rel) {
  return `/runs/${encodeURIComponent(runId)}/${rel.split("/").map(encodeURIComponent).join("/")}`;
}
function fileName(rel) {
  return rel.split("/").pop();
}
/* 截图文件名 = 步骤描述（Step3__Unlock_Network_Interfaces.png） */
function stepName(rel) {
  return fileName(rel).replace(/\.[a-z]+$/i, "").replace(/_{2,}/g, " ").replace(/_/g, " ");
}
async function load() {
  if (props.files || !props.runId) return;
  loading.value = true;
  try {
    const d = await asJson(await apiFetch(`/api/runs/${encodeURIComponent(props.runId)}/artifacts`));
    fetched.value = Array.isArray(d) ? d : [];
  } catch { fetched.value = []; }
  loading.value = false;
}
function toggleLog(runId, rel) {
  const key = runId + "|" + rel;
  openLog.value = openLog.value === key ? "" : key;
}
</script>

<template>
  <n-spin :show="loading">
    <div v-if="!(props.files || fetched).length" class="mat-empty faint">该 run 没有材料记录</div>
    <div v-for="k in kinds" :key="k" class="mat-group">
      <div class="mat-kind">{{ KIND_LABEL[k] || k }} <span class="faint">({{ byKind[k].length }})</span></div>

      <!-- 日志类：点击就地展开 -->
      <template v-if="k === 'job_log' || k === 'case_log'">
        <template v-for="f in byKind[k]" :key="f.relpath">
          <button type="button" class="mat-log mono" @click="toggleLog(runId, f.relpath)">
            <span>{{ fileName(f.relpath) }}</span>
            <span class="faint">{{ fmtSize(f.size_bytes) }} · 点击{{ openLog === runId + '|' + f.relpath ? "收起" : "展开" }}</span>
          </button>
          <LogViewer
            v-if="openLog === runId + '|' + f.relpath"
            :run-id="runId" :relpath="f.relpath"
          />
        </template>
      </template>

      <!-- 截图：缩略图 + 点击放大 -->
      <div v-else-if="k === 'screenshot'" class="mat-shots">
        <n-image
          v-for="f in byKind[k]" :key="f.relpath"
          :src="fileUrl(runId, f.relpath)"
          :title="stepName(f.relpath)"
          width="120" height="72" object-fit="cover" lazy
          class="mat-shot"
        />
      </div>

      <!-- 其余：链接（浏览器按类型预览/下载） -->
      <template v-else>
        <a
          v-for="f in byKind[k]" :key="f.relpath"
          class="mat-file" :href="fileUrl(runId, f.relpath)"
          :download="k !== 'other' ? fileName(f.relpath) : undefined"
          target="_blank" rel="noopener"
        >
          <span class="mono">{{ fileName(f.relpath) }}</span>
          <span class="faint">{{ fmtSize(f.size_bytes) }}</span>
        </a>
      </template>
    </div>
  </n-spin>
</template>

<style scoped>
.mat-empty { padding: 8px 0; font-size: 12.5px; }
.mat-group { margin-bottom: 12px; }
.mat-kind { font-size: 12px; font-weight: 600; color: var(--ink-2); margin-bottom: 6px; }
.mat-log {
  display: flex; justify-content: space-between; gap: 10px; width: 100%;
  padding: 7px 10px; margin-bottom: 4px; text-align: left;
  border: 1px solid var(--line-soft); border-radius: 6px; background: #fff;
  font-size: 12px; cursor: pointer;
}
.mat-log:hover { background: var(--surface-sub); border-color: var(--line); }
.mat-shots { display: flex; flex-wrap: wrap; gap: 8px; }
.mat-shot :deep(img) { border-radius: 6px; border: 1px solid var(--line-soft); }
.mat-file {
  display: flex; justify-content: space-between; gap: 10px;
  padding: 7px 10px; margin-bottom: 4px;
  border: 1px solid var(--line-soft); border-radius: 6px; font-size: 12px;
}
.mat-file:hover { background: var(--surface-sub); }
</style>
