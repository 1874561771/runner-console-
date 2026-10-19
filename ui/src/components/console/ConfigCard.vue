<script setup>
/* 运行配置卡：目标三模式 / 执行参数 / 命令预览 / RUN-STOP / 定时弹层 / 另存套件 */
import { ref, computed } from "vue";
import {
  NCard, NSelect, NInput, NInputNumber, NSwitch, NButton, NTabs, NTabPane,
  NModal, NForm, NFormItem, NTimePicker, NDatePicker, useMessage,
} from "naive-ui";
import { useConsoleStore } from "../../stores/consoleStore.js";
import { apiFetch } from "../../api/client.js";
import CasePicker from "./CasePicker.vue";

const emit = defineEmits(["run", "stop"]);
const store = useConsoleStore();
const message = useMessage();
const f = store.form;

const running = computed(() => store.loop?.loop?.status === "running");

const envOptions = computed(() => store.envs.map((e) => ({
  value: e.id, label: `${e.name}${e.disabled ? "（停用）" : ""}`, disabled: !!e.disabled,
})));
const branchOptions = computed(() => (store.config.branches || []).map((b) => ({
  value: b.name, label: b.name + (b.current ? "（当前）" : ""),
})));
const suiteOptions = computed(() => (store.config.suites || []).map((s) => ({
  value: s.name, label: `${s.name}（${s.cases} cases）`,
})));
const testOptions = computed(() => (store.config.tests || []).map((t) => ({ value: t, label: t })));
const uploadOptions = computed(() => store.uploads.length
  ? [{ value: "", label: "请选择…" },
     ...store.uploads.map((u) => ({ value: u.id, label: `[${u.kind === "suite" ? "suite" : "脚本"}] ${u.relpath}` }))]
  : [{ value: "", label: "还没有上传" }]);
const savedSuiteOptions = computed(() => [
  { value: "", label: "（手动勾选）" },
  ...store.suitesSaved.map((s) => ({ value: s.id, label: `[套件] ${s.name}（${s.cases.length} cases）` })),
]);

const targetTabs = computed({
  get: () => f.targetMode,
  set: (v) => { f.targetMode = v; },
});
const sourceTabs = computed({
  get: () => f.source,
  set: (v) => { f.source = v; },
});
const productTabs = computed({
  get: () => f.product,
  set: (v) => { f.product = v; },
});

function onRun() {
  const err = store.validateTarget();
  if (err) { message.error(err); return; }
  emit("run");
}
function onStop() { emit("stop"); }

async function copyCommand() {
  try {
    await navigator.clipboard.writeText(store.commandPreview.pure);
    message.success("已复制命令");
  } catch { message.error("复制失败"); }
}

/* ── 定时弹层 ── */
const schedShow = ref(false);
const schedName = ref("");
const schedRule = ref("daily");
const schedTimeTs = ref(null);   // n-time-picker 时间戳
const schedRunAtTs = ref(null);  // n-date-picker 时间戳

function openSchedule() {
  const err = store.validateTarget();
  if (err) { message.error(err); return; }
  schedName.value = "";
  schedRule.value = "daily";
  schedTimeTs.value = toDate(8, 30);
  schedRunAtTs.value = Date.now() + 3600_000;
  schedShow.value = true;
}
function toDate(h, m) {
  const d = new Date(); d.setHours(h, m, 0, 0); return d.getTime();
}
function fmtHHMM(ts) {
  const d = new Date(ts);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}
function fmtRunAt(ts) {
  const d = new Date(ts);
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}
async function saveSchedule() {
  const name = schedName.value.trim();
  if (!name) { message.error("请输入名称"); return; }
  if (schedRule.value === "daily" && !schedTimeTs.value) { message.error("请选择每天运行的时间"); return; }
  if (schedRule.value === "once" && !schedRunAtTs.value) { message.error("请选择单次运行时间"); return; }
  try {
    const d = await apiFetch("/api/schedules", {
      method: "POST",
      body: {
        name,
        rule_type: schedRule.value,
        time: schedRule.value === "daily" ? fmtHHMM(schedTimeTs.value) : "",
        run_at: schedRule.value === "once" ? fmtRunAt(schedRunAtTs.value) : "",
        enabled: true,
        run: store.runParams,
      },
    });
    schedShow.value = false;
    message.success(`定时任务「${name}」已创建（下次运行 ${d.schedule?.next_run_at || "—"}）`);
  } catch (err) { message.error(err.message || "创建失败"); }
}

/* ── 另存为套件 ── */
const suiteName = ref("");
async function saveSuite() {
  if (!f.cases.length) { message.error("先勾选 case 再保存"); return; }
  const name = suiteName.value.trim();
  if (!name) { message.error("请输入套件名称"); return; }
  try {
    await apiFetch("/api/suites", {
      method: "POST",
      body: { name, product: f.product, cases: [...f.cases] },
    });
    await store.refreshSuites();
    store.applySavedSuite(store.suitesSaved.find((s) => s.name === name)?.id || "");
    suiteName.value = "";
    message.success(`已保存套件「${name}」（可在资源页管理）`);
  } catch (err) { message.error(err.message || "保存失败"); }
}
</script>

<template>
  <n-card title="运行配置" size="small" class="cfg-card">
    <template #header-extra>
      <n-button size="tiny" quaternary @click="copyCommand">复制命令</n-button>
    </template>

    <div class="grp-label">目标</div>
    <div class="fld">
      <div class="fld-label">Product</div>
      <n-tabs v-model:value="productTabs" type="segment" size="small">
        <n-tab-pane v-for="p in store.config.products" :key="p" :name="p" :tab="p"><span /></n-tab-pane>
      </n-tabs>
    </div>
    <div class="fld">
      <div class="fld-label">来源</div>
      <n-tabs v-model:value="sourceTabs" type="segment" size="small">
        <n-tab-pane name="repo" tab="仓库测试"><span /></n-tab-pane>
        <n-tab-pane name="upload" tab="我的测试"><span /></n-tab-pane>
      </n-tabs>
    </div>
    <div v-if="f.source === 'repo'" class="fld">
      <div class="fld-label">分支 / ref</div>
      <n-select v-model:value="f.gitRef" :options="branchOptions" size="small"
        @update:value="f.savedSuiteId = ''" />
    </div>
    <div v-else class="fld">
      <div class="fld-label">我的测试</div>
      <n-select v-model:value="f.uploadId" :options="uploadOptions" size="small" />
    </div>

    <template v-if="f.source === 'repo'">
      <div class="fld">
        <div class="fld-label">运行目标</div>
        <n-tabs v-model:value="targetTabs" type="segment" size="small">
          <n-tab-pane name="suite" tab="按 Suite"><span /></n-tab-pane>
          <n-tab-pane name="test" tab="按 Test"><span /></n-tab-pane>
          <n-tab-pane name="cases" tab="勾选 Case"><span /></n-tab-pane>
        </n-tabs>
      </div>
      <div v-if="f.targetMode === 'suite'" class="fld">
        <div class="fld-label">Suite</div>
        <n-select v-model:value="f.suite" :options="suiteOptions" size="small" />
      </div>
      <div v-if="f.targetMode === 'test'" class="fld">
        <div class="fld-label">Test</div>
        <n-select v-model:value="f.test" :options="testOptions" size="small" filterable />
      </div>
      <div v-if="f.targetMode === 'cases'" class="fld">
        <div class="fld-label">
          勾选 Case <span class="faint">（分支：{{ f.gitRef }}，运行时生成临时套件并在结束后删除）</span>
        </div>
        <n-select
          :value="f.savedSuiteId" :options="savedSuiteOptions" size="small" style="margin-bottom: 8px"
          placeholder="选用已保存套件（可选）" clearable
          @update:value="(v) => v && store.applySavedSuite(v)"
        />
        <CasePicker
          v-model:selected="f.cases" :ref-name="f.gitRef" :product="f.product" :height="300"
        />
        <div class="save-suite-row">
          <n-input v-model:value="suiteName" size="small" placeholder="套件名称（另存当前勾选）" />
          <n-button size="small" @click="saveSuite">另存为套件</n-button>
        </div>
      </div>
    </template>

    <div class="grp-label">执行</div>
    <div class="fld row">
      <div class="repeat-box">
        <span class="mono x">×</span>
        <n-input-number v-model:value="f.repeat" size="small" :min="1" :disabled="f.unlimited" style="width: 84px" />
      </div>
      <n-button
        class="tgl" block size="small"
        :type="f.unlimited ? 'primary' : 'default'" :secondary="!f.unlimited"
        @click="f.unlimited = !f.unlimited"
      >{{ f.unlimited ? "✓ 无限循环" : "无限循环" }}</n-button>
    </div>
    <div class="fld toggles">
      <n-button
        block size="small"
        :type="f.pauseOnFail ? 'primary' : 'default'" :secondary="!f.pauseOnFail"
        @click="f.pauseOnFail = !f.pauseOnFail"
      >{{ f.pauseOnFail ? "✓ " : "" }}Pause on fail（失败暂停）</n-button>
      <n-button
        block size="small"
        :type="f.headless ? 'primary' : 'default'" :secondary="!f.headless"
        @click="f.headless = !f.headless"
      >{{ f.headless ? "✓ " : "" }}跳过 Job setup / teardown</n-button>
    </div>

    <div class="grp-label">命令预览</div>
    <div class="cmd mono">
      {{ store.commandPreview.pure }} <span class="faint"># {{ store.commandPreview.note }}</span>
    </div>

    <div class="run-row">
      <n-button v-if="!running" type="primary" block @click="onRun">RUN</n-button>
      <n-button v-else type="error" block @click="onStop">STOP</n-button>
      <n-button quaternary @click="openSchedule">定时</n-button>
    </div>

    <n-modal v-model:show="schedShow" preset="card" title="保存为定时任务" style="width: 480px">
      <n-form label-placement="top" size="small">
        <n-form-item label="名称">
          <n-input v-model:value="schedName" placeholder="如：每晚报关回归" />
        </n-form-item>
        <n-form-item label="触发规则（服务器本机时间）">
          <div style="width: 100%">
            <n-tabs v-model:value="schedRule" type="segment" size="small" style="margin-bottom: 10px">
              <n-tab-pane name="daily" tab="每天"><span /></n-tab-pane>
              <n-tab-pane name="once" tab="单次"><span /></n-tab-pane>
            </n-tabs>
            <div v-if="schedRule === 'daily'" class="rule-row">
              <n-time-picker v-model:value="schedTimeTs" format="HH:mm" style="width: 130px" />
              <span class="faint" style="font-size: 12px">到点自动运行</span>
            </div>
            <div v-else class="rule-row">
              <n-date-picker v-model:value="schedRunAtTs" type="datetime" style="width: 220px" />
              <span class="faint" style="font-size: 12px">该时间点运行一次后自动停用</span>
            </div>
          </div>
        </n-form-item>
      </n-form>
      <p class="faint" style="font-size: 12px; margin: 0 0 4px">
        快照 = 当前运行台表单（环境 / 分支 / 目标 / 次数 / 固件）。分支类目标每次运行取该分支当时最新；
        到点设备忙时自动排队。任务在「定时任务」页管理。
      </p>
      <template #footer>
        <div style="display: flex; justify-content: flex-end; gap: 8px">
          <n-button @click="schedShow = false">取消</n-button>
          <n-button type="primary" @click="saveSchedule">创建定时任务</n-button>
        </div>
      </template>
    </n-modal>
  </n-card>
</template>

<style scoped>
.cfg-card :deep(.n-card__content) { display: flex; flex-direction: column; gap: 4px; }
.grp-label {
  font-size: 12px; font-weight: 700; color: var(--ink-2);
  margin: 10px 0 6px; padding-bottom: 4px; border-bottom: 1px solid var(--line-soft);
}
.fld { margin-bottom: 8px; }
.fld-label { font-size: 12px; color: var(--ink-2); margin-bottom: 4px; }
.fld.row { display: flex; align-items: center; gap: 8px; min-height: 26px; }
.fld.row .tgl { flex: 1; }
.fld.toggles { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.repeat-box { display: flex; align-items: center; gap: 4px; flex: none; }
.x { color: var(--ink-3); }
.cmd {
  background: var(--surface-sub); border: 1px solid var(--line-soft); border-radius: 6px;
  padding: 9px 11px; font-size: 10.5px; line-height: 1.6; word-break: break-all; user-select: all;
}
.run-row { display: flex; gap: 8px; margin-top: 12px; }
.run-row .n-button:first-child { flex: 1; }
.save-suite-row { display: flex; gap: 8px; margin-top: 8px; }
.save-suite-row .n-input { flex: 1; }
.rule-row { display: flex; align-items: center; gap: 10px; }
</style>
