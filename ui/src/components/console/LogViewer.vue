<script setup>
/* 内嵌 log 查看器：拉取 /runs/<run_id>/<relpath> 文本，step 行高亮 */
import { ref, computed, onMounted } from "vue";
import { NSpin } from "naive-ui";
import { apiFetch } from "../../api/client.js";

const props = defineProps({
  runId: { type: String, required: true },
  relpath: { type: String, required: true },
});

const MAX_LINES = 5000;
const text = ref("");
const loading = ref(true);
const error = ref("");
const truncated = ref(false);

onMounted(async () => {
  try {
    const res = await apiFetch(`/runs/${encodeURIComponent(props.runId)}/${props.relpath.split("/").map(encodeURIComponent).join("/")}`);
    const t = await res.text();
    const lines = t.split("\n");
    truncated.value = lines.length > MAX_LINES;
    text.value = lines.slice(0, MAX_LINES).join("\n");
  } catch (err) {
    error.value = err.message || "加载失败";
  }
  loading.value = false;
});

const lines = computed(() => text.value.split("\n"));

/* 行分类（对齐 runner 的日志格式：ui_automation.step 的 START/PASS/FAIL、
   截图行、Job setup 的 === StepN、错误栈） */
function lineClass(line) {
  if (/ui_automation\.step:.*\bPASS\b|\bPASS\s+\S+\s*\|/.test(line)) return "ln-pass";
  if (/ui_automation\.step:.*\bFAIL\b|\bFAIL\s+\S+\s*\|/.test(line)) return "ln-fail";
  if (/ui_automation\.step:.*\bSTART\b|\bSTART\s+\S+\s*\|/.test(line)) return "ln-step";
  if (/Saved (pass|fail) screenshot/i.test(line)) return "ln-shot";
  if (/===\s*Step\d+/i.test(line)) return "ln-head";
  if (/\[ERROR\]|Traceback|Exception:/.test(line)) return "ln-err";
  if (/^=====\s.+CASE|^RESULT\b|^CASE\b/.test(line)) return "ln-head";
  return "";
}
</script>

<template>
  <div class="lv">
    <n-spin :show="loading">
      <div v-if="error" class="lv-err-msg">{{ error }}</div>
      <div v-else class="lv-body mono">
        <div v-for="(line, i) in lines" :key="i" class="lv-line" :class="lineClass(line)">{{ line || " " }}</div>
        <div v-if="truncated" class="lv-truncated">
          —— 日志过长，仅显示前 {{ MAX_LINES }} 行；完整文件请在材料区下载 ——
        </div>
      </div>
    </n-spin>
  </div>
</template>

<style scoped>
.lv { border-radius: 0 0 6px 6px; overflow: hidden; }
.lv-body {
  background: #16181c; color: #e8eaed;
  font-size: 11px; line-height: 1.65;
  padding: 10px 12px; max-height: 420px; overflow-y: auto;
  white-space: pre-wrap; word-break: break-all;
}
.lv-line { padding-left: 10px; border-left: 3px solid transparent; }
.ln-pass { color: #5bd97c; }
.ln-fail { color: #ff7a8a; }
.ln-step { color: #ffb38a; border-left-color: #d9480f; background: rgba(217, 72, 15, .12); }
.ln-shot { color: #7ec8ff; }
.ln-err { color: #ff7a8a; font-weight: 600; }
.ln-head { color: #aab2bd; font-weight: 700; }
.lv-truncated { color: #ffb38a; padding: 6px 0 2px; font-weight: 600; }
.lv-err-msg { padding: 12px; color: var(--fail, #d9480f); font-size: 12.5px; }
</style>
