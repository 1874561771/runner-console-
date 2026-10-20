import { createRouter, createWebHashHistory } from "vue-router";
import { useAuthStore } from "../stores/auth.js";

const routes = [
  { path: "/login", name: "login", component: () => import("../views/LoginView.vue") },
  {
    path: "/",
    component: () => import("../layouts/MainLayout.vue"),
    children: [
      { path: "", redirect: "/console" },
      { path: "console", name: "console", component: () => import("../views/ConsoleView.vue"), meta: { title: "运行台" } },
      { path: "schedules", name: "schedules", component: () => import("../views/SchedulesView.vue"), meta: { title: "定时任务" } },
      { path: "tasks", name: "tasks", component: () => import("../views/TasksView.vue"), meta: { title: "任务中心" } },
      { path: "dashboard", name: "dashboard", component: () => import("../views/PlaceholderView.vue"), meta: { title: "数据看板" } },
      { path: "resources", name: "resources", component: () => import("../views/ResourcesView.vue"), meta: { title: "资源" } },
      { path: "admin", name: "admin", component: () => import("../views/PlaceholderView.vue"), meta: { title: "管理" } },
    ],
  },
  { path: "/:pathMatch(.*)*", redirect: "/console" },
];

export const router = createRouter({
  history: createWebHashHistory("/v2/"),
  routes,
});

/* 登录守卫：首次导航先拉 /api/me */
router.beforeEach(async (to) => {
  const auth = useAuthStore();
  if (!auth.loaded) await auth.fetchMe();
  if (!auth.user && to.name !== "login") return { name: "login" };
  if (auth.user && to.name === "login") return { path: "/console" };
  return true;
});
