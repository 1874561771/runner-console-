/* 零依赖 SVG 迷你图表（移植旧版 chart-lite.js）
 * 返回 SVG 字符串，调用处 v-html 渲染 */

const ACCENT = "#D9480F";
const GRID = "#EDEEE6";
const INK3 = "#8A8F96";

/**
 * lineChartSvg(points)
 * points: [{ date: "2026-10-09", value: 0.87 }]  value 取 0~1（>1 按百分比归一）
 */
export function lineChartSvg(points) {
  if (!points || !points.length) {
    return `<div style="padding:24px 0;text-align:center;color:${INK3};font-size:12.5px">暂无趋势数据</div>`;
  }
  const W = 640, H = 230, L = 44, R = 16, T = 14, B = 30;
  const iw = W - L - R, ih = H - T - B;
  const vals = points.map((p) => (p.value > 1 ? p.value / 100 : p.value));
  const n = points.length;
  const x = (i) => (n === 1 ? L + iw / 2 : L + (i / (n - 1)) * iw);
  const y = (v) => T + (1 - v) * ih;

  let grid = "";
  for (const g of [0, 0.25, 0.5, 0.75, 1]) {
    grid += `<line x1="${L}" y1="${y(g).toFixed(1)}" x2="${W - R}" y2="${y(g).toFixed(1)}" stroke="${GRID}" stroke-width="1"/>`;
  }
  for (const g of [0, 0.5, 1]) {
    grid += `<text x="${L - 8}" y="${(y(g) + 3.5).toFixed(1)}" text-anchor="end" font-size="10" fill="${INK3}">${Math.round(g * 100)}%</text>`;
  }

  const line = vals.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  const area = `${line} L${x(n - 1).toFixed(1)},${y(0).toFixed(1)} L${x(0).toFixed(1)},${y(0).toFixed(1)} Z`;
  const dots = vals.map((v, i) =>
    `<circle cx="${x(i).toFixed(1)}" cy="${y(v).toFixed(1)}" r="3.2" fill="#fff" stroke="${ACCENT}" stroke-width="2"/>`).join("");

  const fd = (d) => String(d).slice(5);
  const label = (i, anchor) =>
    `<text x="${x(i).toFixed(1)}" y="${H - 8}" text-anchor="${anchor}" font-size="10.5" fill="${INK3}">${fd(points[i].date)}</text>`;
  const xLabels = n === 1 ? label(0, "middle") : label(0, "start") + label(n - 1, "end");

  return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="通过率趋势折线图" style="width:100%;height:auto;display:block">
    ${grid}
    <path d="${area}" fill="${ACCENT}" opacity="0.07"/>
    <path d="${line}" fill="none" stroke="${ACCENT}" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/>
    ${dots}
    ${xLabels}
  </svg>`;
}

/* 循环 iteration 状态点颜色 */
export function iterColor(status) {
  if (status === "pass") return "#3f9e63";
  if (status === "fail") return "#d9480f";
  if (status === "broken") return "#b8860b";
  return "#8a8f96";
}
