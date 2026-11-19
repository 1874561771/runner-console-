<script setup>
/* 环境：列表 + 新建/编辑 + 授权 + 停用/启用 + 强制释放锁 + 删除 */
import { ref, computed, onMounted } from "vue";
import {
  NButton, NTag, NEmpty, NModal, NForm, NFormItem, NInput, NPopconfirm, NSelect, useMessage,
} from "naive-ui";
import { apiFetch } from "../../api/client.js";
import { useAuthStore } from "../../stores/auth.js";

const auth = useAuthStore();
const $msg = useMessage();

const envs = ref([]);
const loading = ref(true);
const modalShow = ref(false);
const editing = ref(null);      // null = 新建
const eName = ref("");
const eContent = ref("");
const saving = ref(false);

onMounted(load);

async function load() {
  loading.value = true;
  try {
    const d = await apiFetch("/api/envs");
    envs.value = Array.isArray(d) ? d : [];
  } catch (err) { $msg.error(err.message || "加载失败"); }
  loading.value = false;
}

function statusOf(e) {
  if (e.disabled) return { tag: "default", text: "停用" };
  if (e.lock?.held) return { tag: "warning", text: "占用" };
  return { tag: "success", text: "空闲" };
}

function openEditor(e) {
  editing.value = e || null;
  eName.value = e?.name || "";
  eContent.value = "";
  modalShow.value = true;
  if (e) {
    // 编辑：加载脱敏后的现有内容
    apiFetch(`/api/envs/${e.id}`)
      .then(async (d) => {
        const r = d?.redacted;
        if (r) {
          eContent.value = Object.entries(r).map(([k, v]) => `${k}=${v}`).join("\n")
            + "\n# 上面密钥已脱敏；要改密钥请整份覆盖粘贴";
        }
      })
      .catch(() => {});
  }
}

async function save() {
  const name = eName.value.trim();
  const content = eContent.value;
  if (!name || !content) { $msg.error("请填写名称与内容"); return; }
  if (content.includes("••••••")) { $msg.error("脱敏内容不能直接保存，请整份覆盖粘贴"); return; }
  saving.value = true;
  try {
    await apiFetch(editing.value ? `/api/envs/${editing.value.id}` : "/api/envs", {
      method: editing.value ? "PATCH" : "POST",
      body: { name, content },
    });
    $msg.success(editing.value ? "环境已更新" : "环境已创建");
    modalShow.value = false;
    load();
  } catch (err) { $msg.error(err.message || "保存失败"); }
  finally { saving.value = false; }
}

async function toggle(e) {
  try {
    await apiFetch(`/api/envs/${e.id}`, { method: "PATCH", body: { disabled: !e.disabled } });
    $msg.success(e.disabled ? "已启用" : "已停用");
    load();
  } catch (err) { $msg.error(err.message || "操作失败"); }
}

async function remove(e) {
  try {
    await apiFetch(`/api/envs/${e.id}`, { method: "DELETE" });
    $msg.success("环境已删除");
    load();
  } catch (err) { $msg.error(err.message || "删除失败"); }
}

/* ---------- 授权（PUT 为整体替换：始终提交完整列表） ---------- */
const LEVEL_OPTIONS = [
  { label: "viewer（只读查看任务与报告）", value: "viewer" },
  { label: "operator（另可发起运行、修改环境文件）", value: "operator" },
];
const VISIBILITY_OPTIONS = [
  { label: "私有（仅授权用户）", value: "private" },
  { label: "登录用户可见", value: "authenticated" },
  { label: "公开（游客可见）", value: "public" },
];
const grantEnv = ref(null);
const grantShow = ref(false);
const grants = ref([]);          // [{user_id, username, level}]
const candidates = ref([]);      // [{id, username, name}]
const newUser = ref(null);
const newLevel = ref("viewer");
const grantSaving = ref(false);

function canGrant(e) {
  return auth.isAdmin || e.owner_id === auth.user?.id;
}

async function changeVisibility(e, visibility) {
  try {
    await apiFetch(`/api/envs/${e.id}`, {
      method: "PATCH",
      body: { visibility },
    });
    e.visibility = visibility;
    $msg.success("环境可见性已更新");
  } catch (err) { $msg.error(err.message || "更新可见性失败"); }
}

const addableUsers = computed(() => {
  const taken = new Set(grants.value.map((g) => g.user_id));
  return candidates.value
    .filter((u) => !taken.has(u.id))
    .map((u) => ({ label: u.name && u.name !== u.username ? `${u.username}（${u.name}）` : u.username, value: u.id }));
});

async function openGrants(e) {
  grantEnv.value = e;
  grants.value = [];
  candidates.value = [];
  newUser.value = null;
  newLevel.value = "viewer";
  grantShow.value = true;
  try {
    const [g, c] = await Promise.all([
      apiFetch(`/api/envs/${e.id}/grants`),
      apiFetch(`/api/envs/${e.id}/grant-candidates`),
    ]);
    grants.value = (Array.isArray(g) ? g : []).map((x) => ({
      user_id: x.user_id, username: x.username, level: x.level,
    }));
    candidates.value = Array.isArray(c) ? c : [];
  } catch (err) { $msg.error(err.message || "加载授权失败"); }
}

function addGrant() {
  const u = candidates.value.find((x) => x.id === newUser.value);
  if (!u) return;
  grants.value.push({ user_id: u.id, username: u.username, level: newLevel.value });
  newUser.value = null;
}

function removeGrant(userId) {
  grants.value = grants.value.filter((g) => g.user_id !== userId);
}

async function saveGrants() {
  grantSaving.value = true;
  try {
    await apiFetch(`/api/envs/${grantEnv.value.id}/grants`, {
      method: "PUT",
      body: { grants: grants.value.map((g) => ({ user_id: g.user_id, level: g.level })) },
    });
    $msg.success("授权已保存");
    grantShow.value = false;
  } catch (err) { $msg.error(err.message || "保存授权失败"); }
  finally { grantSaving.value = false; }
}

async function releaseLock(e) {
  try {
    const d = await apiFetch("/api/lock/force-release", {
      method: "POST",
      body: { env_id: e.id },
    });
    $msg.success(d.message || "锁已释放");
    load();
  } catch (err) { $msg.error(err.message || "释放失败"); }
}
</script>

<template>
  <div class="pane">
    <div class="pane-head">
      <span class="faint" style="font-size: 12.5px">.firebox_env 环境文件，运行时注入 runner；名称用于运行台/定时任务选择</span>
      <span class="spacer"></span>
      <n-button type="primary" size="small" @click="openEditor(null)">＋ 新建环境</n-button>
    </div>

    <n-empty v-if="!envs.length && !loading" description="还没有环境——点击右上角创建第一个" style="padding: 24px 0" />
    <table v-else class="table">
      <thead>
        <tr><th>名称</th><th>属主</th><th>状态</th><th>可见性</th><th>更新时间</th><th style="text-align:right">操作</th></tr>
      </thead>
      <tbody>
        <tr v-for="e in envs" :key="e.id">
          <td>
            <span class="mono" style="font-weight: 600">{{ e.name }}</span>
            <div v-if="e.lock?.held" class="faint" style="font-size: 11.5px">
              锁 {{ e.lock.run_id || "" }} · {{ e.lock.owner_name || "未知属主" }}{{ e.lock.stale ? " · 残留" : "" }}
            </div>
          </td>
          <td class="mono">{{ e.owner_name || "" }}</td>
          <td><n-tag size="small" :type="statusOf(e).tag" :bordered="false">{{ statusOf(e).text }}</n-tag></td>
          <td style="width: 170px">
            <n-select v-if="canGrant(e)" :value="e.visibility || 'private'" size="tiny"
              :options="VISIBILITY_OPTIONS" @update:value="(v) => changeVisibility(e, v)" />
            <n-tag v-else size="small" :bordered="false">{{ e.visibility || "private" }}</n-tag>
          </td>
          <td class="mono faint">{{ e.updated_at || "" }}</td>
          <td style="text-align: right">
            <div class="ops">
              <n-button size="tiny" @click="openEditor(e)">编辑</n-button>
              <n-button v-if="canGrant(e)" size="tiny" @click="openGrants(e)">授权</n-button>
              <n-button v-if="auth.isAdmin" size="tiny" @click="toggle(e)">{{ e.disabled ? "启用" : "停用" }}</n-button>
              <n-popconfirm v-if="auth.isAdmin && e.lock?.held" @positive-click="releaseLock(e)">
                <template #trigger>
                  <n-button size="tiny" type="warning" secondary>强制释放</n-button>
                </template>
                确定强制释放该环境的锁？正在运行的任务可能受影响。
              </n-popconfirm>
              <n-popconfirm @positive-click="remove(e)">
                <template #trigger>
                  <n-button size="tiny" type="error" secondary>删除</n-button>
                </template>
                确定删除环境「{{ e.name }}」？删除后不可恢复。
              </n-popconfirm>
            </div>
          </td>
        </tr>
      </tbody>
    </table>

    <n-modal v-model:show="modalShow" preset="card"
      :title="editing ? '编辑环境' : '新建环境'" style="width: 560px">
      <n-form label-placement="top" size="small">
        <n-form-item label="名称">
          <n-input v-model:value="eName" class="mono" placeholder="lab-fbox-12" />
        </n-form-item>
        <n-form-item label=".firebox_env 内容">
          <n-input v-model:value="eContent" type="textarea" :rows="12" class="mono"
            placeholder="FIREBOX1_WEBUI_URL=..." style="font-size: 12px" />
        </n-form-item>
        <p class="faint" style="font-size: 12px; margin: 0">
          密钥按文件保存；编辑时已有密钥会脱敏显示，需修改请整份覆盖粘贴。
        </p>
      </n-form>
      <template #footer>
        <div style="display: flex; justify-content: flex-end; gap: 8px">
          <n-button @click="modalShow = false">取消</n-button>
          <n-button type="primary" :loading="saving" @click="save">保存</n-button>
        </div>
      </template>
    </n-modal>

    <n-modal v-model:show="grantShow" preset="card"
      :title="`环境授权 · ${grantEnv?.name || ''}`" style="width: 560px">
      <p class="faint" style="font-size: 12px; margin: 0 0 10px">
        被授权用户可在任务中心查看该环境上的全部任务与报告；属主与管理员本就有全部权限，无需授权。
      </p>
      <n-empty v-if="!grants.length" description="还没有授权用户" size="small" style="padding: 12px 0" />
      <table v-else class="table" style="margin-bottom: 12px">
        <thead><tr><th>用户</th><th>级别</th><th style="text-align:right">操作</th></tr></thead>
        <tbody>
          <tr v-for="g in grants" :key="g.user_id">
            <td class="mono">{{ g.username }}</td>
            <td style="width: 260px">
              <n-select v-model:value="g.level" size="tiny" :options="LEVEL_OPTIONS" />
            </td>
            <td style="text-align: right">
              <n-button size="tiny" type="error" secondary @click="removeGrant(g.user_id)">移除</n-button>
            </td>
          </tr>
        </tbody>
      </table>
      <div class="grant-add">
        <n-select v-model:value="newUser" size="small" filterable clearable
          :options="addableUsers" placeholder="选择要授权的用户" style="flex: 1" />
        <n-select v-model:value="newLevel" size="small" :options="LEVEL_OPTIONS" style="width: 230px" />
        <n-button size="small" :disabled="!newUser" @click="addGrant">添加</n-button>
      </div>
      <template #footer>
        <div style="display: flex; justify-content: flex-end; gap: 8px">
          <n-button @click="grantShow = false">取消</n-button>
          <n-button type="primary" :loading="grantSaving" @click="saveGrants">保存</n-button>
        </div>
      </template>
    </n-modal>
  </div>
</template>

<style scoped>
.pane-head { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; }
.pane-head .spacer { flex: 1; }
.ops { display: inline-flex; gap: 6px; flex-wrap: wrap; justify-content: flex-end; }
.grant-add { display: flex; gap: 8px; align-items: center; }
</style>
