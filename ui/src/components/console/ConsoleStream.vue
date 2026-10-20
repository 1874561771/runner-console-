<script setup>
/* 控制台页签：SSE 实时流（连接由 useConsoleStream 管理，切页签不断流） */
import { ref, watch, nextTick } from "vue";
import { consoleStream as stream } from "../../composables/useConsoleStream.js";
import { lineClass } from "../../utils/logHighlight.js";

const bodyEl = ref(null);
const stick = ref(true);   // 贴底跟随（用户上滚即暂停）

function onScroll() {
  const el = bodyEl.value;
  if (!el) return;
  stick.value = el.scrollTop + el.clientHeight >= el.scrollHeight - 40;
}
function scrollToBottom() {
  const el = bodyEl.value;
  if (el && stick.value) el.scrollTop = el.scrollHeight;
}
watch(() => stream.text.value, async () => {
  await nextTick();
  scrollToBottom();
});
</script>

<template>
  <div class="cs">
    <div v-if="stream.state.value === 'connecting'" class="cs-banner faint">
      正在连接控制台流…
    </div>
    <div
      ref="bodyEl" class="cs-body mono" @scroll="onScroll"
      :class="{ dim: stream.state.value === 'connecting' }"
    >
      <div v-for="(line, i) in stream.text.value.split('\n')" :key="i"
        class="cs-line" :class="lineClass(line)">{{ line || " " }}</div>
      <div v-if="!stream.text.value && stream.state.value !== 'connecting'" class="faint" style="padding: 8px 0">
        （暂无输出）
      </div>
    </div>
    <div v-if="stream.state.value === 'end'" class="cs-end">
      — 控制台流结束{{ stream.endStatus.value ? `（${stream.endStatus.value}）` : "" }} —
      <span class="faint" style="font-weight: 400">（上方输出为完整回放）</span>
    </div>
    <div v-else-if="stream.state.value === 'open'" class="cs-live faint">● 实时输出中（向上滚动查看历史）</div>
  </div>
</template>

<style scoped>
.cs { position: relative; }
.cs-banner { font-size: 12px; padding: 4px 0; }
.cs-body {
  background: #16181c; color: #e8eaed;
  font-size: 11px; line-height: 1.65;
  padding: 10px 12px; height: 480px; overflow-y: auto;
  white-space: pre-wrap; word-break: break-all;
  border-radius: 6px;
}
.cs-body.dim { opacity: .6; }
.cs-line { padding-left: 10px; border-left: 3px solid transparent; }
.ln-pass { color: #5bd97c; }
.ln-fail { color: #ff7a8a; }
.ln-step { color: #ffb38a; border-left-color: #d9480f; background: rgba(217, 72, 15, .12); }
.ln-shot { color: #7ec8ff; }
.ln-err { color: #ff7a8a; font-weight: 600; }
.ln-head { color: #aab2bd; font-weight: 700; }
.cs-end {
  margin-top: 8px; padding: 6px 10px; border-radius: 6px;
  background: rgba(217, 72, 15, .1); color: #d9480f; font-weight: 600; font-size: 12.5px;
}
.cs-live { font-size: 11.5px; margin-top: 6px; color: #2f9e63; }
</style>
