/* 格式化工具 */

export function fmtDuration(loop) {
  const jobs = loop?.jobs || [];
  const starts = jobs.map((j) => j.started_at && new Date(j.started_at.replace(" ", "T")).getTime())
    .filter(Number.isFinite);
  if (!starts.length) return "—";
  const ends = jobs.map((j) => j.ended_at && new Date(j.ended_at.replace(" ", "T")).getTime())
    .filter(Number.isFinite);
  const end = ends.length ? Math.max(...ends) : Date.now();
  const sec = Math.max(0, Math.round((end - Math.min(...starts)) / 1000));
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  const p = (n) => String(n).padStart(2, "0");
  return h ? `${h}h${p(m)}m${p(s)}s` : m ? `${m}m${p(s)}s` : `${s}s`;
}

export function fmtSize(bytes) {
  const n = Number(bytes) || 0;
  if (n >= 1024 * 1024) return (n / 1024 / 1024).toFixed(1) + " MB";
  if (n >= 1024) return (n / 1024).toFixed(1) + " KB";
  return n + " B";
}

export function caseBadge(status) {
  const s = String(status || "").toLowerCase();
  if (s === "pass" || s === "passed") return { tag: "success", text: "PASS" };
  if (s === "fail" || s === "failed") return { tag: "error", text: "FAIL" };
  if (s === "broken") return { tag: "warning", text: "BROKEN" };
  if (s === "skipped") return { tag: "default", text: "SKIP" };
  return { tag: "info", text: s === "" ? "—" : s.toUpperCase() };
}
