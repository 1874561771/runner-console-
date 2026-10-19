<script setup>
import { computed } from "vue";
import { useRoute, useRouter } from "vue-router";
import { NButton, useDialog, useMessage } from "naive-ui";
import { useAuthStore } from "../stores/auth.js";

const route = useRoute();
const router = useRouter();
const auth = useAuthStore();
const dialog = useDialog();
const message = useMessage();

const navs = [
  { to: "/console", label: "运行台" },
  { to: "/schedules", label: "定时任务" },
  { to: "/tasks", label: "任务中心" },
  { to: "/dashboard", label: "数据看板" },
  { to: "/resources", label: "资源" },
  { to: "/admin", label: "管理" },
];
const title = computed(() => route.meta.title || "Runner Console");

async function logout() {
  dialog.warning({
    title: "退出登录",
    content: "确定退出当前会话？",
    positiveText: "退出",
    negativeText: "取消",
    onPositiveClick: async () => {
      await auth.logout();
      message.success("已退出");
      router.push("/login");
    },
  });
}
</script>

<template>
  <div class="app-shell">
    <header class="app-topbar">
      <span class="brand">Runner Console</span>
      <span style="font-size:12px;opacity:.6">{{ title }}</span>
      <span class="spacer"></span>
      <span class="user">{{ auth.displayName }}（{{ auth.user?.role }}）</span>
      <n-button size="tiny" quaternary color="#f0f1ee" @click="logout">退出</n-button>
    </header>
    <div class="app-main">
      <nav class="app-nav">
        <router-link v-for="n in navs" :key="n.to" :to="n.to">{{ n.label }}</router-link>
      </nav>
      <main class="app-content">
        <router-view />
      </main>
    </div>
  </div>
</template>
