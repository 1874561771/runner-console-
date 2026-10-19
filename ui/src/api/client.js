/* API client：fetch 封装（401 处理 / 错误统一）+ mock 拦截
 *
 * 真实请求：同源 cookie 会话；JSON 体；错误抛 ApiError{status, message, data}
 * mock：URL 带 ?mock=1 时走 src/api/mock.js（演示模式，无后端）
 */
import { mockRoute, MOCK_ENABLED } from "./mock.js";

export class ApiError extends Error {
  constructor(status, message, data) {
    super(message);
    this.status = status;
    this.data = data;
  }
}

let onUnauthorized = null;
export function setUnauthorizedHandler(fn) { onUnauthorized = fn; }

export async function apiFetch(path, opts = {}) {
  if (MOCK_ENABLED) {
    const hit = mockRoute(opts.method || "GET", path, opts.body);
    if (hit !== undefined) return hit;
  }
  const res = await fetch(path, {
    method: opts.method || "GET",
    headers: opts.body instanceof FormData
      ? undefined
      : opts.body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: opts.body instanceof FormData ? opts.body
      : opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
    credentials: "same-origin",
  });
  if (res.status === 401) {
    if (onUnauthorized) onUnauthorized();
    throw new ApiError(401, "未登录或会话已过期");
  }
  // 纯文本/HTML 响应（run 产物预览）直接返回 Response
  const ctype = res.headers.get("content-type") || "";
  if (!ctype.includes("application/json")) {
    if (!res.ok) throw new ApiError(res.status, `请求失败（${res.status}）`);
    return res;
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const msg = typeof data.detail === "object"
      ? (data.detail?.error || data.detail?.detail || "请求失败")
      : (data.error || data.detail || `请求失败（${res.status}）`);
    throw new ApiError(res.status, msg, data);
  }
  return data;
}

/* 便捷 JSON 读取（apiFetch 可能返回 Response） */
export async function asJson(result) {
  return result instanceof Response ? result.json() : result;
}
