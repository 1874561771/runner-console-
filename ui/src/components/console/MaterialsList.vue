<script setup>
/* 材料清单（按 case 归属）：
 * - Job 级：job.log（内嵌展开）、运行元数据 / 配置 / 支持包（下载）
 * - Case 级：每个 case 一块——自己的 case.log（内嵌展开）+ 自己的截图
 *   （匹配规则：runner 把产物放在 <case 名>/ 目录下）
 * - 匹配不上的 case 日志/截图进「未归属」组兜底
 */
import { ref, computed, watch } from "vue";
import { NImage, NButton, NSpin, NTag } from "naive-ui";
import { apiFetch, asJson } from "../../api/client.js";
import { fmtSize, caseBadge } from "../../utils/format.js";
import LogViewer from "./LogViewer.vue";

const props = defineProps({
  runId: { type: String, required: true },
  files: { type: Array, default: null },   // live 模式直接传
  cases: { type: Array, default: () => [] }, // [{name, status, ...}]
});

const fetched = ref([]);
const loading = ref(false);
const openLog = ref(""); // "runId|relpath"（同时只展开一个）
const openShot = ref(null); // {url, name} 自定义放大层（带步骤名）
const caseBlockEls = ref([]);

watch(() => [props.runId, props.files, props.cases], load, { immediate: true });

const all = computed(() => props.files || fetched.value);

function baseName(caseName) {
  return String(caseName || "").split("/").pop();
}
function belongsTo(rel, caseName) {
  return rel.includes(`/${baseName(caseName)}/`);
}

const jobLogs = computed(() => all.value.filter((f) => f.kind === "job_log"));
const miscFiles = computed(() =>
  all.value.filter((f) => ["run_meta", "support_tgz", "config"].includes(f.kind)));

const caseBlocks = computed(() => props.cases.map((c) => ({
  name: c.name,
  short: baseName(c.name),
  status: c.status,
  logs: all.value.filter((f) => f.kind === "case_log" && belongsTo(f.relpath, c.name)),
  shots: all.value.filter((f) => f.kind === "screenshot" && belongsTo(f.relpath, c.name)),
})));

const unassigned = computed(() => {
  const matched = new Set(caseBlocks.value.flatMap((c) => [...c.logs, ...c.shots].map((f) => f.relpath)));
  return all.value.filter((f) =>
    (f.kind === "case_log" || f.kind === "screenshot") && !matched.has(f.relpath));
});

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

/* case 表行点击 → 滚动定位到对应 case 材料块并高亮 */
function scrollToCase(i) {
  const el = caseBlockEls.value[i];
  if (!el) return;
  el.scrollIntoView({ behavior: "smooth", block: "start" });
  el.classList.remove("hl");
  requestAnimationFrame(() => el.classList.add("hl"));
  setTimeout(() => el.classList.remove("hl"), 1800);
}
defineExpose({ scrollToCase });
</script>

<template>
  <n-spin :show="loading">
    <div v-if="!all.length" class="mat-empty faint">该 run 没有材料记录</div>

    <!-- Job 级 -->
    <div v-if="jobLogs.length" class="mat-group">
      <div class="mat-kind">Job 日志</div>
      <template v-for="f in jobLogs" :key="f.relpath">
        <button type="button" class="mat-log mono" @click="toggleLog(runId, f.relpath)">
          <span>{{ fileName(f.relpath) }}</span>
          <span class="faint">{{ fmtSize(f.size_bytes) }} · 点击{{ openLog === runId + '|' + f.relpath ? "收起" : "展开" }}</span>
        </button>
        <LogViewer
          v-if="openLog === runId + '|' + f.relpath"
          :run-id="runId" :relpath="f.relpath"
        />
      </template>
    </div>

    <!-- 每个 case 一块 -->
    <div
      v-for="(c, i) in caseBlocks" :key="c.name"
      :ref="(el) => (caseBlockEls[i] = el)" class="mat-group case-block"
    >
      <div class="case-head">
        <span class="mono case-name">{{ c.short }}</span>
        <n-tag size="tiny" :type="caseBadge(c.status).tag" :bordered="false">{{ caseBadge(c.status).text }}</n-tag>
        <span class="spacer"></span>
        <span class="faint" style="font-size: 11.5px">
          {{ c.logs.length ? `日志×${c.logs.length}` : "无日志" }} ·
          {{ c.shots.length ? `截图×${c.shots.length}` : "无截图" }}
        </span>
      </div>
      <template v-for="f in c.logs" :key="f.relpath">
        <button type="button" class="mat-log mono" @click="toggleLog(runId, f.relpath)">
          <span>{{ fileName(f.relpath) }}</span>
          <span class="faint">{{ fmtSize(f.size_bytes) }} · 点击{{ openLog === runId + '|' + f.relpath ? "收起" : "展开" }}</span>
        </button>
        <LogViewer
          v-if="openLog === runId + '|' + f.relpath"
          :run-id="runId" :relpath="f.relpath"
        />
      </template>
      <div v-if="c.shots.length" class="mat-shots">
        <figure v-for="f in c.shots" :key="f.relpath" class="mat-shot">
          <n-image
            :src="fileUrl(runId, f.relpath)" preview-disabled
            :title="stepName(f.relpath)"
            width="120" height="72" object-fit="cover" lazy
            @click="openShot = { url: fileUrl(runId, f.relpath), name: stepName(f.relpath) }"
          />
          <figcaption :title="stepName(f.relpath)">{{ stepName(f.relpath) }}</figcaption>
        </figure>
      </div>
    </div>

    <!-- 未归属 -->
    <div v-if="unassigned.length" class="mat-group">
      <div class="mat-kind" style="color: #b8860b">未归属（目录结构与 case 不匹配）</div>
      <template v-for="f in unassigned" :key="f.relpath">
        <button type="button" class="mat-log mono" @click="toggleLog(runId, f.relpath)">
          <span>{{ f.relpath }}</span>
          <span class="faint">{{ fmtSize(f.size_bytes) }}</span>
        </button>
        <LogViewer
          v-if="openLog === runId + '|' + f.relpath"
          :run-id="runId" :relpath="f.relpath"
        />
      </template>
      <div v-if="unassigned.some((f) => f.kind === 'screenshot')" class="mat-shots">
        <figure v-for="f in unassigned.filter((x) => x.kind === 'screenshot')" :key="f.relpath" class="mat-shot">
          <n-image
            :src="fileUrl(runId, f.relpath)" preview-disabled :title="stepName(f.relpath)"
            width="120" height="72" object-fit="cover" lazy
            @click="openShot = { url: fileUrl(runId, f.relpath), name: stepName(f.relpath) }"
          />
          <figcaption :title="stepName(f.relpath)">{{ stepName(f.relpath) }}</figcaption>
        </figure>
      </div>
    </div>

    <!-- 其它级别文件 -->
    <div v-if="miscFiles.length" class="mat-group">
      <div class="mat-kind">运行元数据 / 配置 / 支持包</div>
      <a
        v-for="f in miscFiles" :key="f.relpath"
        class="mat-file" :href="fileUrl(runId, f.relpath)"
        :download="fileName(f.relpath)" target="_blank" rel="noopener"
      >
        <span class="mono">{{ f.relpath }}</span>
        <span class="faint">{{ fmtSize(f.size_bytes) }}</span>
      </a>
    </div>

    <!-- 截图放大层：图片下方显示步骤名；点遮罩空白处关闭 -->
    <div v-if="openShot" class="shot-lightbox" @click.self="openShot = null">
      <img :src="openShot.url" :alt="openShot.name" />
      <div class="shot-name mono">{{ openShot.name }}</div>
    </div>
  </n-spin>
</template>

<style scoped>
.mat-empty { padding: 8px 0; font-size: 12.5px; }
.mat-group { margin-bottom: 12px; }
.mat-kind { font-size: 12px; font-weight: 600; color: var(--ink-2); margin-bottom: 6px; }
.case-block { border: 1px solid var(--line-soft); border-radius: 6px; padding: 8px 10px; }
.case-head { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.case-name { font-size: 12.5px; font-weight: 600; }
.case-head .spacer { flex: 1; }
.mat-log {
  display: flex; justify-content: space-between; gap: 10px; width: 100%;
  padding: 6px 10px; margin-bottom: 4px; text-align: left;
  border: 1px solid var(--line-soft); border-radius: 6px; background: #fff;
  font-size: 12px; cursor: pointer;
}
.mat-log:hover { background: var(--surface-sub); border-color: var(--line); }
.mat-shots { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 4px; }
.mat-shot { margin: 0; width: 120px; }
.mat-shot :deep(img) { border-radius: 6px; border: 1px solid var(--line-soft); display: block; cursor: zoom-in; }
.mat-shot figcaption {
  font-size: 11px; color: var(--ink-2); margin-top: 3px;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  font-family: var(--font-mono);
}
.case-block.hl { box-shadow: 0 0 0 2px var(--accent); transition: box-shadow .3s; }
.shot-lightbox {
  position: fixed; inset: 0; z-index: 90;
  background: rgba(10, 11, 13, .84);
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  cursor: zoom-out;
}
.shot-lightbox img {
  max-width: 92vw; max-height: 88vh;
  border-radius: 6px; box-shadow: 0 12px 48px rgba(0, 0, 0, .5);
  cursor: default;
}
.shot-name {
  margin-top: 12px; padding: 5px 14px; border-radius: 14px;
  background: rgba(255, 255, 255, .12); color: #f0f1ee; font-size: 12.5px;
  max-width: 80vw; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.mat-file {
  display: flex; justify-content: space-between; gap: 10px;
  padding: 7px 10px; margin-bottom: 4px;
  border: 1px solid var(--line-soft); border-radius: 6px; font-size: 12px;
}
.mat-file:hover { background: var(--surface-sub); }
</style>
