/* ?mock=1 演示模式：无后端时的可插拔拦截器。
 * P0 先放最小集（login/me/config），后续每迁移一页补对应 mock 数据。
 * 未命中的方法返回 undefined → client 落回真实 fetch。
 */
export const MOCK_ENABLED =
  typeof location !== "undefined" && location.search.includes("mock=1");

const me = { user: { id: 1, username: "wyj", name: "wyj", role: "admin" } };

const config = {
  workdir: "D:\\UIAutomation",
  products: ["firebox"],
  branches: [{ name: "main", current: true }, { name: "feat/demo", current: false }],
  suites: [{ name: "regression-test", cases: 3 }],
  tests: ["scripts/firebox/smoke/firebox_smoke_login.py"],
};

const envs = [
  { id: "envmock01", name: "lab-fbox-12", owner_name: "wyj", disabled: false,
    lock: { held: false }, updated_at: "2026-10-19 09:00:00" },
];

const loops = [];

const table = {
  "POST /api/login": (body) => {
    if (body?.mode === "gitlab" ? !body?.token : !body?.username || !body?.password) {
      throw { status: 400, data: { error: "请输入凭据" } };
    }
    return { user: me.user };
  },
  "POST /api/logout": () => ({}),
  "GET /api/me": () => me,
  "GET /api/config": () => config,
  "GET /api/envs": () => envs,
  "GET /api/uploads": () => [],
  "GET /api/loops": () => loops,
  "GET /api/suites": () => [],
  "GET /api/schedules": () => [],
};

export function mockRoute(method, path, body) {
  const base = path.split("?")[0];
  const key = `${method} ${base}`;
  const fn = table[key];
  if (!fn) return undefined;
  try {
    const parsed = typeof body === "string" ? JSON.parse(body) : body;
    const result = fn(parsed);
    return Promise.resolve(result);
  } catch (err) {
    const status = err?.status || 400;
    return Promise.reject(
      Object.assign(new Error(err?.data?.error || "请求失败"), { status, data: err?.data }),
    );
  }
}
