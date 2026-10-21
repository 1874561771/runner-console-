<script setup>
/* 管理（P5b）：用户管理 / 审计日志 / 保留策略（admin 专属，路由仅 admin 可进） */
import { ref, onMounted } from "vue";
import {
  NCard, NTabs, NTabPane, NButton, NTag, NSelect, NModal, NForm, NFormItem,
  NInput, NInputNumber, useMessage,
} from "naive-ui";
import { apiFetch, asJson } from "../api/client.js";
import { useAuthStore } from "../stores/auth.js";

const auth = useAuthStore();
const $msg = useMessage();

/* ── 用户 ── */
const users = ref([]);
const createShow = ref(false);
const cUsername = ref("");
const cName = ref("");
const cRole = ref("user");
const cPassword = ref("");
const createdPwd = ref("");     // 一次性口令展示
const pwdShow = ref(false);

const roleOptions = [
  { value: "user", label: "user（普通）" },
  { value: "admin", label: "admin（管理员）" },
];

async function loadUsers() {
  users.value = await apiFetch("/api/admin/users").then(asJson).catch(() => []);
}

function openCreate() {
  cUsername.value = ""; cName.value = ""; cRole.value = "user"; cPassword.value = "";
  createShow.value = true;
}

async function createUser() {
  if (!cUsername.value.trim()) { $msg.error("请输入用户名"); return; }
  try {
    const d = await apiFetch("/api/admin/users", {
      method: "POST",
      body: {
        username: cUsername.value.trim(), name: cName.value.trim(),
        role: cRole.value, password: cPassword.value,
      },
    });
    createShow.value = false;
    if (d.password) { createdPwd.value = d.password; pwdShow.value = true; }
    else $msg.success(`用户 ${d.username} 已创建`);
    loadUsers();
  } catch (err) { $msg.error(err.message || "创建失败"); }
}

async function changeRole(u, role) {
  try {
    await apiFetch(`/api/admin/users/${u.id}/role`, { method: "PATCH", body: { role } });
    $msg.success(`${u.username} 角色已改为 ${role}`);
    loadUsers();
  } catch (err) { $msg.error(err.message || "操作失败"); }
}

async function resetPwd(u) {
  try {
    const d = await apiFetch(`/api/admin/users/${u.id}/reset-password`, { method: "POST" });
    createdPwd.value = d.password;
    pwdShow.value = true;
  } catch (err) { $msg.error(err.message || "重置失败"); }
}

/* ── 审计 ── */
const auditItems = ref([]);
const auditTotal = ref(0);
const auditOffset = ref(0);
const PAGE = 20;

async function loadAudit() {
  const d = await apiFetch(`/api/admin/audit?offset=${auditOffset.value}&limit=${PAGE}`).then(asJson).catch(() => ({}));
  auditItems.value = d?.items || [];
  auditTotal.value = d?.total || 0;
}
function auditPage(delta) {
  auditOffset.value = Math.max(0, auditOffset.value + delta * PAGE);
  loadAudit();
}
const ACTION_BADGE = {
  "user.create": { tag: "success", text: "建号" },
  "user.role": { tag: "warning", text: "改角色" },
  "user.reset": { tag: "warning", text: "重置口令" },
  "retain.save": { tag: "warning", text: "保留策略" },
  "env.del": { tag: "error", text: "删环境" },
  "upload.del": { tag: "error", text: "删上传" },
  "lock.release": { tag: "error", text: "强制释放" },
  "schedule.create": { tag: "success", text: "建定时" },
  "schedule.update": { tag: "warning", text: "改定时" },
  "schedule.del": { tag: "error", text: "删定时" },
  "schedule.run": { tag: "info", text: "触发定时" },
  "suite.create": { tag: "success", text: "建套件" },
  "suite.update": { tag: "warning", text: "改套件" },
  "suite.del": { tag: "error", text: "删套件" },
};

/* ── 保留策略 ── */
const retainCount = ref(50);
const retainDays = ref(30);
async function loadSettings() {
  const d = await apiFetch("/api/admin/settings").then(asJson).catch(() => ({}));
  retainCount.value = d?.retain_count ?? 50;
  retainDays.value = d?.retain_days ?? 30;
}
async function saveSettings() {
  try {
    await apiFetch("/api/admin/settings", {
      method: "POST",
      body: { retain_count: retainCount.value, retain_days: retainDays.value },
    });
    $msg.success("保留策略已保存");
    loadAudit();
  } catch (err) { $msg.error(err.message || "保存失败"); }
}

onMounted(() => { loadUsers(); loadAudit(); loadSettings(); });
</script>

<template>
  <div class="view-head">
    <h1 class="view-title">管理</h1>
    <span class="faint" style="font-size: 12.5px">用户 / 审计 / 保留策略（仅管理员）</span>
  </div>

  <n-card size="small" :content-style="{ padding: '6px 14px 14px' }">
    <n-tabs type="line" size="small" animated default-value="users">
      <!-- ── 用户 ── -->
      <n-tab-pane name="users" tab="用户" display-directive="show:lazy">
        <div class="pane-head">
          <span class="faint" style="font-size: 12.5px">账号由管理员创建（本地账号制）；口令重置后为一次性随机口令，仅展示一次</span>
          <span class="spacer"></span>
          <n-button type="primary" size="small" @click="openCreate">＋ 新建用户</n-button>
        </div>
        <table class="table">
          <thead>
            <tr><th>ID</th><th>用户名</th><th>姓名</th><th>角色</th><th>来源</th><th>最近登录</th><th style="text-align:right">操作</th></tr>
          </thead>
          <tbody>
            <tr v-for="u in users" :key="u.id">
              <td class="mono">{{ u.id }}</td>
              <td class="mono" style="font-weight: 600">{{ u.username }}</td>
              <td>{{ u.name }}</td>
              <td>
                <n-tag size="small" :type="u.role === 'admin' ? 'warning' : 'default'" :bordered="false">{{ u.role }}</n-tag>
              </td>
              <td class="mono faint">{{ u.auth_source || "" }}</td>
              <td class="mono faint">{{ u.last_login || "—" }}</td>
              <td style="text-align: right">
                <div class="ops">
                  <n-button v-if="u.role === 'admin' && u.id !== auth.user?.id" size="tiny"
                    @click="changeRole(u, 'user')">降为 user</n-button>
                  <n-button v-if="u.role === 'user'" size="tiny"
                    @click="changeRole(u, 'admin')">升为 admin</n-button>
                  <n-button size="tiny" @click="resetPwd(u)">重置口令</n-button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>

        <!-- 新建用户 -->
        <n-modal v-model:show="createShow" preset="card" title="新建用户" style="width: 440px">
          <n-form label-placement="top" size="small">
            <n-form-item label="用户名（字母/数字/. _ -，2-40 位）">
              <n-input v-model:value="cUsername" class="mono" placeholder="zhangsan" />
            </n-form-item>
            <n-form-item label="姓名（选填，默认同用户名）">
              <n-input v-model:value="cName" placeholder="张三" />
            </n-form-item>
            <n-form-item label="角色">
              <n-select v-model:value="cRole" :options="roleOptions" />
            </n-form-item>
            <n-form-item label="初始口令（留空 = 自动生成一次性口令）">
              <n-input v-model:value="cPassword" type="password" show-password-on="click" placeholder="留空自动生成" />
            </n-form-item>
          </n-form>
          <template #footer>
            <div style="display: flex; justify-content: flex-end; gap: 8px">
              <n-button @click="createShow = false">取消</n-button>
              <n-button type="primary" @click="createUser">创建</n-button>
            </div>
          </template>
        </n-modal>
      </n-tab-pane>

      <!-- ── 审计 ── -->
      <n-tab-pane name="audit" tab="审计日志" display-directive="show:lazy">
        <table class="table">
          <thead><tr><th style="width:170px">时间</th><th style="width:110px">操作者</th><th style="width:110px">动作</th><th>详情</th></tr></thead>
          <tbody>
            <tr v-for="a in auditItems" :key="a.id">
              <td class="mono faint">{{ a.created_at }}</td>
              <td class="mono">{{ a.actor }}</td>
              <td>
                <n-tag size="small" :type="(ACTION_BADGE[a.action] || {}).tag || 'default'" :bordered="false">
                  {{ (ACTION_BADGE[a.action] || {}).text || a.action }}
                </n-tag>
              </td>
              <td class="mono faint detail-cell">{{ a.detail }}</td>
            </tr>
          </tbody>
        </table>
        <div style="display: flex; align-items: center; gap: 10px; margin-top: 10px">
          <n-button size="tiny" :disabled="auditOffset <= 0" @click="auditPage(-1)">上一页</n-button>
          <n-button size="tiny" :disabled="auditOffset + PAGE >= auditTotal" @click="auditPage(1)">下一页</n-button>
          <span class="faint" style="font-size: 12px">
            共 {{ auditTotal }} 条 · 第 {{ auditOffset / PAGE + 1 }} 页
          </span>
        </div>
      </n-tab-pane>

      <!-- ── 保留策略 ── -->
      <n-tab-pane name="retain" tab="保留策略" display-directive="show:lazy">
        <div style="max-width: 420px">
          <p class="faint" style="font-size: 12.5px; margin-top: 0">
            启动时与每日清理按此策略删除过期 run 产物：超过保留数量或保留天数的先删。
          </p>
          <n-form label-placement="left" size="small" label-width="150">
            <n-form-item label="保留最近 run 数">
              <n-input-number v-model:value="retainCount" :min="5" :max="500" style="width: 140px" />
            </n-form-item>
            <n-form-item label="保留天数">
              <n-input-number v-model:value="retainDays" :min="1" :max="365" style="width: 140px" />
            </n-form-item>
            <n-button type="primary" @click="saveSettings">保存</n-button>
          </n-form>
        </div>
      </n-tab-pane>
    </n-tabs>

    <!-- 一次性口令展示 -->
    <n-modal v-model:show="pwdShow" preset="card" title="一次性口令（仅本次展示）" style="width: 420px">
      <p style="margin: 0 0 10px; font-size: 13px">
        请立即复制并告知用户，关闭后无法再次查看：
      </p>
      <n-input :value="createdPwd" readonly class="mono" style="font-size: 15px" />
      <template #footer>
        <div style="display: flex; justify-content: flex-end">
          <n-button type="primary" @click="pwdShow = false">我已保存</n-button>
        </div>
      </template>
    </n-modal>
  </n-card>
</template>

<style scoped>
.pane-head { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; }
.pane-head .spacer { flex: 1; }
.ops { display: inline-flex; gap: 6px; justify-content: flex-end; }
.detail-cell { font-size: 11.5px; word-break: break-all; max-width: 420px; }
</style>
