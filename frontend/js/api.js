/* ═══════════════════════════════════════════════════════════════
   api.js — fetch 封装 + Mock 拦截 + SSE 客户端
   真实后端未就绪时，T10-T12 通过 mock 模式开发，API 契约不变。
   ═══════════════════════════════════════════════════════════════ */
import * as mock from "./mock-data.js";

/* ── Mock 开关：URL 带 ?mock=1，或 localStorage.rc_mock = "1" ── */
export const MOCK = new URLSearchParams(location.search).has("mock")
  || localStorage.getItem("rc_mock") === "1";

export class AuthError extends Error {
  constructor() {
    super("unauthorized");
    this.name = "AuthError";
  }
}

/* 401 时触发全局登出事件（main.js / router.js 监听） */
function fireLogout() {
  window.dispatchEvent(new CustomEvent("rc:logout"));
}

/* ── Mock 路由表 ─────────────────────────────────────────────
   key: "METHOD path"（支持 :param 占位）；value: (body, params) => data   */
const mockRoutes = {
  "POST /api/login": (body) => {
    if (!body || !body.token) throw new Error("请输入 token / 口令");
    return { session: mock.MOCK_SESSION, user: mock.mockMe.user };
  },
  "POST /api/logout": () => ({}),
  "GET /api/me": () => mock.mockMe,
  "GET /api/config": () => mock.mockConfig,
  "GET /api/status": () => ({
    jobs: mock.mockLoops
      .filter((l) => l.status === "running")
      .map((l) => ({ loop_id: l.id, iteration: l.passed_iters + l.fail_iters + 1, repeat_total: l.repeat_total, console_tail: mock.mockConsoleLines.slice(-3) })),
  }),
  "GET /api/envs": () => mock.mockEnvs,
  "POST /api/run": (body) => mock.mockRun(body),
  /* T7 对齐：/api/loops 支持列表过滤 query
     days=today|7|14|30|all  env_id=…  status=running|failed
     （failed = loop 终态 failed，或含失败轮次 fail_iters>0） */
  "GET /api/loops": (_body, _p, query) => {
    let list = [...mock.mockLoops];
    const days = query?.get("days");
    const envId = query?.get("env_id");
    const status = query?.get("status");
    if (days && days !== "all") {
      const min = days === "today"
        ? new Date(new Date().setHours(0, 0, 0, 0)).getTime()
        : Date.now() - Number(days) * 864e5;
      list = list.filter((l) =>
        new Date(String(l.created_at || "").replace(" ", "T")).getTime() >= min);
    }
    if (envId) list = list.filter((l) => l.env_id === envId);
    if (status === "running") list = list.filter((l) => l.status === "running");
    else if (status === "failed") list = list.filter((l) => l.status === "failed" || l.fail_iters > 0);
    return list;
  },
  "GET /api/loops/:id": (_body, p) =>
    mock.mockLoops.find((l) => l.id === p.id) || { error: "loop not found" },
  "GET /api/loops/:id/status": (_body, p) => {
    const l = mock.mockLoops.find((x) => x.id === p.id);
    return { loop: l || null };
  },
  "POST /api/loops/:id/stop": (_body, p) => {
    const l = mock.mockLoops.find((x) => x.id === p.id);
    if (l) l.status = "stopped";
    return { message: `loop ${p.id} 已停止` };
  },
  /* T7 对齐：/api/runs 支持 loop_id 过滤（任务中心 Inspector 的 run 迷你表用） */
  "GET /api/runs": (_body, _p, query) => {
    const loopId = query?.get("loop_id");
    return loopId ? mock.mockRuns.filter((r) => r.loop_id === loopId) : mock.mockRuns;
  },
  "GET /api/runs/:id": (_body, p) => {
    const run = mock.mockRuns.find((r) => r.run_id === p.id);
    if (!run) return { error: "run not found" };
    return { ...run, cases: mock.mockCases[p.id] || [] };
  },
  "GET /api/runs/:id/joblog": () => mock.mockConsoleLines.join("\n"),
  "GET /api/stats": () => mock.mockStats,
  /* ── 资源：环境 CRUD / 锁（T12，T7 对齐契约）───────────────── */
  "GET /api/envs/:id": (_body, p) => {
    const e = mock.mockEnvs.find((x) => x.id === p.id);
    return e
      ? { id: e.id, name: e.name, redacted: { FIREBOX1_WEBUI_URL: "https://••••••" } }
      : { error: "env not found" };
  },
  "POST /api/envs": (b) => {
    const e = {
      id: "env-" + Date.now(), name: b.name, owner_id: 1, owner_name: "wyj",
      disabled: false, updated_at: mock.now(), missing: [],
      lock: { held: false, stale: false, run_id: null, owner_name: null },
    };
    mock.mockEnvs.unshift(e);
    return e;
  },
  "PATCH /api/envs/:id": (b, p) => {
    const e = mock.mockEnvs.find((x) => x.id === p.id);
    if (!e) return { error: "env not found" };
    if (b.name) e.name = b.name;
    if (b.disabled !== undefined) e.disabled = !!b.disabled;
    if (b.content) e.updated_at = mock.now();
    return e;
  },
  "DELETE /api/envs/:id": (_body, p) => {
    const i = mock.mockEnvs.findIndex((x) => x.id === p.id);
    if (i >= 0) mock.mockEnvs.splice(i, 1);
    return { ok: true };
  },
  "POST /api/lock/force-release": (b) => {
    const e = mock.mockEnvs.find((x) => x.id === b.env_id);
    if (!e) return { error: "env not found" };
    e.lock = { held: false, stale: false, run_id: null, owner_name: null };
    return { cleared: true, message: `已释放 ${e.name} 的锁` };
  },
  /* ── 资源：我的上传（T12，T7 对齐契约）─────────────────────── */
  "GET /api/uploads": () => mock.mockUploads,
  "POST /api/uploads": (b) => {
    const f = b && typeof b.get === "function" ? b.get("file") : null;
    const name = f && f.name ? f.name : "unnamed";
    const u = {
      id: "up-" + Date.now(), name,
      kind: /\.py$/i.test(name) ? "script" : "suite",
      relpath: name, owner_name: "wyj", uploaded_at: mock.now(),
    };
    mock.mockUploads.unshift(u);
    return u;
  },
  "DELETE /api/uploads/:id": (_body, p) => {
    const i = mock.mockUploads.findIndex((x) => x.id === p.id);
    if (i >= 0) mock.mockUploads.splice(i, 1);
    return { ok: true };
  },
  /* ── 管理：建号 / 用户角色 / 重置口令 / 保留策略保存 / 审计分页（T12）── */
  "POST /api/admin/users": (b) => {
    const username = (b.username || "").trim();
    if (!/^[A-Za-z0-9._-]{2,40}$/.test(username)) return { error: "用户名只能是字母/数字/. _ -，长度 2-40" };
    if (mock.mockUsers.some((x) => x.username === username)) return { error: `用户名已存在：${username}` };
    const generated = !b.password;
    const u = {
      id: mock.mockUsers.reduce((m, x) => Math.max(m, x.id), 0) + 1,
      username,
      name: b.name || username,
      role: b.role === "admin" ? "admin" : "user",
      source: "local", created_at: mock.now(), last_login: null,
    };
    mock.mockUsers.push(u);
    const password = generated ? "rc-" + Math.random().toString(36).slice(2, 8) : undefined;
    mock.mockAudit.unshift({
      created_at: mock.now(), actor: "wyj", action: "user.create",
      detail: `${username}（${u.role}）由管理员创建`,
    });
    return generated ? { ...u, password } : u;
  },
  "PATCH /api/admin/users/:id/role": (b, p) => {
    const u = mock.mockUsers.find((x) => x.id === Number(p.id));
    if (!u) return { error: "user not found" };
    u.role = b.role === "admin" ? "admin" : "user";
    mock.mockAudit.unshift({
      created_at: mock.now(), actor: "wyj", action: "user.role",
      detail: `${u.username} → ${u.role}`,
    });
    return u;
  },
  "POST /api/admin/users/:id/reset-password": (_body, p) => {
    const u = mock.mockUsers.find((x) => x.id === Number(p.id));
    if (!u) return { error: "user not found" };
    mock.mockAudit.unshift({
      created_at: mock.now(), actor: "wyj", action: "user.reset",
      detail: `${u.username} 新口令已生成`,
    });
    return { ok: true, password: "rc-" + Math.random().toString(36).slice(2, 8) };
  },
  "POST /api/admin/settings": (b) => {
    mock.mockRetention.retain_count = Math.max(0, Number(b.retain_count) || 0);
    mock.mockRetention.retain_days = Math.max(0, Number(b.retain_days) || 0);
    mock.mockAudit.unshift({
      created_at: mock.now(), actor: "wyj", action: "retain.save",
      detail: `count=${mock.mockRetention.retain_count} days=${mock.mockRetention.retain_days}`,
    });
    return { ok: true, cleaned: 3 };   // cleaned：本次清理掉的 run 数
  },
  "GET /api/admin/audit": (_body, _p, query) => {
    const q = query instanceof URLSearchParams ? query : new URLSearchParams();
    const offset = Math.max(0, Number(q.get("offset")) || 0);
    const limit = Math.min(100, Math.max(1, Number(q.get("limit")) || 20));
    return { items: mock.mockAudit.slice(offset, offset + limit), total: mock.mockAudit.length };
  },
  "GET /api/admin/users": () => mock.mockUsers,
  /* ── 定时任务 / 保存的套件 / 按分支列 case（T16/T17，mock 演示）── */
  "GET /api/cases": (_body, _p, query) => {
    const q = query instanceof URLSearchParams ? query : new URLSearchParams();
    const ref = q.get("ref") || "HEAD";
    return { ref, total: mock.mockCaseGroups.reduce((n, g) => n + g.cases.length, 0), groups: mock.mockCaseGroups };
  },
  "GET /api/suites": () => mock.mockSuites,
  "POST /api/suites": (body) => {
    const s = { id: "mock" + Math.random().toString(16).slice(2, 8), owner_id: 1, owner_name: "mock", product: "firebox", created_at: "2026-01-01 00:00:00", updated_at: "2026-01-01 00:00:00", ...body };
    mock.mockSuites.unshift(s);
    return { suite: s };
  },
  "PUT /api/suites/:id": (body, p) => {
    const s = mock.mockSuites.find((x) => x.id === p.id);
    if (!s) return { error: "suite not found" };
    Object.assign(s, body, { updated_at: "2026-01-01 00:00:00" });
    return { suite: s };
  },
  "DELETE /api/suites/:id": (_body, p) => {
    mock.mockSuites = mock.mockSuites.filter((x) => x.id !== p.id);
    return { ok: true };
  },
  "GET /api/schedules": () => mock.mockSchedules,
  "POST /api/schedules": (body) => {
    const s = { id: "mock" + Math.random().toString(16).slice(2, 8), owner_id: 1, owner_name: "mock", env_name: "mock-env", last_loop_id: null, last_status: null, last_note: null, created_at: "2026-01-01 00:00:00", next_run_at: body.rule_type === "daily" ? "2026-01-02 " + (body.time || "08:00") + ":00" : body.run_at + ":00", ...body };
    mock.mockSchedules.unshift(s);
    return { schedule: s };
  },
  "PATCH /api/schedules/:id": (body, p) => {
    const s = mock.mockSchedules.find((x) => x.id === p.id);
    if (!s) return { error: "schedule not found" };
    Object.assign(s, body);
    return { schedule: s };
  },
  "DELETE /api/schedules/:id": (_body, p) => {
    mock.mockSchedules = mock.mockSchedules.filter((x) => x.id !== p.id);
    return { ok: true };
  },
  "POST /api/schedules/:id/run-now": (_body, p) => {
    const s = mock.mockSchedules.find((x) => x.id === p.id);
    if (s) { s.last_status = "started"; s.last_loop_id = "20260101000000-mock00"; }
    return { loop_id: "20260101000000-mock00" };
  },
  /* ── 在线编辑 / 新建上传文件（资源页编辑器，mock 演示）──────── */
  "GET /api/uploads/:id/content": (_body, p) => {
    const u = mock.mockUploads.find((x) => x.id === p.id);
    if (!u) return { error: "upload not found" };
    return `# ${u.name}\n# （mock 演示内容）\nscripts/firebox/demo/fbox_demo_login.py\n`;
  },
  "PUT /api/uploads/:id/content": () => ({ ok: true }),
  "POST /api/uploads/text": (b) => {
    const name = (b.name || "").trim() || "untitled.txt";
    const u = {
      id: "up-" + Date.now(), name,
      kind: /\.py$/i.test(name) ? "script" : "suite",
      relpath: name, owner_name: "wyj", uploaded_at: mock.now(),
    };
    mock.mockUploads.unshift(u);
    return u;
  },
};

function matchMockRoute(method, path) {
  const q = path.indexOf("?");
  const pathname = q >= 0 ? path.slice(0, q) : path;
  // T7 对齐：query 透传给 handler（/api/loops、/api/runs 等列表过滤依赖它）
  const query = q >= 0 ? new URLSearchParams(path.slice(q + 1)) : new URLSearchParams();
  for (const key of Object.keys(mockRoutes)) {
    const [m, pattern] = key.split(" ");
    if (m !== method) continue;
    const pp = pattern.split("/");
    const aa = pathname.split("/");
    if (pp.length !== aa.length) continue;
    const params = {};
    let ok = true;
    for (let i = 0; i < pp.length; i++) {
      if (pp[i].startsWith(":")) params[pp[i].slice(1)] = decodeURIComponent(aa[i]);
      else if (pp[i] !== aa[i]) { ok = false; break; }
    }
    if (ok) return { handler: mockRoutes[key], params, query };
  }
  return null;
}

/* ── apiFetch ──────────────────────────────────────────────── */
export async function apiFetch(path, opts = {}) {
  if (MOCK) {
    const method = (opts.method || "GET").toUpperCase();
    const hit = matchMockRoute(method, path);
    if (!hit) return new Response(JSON.stringify({ error: `mock 未实现 ${method} ${path}` }), { status: 404 });
    let body = null;
    if (opts.body) {
      try { body = JSON.parse(opts.body); } catch { body = opts.body; }
    }
    const data = await hit.handler(body, hit.params, hit.query);
    return new Response(JSON.stringify(data), {
      status: 200, headers: { "Content-Type": "application/json" },
    });
  }

  const headers = { ...(opts.headers || {}) };
  const res = await fetch(path, { credentials: "include", ...opts, headers });
  if (res.status === 401 && path !== "/api/login" && path !== "/api/me") {
    fireLogout();
    throw new AuthError();
  }
  return res;
}

/* ── SSE 控制台流 ────────────────────────────────────────────
   真实：EventSource /api/streams/console?loop_id=…
   mock：定时器逐行 append mockConsoleLines，结束后 onend            */
export function openConsoleStream(loopId, handlers = {}) {
  const { onmessage, onreset, onend, onerror } = handlers;
  let closed = false;
  let timer = null;
  let es = null;

  const cleanup = () => {
    if (timer) { clearInterval(timer); timer = null; }
    if (es) { es.close(); es = null; }
  };

  if (MOCK) {
    let i = 0;
    onreset?.();
    timer = setInterval(() => {
      if (closed) return;
      if (i < mock.mockConsoleLines.length) {
        onmessage?.({ loop_id: loopId, line: mock.mockConsoleLines[i++] });
      } else {
        cleanup();
        onend?.({ loop_id: loopId });
      }
    }, 600);
  } else {
    es = new EventSource(`/api/streams/console?loop_id=${encodeURIComponent(loopId)}`);
    es.addEventListener("reset", () => onreset?.());
    // 后端事件：snapshot（重连/初次，{offset,text}）→ 展开为逐行 onmessage
    es.addEventListener("snapshot", (e) => {
      onreset?.();
      try {
        const d = JSON.parse(e.data);
        (d.text || "").split("\n").forEach((l) => l && onmessage?.({ loop_id: loopId, line: l }));
      } catch { /* 忽略坏帧 */ }
    });
    // 后端命名事件 append：data 为原始文本块（可能多行）
    es.addEventListener("append", (e) => {
      if (e.data == null || e.data === "") return;
      e.data.split("\n").forEach((l) => l && onmessage?.({ loop_id: loopId, line: l }));
    });
    // 兼容默认 message 事件（mock 与旧协议）
    es.addEventListener("message", (e) => {
      try { onmessage?.(JSON.parse(e.data)); } catch { onmessage?.({ line: e.data }); }
    });
    es.addEventListener("end", (e) => {
      cleanup();
      let status = null;
      try { status = JSON.parse(e.data)?.status ?? null; } catch { /* ignore */ }
      onend?.({ loop_id: loopId, status });
    });
    es.onerror = () => {
      if (closed) return;
      onerror?.();
      // EventSource 自动重连；无需手动处理，除非已 closed
    };
  }

  return {
    close() {
      closed = true;
      cleanup();
    },
  };
}
