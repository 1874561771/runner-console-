<script setup>
/* 我的套件：勾选 Case 集合的命名保存——列表 + 新建/编辑（勾选器）+ 删除 */
import { ref, onMounted } from "vue";
import { NButton, NEmpty, NModal, NForm, NFormItem, NInput, NPopconfirm, useMessage } from "naive-ui";
import { apiFetch } from "../../api/client.js";
import CasePicker from "../console/CasePicker.vue";

const $msg = useMessage();

const suites = ref([]);
const loading = ref(true);

onMounted(load);

async function load() {
  loading.value = true;
  try {
    const d = await apiFetch("/api/suites");
    suites.value = Array.isArray(d) ? d : [];
  } catch (err) { $msg.error(err.message || "加载失败"); }
  loading.value = false;
}

/* ── 新建 / 编辑弹层 ── */
const modalShow = ref(false);
const editing = ref(null);
const eName = ref("");
const eCases = ref([]);
const saving = ref(false);

function openEditor(s) {
  editing.value = s || null;
  eName.value = s?.name || "";
  eCases.value = s ? [...s.cases] : [];
  modalShow.value = true;
}

async function save() {
  const name = eName.value.trim();
  if (!name) { $msg.error("请输入套件名称"); return; }
  if (!eCases.value.length) { $msg.error("请勾选至少一个 case"); return; }
  saving.value = true;
  try {
    await apiFetch(editing.value ? `/api/suites/${editing.value.id}` : "/api/suites", {
      method: editing.value ? "PUT" : "POST",
      body: { name, product: "firebox", cases: [...eCases.value] },
    });
    $msg.success(editing.value ? "套件已更新" : `已创建套件「${name}」`);
    modalShow.value = false;
    load();
  } catch (err) { $msg.error(err.message || "保存失败"); }
  finally { saving.value = false; }
}

async function remove(s) {
  try {
    await apiFetch(`/api/suites/${s.id}`, { method: "DELETE" });
    $msg.success("已删除");
    load();
  } catch (err) { $msg.error(err.message || "删除失败"); }
}
</script>

<template>
  <div class="pane">
    <div class="pane-head">
      <span class="faint" style="font-size: 12.5px">
        套件 = 勾选的 case 集合；运行时按所选分支当时的内容生成临时 suite，任务结束后删除
      </span>
      <span class="spacer"></span>
      <n-button type="primary" size="small" @click="openEditor(null)">＋ 新建套件</n-button>
    </div>

    <n-empty v-if="!suites.length && !loading" description="还没有套件——新建后可在运行台「勾选 Case」模式一键选用"
      style="padding: 16px 0" />
    <table v-else class="table">
      <thead>
        <tr><th>名称</th><th>Case 数</th><th>更新时间</th><th style="text-align:right">操作</th></tr>
      </thead>
      <tbody>
        <tr v-for="s in suites" :key="s.id">
          <td><span class="mono" style="font-weight: 600">{{ s.name }}</span></td>
          <td class="mono">{{ s.cases.length }}</td>
          <td class="mono faint">{{ s.updated_at || "" }}</td>
          <td style="text-align: right">
            <div class="ops">
              <n-button size="tiny" @click="openEditor(s)">编辑</n-button>
              <n-popconfirm @positive-click="remove(s)">
                <template #trigger>
                  <n-button size="tiny" type="error" secondary>删除</n-button>
                </template>
                确定删除套件「{{ s.name }}」（{{ s.cases.length }} cases）？
              </n-popconfirm>
            </div>
          </td>
        </tr>
      </tbody>
    </table>

    <n-modal v-model:show="modalShow" preset="card"
      :title="editing ? `编辑套件 · ${editing.name}` : '新建套件'" style="width: 640px">
      <n-form label-placement="top" size="small">
        <n-form-item label="名称">
          <n-input v-model:value="eName" placeholder="如：报关冒烟集" />
        </n-form-item>
        <n-form-item label="勾选 Case（基于当前 HEAD 展示；运行时按所选分支解析）">
          <CasePicker
            ref-name="HEAD" product="firebox" :selected="eCases" :height="240"
            @update:selected="(v) => (eCases = v)"
          />
        </n-form-item>
      </n-form>
      <template #footer>
        <div style="display: flex; justify-content: flex-end; gap: 8px">
          <n-button @click="modalShow = false">取消</n-button>
          <n-button type="primary" :loading="saving" @click="save">{{ editing ? "保存" : "创建" }}</n-button>
        </div>
      </template>
    </n-modal>
  </div>
</template>

<style scoped>
.pane-head { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; }
.pane-head .spacer { flex: 1; }
.ops { display: inline-flex; gap: 6px; justify-content: flex-end; }
</style>
