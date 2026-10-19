import { defineStore } from "pinia";
import { apiFetch, asJson } from "../api/client.js";

export const useConsoleStore = defineStore("console", {
  state: () => ({
    loaded: false,
    config: { products: [], branches: [], suites: [], tests: [] },
    envs: [],
    uploads: [],
    suitesSaved: [],
    loops: [],
    envId: "",
    form: {
      product: "firebox", source: "repo", gitRef: "HEAD", uploadId: "",
      targetMode: "suite", suite: "", test: "", cases: [], savedSuiteId: "",
      repeat: 1, unlimited: false, pauseOnFail: false, headless: false,
      fwBranch: "", fwBuild: "",
    },
    loop: null, // 绑定的 loop 详情 {loop: {...}}
  }),

  getters: {
    currentEnv: (s) => s.envs.find((e) => e.id === s.envId) || null,
    repeatCount: (s) => (s.form.unlimited ? 0 : Math.max(1, parseInt(s.form.repeat, 10) || 1)),

    /* POST /api/run / 定时任务快照共用的载荷 */
    runParams(state) {
      const f = state.form;
      return {
        env_id: state.envId,
        product: f.product,
        source: f.source,
        git_ref: f.gitRef,
        upload_id: f.source === "upload" ? f.uploadId : "",
        suite: f.source === "repo" && f.targetMode === "suite" ? f.suite : "",
        test: f.source === "repo" && f.targetMode === "test" ? f.test : "",
        cases: f.source === "repo" && f.targetMode === "cases" ? [...f.cases] : [],
        headless: f.headless,
        branch: f.fwBranch,
        build: f.fwBuild,
        repeat: f.unlimited ? 0 : Math.max(1, parseInt(f.repeat, 10) || 1),
        pause_on_fail: f.pauseOnFail,
      };
    },

    /* 命令预览 {pure, note} */
    commandPreview(state) {
      const f = state.form;
      const parts = [`python -m runner --product ${f.product}`];
      const notes = [];
      if (f.source === "repo") {
        if (f.targetMode === "suite") {
          f.suite ? parts.push(`--suite ${f.suite}`) : notes.push("未选择 Suite");
        } else if (f.targetMode === "test") {
          f.test ? parts.push(`--test ${f.test}`) : notes.push("未选择 Test");
        } else {
          f.cases.length
            ? parts.push(`--suite （勾选 ${f.cases.length} case → 运行时生成临时套件）`)
            : notes.push("未勾选 Case");
        }
      } else {
        const up = state.uploads.find((u) => u.id === f.uploadId);
        if (!up) notes.push("未选择我的测试");
        else if (up.kind === "suite") parts.push(`--suite ${up.name}`);
        else parts.push(`--test ${up.relpath}`);
      }
      if (f.headless) parts.push("--headless true");
      if (f.fwBranch) {
        parts.push(`--branch ${f.fwBranch}`);
        if (f.fwBuild) parts.push(`--build ${f.fwBuild}`);
      }
      notes.push(f.gitRef || "HEAD");
      notes.push(f.unlimited ? "×∞" : `×${Math.max(1, parseInt(f.repeat, 10) || 1)}`);
      if (f.pauseOnFail) notes.push("pause-on-fail");
      return { pure: parts.join(" "), note: notes.join(" · ") };
    },
  },

  actions: {
    async loadAll() {
      const [config, envs, uploads, loops, suitesSaved] = await Promise.all([
        apiFetch("/api/config", {}).then(asJson).catch(() => ({})),
        apiFetch("/api/envs", []).then(asJson).catch(() => []),
        apiFetch("/api/uploads", []).then(asJson).catch(() => []),
        apiFetch("/api/loops", []).then(asJson).catch(() => []),
        apiFetch("/api/suites", []).then(asJson).catch(() => []),
      ]);
      this.config = { products: [], branches: [], suites: [], tests: [], ...config };
      this.envs = Array.isArray(envs) ? envs : [];
      this.uploads = Array.isArray(uploads) ? uploads : [];
      this.loops = Array.isArray(loops) ? loops : [];
      this.suitesSaved = Array.isArray(suitesSaved) ? suitesSaved : [];
      if (!this.envId) this.envId = this.envs.find((e) => !e.disabled)?.id || "";
      if (!this.loaded) this._initFormDefaults();
      this.loaded = true;
    },

    _initFormDefaults() {
      const f = this.form;
      f.product = this.config.products[0] || "firebox";
      const cur = (this.config.branches || []).find((b) => b.current);
      f.gitRef = cur?.name || this.config.branches?.[0]?.name || "HEAD";
      f.suite = this.config.suites?.[0]?.name || "";
      f.test = this.config.tests?.[0] || "";
      f.uploadId = this.uploads[0]?.id || "";
    },

    async refreshLoops() {
      try {
        const loops = await asJson(await apiFetch("/api/loops"));
        this.loops = Array.isArray(loops) ? loops : [];
      } catch { /* 瞬时错误忽略 */ }
    },

    async refreshSuites() {
      try {
        const suites = await asJson(await apiFetch("/api/suites"));
        this.suitesSaved = Array.isArray(suites) ? suites : [];
      } catch { /* 忽略 */ }
    },

    applySavedSuite(id) {
      const s = this.suitesSaved.find((x) => x.id === id);
      this.form.savedSuiteId = id;
      this.form.cases = s ? [...s.cases] : [];
    },

    validateTarget() {
      const f = this.form;
      if (!this.envId) return "请先选择环境";
      if (f.source === "repo" && f.targetMode === "suite" && !f.suite) return "请选择 Suite";
      if (f.source === "repo" && f.targetMode === "test" && !f.test) return "请选择 Test";
      if (f.source === "repo" && f.targetMode === "cases" && !f.cases.length) return "请勾选至少一个 Case";
      if (f.source === "upload" && !f.uploadId) return "请选择我的测试";
      return "";
    },

    async bindLoop(id) {
      const d = await asJson(await apiFetch(`/api/loops/${encodeURIComponent(id)}/status`));
      this.loop = d?.loop ? d : { loop: d };
      return this.loop;
    },
  },
});
