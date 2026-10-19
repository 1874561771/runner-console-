<script setup>
/* Case 勾选器（业务组件）：按分支列 case、搜索过滤、全选/清除、组级全选 */
import { ref, watch, computed } from "vue";
import { NInput, NButton, NCheckbox, NSpin } from "naive-ui";
import { apiFetch, asJson } from "../../api/client.js";

const props = defineProps({
  refName: { type: String, default: "HEAD" },
  product: { type: String, default: "" },
  selected: { type: Array, default: () => [] },
  height: { type: Number, default: 260 },
});
const emit = defineEmits(["update:selected"]);

const groups = ref([]);
const loading = ref(false);
const error = ref("");
const filter = ref("");
const selectedSet = ref(new Set(props.selected));

watch(() => props.selected, (v) => { selectedSet.value = new Set(v || []); });
watch(() => [props.refName, props.product], load, { immediate: true });

const visibleGroups = computed(() => {
  const kw = filter.value.trim().toLowerCase();
  if (!kw) return groups.value;
  return groups.value
    .map((g) => ({ feature: g.feature, cases: g.cases.filter((c) => c.toLowerCase().includes(kw)) }))
    .filter((g) => g.cases.length);
});
const totalCount = computed(() => groups.value.reduce((n, g) => n + g.cases.length, 0));

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const d = await asJson(await apiFetch(
      `/api/cases?ref=${encodeURIComponent(props.refName)}&product=${encodeURIComponent(props.product)}`));
    groups.value = Array.isArray(d.groups) ? d.groups : [];
    const existing = new Set(groups.value.flatMap((g) => g.cases));
    const missing = [...selectedSet.value].filter((c) => !existing.has(c));
    if (missing.length) {
      groups.value.push({ feature: `已勾选但该分支不存在 (${missing.length})`, cases: missing });
    }
  } catch (err) {
    error.value = err.message || "加载失败";
  }
  loading.value = false;
}

function toggle(path, on) {
  if (on) selectedSet.value.add(path);
  else selectedSet.value.delete(path);
  emitUpdate();
}
function selectAll() {
  visibleGroups.value.forEach((g) => g.cases.forEach((c) => selectedSet.value.add(c)));
  emitUpdate();
}
function clearAll() {
  selectedSet.value.clear();
  emitUpdate();
}
function toggleGroup(g, on) {
  g.cases.forEach((c) => (on ? selectedSet.value.add(c) : selectedSet.value.delete(c)));
  emitUpdate();
}
function emitUpdate() {
  selectedSet.value = new Set(selectedSet.value);
  emit("update:selected", [...selectedSet.value]);
}
</script>

<template>
  <div class="cp-box" :style="{ maxHeight: height + 'px' }">
    <div class="cp-toolbar">
      <n-input v-model:value="filter" size="small" placeholder="搜索 case（路径 / 名称）…" clearable />
      <n-button size="small" @click="selectAll">全选</n-button>
      <n-button size="small" @click="clearAll">清除</n-button>
      <span class="cp-count faint">已选 {{ selectedSet.size }} / {{ totalCount }}</span>
    </div>
    <n-spin :show="loading">
      <div class="cp-body" :style="{ maxHeight: (height - 46) + 'px' }">
        <div v-if="error" class="cp-loading">{{ error }}</div>
        <div v-else-if="!groups.length && !loading" class="cp-loading">该分支下没有 case</div>
        <div v-for="g in visibleGroups" :key="g.feature" class="cp-group">
          <div class="cp-group-head">
            <n-checkbox
              size="small"
              :checked="g.cases.every((c) => selectedSet.has(c))"
              :indeterminate="g.cases.some((c) => selectedSet.has(c)) && !g.cases.every((c) => selectedSet.has(c))"
              @update:checked="(on) => toggleGroup(g, on)"
            >
              <span class="cp-feat mono">{{ g.feature }}</span>
              <span class="faint">({{ g.cases.length }})</span>
            </n-checkbox>
          </div>
          <div class="cp-cases">
            <n-checkbox
              v-for="c in g.cases" :key="c"
              size="small" class="cp-case"
              :checked="selectedSet.has(c)"
              @update:checked="(on) => toggle(c, on)"
            >
              <span class="cp-path">{{ c.split('/').pop() }}</span>
            </n-checkbox>
          </div>
        </div>
      </div>
    </n-spin>
  </div>
</template>

<style scoped>
.cp-box { border: 1px solid var(--line-soft); border-radius: 6px; background: #fff; }
.cp-toolbar { display: flex; align-items: center; gap: 6px; padding: 8px 10px; border-bottom: 1px solid var(--line-soft); }
.cp-toolbar .n-input { flex: 1; }
.cp-count { font-size: 11.5px; flex: none; white-space: nowrap; }
.cp-body { overflow-y: auto; padding: 0 0 10px; }
.cp-loading { padding: 18px 0; text-align: center; color: var(--ink-3); font-size: 12.5px; }
.cp-group { margin-top: 8px; }
.cp-group-head {
  background: var(--surface-sub); border-top: 1px solid var(--line-soft);
  border-bottom: 1px solid var(--line-soft);
  padding: 5px 10px;
}
.cp-feat { font-size: 12px; font-weight: 600; }
.cp-cases { padding: 4px 0 2px 28px; }
.cp-case { display: flex; margin: 2px 0; }
.cp-path { font-size: 12.5px; }
</style>
