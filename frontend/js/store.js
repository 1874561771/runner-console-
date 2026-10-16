/* ═══════════════════════════════════════════════════════════════
   store.js — 极简全局状态 + 事件总线
   ═══════════════════════════════════════════════════════════════ */

export const store = {
  currentUser: null,   // { id, username, name, role }
  status: "idle",      // idle | running | error
  authMode: "local",   // local | gitlab
  workdir: "",
};

/* ── 事件总线 ── */
const listeners = new Map(); // event -> Set<fn>

export function on(event, fn) {
  if (!listeners.has(event)) listeners.set(event, new Set());
  listeners.get(event).add(fn);
  return () => off(event, fn); // 返回取消函数
}

export function off(event, fn) {
  listeners.get(event)?.delete(fn);
}

export function emit(event, payload) {
  listeners.get(event)?.forEach((fn) => {
    try { fn(payload); } catch (e) { console.error(`[store] handler for ${event}`, e); }
  });
}
