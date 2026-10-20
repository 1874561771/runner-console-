<script setup>
/* 定时任务：列表 + 新建/编辑弹层（目标支持按 Suite / 勾选 Case / 保存的套件） */
import { ref, onMounted } from "vue";
import {
  NCard, NButton, NTag, NEmpty, NModal, NForm, NFormItem, NInput, NSelect,
  NInputNumber, NCheckbox, NTabs, NTabPane, NTimePicker, NDatePicker,
  NPopconfirm, useMessage,
} from "naive-ui";
import { apiFetch } from "../api/client.js";
import CasePicker from "../components/console/CasePicker.vue";

const $msg = useMessage();

const rows = ref([]);
const loading = ref(true);
const envs = ref([]);
const config = ref({ branches: [], suites: [], products: [] });
const suites = ref([]);

onMounted(async () => {
  await refresh();
});

async function refresh() {
  loading.value = true;
  try {
    const [list, envList, cfg, suiteList] = await Promise.all([
      apiFetch("/api/schedules").catch(() => []),
      apiFetch("/api/envs").catch(() => []),
      apiFetch("/api/config").catch(() => ({})),
      apiFetch("/api/suites").catch(() => []),
    ]);
    rows.value = Array.isArray(list) ? list : [];
    envs.value = Array.isArray(envList) ? envList : [];
    config.value = cfg;
    suites.value = Array.isArray(suiteList) ? suiteList : [];
  } finally { loading.value = false; }
}

const STATUS_BADGE = {
  started: { tag: "info", text: "已发起" },
  start_error: { tag: "error", text: "发起失败" },
  missed: { tag: "warning", text: "已错过" },
  ok: { tag: "success", text: "完成" },
  failed: { tag: "error", text: "失败" },
  stopped: { tag: "warning", text: "已停止" },
};

function targetText(p) {
  if (!p) return "—";
  if (p.cases?.length) return `勾选 ${p.cases.length} case`;
  return p.suite ? `suite ${p.suite}` : "—";
}
function ruleText(s) {
  return s.rule_type === "daily" ? `每天 ${s.time || ""}` : `单次 ${s.run_at || ""}`;
}

async function toggle(s) {
  try {
    await apiFetch(`/api/schedules/${s.id}`, { method: "PATCH", body: { enabled: !s.enabled } });
    $msg.success(s.enabled ? "已停用" : "已启用");
    refresh();
  } catch (err) { $msg.error(err.message || "操作失败"); }
}
async function runNow(s) {
  try {
    const d = await apiFetch(`/api/schedules/${s.id}/run-now`, { method: "POST" });
    $msg.success(`已发起 loop：${d.loop_id}`);
  } catch (err) { $msg.error(err.message || "触发失败"); }
  refresh();
}
async function remove(s) {
  try {
    await apiFetch(`/api/schedules/${s.id}`, { method: "DELETE" });
    $msg.success("已删除");
    refresh();
  } catch (err) { $msg.error(err.message || "删除失败"); }
}

/* ── 新建 / 编辑弹层 ── */
const editorShow = ref(false);
const editing = ref(null);        // null = 新建
const saving = ref(false);
const eName = ref("");
const eRule = ref("daily");
const eTime = ref("08:30");       // 'HH:MM'
const eRunAt = ref(null);         // 时间戳（n-date-picker）
const eEnv = ref("");
const eBranch = ref("HEAD");
const eMode = ref("suite");       // suite | cases
const eSuite = ref("");
const eSaved = ref("");           // 保存的套件 id
const eCases = ref([]);
const eRepeat = ref(1);
const eHeadless = ref(false);
let editorApi = null;             // CasePicker 控制柄

const envOptions = ref([]);
const branchOptions = ref([]);
const suiteOptions = ref([]);
const savedOptions = ref([]);

function tsToHHMM(ts) {
  const d = new Date(ts);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}
function tsToRunAt(ts) {
  const d = new Date(ts);
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

function openEditor(s) {
  editing.value = s || null;
  const p = s?.params || {};
  eName.value = s?.name || "";
  eRule.value = s?.rule_type || "daily";
  eTime.value = s?.time || "08:30";
  eRunAt.value = s?.run_at ? new Date(s.run_at.replace(" ", "T")).getTime() : Date.now() + 3600_000;
  eEnv.value = p.env_id || envs.value.find((e) => !e.disabled)?.id || "";
  eBranch.value = p.git_ref
    || (config.value.branches || []).find((b) => b.current)?.name
    || (config.value.branches || [])[0]?.name
    || "HEAD";
  eMode.value = p.cases?.length ? "cases" : "suite";
  eSuite.value = p.suite || config.value.suites?.[0]?.name || "";
  eSaved.value = "";
  eCases.value = [...(p.cases || [])];
  eRepeat.value = p.repeat ?? 1;
  eHeadless.value = !!p.headless;

  envOptions.value = envs.value.map((e) => ({
    value: e.id, label: `${e.name}${e.disabled ? "（停用）" : ""}`, disabled: !!e.disabled,
  }));
  branchOptions.value = (config.value.branches || []).map((b) => ({
    value: b.name, label: b.name + (b.current ? "（当前）" : ""),
  }));
  suiteOptions.value = (config.value.suites || []).map((x) => ({
    value: x.name, label: `${x.name}（${x.cases} cases）`,
  }));
  savedOptions.value = [
    { value: "", label: "（手动勾选）" },
    ...suites.value.map((x) => ({ value: x.id, label: `${x.name}（${x.cases.length}）` })),
  ];
  editorShow.value = true;
}

function applySaved(id) {
  const s = suites.value.find((x) => x.id === id);
  eCases.value = s ? [...s.cases] : [];
  editorApi?.setSelected(eCases.value);
}

async function saveEditor() {
  const name = eName.value.trim();
  if (!name) { $msg.error("请输入名称"); return; }
  if (eRule.value === "daily" && !/^\d{2}:\d{2}$/.test(eTime.value)) { $msg.error("请选择每天运行的时间"); return; }
  if (eRule.value === "once" && !eRunAt.value) { $msg.error("请选择单次运行时间"); return; }
  if (!eEnv.value) { $msg.error("请选择环境"); return; }
  if (eMode.value === "suite" && !eSuite.value) { $msg.error("请选择 Suite"); return; }
  if (eMode.value === "cases" && !eCases.value.length) { $msg.error("请勾选至少一个 Case"); return; }
  const body = {
    name,
    rule_type: eRule.value,
    time: eRule.value === "daily" ? eTime.value : "",
    run_at: eRule.value === "once" ? tsToRunAt(eRunAt.value) : "",
    enabled: true,
    run: {
      env_id: eEnv.value,
      product: "firebox",
      source: "repo",
      git_ref: eBranch.value,
      suite: eMode.value === "suite" ? eSuite.value : "",
      cases: eMode.value === "cases" ? [...eCases.value] : [],
      repeat: Math.max(0, Number(eRepeat.value) || 0),
      headless: eHeadless.value,
    },
  };
  saving.value = true;
  try {
    if (editing.value) {
      await apiFetch(`/api/schedules/${editing.value.id}`, { method: "PATCH", body });
      $msg.success("已保存");
    } else {
      const d = await apiFetch("/api/schedules", { method: "POST", body });
      $msg.success(`定时任务已创建（下次运行 ${d.schedule?.next_run_at || "—"}）`);
    }
    editorShow.value = false;
    refresh();
  } catch (err) { $msg.error(err.message || "保存失败"); }
  finally { saving.value = false; }
}
</script>

<template>
  <div class="view-head">
    <h1 class="view-title">定时任务</h1>
    <span class="spacer"></span>
    <n-button type="primary" @click="openEditor(null)">＋ 新建定时任务</n-button>
  </div>

  <n-card size="small">
    <n-empty v-if="!rows.length && !loading" description="还没有定时任务——点右上角创建：每天固定时间自动运行，或指定时间运行一次"
      style="padding: 30px 0" />
    <table v-else class="table">
      <thead>
        <tr><th>名称</th><th>运行配置</th><th>规则</th><th>下次运行</th><th>上次运行</th><th style="text-align:right">操作</th></tr>
      </thead>
      <tbody>
        <tr v-for="s in rows" :key="s.id">
          <td>
            <b>{{ s.name }}</b>
            <n-tag v-if="!s.enabled" size="tiny" :bordered="false" style="margin-left:6px">已停用</n-tag>
            <div v-if="s.last_note" class="faint note">{{ s.last_note }}</div>
          </td>
          <td class="cfg">{{ s.env_name || (s.params?.env_id ?? "—") }} · {{ s.params?.product || "firebox" }} ·
            {{ targetText(s.params) }} ·
            {{ s.params?.repeat === 0 ? "∞" : "×" + (s.params?.repeat || 1) }}
            <template v-if="s.params?.git_ref"> · {{ s.params.git_ref }}</template>
          </td>
          <td>{{ ruleText(s) }}</td>
          <td class="mono">{{ s.enabled ? s.next_run_at || "—" : "—" }}</td>
          <td>
            <n-tag v-if="s.last_status" size="small" :type="(STATUS_BADGE[s.last_status] || {}).tag || 'default'" :bordered="false">
              {{ (STATUS_BADGE[s.last_status] || {}).text || s.last_status }}
            </n-tag>
            <a v-if="s.last_loop_id" class="mono link" href="javascript:void(0)"
              @click="$router.push(`/console?loop=${s.last_loop_id}`)">{{ s.last_loop_id }}</a>
            <span v-else class="faint">—</span>
          </td>
          <td style="text-align:right">
            <div class="ops">
              <n-button size="tiny" @click="toggle(s)">{{ s.enabled ? "停用" : "启用" }}</n-button>
              <n-button size="tiny" @click="runNow(s)">立即运行</n-button>
              <n-button size="tiny" @click="openEditor(s)">编辑</n-button>
              <n-popconfirm @positive-click="remove(s)">
                <template #trigger>
                  <n-button size="tiny" type="error" secondary>删除</n-button>
                </template>
                确定删除「{{ s.name }}」？
              </n-popconfirm>
            </div>
          </td>
        </tr>
      </tbody>
    </table>
  </n-card>

  <n-modal v-model:show="editorShow" preset="card"
    :title="editing ? `编辑定时任务：${editing.name}` : '新建定时任务'" style="width: 620px">
    <n-form label-placement="top" size="small">
      <n-form-item label="名称">
        <n-input v-model:value="eName" placeholder="如：每晚报关回归" />
      </n-form-item>
      <n-form-item label="触发规则（服务器本机时间）">
        <div style="width: 100%">
          <n-tabs v-model:value="eRule" type="segment" size="small" style="margin-bottom: 10px">
            <n-tab-pane name="daily" tab="每天"><span /></n-tab-pane>
            <n-tab-pane name="once" tab="单次"><span /></n-tab-pane>
          </n-tabs>
          <div v-if="eRule === 'daily'" class="rule-row">
            <n-time-picker v-model:formatted-value="eTime" value-format="HH:mm" format="HH:mm" style="width: 130px" />
            <span class="faint" style="font-size: 12px">到点自动运行（设备忙时排队等待）</span>
          </div>
          <div v-else class="rule-row">
            <n-date-picker v-model:formatted-value="eRunAt" value-format="yyyy-MM-dd HH:mm" format="yyyy-MM-dd HH:mm"
              type="datetime" style="width: 220px" />
            <span class="faint" style="font-size: 12px">该时间点运行一次后自动停用</span>
          </div>
        </div>
      </n-form-item>
      <n-form-item label="环境">
        <n-select v-model:value="eEnv" :options="envOptions" placeholder="选择环境" />
      </n-form-item>
      <n-form-item label="分支（每次运行取该分支当时最新）">
        <n-select v-model:value="eBranch" :options="branchOptions" />
      </n-form-item>
      <n-form-item label="运行目标">
        <div style="width: 100%">
          <n-tabs v-model:value="eMode" type="segment" size="small" style="margin-bottom: 10px">
            <n-tab-pane name="suite" tab="按 Suite"><span /></n-tab-pane>
            <n-tab-pane name="cases" tab="勾选 Case"><span /></n-tab-pane>
          </n-tabs>
          <n-select v-if="eMode === 'suite'" v-model:value="eSuite" :options="suiteOptions" />
          <div v-else>
            <n-select v-model:value="eSaved" :options="savedOptions" size="small"
              placeholder="选用已保存套件（可选）" clearable style="margin-bottom: 8px"
              @update:value="applySaved" />
            <CasePicker
              :ref-name="eBranch" product="firebox" :selected="eCases" :height="220"
              @update:selected="(v) => (eCases = v)"
            />
          </div>
        </div>
      </n-form-item>
      <n-form-item label="重复次数（0 = 无限循环）">
        <n-input-number v-model:value="eRepeat" :min="0" style="width: 120px" />
      </n-form-item>
      <n-form-item>
        <n-checkbox v-model:checked="eHeadless">跳过 Job setup / teardown</n-checkbox>
      </n-form-item>
    </n-form>
    <template #footer>
      <div style="display: flex; justify-content: flex-end; gap: 8px">
        <n-button @click="editorShow = false">取消</n-button>
        <n-button type="primary" :loading="saving" @click="saveEditor">
          {{ editing ? "保存" : "创建" }}
        </n-button>
      </div>
    </template>
  </n-modal>
</template>

<style scoped>
.note { font-size: 11.5px; margin-top: 2px; max-width: 260px; }
.cfg { font-size: 12.5px; }
.link { font-size: 11.5px; margin-left: 6px; }
.ops { display: inline-flex; gap: 6px; flex-wrap: wrap; justify-content: flex-end; }
.rule-row { display: flex; align-items: center; gap: 10px; }
.table th, .table td { font-size: 12.5px; }
</style>
