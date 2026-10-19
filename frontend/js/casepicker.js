/* ═══════════════════════════════════════════════════════════════
   casepicker.js — Case 勾选器（运行台「勾选 Case」模式 / 定时任务 /
   资源页套件编辑共用）。

   mountCasePicker(container, {ref, product, selected, onChange, height})
   * 拉取 GET /api/cases?ref=&product=，按 feature 分组展示
   * 搜索框实时过滤（路径/名称）+ 一键全选（对当前过滤结果）+ 一键清除
   * 组头有组级全选；选中集合通过 onChange(Set) 回调
   * 返回 { getSelected(), refresh(), destroy() }
   ═══════════════════════════════════════════════════════════════ */
import { apiFetch } from "./api.js";
import { esc } from "./ui.js";

export function mountCasePicker(container, opts = {}) {
  const state = {
    ref: opts.ref || "HEAD",
    product: opts.product || "",
    selected: new Set(opts.selected || []),
    groups: [],          // [{feature, cases:[path]}]
    filter: "",
    loading: true,
    error: "",
    dead: false,
  };
  const onChange = opts.onChange || (() => {});

  container.innerHTML = `
    <div class="cp-box" style="${opts.height ? `max-height:${opts.height}px;` : ""}">
      <div class="cp-toolbar">
        <input class="input cp-search" type="text" placeholder="搜索 case（路径 / 名称）…" autocomplete="off"/>
        <button type="button" class="btn btn-ghost btn-sm cp-all">全选</button>
        <button type="button" class="btn btn-ghost btn-sm cp-clear">清除</button>
        <span class="cp-count faint"></span>
      </div>
      <div class="cp-body"><div class="cp-loading">加载中…</div></div>
    </div>`;

  const searchEl = container.querySelector(".cp-search");
  const bodyEl = container.querySelector(".cp-body");
  const countEl = container.querySelector(".cp-count");

  searchEl.addEventListener("input", () => {
    state.filter = searchEl.value.trim().toLowerCase();
    renderGroups();
  });
  container.querySelector(".cp-all").addEventListener("click", () => {
    visibleCases().forEach((c) => state.selected.add(c));
    renderGroups();
    onChange(new Set(state.selected));
  });
  container.querySelector(".cp-clear").addEventListener("click", () => {
    state.selected.clear();
    renderGroups();
    onChange(new Set(state.selected));
  });

  function visibleGroups() {
    if (!state.filter) return state.groups;
    return state.groups
      .map((g) => ({
        feature: g.feature,
        cases: g.cases.filter((c) => c.toLowerCase().includes(state.filter)),
      }))
      .filter((g) => g.cases.length);
  }
  function visibleCases() {
    return visibleGroups().flatMap((g) => g.cases);
  }

  function renderGroups() {
    if (state.dead || !bodyEl) return;
    if (state.loading) { bodyEl.innerHTML = `<div class="cp-loading">加载中…</div>`; return; }
    if (state.error) { bodyEl.innerHTML = `<div class="cp-loading">${esc(state.error)}</div>`; return; }
    if (!state.groups.length) {
      bodyEl.innerHTML = `<div class="cp-loading">该分支下没有 case</div>`;
      countEl.textContent = "";
      return;
    }
    const groups = visibleGroups();
    const total = state.groups.reduce((n, g) => n + g.cases.length, 0);
    countEl.textContent = `已选 ${state.selected.size} / ${total}`;
    bodyEl.innerHTML = groups.map((g) => {
      const allOn = g.cases.every((c) => state.selected.has(c));
      return `
        <div class="cp-group">
          <label class="cp-group-head">
            <input type="checkbox" class="cp-grp-chk" data-feat="${esc(g.feature)}" ${allOn ? "checked" : ""}/>
            <span class="cp-feat">${esc(g.feature)}</span>
            <span class="faint">(${g.cases.length})</span>
          </label>
          ${g.cases.map((c) => `
            <label class="cp-case ${state.filter ? "cp-hit" : ""}">
              <input type="checkbox" data-path="${esc(c)}" ${state.selected.has(c) ? "checked" : ""}/>
              <span class="cp-path" title="${esc(c)}">${esc(c.split("/").pop())}</span>
              <span class="cp-dir faint">${esc(c.split("/").slice(0, -1).join("/"))}</span>
            </label>`).join("")}
        </div>`;
    }).join("");
    bodyEl.querySelectorAll("input[data-path]").forEach((chk) =>
      chk.addEventListener("change", () => {
        if (chk.checked) state.selected.add(chk.dataset.path);
        else state.selected.delete(chk.dataset.path);
        countEl.textContent = `已选 ${state.selected.size}`;
        onChange(new Set(state.selected));
      }));
    bodyEl.querySelectorAll(".cp-grp-chk").forEach((chk) =>
      chk.addEventListener("change", () => {
        const g = groups.find((x) => x.feature === chk.dataset.feat);
        if (!g) return;
        g.cases.forEach((c) => (chk.checked ? state.selected.add(c) : state.selected.delete(c)));
        renderGroups();
        onChange(new Set(state.selected));
      }));
  }

  async function load() {
    state.loading = true;
    state.error = "";
    renderGroups();
    try {
      const res = await apiFetch(
        `/api/cases?ref=${encodeURIComponent(state.ref)}&product=${encodeURIComponent(state.product)}`);
      const data = await res.json();
      if (state.dead) return;
      if (!res.ok) throw new Error(data.error || "加载失败");
      state.groups = Array.isArray(data.groups) ? data.groups : [];
      // 分支上已不存在的勾选项保留显示（运行时会由 runner 报错提示）
      const existing = new Set(state.groups.flatMap((g) => g.cases));
      const missing = [...state.selected].filter((c) => !existing.has(c));
      if (missing.length) {
        state.groups.push({ feature: `已勾选但该分支不存在 (${missing.length})`, cases: missing });
      }
    } catch (err) {
      state.error = err.message || "加载失败";
    }
    state.loading = false;
    renderGroups();
  }

  load();

  return {
    getSelected: () => new Set(state.selected),
    setSelected(list) { state.selected = new Set(list || []); renderGroups(); },
    setRef(ref) { if (ref && ref !== state.ref) { state.ref = ref; load(); } },
    destroy() { state.dead = true; },
  };
}
