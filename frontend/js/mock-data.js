/* ═══════════════════════════════════════════════════════════════
   mock-data.js — Mock 模式内存假数据
   后端未就绪时 T10-T12 全靠它开发。数据形状 = 未来真实 API 契约。
   loop_id 形如 20261015093000-a1b2c3；run_id 形如 20261015093112-f3e4d5。
   ═══════════════════════════════════════════════════════════════ */

/* T12：导出供 api.js mock 路由复用（生成 updated_at / 审计时间戳） */
export const now = () => new Date().toISOString().replace("T", " ").slice(0, 19);

export const mockMe = {
  auth_mode: "local",
  gitlab_url: "",
  user: {
    id: 1,
    username: "wyj",
    name: "王奕杰",
    role: "admin",
    last_login: now(),
  },
};

export const mockConfig = {
  workdir: "D:\\RunnerConsole",
  products: ["firebox"],
  branches: [
    { name: "HEAD", current: true },
    { name: "main", current: false },
    { name: "release/2.6", current: false },
  ],
  suites: [
    { name: "smoke_all", cases: 12 },
    { name: "network_basic", cases: 8 },
    { name: "vpn_tunnel", cases: 15 },
  ],
  tests: [
    "scripts/firebox/network/ping_wan.py",
    "scripts/firebox/vpn/ssl_vpn_login.py",
    "scripts/firebox/ui/login_logout.py",
  ],
};

export const mockEnvs = [
  {
    id: "env-01", name: "lab-fbox-12", owner_id: 1, owner_name: "wyj",
    disabled: false, updated_at: now(),
    lock: { held: true, stale: false, run_id: "20261015093112-f3e4d5", owner_name: "wyj" },
    missing: [],
  },
  {
    id: "env-02", name: "lab-fbox-13", owner_id: 2, owner_name: "lct",
    disabled: false, updated_at: now(),
    lock: { held: false, stale: false, run_id: null, owner_name: null },
    missing: [],
  },
  {
    id: "env-03", name: "lab-fbox-21", owner_id: 1, owner_name: "wyj",
    disabled: true, updated_at: now(),
    lock: { held: false, stale: true, run_id: "20261014082210-99a0bb", owner_name: null },
    missing: ["FIREBOX1_WEBUI_URL"],
  },
];

/* T7 对齐：用户增加 source 字段（gitlab | local），管理页「来源」列用 */
export const mockUsers = [
  { id: 1, username: "wyj", name: "王奕杰", role: "admin", source: "local",  last_login: now() },
  { id: 2, username: "lct", name: "李晨涛", role: "user",  source: "local",  last_login: now() },
  { id: 3, username: "qhl", name: "钱浩岚", role: "user",  source: "gitlab", last_login: "2026-10-12 16:40:21" },
];

/* T7 对齐：审计日志 GET /api/admin/audit?offset=&limit= → { items, total }
   26 条滚动生成，管理页「加载更多」分页可见效果 */
const AUDIT_SEEDS = [
  ["wyj",   "run.start",    "loop 20261015{h} · smoke_all ×3"],
  ["lct",   "env.save",     "lab-fbox-13"],
  ["admin", "retain.save",  "count=0 days=14"],
  ["wyj",   "user.role",    "qhl → user"],
  ["lct",   "upload.del",   "vpn_regress.py"],
  ["wyj",   "env.del",      "lab-fbox-99"],
  ["lct",   "run.start",    "loop 20261014{h} · network_basic ×2"],
  ["admin", "user.reset",   "qhl 新口令已生成"],
];
export const mockAudit = Array.from({ length: 26 }, (_, i) => {
  const [actor, action, tpl] = AUDIT_SEEDS[i % AUDIT_SEEDS.length];
  const day = Math.max(1, 15 - Math.floor(i / 4));
  const hh = 21 - (i % 4) * 3;
  return {
    created_at: `2026-10-${String(day).padStart(2, "0")} ${String(hh).padStart(2, "0")}:${String((i * 17) % 60).padStart(2, "0")}:12`,
    actor, action,
    detail: tpl.replace("{h}", String(hh).padStart(2, "0")),
  };
});

/* T7 对齐：POST /api/admin/settings 响应增加 cleaned（本次清理 run 数） */
export const mockRetention = {
  retain_count: 0,
  retain_days: 14,
};

/* ── Jobs（loop 内 iteration 明细）────────────────────────── */
const jobsFor = (loopId, n, mixed) => {
  const out = [];
  for (let i = 1; i <= n; i++) {
    const status = mixed
      ? (i === 1 ? "fail" : i === n && n > 2 ? "running" : "pass")
      : "pass";
    out.push({
      iteration: i,
      loop_id: loopId,
      run_id: status === "running" ? null : `${loopId.split("-")[0]}1${String(i).padStart(2, "0")}-r${i}e4d5`,
      status,                                   // pass | fail | setup_fail | running
      passed: status === "pass" ? 12 : status === "fail" ? 10 : null,
      total: status === "running" ? null : 12,
      started_at: now(),
      ended_at: status === "running" ? null : now(),
      job_duration_s: 214 + i * 17,
      exit_code: status === "setup_fail" ? 2 : 0,
      failed_reason: status === "fail" ? "3 case(s) failed: vpn/ssl_vpn_login ×2" : "",
      has_artifacts: status !== "running",
      has_summary: status !== "running",
    });
  }
  return out;
};

export const mockLoops = [
  {
    id: "20261015093000-a1b2c3",
    created_at: "2026-10-15 09:30:00",              // T7 对齐：列表时间筛选依赖 created_at
    owner_name: "wyj", env_id: "env-01", env_name: "lab-fbox-12",
    product: "firebox", source: "repo",
    suite: "smoke_all", test: "", git_ref: "main",
    firmware_branch: "utm-2026_2", firmware_build: "733385",
    repeat_total: 3, iterations: 3, passed_iters: 2, fail_iters: 1,
    status: "running",                            // running | done | stopped
    pause_on_fail: false, stop_reason: "",
    iteration_statuses: [
      { iteration: 1, status: "fail" },
      { iteration: 2, status: "pass" },
      { iteration: 3, status: "running" },
    ],
    jobs: jobsFor("20261015093000-a1b2c3", 3, true),
  },
  {
    id: "20261014201500-d4e5f6",
    created_at: "2026-10-14 20:15:00",
    owner_name: "lct", env_id: "env-02", env_name: "lab-fbox-13",
    product: "firebox", source: "repo",
    suite: "network_basic", test: "", git_ref: "HEAD",
    firmware_branch: "", firmware_build: "",
    repeat_total: 2, iterations: 2, passed_iters: 2, fail_iters: 0,
    status: "done", pause_on_fail: false, stop_reason: "",
    iteration_statuses: [
      { iteration: 1, status: "pass" },
      { iteration: 2, status: "pass" },
    ],
    jobs: jobsFor("20261014201500-d4e5f6", 2, false),
  },
  {
    id: "20261013142200-g7h8i9",
    created_at: "2026-10-13 14:22:00",
    owner_name: "qhl", env_id: "env-03", env_name: "lab-fbox-21",
    product: "firebox", source: "repo",
    suite: "vpn_tunnel", test: "", git_ref: "release/2.6",
    firmware_branch: "utm-2026_2", firmware_build: "732001",
    repeat_total: 0, iterations: 3, passed_iters: 1, fail_iters: 2,
    status: "stopped", pause_on_fail: true,
    stop_reason: "手动停止：连续 setup_fail",
    iteration_statuses: [
      { iteration: 1, status: "pass" },
      { iteration: 2, status: "setup_fail" },
      { iteration: 3, status: "fail" },
    ],
    jobs: jobsFor("20261013142200-g7h8i9", 3, false),
  },
];

/* ── 我的测试上传列表（T10「我的测试」下拉 + T12 资源页共用）──
   T7 对齐：资源页/上传契约含 uploaded_at（suite | script 徽标） */
export const mockUploads = [
  { id: "up-01", kind: "suite",  name: "my_smoke",   relpath: "my_smoke.suite",            owner_name: "wyj", uploaded_at: "2026-10-15 09:12:44" },
  { id: "up-02", kind: "script", name: "ping_wan",   relpath: "scripts/my/ping_wan.py",    owner_name: "wyj", uploaded_at: "2026-10-14 17:03:21" },
  { id: "up-03", kind: "script", name: "ui_probe",   relpath: "scripts/my/ui_probe.py",    owner_name: "lct", uploaded_at: "2026-10-13 11:40:08" },
];

/* ── POST /api/run：新建 loop 并置于 running（T10 mock 验收用）────────
   契约：请求体 { env_id, product, source, git_ref, upload_id, suite, test,
   headless, branch, build, repeat(0=无限), pause_on_fail } → 响应 { loop_id } */
export function mockRun(body = {}) {
  const env = mockEnvs.find((e) => e.id === body.env_id) || mockEnvs[0];
  const stamp = new Date().toISOString().replace(/[-:T]/g, "").slice(0, 14);
  const id = `${stamp}-${Math.random().toString(16).slice(2, 8)}`;
  const loop = {
    id, owner_name: mockMe.user.username, env_id: env.id, env_name: env.name,
    product: body.product || "firebox", source: body.source || "repo",
    suite: body.suite || "", test: body.test || "", git_ref: body.git_ref || "HEAD",
    firmware_branch: body.branch || "", firmware_build: body.build || "",
    repeat_total: body.repeat ?? 1, iterations: 0, passed_iters: 0, fail_iters: 0,
    status: "running", pause_on_fail: !!body.pause_on_fail, stop_reason: "",
    iteration_statuses: [{ iteration: 1, status: "running" }],
    jobs: [{
      iteration: 1, loop_id: id, run_id: null, status: "running",
      passed: null, total: null, started_at: now(), ended_at: null,
      job_duration_s: null, exit_code: null, failed_reason: "",
      has_artifacts: false, has_summary: false,
    }],
  };
  mockLoops.unshift(loop);
  return { loop_id: id };
}

/* ── Runs（全部 Job / 历史材料，含 legacy）────────────────── */
export const mockRuns = [
  {
    run_id: "20261015093112-f3e4d5", mtime: now(),
    status: "running", passed: null, failed: null, broken: null, total: null,
    branch: "utm-2026_2", build: "733385",
    env_name: "lab-fbox-12", git_ref: "main", host: "lab-fbox-12",
    loop_id: "20261015093000-a1b2c3", iteration: 3,
    owner_name: "wyj", job_duration_s: null,
    failed_reason: "", has_summary: false,
  },
  {
    run_id: "20261015092705-b7c8d9", mtime: "2026-10-15 09:32:40",
    status: "fail", passed: 10, failed: 2, broken: 0, total: 12,
    branch: "utm-2026_2", build: "733385",
    env_name: "lab-fbox-12", git_ref: "main", host: "lab-fbox-12",
    loop_id: "20261015093000-a1b2c3", iteration: 1,
    owner_name: "wyj", job_duration_s: 231,
    failed_reason: "vpn/ssl_vpn_login ×2", has_summary: true,
  },
  {
    run_id: "20261015093012-c2d3e4", mtime: "2026-10-15 09:36:02",
    status: "pass", passed: 12, failed: 0, broken: 0, total: 12,
    branch: "utm-2026_2", build: "733385",
    env_name: "lab-fbox-12", git_ref: "main", host: "lab-fbox-12",
    loop_id: "20261015093000-a1b2c3", iteration: 2,
    owner_name: "wyj", job_duration_s: 248,
    failed_reason: "", has_summary: true,
  },
  {
    run_id: "20261014201611-e5f6a7", mtime: "2026-10-14 20:22:38",
    status: "pass", passed: 8, failed: 0, broken: 0, total: 8,
    branch: "", build: "",
    env_name: "lab-fbox-13", git_ref: "HEAD", host: "lab-fbox-13",
    loop_id: "20261014201500-d4e5f6", iteration: 1,
    owner_name: "lct", job_duration_s: 176,
    failed_reason: "", has_summary: true,
  },
];

/* ── Cases（run 内用例明细）───────────────────────────────── */
export const mockCases = {
  "20261015092705-b7c8d9": [
    { name: "network/ping_wan",              status: "pass", duration_s: 4.2,  message: "" },
    { name: "network/dns_resolve",           status: "pass", duration_s: 3.8,  message: "" },
    { name: "vpn/ssl_vpn_login",             status: "fail", duration_s: 61.4, message: "Timeout waiting for portal page" },
    { name: "vpn/ssl_vpn_tunnel",            status: "fail", duration_s: 58.9, message: "Tunnel not up after 60s" },
    { name: "ui/login_logout",               status: "pass", duration_s: 11.2, message: "" },
    { name: "smoke/device_info",             status: "broken", duration_s: 0,  message: "Job setup: firmware build not reachable" },
  ],
  "20261015093012-c2d3e4": [
    { name: "network/ping_wan", status: "pass", duration_s: 4.0, message: "" },
    { name: "vpn/ssl_vpn_login", status: "pass", duration_s: 33.1, message: "" },
    { name: "ui/login_logout", status: "pass", duration_s: 10.8, message: "" },
  ],
};

/* ── 运行台 console append 流（SSE mock 用）────────────────── */
export const mockConsoleLines = [
  "[09:31:12] runner: worktree ready (main @ 4f2a9c1)",
  "[09:31:13] runner: firmware utm-2026_2 build 733385",
  "[09:31:14] suite smoke_all: 12 cases",
  "[09:31:15] case network/ping_wan … PASS (4.0s)",
  "[09:31:19] case network/dns_resolve … PASS (3.8s)",
  "[09:31:23] case vpn/ssl_vpn_login … running",
  "[09:31:47] case vpn/ssl_vpn_login … FAIL (61.4s) Timeout waiting for portal page",
  "[09:32:50] case ui/login_logout … PASS (11.2s)",
  "[09:32:52] summary: 10/12 pass, 2 fail",
];

/* ── 数据看板 stats（T12 Chart.js 用）───────────────────────── */
export const mockStats = {
  jobs: 148, loops: 39, running: 1,
  pass_rate: 0.872, failed_jobs: 12, broken_jobs: 4,
  trend: [
    { date: "2026-10-09", pass_rate: 0.83 }, { date: "2026-10-10", pass_rate: 0.86 },
    { date: "2026-10-11", pass_rate: 0.91 }, { date: "2026-10-12", pass_rate: 0.88 },
    { date: "2026-10-13", pass_rate: 0.85 }, { date: "2026-10-14", pass_rate: 0.90 },
    { date: "2026-10-15", pass_rate: 0.87 },
  ],
  fail_cases: [
    { name: "vpn/ssl_vpn_login", count: 7 },
    { name: "vpn/ssl_vpn_tunnel", count: 5 },
    { name: "network/dns_resolve", count: 3 },
    { name: "ui/login_logout", count: 2 },
  ],
  loop_bars: [
    { created_at: "2026-10-15 09:30", suite: "smoke_all",
      iterations: [{ iteration: 1, status: "fail" }, { iteration: 2, status: "pass" }, { iteration: 3, status: "running" }] },
    { created_at: "2026-10-14 20:15", suite: "network_basic",
      iterations: [{ iteration: 1, status: "pass" }, { iteration: 2, status: "pass" }] },
  ],
};

/* mock 登录会话 token */
export const MOCK_SESSION = "mock-session-token";

/* ── T16/T17：定时任务 / 保存的套件 / 按分支 case（mock 演示）── */
export const mockCaseGroups = [
  { feature: "scripts/firebox/network", cases: [
    "scripts/firebox/network/firebox_network_dhcp_secondary.py",
    "scripts/firebox/network/firebox_network_lan_basic.py",
    "scripts/firebox/network/firebox_network_wan_pppoe.py",
  ] },
  { feature: "scripts/firebox/smoke", cases: [
    "scripts/firebox/smoke/firebox_smoke_login.py",
  ] },
  { feature: "scripts/firebox/dashboard", cases: [
    "scripts/firebox/dashboard/firebox_dashboard_front_panel.py",
  ] },
];

export const mockSuites = [
  { id: "suitemock01", owner_id: 1, owner_name: "wyj", name: "报关冒烟集", product: "firebox",
    cases: ["scripts/firebox/smoke/firebox_smoke_login.py", "scripts/firebox/network/firebox_network_lan_basic.py"],
    created_at: "2026-10-15 09:00:00", updated_at: "2026-10-16 14:20:00" },
];

export const mockSchedules = [
  { id: "schedmock01", owner_id: 1, owner_name: "wyj", name: "每晚报关回归",
    env_id: "envmock01", env_name: "lab-fbox-12",
    params: { env_id: "envmock01", product: "firebox", source: "repo", git_ref: "main",
      suite: "", cases: ["scripts/firebox/smoke/firebox_smoke_login.py"], repeat: 1, headless: false },
    rule_type: "daily", time: "22:30", run_at: null,
    enabled: true, next_run_at: "2026-10-17 22:30:00",
    last_loop_id: "20261016223000-a1b2c3", last_status: "started",
    last_note: "已发起 loop 20261016223000-a1b2c3", created_at: "2026-10-15 09:00:00" },
];
