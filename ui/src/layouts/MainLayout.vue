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
  { to: "/console", label: "运行台", public: true },
  { to: "/schedules", label: "定时任务" },
  { to: "/tasks", label: "任务中心", public: true },
  { to: "/dashboard", label: "数据看板" },
  { to: "/resources", label: "资源" },
  { to: "/admin", label: "管理", adminOnly: true },
];
const title = computed(() => route.meta.title || "Runner Console");
const visibleNavs = computed(() => navs.filter((n) =>
  (!n.adminOnly || auth.isAdmin) && (auth.user || n.public)
));

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
      <span class="user">{{ auth.user ? `${auth.displayName}（${auth.user.role}）` : "游客（只读）" }}</span>
      <n-button v-if="auth.user" size="tiny" quaternary color="#f0f1ee" @click="logout">退出</n-button>
      <n-button v-else size="tiny" quaternary color="#f0f1ee"
        @click="router.push({ name: 'login', query: { redirect: route.fullPath } })">登录</n-button>
    </header>
    <div class="app-main">
      <nav class="app-nav">
        <router-link v-for="n in visibleNavs" :key="n.to" :to="n.to">{{ n.label }}</router-link>
      </nav>
      <main class="app-content">
        <router-view />
      </main>
    </div>
  </div>
</template>
