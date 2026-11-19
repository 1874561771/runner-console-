import { defineStore } from "pinia";
import { apiFetch, setUnauthorizedHandler } from "../api/client.js";

export const useAuthStore = defineStore("auth", {
  state: () => ({ user: null, loaded: false }),
  getters: {
    isAdmin: (s) => s.user?.role === "admin",
    displayName: (s) => s.user?.name || s.user?.username || "",
  },
  actions: {
    async fetchMe() {
      try {
        // 首次导航由路由守卫负责跳转并保留目标地址，避免全局 401
        // 处理器抢先跳到登录页而丢失用户原本访问的页面。
        const d = await apiFetch("/api/me", { handleUnauthorized: false });
        this.user = d?.user || d || null;
      } catch {
        this.user = null;
      }
      this.loaded = true;
      return this.user;
    },
    async login(payload) {
      const d = await apiFetch("/api/login", { method: "POST", body: payload });
      this.user = d?.user || d || null;
      return this.user;
    },
    async logout() {
      try { await apiFetch("/api/logout", { method: "POST" }); } catch { /* 忽略 */ }
      this.user = null;
    },
  },
});

/* 401 → 清会话；路由守卫会跳登录页 */
export function wireUnauthorized(router) {
  setUnauthorizedHandler(() => {
    const auth = useAuthStore();
    auth.user = null;
    auth.loaded = true;
    const current = router.currentRoute.value;
    if (current.name !== "login") {
      router.replace({
        name: "login",
        query: { redirect: current.fullPath },
      });
    }
  });
}
