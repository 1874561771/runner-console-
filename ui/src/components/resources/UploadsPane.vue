<script setup>
/* 我的上传：拖拽/选择上传 + 在线新建/编辑（文本）+ 删除 */
import { ref, onMounted } from "vue";
import { NButton, NTag, NEmpty, NModal, NForm, NFormItem, NInput, NPopconfirm, useMessage } from "naive-ui";
import { apiFetch } from "../../api/client.js";

const $msg = useMessage();

const uploads = ref([]);
const loading = ref(true);
const dropEl = ref(null);
const fileEl = ref(null);

onMounted(load);

async function load() {
  loading.value = true;
  try {
    const d = await apiFetch("/api/uploads");
    uploads.value = Array.isArray(d) ? d : [];
  } catch (err) { $msg.error(err.message || "加载失败"); }
  loading.value = false;
}

async function uploadFiles(files) {
  if (!files?.length) return;
  let ok = 0;
  for (const f of files) {
    try {
      const fd = new FormData();
      fd.append("file", f, f.name);
      await apiFetch("/api/uploads", { method: "POST", body: fd });
      ok++;
    } catch { /* 单个失败不中断 */ }
  }
  $msg.info(ok === files.length ? `已上传 ${ok} 个文件` : `已上传 ${ok}/${files.length} 个文件`);
  load();
}

/* ── 在线新建 / 编辑 ── */
const modalShow = ref(false);
const editing = ref(null);      // null = 新建
const eName = ref("");
const eContent = ref("");
const saving = ref(false);

function openEditor(u) {
  editing.value = u || null;
  eName.value = u?.name || "";
  eContent.value = "";
  modalShow.value = true;
  if (u) {
    apiFetch(`/api/uploads/${u.id}/content`)
      .then(async (res) => {
        if (res instanceof Response) eContent.value = await res.text();
        else eContent.value = String(res ?? "");
      })
      .catch((err) => $msg.error(err.message || "内容加载失败"));
  }
}

async function save() {
  const content = eContent.value;
  try {
    if (editing.value) {
      await apiFetch(`/api/uploads/${editing.value.id}/content`, {
        method: "PUT", body: { content },
      });
      $msg.success("已保存");
    } else {
      const name = eName.value.trim();
      if (!name) { $msg.error("请输入文件名"); return; }
      const d = await apiFetch("/api/uploads/text", { method: "POST", body: { name, content } });
      $msg.success(`已创建 ${d.name}`);
    }
    modalShow.value = false;
    load();
  } catch (err) { $msg.error(err.message || "保存失败"); }
}

async function remove(u) {
  try {
    await apiFetch(`/api/uploads/${u.id}`, { method: "DELETE" });
    $msg.success("已删除");
    load();
  } catch (err) { $msg.error(err.message || "删除失败"); }
}
</script>

<template>
  <div class="pane">
    <div
      class="up-drop" @click="fileEl?.click()"
      @dragover.prevent="dropEl?.classList.add('drag')"
      @dragleave="dropEl?.classList.remove('drag')"
      @drop.prevent="dropEl?.classList.remove('drag'); uploadFiles($event.dataTransfer.files)"
      ref="dropEl"
    >
      将 suite / 脚本文件拖到这里，或<b>点击选择文件</b><br />
      <span class="faint" style="font-size: 11.5px">.py 识别为脚本（script），其余识别为 suite；可多选</span>
    </div>
    <input ref="fileEl" type="file" multiple hidden @change="uploadFiles(fileEl.files); fileEl.value = ''" />

    <div style="margin: 10px 0">
      <n-button size="small" @click="openEditor(null)">＋ 新建文件</n-button>
    </div>

    <n-empty v-if="!uploads.length && !loading" description="还没有上传——suite / 脚本上传后，可在运行台选择「我的测试」运行"
      style="padding: 16px 0" />
    <table v-else class="table">
      <thead>
        <tr><th>名称</th><th>类型</th><th>上传时间</th><th style="text-align:right">操作</th></tr>
      </thead>
      <tbody>
        <tr v-for="u in uploads" :key="u.id">
          <td><span class="mono" style="font-weight: 600">{{ u.name }}</span></td>
          <td><n-tag size="small" :type="u.kind === 'script' ? 'warning' : 'info'" :bordered="false">{{ u.kind }}</n-tag></td>
          <td class="mono faint">{{ u.uploaded_at || "" }}</td>
          <td style="text-align: right">
            <div class="ops">
              <n-button size="tiny" @click="openEditor(u)">编辑</n-button>
              <n-popconfirm @positive-click="remove(u)">
                <template #trigger>
                  <n-button size="tiny" type="error" secondary>删除</n-button>
                </template>
                确定删除「{{ u.name }}」（{{ u.kind }}）？
              </n-popconfirm>
            </div>
          </td>
        </tr>
      </tbody>
    </table>

    <n-modal v-model:show="modalShow" preset="card"
      :title="editing ? `编辑文件 · ${editing.name}` : '新建文件'" style="width: 640px">
      <n-form label-placement="top" size="small">
        <n-form-item v-if="!editing" label="文件名（.py 识别为脚本，其余为 suite）">
          <n-input v-model:value="eName" class="mono" placeholder="regression-test.txt" />
        </n-form-item>
        <n-form-item label="内容">
          <n-input v-model:value="eContent" type="textarea" :rows="14" class="mono"
            style="font-size: 12px; line-height: 1.6" spellcheck="false"
            placeholder="每行一个 case 脚本路径（suite）；# 开头为注释" />
        </n-form-item>
      </n-form>
      <template #footer>
        <div style="display: flex; justify-content: flex-end; gap: 8px">
          <n-button @click="modalShow = false">取消</n-button>
          <n-button type="primary" :loading="saving" @click="save">保存</n-button>
        </div>
      </template>
    </n-modal>
  </div>
</template>

<style scoped>
.up-drop {
  border: 2px dashed var(--line); border-radius: 8px; background: var(--surface-sub);
  padding: 22px 0; text-align: center; font-size: 13px; cursor: pointer;
  color: var(--ink-2); user-select: none;
}
.up-drop.drag { border-color: var(--accent); background: var(--accent-soft); }
.ops { display: inline-flex; gap: 6px; justify-content: flex-end; }
</style>
