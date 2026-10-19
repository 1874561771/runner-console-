<script setup>
import { ref } from "vue";
import { useRouter } from "vue-router";
import { NCard, NTabs, NTabPane, NForm, NFormItem, NInput, NButton, useMessage } from "naive-ui";
import { useAuthStore } from "../stores/auth.js";

const router = useRouter();
const auth = useAuthStore();
const message = useMessage();

const tab = ref("local");
const username = ref("");
const password = ref("");
const token = ref("");
const busy = ref(false);

async function submit() {
  busy.value = true;
  try {
    const payload = tab.value === "local"
      ? { username: username.value.trim(), password: password.value, mode: "local" }
      : { token: token.value.trim(), mode: "gitlab" };
    await auth.login(payload);
    message.success(`欢迎，${auth.displayName}`);
    router.push("/console");
  } catch (err) {
    message.error(err.message || "登录失败");
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <div class="login-wrap">
    <div class="login-card">
      <h1 class="login-title">Runner Console</h1>
      <p class="login-sub">内网自动化运行平台 · 账号由管理员创建</p>
      <n-card>
        <n-tabs v-model:value="tab" type="segment" size="small">
          <n-tab-pane name="local" tab="本地账号">
            <n-form label-placement="top" size="small" @keyup.enter="submit">
              <n-form-item label="用户名">
                <n-input v-model:value="username" placeholder="你的名字" />
              </n-form-item>
              <n-form-item label="密码">
                <n-input v-model:value="password" type="password" show-password-on="click" placeholder="密码" />
              </n-form-item>
              <n-button type="primary" block :loading="busy" @click="submit">登录</n-button>
            </n-form>
          </n-tab-pane>
          <n-tab-pane name="gitlab" tab="GitLab PAT">
            <n-form label-placement="top" size="small" @keyup.enter="submit">
              <n-form-item label="Personal Access Token（至少 read_api，仅用于校验）">
                <n-input v-model:value="token" type="password" show-password-on="click" placeholder="glpat-…" />
              </n-form-item>
              <n-button type="primary" block :loading="busy" @click="submit">登录</n-button>
            </n-form>
          </n-tab-pane>
        </n-tabs>
      </n-card>
    </div>
  </div>
</template>
