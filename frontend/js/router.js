/* ═══════════════════════════════════════════════════════════════
   router.js — hash 路由
   #/console（默认）| #/tasks | #/dashboard | #/resources | #/admin
   未登录 → 任何路由先弹登录浮层；nav 高亮同步。
   ═══════════════════════════════════════════════════════════════ */
import { store } from "./store.js";

const routes = {
  console:   () => import("./views/console.js"),
  schedules: () => import("./views/schedules.js"),
  tasks:     () => import("./views/tasks.js"),
  dashboard: () => import("./views/dashboard.js"),
  resources: () => import("./views/resources.js"),
  admin:     () => import("./views/admin.js"),
};

let viewEl = null;
let teardown = null;   // 当前视图的 destroy（清理 timer 等）

export function initRouter(el) {
  viewEl = el;
  window.addEventListener("hashchange", handleRoute);
  handleRoute();
}

export function navigate(route) {
  location.hash = "#/" + route;
}

export function isLoggedIn() {
  return !!store.currentUser;
}

async function handleRoute() {
  if (!viewEl) return;
  if (!isLoggedIn()) {
    // 未登录：只弹登录浮层，不渲染内容；main.js 登录成功后 emit "auth:login" 再调 rerender
    return;
  }
  const name = (location.hash.replace(/^#\//, "") || "console").split("?")[0];
  const loader = routes[name] || routes.console;
  const mod = await loader();
  if (teardown) { try { teardown(); } catch { /* 忽略清理错误 */ } }
  teardown = typeof mod.destroy === "function" ? mod.destroy : null;
  viewEl.innerHTML = "";
  mod.render(viewEl);
  syncNav(name);
}

/* 登录成功 / 登出后由 main.js 调用，重新走当前路由 */
export function rerender() {
  handleRoute();
}

function syncNav(name) {
  document.querySelectorAll(".nav-item[data-route]").forEach((a) => {
    a.classList.toggle("active", a.dataset.route === name);
  });
}
