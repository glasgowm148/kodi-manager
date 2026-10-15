/* Small hand-written SVG charts and number formats for the dashboard. No library, no network.
   Pure builders return markup strings (every interpolated label goes through esc());
   mountCharts() renders registered charts at their real width and adds hover and keyboard reading. */
const CHART_REGISTRY = new Map();
const CHART_OBSERVERS = [];
let chartSeq = 0;
/* Forget charts from the previous render (called before a page is drawn again). */
function resetCharts() {
  CHART_REGISTRY.clear();
  while (CHART_OBSERVERS.length) CHART_OBSERVERS.pop().disconnect();
}

function finite(value) { return typeof value === "number" && Number.isFinite(value); }

/* ---- numbers and times ---------------------------------------------------------------- */
function formatMB(mb) {
  if (!finite(mb)) return "—";
  if (Math.abs(mb) >= 1024) return `${(mb / 1024).toFixed(mb >= 10240 ? 0 : 1)} GB`;
  return `${Math.round(mb)} MB`;
}
function formatMs(ms) {
  if (!finite(ms)) return "—";
  return ms >= 1000 ? `${(ms / 1000).toFixed(ms >= 10000 ? 0 : 1)} s` : `${Math.round(ms)} ms`;
}
function formatBytes(bytes) {
  if (!finite(bytes) || bytes < 0) return "—";
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB"];
  let value = bytes / 1024, unit = 0;
  while (value >= 1024 && unit < units.length - 1) { value /= 1024; unit++; }
  return `${value.toFixed(value >= 10 ? 0 : 1)} ${units[unit]}`;
}
function formatCount(n) {
  if (!finite(n)) return "—";
  if (Math.abs(n) >= 10000) return `${Math.round(n / 1000)}K`;
  if (Math.abs(n) >= 1000) return `${(n / 1000).toFixed(1).replace(/\.0$/, "")}K`;
  return String(Math.round(n * 10) / 10);
}
const DAY_NAMES = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
function pad2(n) { return String(n).padStart(2, "0"); }
function formatClock(t) { const d = new Date(t * 1000); return `${pad2(d.getHours())}:${pad2(d.getMinutes())}`; }
function formatDay(t) { const d = new Date(t * 1000); return `${DAY_NAMES[d.getDay()]} ${d.getDate()}`; }
function formatWhen(t) { return `${formatDay(t)}, ${formatClock(t)}`; }
/* "3 hours ago", "in 2 days"; seconds may be negative for the future. */
function formatRelative(seconds) {
  if (!finite(seconds)) return "—";
  const future = seconds < 0, s = Math.abs(seconds);
  const [value, unit] = s < 90 ? [0, ""] : s < 5400 ? [Math.round(s / 60), "minute"] : s < 129600 ? [Math.round(s / 3600), "hour"] : [Math.round(s / 86400), "day"];
  if (!unit) return future ? "in a moment" : "just now";
  const text = `${value} ${unit}${value === 1 ? "" : "s"}`;
  return future ? `in ${text}` : `${text} ago`;
}
/* Backup ids and timestamps look like 20261011-030012. */
function parseStamp(value) {
  const m = /^(\d{4})(\d{2})(\d{2})[-T_]?(\d{2})(\d{2})(\d{2})/.exec(String(value || ""));
  if (!m) return null;
  const date = new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +m[6]);
  return Number.isNaN(date.getTime()) ? null : Math.floor(date.getTime() / 1000);
}
function median(values) {
  const list = values.filter(finite).sort((a, b) => a - b);
  if (!list.length) return null;
  const mid = Math.floor(list.length / 2);
  return list.length % 2 ? list[mid] : (list[mid - 1] + list[mid]) / 2;
}

/* ---- scales ----------------------------------------------------------------------------- */
function scaleLinear(domain, range) {
  const [d0, d1] = domain, [r0, r1] = range;
  const span = d1 - d0 || 1;
  const scale = value => r0 + (value - d0) / span * (r1 - r0);
  scale.invert = pixel => d0 + (pixel - r0) / ((r1 - r0) || 1) * span;
  return scale;
}
/* Clean, round tick values covering [min, max]: 0 / 500 / 1000 / 1500. */
function niceTicks(min, max, count = 4) {
  if (!finite(min) || !finite(max)) return {min:0, max:1, ticks:[0, 1]};
  if (min === max) { const pad = Math.abs(min) || 1; min -= pad; max += pad; if (min < 0 && max - 2 * pad >= 0) min = 0; }
  const raw = (max - min) / Math.max(1, count);
  const power = Math.pow(10, Math.floor(Math.log10(raw)));
  const step = [1, 2, 2.5, 5, 10].map(f => f * power).find(s => s >= raw) || 10 * power;
  const lo = Math.floor(min / step) * step, hi = Math.ceil(max / step) * step;
  const ticks = [];
  for (let v = lo; v <= hi + step / 2; v += step) ticks.push(Math.round(v * 1e6) / 1e6);
  return {min:lo, max:hi, ticks};
}
/* Time ticks: hours for a day or less, local midnights for longer spans. */
function timeTicks(t0, t1, width = 600) {
  const span = t1 - t0;
  if (!(span > 0)) return [];
  const ticks = [];
  if (span <= 36 * 3600) {
    const every = (width < 420 ? 12 : 6) * 3600;
    const start = new Date(t0 * 1000); start.setMinutes(0, 0, 0);
    let t = Math.floor(start.getTime() / 1000);
    while (t <= t1) { if (t >= t0 && new Date(t * 1000).getHours() % (every / 3600) === 0) ticks.push({t, label:formatClock(t)}); t += 3600; }
    return ticks;
  }
  const days = span / 86400, step = width < 420 && days > 4 ? 2 : 1;
  const start = new Date(t0 * 1000); start.setHours(0, 0, 0, 0); start.setDate(start.getDate() + 1);
  let i = 0;
  for (let d = new Date(start); d.getTime() / 1000 <= t1; d.setDate(d.getDate() + 1), i++) if (i % step === 0) ticks.push({t:Math.floor(d.getTime() / 1000), label:formatDay(d.getTime() / 1000)});
  return ticks;
}
/* Drop x labels that would overlap or spill past the plot: each needs its own width plus a gap. */
function thinTicks(ticks, x, minX, maxX) {
  const kept = [];
  let lastRight = -Infinity;
  const width = tick => String(tick.label).length * 7 + 10;
  const inside = ticks.filter(tick => x(tick.t) - width(tick) / 2 >= minX - 20 && x(tick.t) + width(tick) / 2 <= maxX + 20);
  // Keep every n-th label so the spacing stays even, choosing the smallest n that never overlaps.
  for (let step = 1; step <= Math.max(1, inside.length); step++) {
    kept.length = 0; lastRight = -Infinity;
    let ok = true;
    for (let i = inside.length - 1; i >= 0; i -= step) {
      const tick = inside[i], centre = x(tick.t), half = width(tick) / 2;
      if (kept.length && centre + half > lastRight) { ok = false; break; }
      kept.unshift(tick); lastRight = centre - half;
    }
    if (ok) return kept;
  }
  return inside.slice(-1);
}
/* Split a series into drawable runs: a missing value or a gap longer than maxGap breaks the line. */
function splitSegments(t, values, maxGap = Infinity) {
  const segments = [];
  let current = [];
  for (let i = 0; i < t.length; i++) {
    const v = values[i];
    if (!finite(v) || !finite(t[i])) { if (current.length) segments.push(current); current = []; continue; }
    if (current.length && t[i] - current[current.length - 1][0] > maxGap) { segments.push(current); current = []; }
    current.push([t[i], v]);
  }
  if (current.length) segments.push(current);
  return segments;
}
/* Median per time bucket, for dense series over long ranges. Buckets with no value stay null. */
function bucketMedian(t, valuesList, bucket) {
  const keys = [], groups = new Map();
  t.forEach((time, i) => {
    const key = Math.floor(time / bucket) * bucket + bucket / 2;
    if (!groups.has(key)) { groups.set(key, valuesList.map(() => [])); keys.push(key); }
    valuesList.forEach((values, k) => { if (finite(values[i])) groups.get(key)[k].push(values[i]); });
  });
  return {t:keys, values:valuesList.map((_, k) => keys.map(key => median(groups.get(key)[k])))};
}
function seriesExtent(series, extra = []) {
  const all = series.flatMap(s => s.values.filter(finite)).concat(extra.filter(finite));
  return all.length ? [Math.min(...all), Math.max(...all)] : [null, null];
}
function pathFor(points, x, y, step = false) {
  return points.map(([t, v], i) => {
    const px = x(t).toFixed(1), py = y(v).toFixed(1);
    if (!i) return `M${px} ${py}`;
    return step ? `H${px}V${py}` : `L${px} ${py}`;
  }).join("");
}

/* ---- sparkline (a tile's 7-day trend; no text inside) ------------------------------------ */
function sparkline(t, values, {label = "Trend", maxGap = Infinity, min = null, max = null, kind = "line"} = {}) {
  const width = 120, height = 32;
  if (!Array.isArray(t) || !t.length || !values.some(finite)) return "";
  const [lo, hi] = seriesExtent([{values}]);
  const yMin = min ?? lo, yMax = max ?? (hi === yMin ? yMin + 1 : hi);
  const x = scaleLinear([t[0], t[t.length - 1] === t[0] ? t[0] + 1 : t[t.length - 1]], [1, width - 1]);
  const y = scaleLinear([yMin, yMax], [height - 2, 3]);
  let marks;
  if (kind === "bars") {
    const w = Math.max(1.5, Math.min(6, (width - 2) / values.length - 1.5));
    marks = values.map((v, i) => finite(v) && v > 0 ? `<rect class="spark-bar" x="${(x(t[i]) - w / 2).toFixed(1)}" y="${y(v).toFixed(1)}" width="${w.toFixed(1)}" height="${Math.max(1, height - 2 - y(v)).toFixed(1)}" rx="1"/>` : "").join("");
  } else {
    const segments = splitSegments(t, values, maxGap);
    marks = segments.map(points => {
      // A lone sample (one point, or one between gaps) is a dot, like the full chart's. The SVG is stretched
      // (preserveAspectRatio="none"), so it is drawn as a round-capped zero-length stroke, which stays round.
      if (points.length === 1) return `<path class="spark-line spark-dot" d="M${x(points[0][0]).toFixed(1)} ${y(points[0][1]).toFixed(1)}h0" vector-effect="non-scaling-stroke"/>`;
      const line = pathFor(points, x, y);
      const area = `${line}V${height - 1}H${x(points[0][0]).toFixed(1)}Z`;
      return `<path class="spark-area" d="${area}"/><path class="spark-line" d="${line}" vector-effect="non-scaling-stroke"/>`;
    }).join("");
  }
  return `<svg class="spark" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" role="img" aria-label="${esc(label)}" focusable="false">${marks}</svg>`;
}

/* ---- full charts ---------------------------------------------------------------------- */
/* spec: {title, summary, t[], series:[{name, values[], cls}], format(v), yMin?, yMax?, step?, maxGap?,
          kind:"line"|"columns", markers:[{t, series index, label}], height?, empty} */
function chartFigure(spec) {
  const id = `chart-${++chartSeq}`;
  CHART_REGISTRY.set(id, spec);
  const series = spec.series || [];
  const hasData = (spec.t || []).length && series.some(s => s.values.some(finite));
  const legend = series.length >= 2 ? `<ul class="chart-legend" aria-label="Legend">${series.map((s, i) => `<li><span class="key key-${esc(s.cls || `s${i + 1}`)}${spec.kind === "columns" ? " key-box" : ""}" aria-hidden="true"></span>${esc(s.name)}</li>`).join("")}</ul>` : "";
  return `<figure class="chart" data-chart="${id}"><figcaption><span class="chart-title">${esc(spec.title)}</span>${spec.summary ? `<span class="chart-summary">${esc(spec.summary)}</span>` : ""}</figcaption>${legend}${hasData
    ? `<div class="chart-plot" data-chart-plot="${id}" tabindex="0" role="group" aria-label="${esc(`${spec.title}. Use the left and right arrow keys to read values.`)}"><div class="chart-svg" style="height:${spec.height || 200}px"></div><div class="chart-tip" role="status" aria-live="polite" hidden></div></div>${chartTable(spec)}`
    : `<div class="chart-empty">${esc(spec.empty || "No history yet.")}</div>`}</figure>`;
}
function chartTable(spec) {
  const series = spec.series || [];
  const format = spec.format || formatCount;
  const xLabel = spec.xLabel || (t => formatWhen(t));
  const rows = (spec.t || []).map((t, i) => [t, i]).filter(([, i]) => series.some(s => finite(s.values[i]))).slice(-200).reverse();
  return `<details class="chart-table"><summary>Show as table</summary><div class="table-scroll"><table><thead><tr><th scope="col">${esc(spec.xName || "Time")}</th>${series.map(s => `<th scope="col">${esc(s.name)}</th>`).join("")}</tr></thead><tbody>${rows.map(([t, i]) => `<tr><th scope="row">${esc(xLabel(t))}</th>${series.map(s => `<td>${esc(finite(s.values[i]) ? format(s.values[i]) : (s.missing || "—"))}</td>`).join("")}</tr>`).join("")}</tbody></table></div></details>`;
}
function lastValue(values) { for (let i = values.length - 1; i >= 0; i--) if (finite(values[i])) return values[i]; return null; }
/* Margins sized to the labels they hold: tick labels on the left, direct end labels on the right. */
function chartLayout(spec, width) {
  const height = spec.height || 200, series = spec.series || [], t = spec.t || [];
  const columns = spec.kind === "columns";
  const top = 12, bottom = 26, plotH = height - top - bottom;
  const format = spec.format || formatCount;
  const [lo, hi] = seriesExtent(series, [spec.yMin, spec.yMax].filter(v => v !== undefined && v !== null));
  const ticks = niceTicks(spec.yMin ?? Math.min(0, lo ?? 0), spec.yMax ?? (hi ?? 1), plotH < 140 ? 3 : 4);
  const tickText = v => String(spec.tickFormat ? spec.tickFormat(v) : format(v));
  const left = Math.max(30, Math.max(...ticks.ticks.map(v => tickText(v).length)) * 7 + 14);
  const ends = columns || series.length < 2 ? [] : series.map(s => ({s, v:lastValue(s.values)})).filter(e => e.v !== null).map(e => `${e.s.name} ${format(e.v)}`);
  const need = ends.length ? Math.max(...ends.map(text => text.length)) * 6.6 + 18 : 0;
  const labels = ends.length > 0 && ends.length <= 4 && need <= width * 0.32;
  const right = labels ? need : 14;
  const plotW = Math.max(40, width - left - right);
  const halfSlot = columns && t.length ? (spec.slot || 86400) / 2 : 0;
  const t0 = t.length ? t[0] - halfSlot : 0, t1 = t.length ? t[t.length - 1] + halfSlot : 1;
  return {height, top, bottom, plotH, plotW, left, right, labels, ticks, tickText, t0, t1, format,
    x:scaleLinear([t0, t1 === t0 ? t0 + 1 : t1], [left, left + plotW]), y:scaleLinear([ticks.min, ticks.max], [top + plotH, top])};
}
/* Pure SVG for a chart at a given pixel width. */
function chartSvg(spec, width) {
  const series = spec.series || [], t = spec.t || [];
  const columns = spec.kind === "columns";
  const {height, top, plotH, plotW, left, labels, ticks, tickText, t0, t1, format, x, y} = chartLayout(spec, width);
  const grid = ticks.ticks.map(v => `<line class="grid" x1="${left}" x2="${left + plotW}" y1="${y(v).toFixed(1)}" y2="${y(v).toFixed(1)}"/><text class="tick" x="${left - 6}" y="${(y(v) + 4).toFixed(1)}" text-anchor="end">${esc(tickText(v))}</text>`).join("");
  const xTicks = thinTicks(columns && spec.columnLabels ? spec.columnLabels(t, plotW) : timeTicks(t0, t1, width), x, left, left + plotW).map(tick => `<text class="tick" x="${x(tick.t).toFixed(1)}" y="${height - 8}" text-anchor="middle">${esc(tick.label)}</text>`).join("");
  let marks = "";
  if (columns) {
    const slotPx = plotW / Math.max(1, t.length);
    const barW = Math.min(24, Math.max(3, Math.min(slotPx - 2, slotPx * 0.62)));
    const base = y(Math.max(ticks.min, 0));
    t.forEach((time, i) => {
      let acc = 0;
      series.forEach((s, k) => {
        const v = s.values[i];
        if (!finite(v) || v <= 0) return;
        const yTop = y(acc + v), yBottom = y(acc) - (acc > 0 ? 2 : 0);
        const h = Math.max(1, yBottom - yTop), cx = x(time), r = Math.min(4, barW / 2, h);
        const topIsLast = !series.slice(k + 1).some(other => finite(other.values[i]) && other.values[i] > 0);
        const xl = cx - barW / 2, xr = cx + barW / 2;
        const d = topIsLast ? `M${xl.toFixed(1)} ${yBottom.toFixed(1)}V${(yTop + r).toFixed(1)}Q${xl.toFixed(1)} ${yTop.toFixed(1)} ${(xl + r).toFixed(1)} ${yTop.toFixed(1)}H${(xr - r).toFixed(1)}Q${xr.toFixed(1)} ${yTop.toFixed(1)} ${xr.toFixed(1)} ${(yTop + r).toFixed(1)}V${yBottom.toFixed(1)}Z` : `M${xl.toFixed(1)} ${yBottom.toFixed(1)}V${yTop.toFixed(1)}H${xr.toFixed(1)}V${yBottom.toFixed(1)}Z`;
        marks += `<path class="col ${esc(s.cls || `s${k + 1}`)}" d="${d}"/>`;
        acc += v;
      });
    });
    marks = `<line class="baseline" x1="${left}" x2="${left + plotW}" y1="${base.toFixed(1)}" y2="${base.toFixed(1)}"/>` + marks;
  } else {
    const ends = [];
    series.forEach((s, k) => {
      const cls = esc(s.cls || `s${k + 1}`);
      const segments = splitSegments(t, s.values, spec.maxGap ?? Infinity);
      segments.forEach(points => {
        if (points.length === 1) marks += `<circle class="dot ${cls}" cx="${x(points[0][0]).toFixed(1)}" cy="${y(points[0][1]).toFixed(1)}" r="3"/>`;
        else {
          if (s.area) marks += `<path class="area ${cls}" d="${pathFor(points, x, y, spec.step)}V${(top + plotH).toFixed(1)}H${x(points[0][0]).toFixed(1)}Z"/>`;
          marks += `<path class="line ${cls}" d="${pathFor(points, x, y, spec.step)}"/>`;
        }
      });
      const last = segments.length ? segments[segments.length - 1] : null;
      if (last) {
        const [lt, lv] = last[last.length - 1];
        marks += `<circle class="end ${cls}" cx="${x(lt).toFixed(1)}" cy="${y(lv).toFixed(1)}" r="4"/>`;
        ends.push({y:y(lv), text:`${s.name} ${format(lv)}`, x:x(lt)});
      }
    });
    (spec.events || []).forEach(e => { if (finite(e.t) && e.t >= t0 && e.t <= t1) marks += `<g class="event"><line x1="${x(e.t).toFixed(1)}" x2="${x(e.t).toFixed(1)}" y1="${top}" y2="${(top + plotH).toFixed(1)}"/><path d="M${x(e.t).toFixed(1)} ${top}l-5 -6h10z"/></g>`; });
    (spec.markers || []).forEach(m => { if (finite(m.t) && m.t >= t0 && m.t <= t1) marks += `<path class="marker ${esc(m.cls || "s1")}" d="M${x(m.t).toFixed(1)} ${(top + 1).toFixed(1)}l4 4l-4 4l-4 -4z"/>`; });
    // Direct end labels only when they don't collide; otherwise the legend and tooltip carry identity.
    if (labels && ends.length <= 4) {
      ends.sort((a, b) => a.y - b.y);
      const clear = ends.every((e, i) => !i || e.y - ends[i - 1].y >= 13);
      if (clear) marks += ends.map(e => `<text class="end-label" x="${(left + plotW + 8).toFixed(1)}" y="${(e.y + 4).toFixed(1)}">${esc(e.text)}</text>`).join("");
    }
  }
  return `<svg class="chart-canvas" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" role="img" aria-label="${esc(spec.summary || spec.title)}" focusable="false">${grid}${marks}<g class="xaxis">${xTicks}</g><line class="crosshair" x1="0" x2="0" y1="${top}" y2="${top + plotH}" visibility="hidden"/></svg>`;
}
/* Index of the sample nearest to time t (t sorted ascending). */
function nearestIndex(t, target) {
  if (!t.length) return -1;
  let lo = 0, hi = t.length - 1;
  while (hi - lo > 1) { const mid = (lo + hi) >> 1; if (t[mid] < target) lo = mid; else hi = mid; }
  return Math.abs(t[lo] - target) <= Math.abs(t[hi] - target) ? lo : hi;
}
function chartGeometry(spec, width) { return chartLayout(spec, width).x; }
function tooltipLines(spec, index) {
  const format = spec.format || formatCount;
  const time = (spec.xLabel || formatWhen)(spec.t[index]);
  return {time, rows:(spec.series || []).map((s, k) => ({cls:s.cls || `s${k + 1}`, name:s.name, value:finite(s.values[index]) ? format(s.values[index]) : (s.missing || "no sample")}))};
}

function mountCharts(root = typeof document !== "undefined" ? document : null) {
  if (!root || typeof root.querySelectorAll !== "function") return;
  root.querySelectorAll("[data-chart-plot]").forEach(plot => {
    const spec = CHART_REGISTRY.get(plot.dataset.chartPlot);
    if (!spec || plot.dataset.mounted) return;
    plot.dataset.mounted = "1";
    const host = plot.querySelector(".chart-svg"), tip = plot.querySelector(".chart-tip");
    let width = 0, index = -1;
    const draw = () => {
      const next = Math.max(240, Math.round(host.clientWidth || plot.clientWidth || 600));
      if (next === width) return;
      width = next;
      host.innerHTML = chartSvg(spec, width);
      if (index >= 0) show(index);
    };
    const show = i => {
      index = Math.max(0, Math.min(spec.t.length - 1, i));
      const x = chartGeometry(spec, width)(spec.t[index]);
      const line = host.querySelector(".crosshair");
      if (line) { line.setAttribute("x1", x); line.setAttribute("x2", x); line.setAttribute("visibility", "visible"); }
      const data = tooltipLines(spec, index);
      tip.replaceChildren();
      const head = document.createElement("div"); head.className = "tip-time"; head.textContent = data.time; tip.append(head);
      for (const row of data.rows) {
        const line = document.createElement("div"); line.className = "tip-row";
        const key = document.createElement("span"); key.className = `tip-key key-${row.cls}`; key.setAttribute("aria-hidden", "true");
        const value = document.createElement("strong"); value.textContent = row.value;
        const name = document.createElement("span"); name.textContent = row.name;
        line.append(key, value, name); tip.append(line);
      }
      tip.hidden = false;
      const room = host.clientWidth || width;
      tip.style.left = `${Math.min(Math.max(0, x + 12), Math.max(0, room - 190))}px`;
    };
    const hide = () => { index = -1; tip.hidden = true; host.querySelector(".crosshair")?.setAttribute("visibility", "hidden"); };
    plot.addEventListener("pointermove", event => { const rect = host.getBoundingClientRect(); show(nearestIndex(spec.t, chartGeometry(spec, width).invert(event.clientX - rect.left))); });
    plot.addEventListener("pointerleave", hide);
    plot.addEventListener("blur", hide);
    plot.addEventListener("keydown", event => {
      const moves = {ArrowLeft:-1, ArrowRight:1, Home:-Infinity, End:Infinity};
      if (!(event.key in moves)) return;
      event.preventDefault();
      const step = moves[event.key];
      show(!Number.isFinite(step) ? (step < 0 ? 0 : spec.t.length - 1) : (index < 0 ? spec.t.length - 1 : index + step));
    });
    draw();
    if (typeof ResizeObserver === "function") { const observer = new ResizeObserver(() => draw()); observer.observe(host); CHART_OBSERVERS.push(observer); }
  });
}
