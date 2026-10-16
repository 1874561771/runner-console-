/* ═══════════════════════════════════════════════════════════════
   ui.js — 视图共用小组件（T12）
   esc / toast / openModal / confirmDialog / skeletonRows / emptyState
   样式见 design-tokens.css 尾部「视图扩展」分区。
   ═══════════════════════════════════════════════════════════════ */

export const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

/* ── toast（body 级单例）──────────────────────────────────── */
let toastEl = null;
let toastTimer = null;

export function toast(msg, kind = "") {
  if (!toastEl) {
    toastEl = document.createElement("div");
    toastEl.className = "rc-toast";
    document.body.appendChild(toastEl);
  }
  clearTimeout(toastTimer);
  toastEl.textContent = msg;
  toastEl.className = "rc-toast on" + (kind === "error" ? " error" : "");
  toastTimer = setTimeout(() => toastEl.classList.remove("on"),
    kind === "error" ? 4500 : 2600);
}

/* ── 弹层：遮罩 + 居中卡，返回 { root, close } ─────────────── */
export function openModal({ title, body, footer, width = 520 }) {
  const root = document.createElement("div");
  root.className = "modal-overlay";
  root.innerHTML = `
    <div class="modal-card card" style="width:${width}px">
      <div class="modal-head"><b>${esc(title)}</b>
        <button type="button" class="modal-x" aria-label="关闭">×</button></div>
      <div class="modal-body">${body}</div>
      ${footer ? `<div class="modal-foot">${footer}</div>` : ""}
    </div>`;
  document.body.appendChild(root);
  const close = () => root.remove();
  root.querySelector(".modal-x").addEventListener("click", close);
  root.addEventListener("click", (e) => { if (e.target === root) close(); });
  return { root, close };
}

/* ── 确认弹层：Promise<boolean> ───────────────────────────── */
export function confirmDialog({ title = "请确认", message, danger = false, okText = "确认" }) {
  return new Promise((resolve) => {
    const m = openModal({
      title,
      body: `<p class="confirm-msg">${message}</p>`,
      footer: `<button type="button" class="btn btn-ghost" data-act="cancel">取消</button>
               <button type="button" class="btn ${danger ? "btn-danger" : "btn-primary"}" data-act="ok">${esc(okText)}</button>`,
      width: 420,
    });
    m.root.querySelector('[data-act="cancel"]').addEventListener("click", () => { m.close(); resolve(false); });
    m.root.querySelector('[data-act="ok"]').addEventListener("click", () => { m.close(); resolve(true); });
  });
}

/* ── 骨架屏（加载态）──────────────────────────────────────── */
export function skeletonRows(cols = 3, rows = 4) {
  return `<div class="skeleton-wrap">${Array.from({ length: rows }, () =>
    `<div class="skeleton-row">${'<span class="skeleton-block"></span>'.repeat(cols)}</div>`).join("")}</div>`;
}

/* ── 空态卡 ───────────────────────────────────────────────── */
export function emptyState(text, hint = "") {
  return `<div class="empty-state">
    <div class="empty-icon">○</div>
    <div class="empty-text">${esc(text)}</div>
    ${hint ? `<div class="empty-hint">${esc(hint)}</div>` : ""}
  </div>`;
}
