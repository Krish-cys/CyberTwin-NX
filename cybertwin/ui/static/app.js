/* CyberTwin-NX dashboard. Vanilla JS, no dependencies. All dynamic text goes through esc(). */
"use strict";

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const pct = (x, d = 0) => (x == null || isNaN(x) ? "–" : (x * 100).toFixed(d) + "%");
const num = (x, d = 1) => (x == null || isNaN(x) ? "–" : Number(x).toFixed(d));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function api(path, body) {
  const opt = body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  const r = await fetch(path, opt);
  const data = await r.json().catch(() => ({ error: "bad response" }));
  if (!r.ok) throw new Error(data.error || r.statusText);
  return data;
}

/* ---------------------------------------------------------------- theme */
const root = document.documentElement;
try { const t = localStorage.getItem("ctnx-theme"); if (t) root.dataset.theme = t; } catch (e) { /* storage blocked */ }
$("#themeBtn").addEventListener("click", () => {
  root.dataset.theme = root.dataset.theme === "dark" ? "light" : "dark";
  try { localStorage.setItem("ctnx-theme", root.dataset.theme); } catch (e) { /* ignore */ }
});

/* ---------------------------------------------------------------- tooltip */
const tip = $("#tip");
document.addEventListener("mousemove", (e) => {
  const t = e.target.closest && e.target.closest("[data-tip]");
  if (!t) { tip.hidden = true; return; }
  tip.innerHTML = esc(t.dataset.tip).replace(/\n/g, "<br>");
  tip.hidden = false;
  tip.style.left = Math.min(e.clientX + 14, innerWidth - 280) + "px";
  tip.style.top = e.clientY + 16 + "px";
});

/* ---------------------------------------------------------------- map */
const LAYOUT = {
  srv1: [450, 78], srv2: [650, 78], r1: [250, 195], r2: [450, 195], r3: [650, 195], s1: [250, 315], s2: [650, 315],
  h1: [160, 425], h2: [250, 425], h3: [340, 425], h4: [560, 425], h5: [650, 425], h6: [740, 425],
};
function pos(view) {   // fixed layout for the reference topology, circle fallback for anything else
  const out = {}; const unknown = view.nodes.filter((n) => !LAYOUT[n.id]);
  view.nodes.forEach((n) => { if (LAYOUT[n.id]) out[n.id] = LAYOUT[n.id]; });
  unknown.forEach((n, i) => { const a = (i / unknown.length) * 2 * Math.PI; out[n.id] = [450 + 300 * Math.cos(a), 260 + 190 * Math.sin(a)]; });
  return out;
}
const utilColor = (u) => (u < 0.5 ? "var(--cyan)" : u < 0.85 ? "var(--amber)" : "var(--red)");
const hex = (x, y, r) => [0, 1, 2, 3, 4, 5].map((i) => { const a = Math.PI / 3 * i + Math.PI / 6; return `${(x + r * Math.cos(a)).toFixed(1)},${(y + r * Math.sin(a)).toFixed(1)}`; }).join(" ");

function renderMap(el, view, opts = {}) {
  const P = pos(view), byId = Object.fromEntries(view.nodes.map((n) => [n.id, n]));
  let links = "", flows = "", labels = "";
  for (const l of view.links) {
    const [x1, y1] = P[l.a], [x2, y2] = P[l.b];
    const bothR = byId[l.a].role === "router" && byId[l.b].role === "router";
    const curved = bothR && Math.hypot(x2 - x1, y2 - y1) > 300;
    const d = curved ? `M${x1},${y1} Q${(x1 + x2) / 2},${y1 + 120} ${x2},${y2}` : `M${x1},${y1} L${x2},${y2}`;
    const flat = Math.abs(y2 - y1) < 20, t = flat ? 0.5 : 0.62, [ux, uy, lx, ly] = y1 <= y2 ? [x1, y1, x2, y2] : [x2, y2, x1, y1];
    const mx = curved ? (x1 + x2) / 2 : flat ? (x1 + x2) / 2 : ux + (lx - ux) * t, my = curved ? y1 + 78 : flat ? (y1 + y2) / 2 : uy + (ly - uy) * t;
    const w = 2 + Math.max(0, Math.log10(l.cap / 50)) * 2;
    const tipTxt = `${l.a} ↔ ${l.b}\n${l.cap} Mbps · ${l.lat} ms\nutil ${pct(l.util)}${l.up ? "" : "\nLINK DOWN"}${l.penalty > 1 ? "\nrouting penalty ×" + l.penalty : ""}`;
    if (!l.up) {
      links += `<path class="link" d="${d}" style="stroke:var(--red);stroke-width:${w}px;stroke-dasharray:3 9;opacity:.8" data-tip="${esc(tipTxt)}"/>`;
      labels += `<text x="${mx}" y="${my + 5}" style="fill:var(--red);font:700 16px var(--mono);text-anchor:middle">✕</text>`;
    } else {
      const c = utilColor(l.util);
      links += `<path class="link" d="${d}" style="stroke:${c};stroke-width:${w}px;opacity:${0.28 + Math.min(l.util, 1) * 0.5}" data-tip="${esc(tipTxt)}"/>`;
      if (l.util > 0.01) flows += `<path class="flow" d="${d}" style="stroke:${c};stroke-width:2.4px;animation-duration:${(2.4 - Math.min(l.util, 1.2) * 1.4).toFixed(2)}s"/>`;
      if (bothR || l.util >= 0.5) labels += `<text class="link-lbl" x="${mx}" y="${flat && !curved ? my - 8 : my + 4}">${Math.round(l.util * 100)}%</text>`;
    }
  }
  const zones = {};
  view.nodes.forEach((n) => { if (n.zone) (zones[n.zone] ||= []).push(n); });
  let zl = "";
  for (const [z, ns] of Object.entries(zones)) {
    const xs = ns.map((n) => P[n.id][0]), ys = ns.map((n) => P[n.id][1]);
    const host = ns[0].role === "host";
    zl += `<text class="zone" x="${(Math.min(...xs) + Math.max(...xs)) / 2}" y="${host ? Math.max(...ys) + 62 : Math.min(...ys) - 44}" text-anchor="middle">${esc(z)}</text>`;
  }
  let nodes = "";
  for (const n of view.nodes) {
    const [x, y] = P[n.id];
    const cls = ["node", n.role, n.compromised && !n.isolated ? "compromised" : "", n.isolated ? "isolated" : "", !n.up ? "down" : "",
      n.rate_limit < 1 ? "limited" : "", opts.selected === n.id ? "selected" : ""].join(" ");
    let shape;
    if (n.role === "router") shape = `<polygon class="shape" points="${hex(x, y, 28)}"/>`;
    else if (n.role === "switch") shape = `<rect class="shape" x="${x - 26}" y="${y - 17}" width="52" height="34" rx="7"/>`;
    else if (n.role === "server") shape = `<rect class="shape" x="${x - 28}" y="${y - 20}" width="56" height="40" rx="7"/><line x1="${x - 18}" x2="${x + 18}" y1="${y + 9}" y2="${y + 9}" style="stroke:var(--violet);opacity:.6"/>`;
    else shape = `<circle class="shape" cx="${x}" cy="${y}" r="20"/>`;
    const flag = n.isolated ? "ISOLATED" : n.compromised ? "COMPROMISED" : !n.up ? "DOWN" : n.rate_limit < 1 ? `RATE ${Math.round(n.rate_limit * 100)}%` : "";
    const sub = flag || (n.role === "host" ? "" : n.role);
    const tipTxt = `${n.id} · ${n.role}${n.zone ? " · " + n.zone : ""}\nasset value ${n.value}${flag ? "\n" + flag : ""}${n.isolated && n.compromised ? "\n(was compromised, now contained)" : ""}`;
    nodes += `<g class="${cls}" data-node="${esc(n.id)}" data-tip="${esc(tipTxt)}" tabindex="0" role="button" aria-label="${esc(n.id)} ${esc(n.role)} ${esc(flag)}">${shape}
      <text x="${x}" y="${y + 4}">${esc(n.id)}</text>${sub ? `<text class="sub" x="${x}" y="${y + (n.role === "host" ? 36 : 44)}" style="${flag ? "fill:var(--red);font-weight:700" : ""}">${esc(sub)}</text>` : ""}</g>`;
  }
  el.innerHTML = `<svg viewBox="0 0 900 500" role="img" aria-label="Network topology map">${zl}${links}${flows}${labels}${nodes}</svg>`;
  if (opts.onNode) $$("[data-node]", el).forEach((g) => {
    const go = () => opts.onNode(g.dataset.node);
    g.addEventListener("click", go);
    g.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); } });
  });
}
function legend(el) {
  el.innerHTML = [["var(--cyan)", "util &lt; 50%"], ["var(--amber)", "50–85%"], ["var(--red)", "&gt; 85% / compromised"]]
    .map(([c, t]) => `<span><i style="background:${c}"></i>${t}</span>`).join("") +
    `<span>⬡ router</span><span>▭ switch</span><span>◯ host</span><span>▬ server</span>`;
}

/* ---------------------------------------------------------------- shared widgets */
function kpi(label, value, cls = "", delta = "", dcls = "") {
  return `<div class="kpi ${cls}"><div class="l">${esc(label)}</div><div class="v${String(value).length > 9 ? " long" : ""}">${esc(value)}</div>${delta ? `<div class="d ${dcls}">${esc(delta)}</div>` : ""}</div>`;
}
function lineChart(el, o) {
  const W = 640, H = 230, m = { l: 48, r: 14, t: 14, b: 26 };
  const all = o.series.flatMap((s) => s.vals).concat((o.hlines || []).map((h) => h.y));
  if (!all.length) { el.innerHTML = `<div class="empty">No data yet</div>`; return; }
  let lo = Math.min(...all), hi = Math.max(...all); if (hi - lo < 1e-9) { hi += 1; lo -= 1; }
  const pad = (hi - lo) * 0.08; lo -= pad; hi += pad;
  const n = Math.max(...o.series.map((s) => s.vals.length));
  const X = (i) => m.l + (i / Math.max(1, n - 1)) * (W - m.l - m.r), Y = (v) => m.t + (1 - (v - lo) / (hi - lo)) * (H - m.t - m.b);
  const fmt = o.yFmt || ((v) => v.toFixed(2));
  let g = "";
  for (let i = 0; i <= 4; i++) { const v = lo + ((hi - lo) * i) / 4, y = Y(v); g += `<line class="ax" x1="${m.l}" x2="${W - m.r}" y1="${y}" y2="${y}" opacity=".5"/><text x="${m.l - 6}" y="${y + 3}" text-anchor="end">${esc(fmt(v))}</text>`; }
  (o.vlines || []).forEach((v) => { g += `<line x1="${X(v.x)}" x2="${X(v.x)}" y1="${m.t}" y2="${H - m.b}" style="stroke:${v.color || "var(--red)"};stroke-dasharray:4 4"/><text x="${X(v.x) + (X(v.x) > W * 0.7 ? -4 : 4)}" y="${m.t + 10}" text-anchor="${X(v.x) > W * 0.7 ? "end" : "start"}" style="fill:${v.color || "var(--red)"}">${esc(v.label)}</text>`; });
  (o.hlines || []).forEach((h) => { g += `<line x1="${m.l}" x2="${W - m.r}" y1="${Y(h.y)}" y2="${Y(h.y)}" style="stroke:${h.color || "var(--amber)"};stroke-dasharray:6 4"/><text x="${W - m.r}" y="${Y(h.y) - 4}" text-anchor="end" style="fill:${h.color || "var(--amber)"}">${esc(h.label)}</text>`; });
  o.series.forEach((s) => {
    const d = s.vals.map((v, i) => `${i ? "L" : "M"}${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join(" ");
    g += `<path d="${d}" fill="none" style="stroke:${s.color};stroke-width:${s.width || 1.6}px;opacity:${s.opacity ?? 1}"/>`;
  });
  const leg = o.series.filter((s) => s.name && s.showLegend).map((s, i) => `<text x="${m.l + 8 + i * 110}" y="${H - 6}" style="fill:${s.color}">● ${esc(s.name)}</text>`).join("");
  el.innerHTML = `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(o.label || "chart")}">${g}${leg}</svg>`;
}
function setError(id, msg) { const e = $(id); e.hidden = !msg; e.textContent = msg || ""; }

/* ---------------------------------------------------------------- tabs */
const TABS = ["map", "whatif", "incident", "audit"];
function showTab(name) {
  if (!TABS.includes(name)) name = "map";
  TABS.forEach((t) => { $("#tab-" + t).hidden = t !== name; });
  $$(".tabs button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === name)));
  if (name === "audit") loadAudit();
}
$$(".tabs button").forEach((b) => b.addEventListener("click", () => { location.hash = b.dataset.tab; }));
addEventListener("hashchange", () => showTab(location.hash.slice(1)));

/* ---------------------------------------------------------------- map tab */
let TOPO = null;
async function initMap() {
  TOPO = await api("/api/topology");
  const v = TOPO.view, k = TOPO.kpi;
  legend($("#legend"));
  const draw = (sel) => renderMap($("#map-main"), v, { selected: sel, onNode: (id) => { draw(id); nodeDetail(id); } });
  draw();
  $("#kpi-map").innerHTML =
    kpi("Nodes", v.nodes.length) + kpi("Links", v.links.length) +
    kpi("Peak link util", pct(k.max_util), k.max_util < 0.7 ? "good" : "warn") +
    kpi("Mean latency", num(k.mean_latency_ms, 1) + " ms") + kpi("Service loss", pct(k.service_loss), k.service_loss ? "bad" : "good");
  $("#tbl-demands").innerHTML = `<tr><th>Flow</th><th>Mbps</th><th>Prio</th></tr>` +
    TOPO.demands.map((d) => `<tr><td class="mono">${esc(d.name)}</td><td class="num">${d.mbps}</td><td class="num">${"★".repeat(d.priority)}</td></tr>`).join("");
  const nodeDetail = (id) => {
    const n = v.nodes.find((x) => x.id === id), links = v.links.filter((l) => l.a === id || l.b === id);
    const acc = TOPO.access.filter((a) => a.src === id).map((a) => `${a.dst} (${pct(a.p)} via ${a.via})`);
    $("#node-detail").className = "";
    $("#node-detail").innerHTML = `<dl class="kv"><dt>name</dt><dd>${esc(n.id)}</dd><dt>role</dt><dd>${esc(n.role)}</dd><dt>zone</dt><dd>${esc(n.zone || "–")}</dd>
      <dt>asset value</dt><dd>${n.value}</dd><dt>links</dt><dd>${links.map((l) => esc(l.a === id ? l.b : l.a) + " (" + pct(l.util) + ")").join(", ")}</dd>
      <dt>can attack</dt><dd>${acc.length ? acc.map(esc).join(", ") : "–"}</dd></dl>`;
  };
  // populate selectors used by other tabs
  const hosts = v.nodes.filter((n) => n.role === "host").map((n) => n.id);
  $("#inc-host").innerHTML = hosts.map((h) => `<option ${h === "h2" ? "selected" : ""}>${esc(h)}</option>`).join("");
  buildWiFields();
}

/* ---------------------------------------------------------------- what-if */
const opts = (arr, sel) => arr.map((x) => `<option ${x === sel ? "selected" : ""}>${esc(x)}</option>`).join("");
function buildWiFields() {
  if (!TOPO) return;
  const v = TOPO.view, ids = (r) => v.nodes.filter((n) => r.includes(n.role)).map((n) => n.id);
  const sc = $("#wi-scenario").value, f = $("#wi-fields");
  if (sc === "link_failure") {
    f.innerHTML = `<label>Link <select id="f-link">${v.links.map((l) => `<option value="${esc(l.a)}|${esc(l.b)}" ${l.id === "r2|r3" ? "selected" : ""}>${esc(l.a)} — ${esc(l.b)}</option>`).join("")}</select></label>`;
  } else if (sc === "router_failure") {
    f.innerHTML = `<label>Node <select id="f-node">${opts(ids(["router", "switch"]), "r2")}</select></label>`;
  } else if (sc === "surge") {
    f.innerHTML = `<label>Factor ×<input id="f-factor" type="number" min="0.1" max="20" step="0.5" value="4"></label>
      <label>Only to (optional)<select id="f-dst"><option value="">all destinations</option>${opts(ids(["server", "host"]))}</select></label>`;
  } else {
    f.innerHTML = `<label>Host <select id="f-host">${opts(ids(["host"]), "h2")}</select></label>
      <label>Target <select id="f-target">${opts(ids(["server"]), "srv2")}</select></label>
      <label>Exfil Mbps<input id="f-exfil" type="number" min="0" max="2000" value="120"></label>`;
  }
}
$("#wi-scenario").addEventListener("change", buildWiFields);
let WI = null;
$("#wi-form").addEventListener("submit", async (e) => {
  e.preventDefault(); setError("#wi-error");
  const sc = $("#wi-scenario").value; let args = {};
  if (sc === "link_failure") { const [a, b] = $("#f-link").value.split("|"); args = { a, b }; }
  else if (sc === "router_failure") args = { node: $("#f-node").value };
  else if (sc === "surge") args = { factor: +$("#f-factor").value, dst: $("#f-dst").value };
  else args = { host: $("#f-host").value, target: $("#f-target").value, exfil_mbps: +$("#f-exfil").value };
  const btn = $("#wi-run"); btn.disabled = true; btn.textContent = "Simulating…";
  try { WI = await api("/api/whatif", { scenario: sc, args }); renderWi("after"); }
  catch (err) { setError("#wi-error", err.message); }
  finally { btn.disabled = false; btn.textContent = "Simulate"; }
});
$$("#tab-whatif .seg button").forEach((b) => b.addEventListener("click", () => WI && renderWi(b.dataset.v)));
function renderWi(which) {
  $("#wi-result").hidden = false;
  $$("#tab-whatif .seg button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.v === which)));
  renderMap($("#map-wi"), WI[which].view);
  const b = WI.before.kpi, a = WI.after.kpi;
  const d = (x, y, f, lowGood = true) => { const diff = y - x; if (Math.abs(diff) < 1e-9) return ["no change", ""]; return [(diff > 0 ? "▲ " : "▼ ") + f(Math.abs(diff)) + " vs before", (diff > 0) === lowGood ? "up" : "down"]; };
  const [d1, c1] = d(b.service_loss, a.service_loss, (x) => pct(x, 1)), [d2, c2] = d(b.max_util, a.max_util, (x) => pct(x)), [d3, c3] = d(b.mean_latency_ms, a.mean_latency_ms, (x) => num(x) + " ms");
  let k = kpi("Service loss", pct(a.service_loss, 1), a.service_loss === 0 ? "good" : a.service_loss < 0.1 ? "warn" : "bad", d1, c1) +
    kpi("Peak link util", pct(a.max_util), a.max_util < 0.7 ? "good" : a.max_util < 1 ? "warn" : "bad", d2, c2) +
    kpi("Mean latency", num(a.mean_latency_ms) + " ms", "", d3, c3) +
    kpi("Unreachable flows", a.unreachable.length, a.unreachable.length ? "bad" : "good") +
    kpi("Congested links", a.congested_links.length, a.congested_links.length ? "bad" : "good", a.congested_links.join(", "));
  if (WI.lateral) k += kpi("Lateral risk", num(WI.lateral.risk, 2), WI.lateral.risk > 3 ? "bad" : "warn");
  $("#kpi-wi").innerHTML = k;
  $("#tbl-flows").innerHTML = `<tr><th>Flow</th><th>Latency</th><th>Status</th></tr>` + WI.flows.map((f) => {
    let st = `<span class="ok-txt">OK</span>`;
    if (!f.after.ok) st = `<span class="bad-txt">UNREACHABLE</span>`;
    else if (f.after.loss > 0.01) st = `<span class="warn-txt">LOSS ${pct(f.after.loss)}</span>`;
    else if (f.before.path.join() !== f.after.path.join()) st = `<span style="color:var(--cyan)" data-tip="${esc(f.after.path.join(" → "))}">REROUTED</span>`;
    return `<tr><td class="mono">${esc(f.name)}</td><td class="num">${f.before.lat == null ? "–" : num(f.before.lat)} → ${f.after.lat == null ? "–" : num(f.after.lat)} ms</td><td>${st}</td></tr>`;
  }).join("");
  const lp = $("#lateral-panel"); lp.hidden = !WI.lateral;
  if (WI.lateral) $("#lateral").innerHTML = `<div class="bars">${WI.lateral.exposed.map((x) => `<div class="bar-row"><span>${esc(x.node)} <span class="muted">(v${x.value})</span></span><div class="bar risk"><i style="width:${x.p * 100}%"></i></div><span>${pct(x.p)}</span></div>`).join("")}</div>
    <p class="muted small">Probability an attacker on ${esc(WI.args.host)} reaches each asset along the most likely path. Probabilities are modelling assumptions.</p>`;
}

/* ---------------------------------------------------------------- incident */
let skip = false;
$("#inc-skip").addEventListener("click", () => { skip = true; });
$("#inc-form").addEventListener("submit", async (e) => {
  e.preventDefault(); setError("#inc-error"); skip = false;
  const btn = $("#inc-run"); btn.disabled = true; btn.textContent = "Running twin…";
  try {
    const run = await api("/api/incident", { attacker: $("#inc-host").value, seed: +$("#inc-seed").value || 0 });
    await playIncident(run);
  } catch (err) { setError("#inc-error", err.message); }
  finally { btn.disabled = false; btn.innerHTML = "&#9889; Launch attack"; $("#inc-skip").hidden = true; }
});
const PHASE = { baseline: ["BASELINE", "ok"], attack: ["UNDER ATTACK", "bad"], after: ["RESPONSE APPLIED (dry-run)", "cy"] };
function setPhase(run, key) {
  const [t, c] = PHASE[key]; const p = $("#inc-phase"); p.textContent = t; p.className = "pill " + c;
  renderMap($("#map-inc"), run.views[key] || run.views.attack);
}
function step(cls, ico, title, sub, body) {
  const li = document.createElement("li"); li.className = "step " + cls;
  li.innerHTML = `<span class="ico">${ico}</span><h3>${esc(title)}<small>${esc(sub || "")}</small></h3>${body || ""}`;
  $("#timeline").appendChild(li); li.scrollIntoView({ behavior: skip ? "auto" : "smooth", block: "nearest" });
}
function anomalyChart(run, upto) {
  const S = run.series.slice(0, upto), hosts = run.events[0].hosts, att = run.meta.attacker, th = run.meta.threshold;
  const ai = S.findIndex((s) => s.phase === "attack");
  const series = hosts.map((h) => ({ name: h, vals: S.map((s) => s.scores[h]), color: h === att ? "var(--red)" : "var(--muted)", width: h === att ? 2.8 : 1.3, opacity: h === att ? 1 : 0.55, showLegend: h === att }));
  lineChart($("#chart-anom"), { series, hlines: [{ y: th, label: "threshold" }], vlines: ai >= 0 ? [{ x: ai, label: "attack starts" }] : [], label: "anomaly scores", yFmt: (v) => v.toFixed(2) });
}
async function playIncident(run) {
  $("#inc-stage").hidden = false; $("#timeline").innerHTML = ""; $("#kpi-inc").innerHTML = ""; $("#inc-skip").hidden = false;
  $("#chart-anom").innerHTML = `<div class="empty">Collecting baseline…</div>`;
  setPhase(run, "baseline");
  const quiet = run.series.filter((s) => s.phase === "quiet").length;
  const wait = async (ms) => { if (!skip) await sleep(ms); };
  for (const ev of run.events) {
    if (ev.type === "warmup") {
      step("good", "1", "Learning the baseline", `${ev.ticks} clean ticks`,
        `<p class="muted">Isolation Forest trained on normal host behaviour only (no attack labels). Twin calibrated against telemetry:</p>
         <p class="mono">observed latency ≈ <b>${num(ev.calibration.a, 3)}</b> × predicted + <b>${num(ev.calibration.b, 3)}</b> ms</p>`);
    } else if (ev.type === "monitor") {
      anomalyChart(run, quiet);
      step(ev.false_alarms ? "warn" : "good", "2", "Quiet period", `${ev.ticks} ticks`,
        `<p>False alarms: <b class="${ev.false_alarms ? "warn-txt" : "ok-txt"}">${ev.false_alarms}</b></p>`);
    } else if (ev.type === "attack") {
      setPhase(run, "attack");
      step("bad", "3", `Attack: ${ev.host} compromised`, "t+0",
        `<p>Attacker begins exfiltrating <b>${ev.exfil_mbps} Mbps</b> from <b>${esc(ev.host)}</b> to <b>${esc(ev.target)}</b>.</p>`);
    } else if (ev.type === "detect") {
      anomalyChart(run, run.series.length);
      if (!ev.host) step("bad", "4", "Not detected", "", `<p class="bad-txt">The detector never flagged the attacker within 10 ticks.</p>`);
      else step("warn", "4", `Detector flagged ${ev.host}`, `after ${ev.delay} tick(s)`,
        `<p>Anomaly score <b class="mono">${num(ev.score, 3)}</b> fell below threshold <b class="mono">${num(run.meta.threshold, 3)}</b>. Two consecutive windows are required before acting (debounce).</p>`);
    } else if (ev.type === "candidates") {
      const rows = ev.rows.map((r) => {
        const c = r.components;
        return `<tr class="${r.chosen ? "chosen" : ""}"><td><b class="mono">${esc(r.label)}</b>${r.chosen ? ' <span class="pill cy">★ CHOSEN</span>' : ""}
          ${r.reasons.length && r.verdict !== "APPROVED" ? `<div class="why">${r.reasons.map(esc).join("<br>")}</div>` : ""}</td>
          <td class="num">${pct(c.service_loss)}</td><td class="num">${pct(c.exfil)}</td><td class="num">${num(c.risk, 2)}</td><td class="num">${num(r.total, 3)}</td>
          <td><span class="badge ${esc(r.verdict)}">${esc(r.verdict)}</span></td></tr>`;
      }).join("");
      step("", "5", "Candidate responses simulated in the twin", `twin fidelity (latency MAPE) ${pct(ev.fidelity_mape)}`,
        `<div class="panel" style="padding:8px 12px"><div class="scroll"><table class="tbl"><tr><th>Action</th><th>Collateral</th><th>Exfil left</th><th>Risk</th><th>Score ↓</th><th>Safety gate</th></tr>${rows}</table></div></div>
         <p class="muted small">Score = collateral damage + leaked exfil + residual lateral risk + action cost (lower is better). The gate can approve, escalate to a human, or block.</p>`);
    } else if (ev.type === "act") {
      setPhase(run, "after");
      const cmds = ev.commands.map((c) => `<span class="c">$</span> ${esc(c)}`).join("\n");
      const rb = ev.rollback.map((c) => `<span class="r">↺</span> ${esc(c)}`).join("\n");
      step("good", "6", `Act: ${ev.action}`, "DRY-RUN — not executed",
        `<p>Gate verdict: <span class="badge ${esc(ev.decision)}">${esc(ev.decision)}</span> <span class="muted">${ev.reasons.map(esc).join("; ")}</span></p>
         <div class="term">${cmds}\n\n<span class="c"># rollback plan</span>\n${rb}</div>`);
    } else if (ev.type === "verify") {
      const row = (lbl, p, a) => `<div class="bar-row"><span>${lbl} predicted</span><div class="bar"><i style="width:${Math.min(100, p * 100)}%"></i></div><span>${pct(p, 1)}</span></div>
        <div class="bar-row"><span>${lbl} actual</span><div class="bar actual"><i style="width:${Math.min(100, a * 100)}%"></i></div><span>${pct(a, 1)}</span></div>`;
      step("good", "7", "Verify: prediction vs reality", "",
        `<div class="bars">${row("service loss", ev.predicted.service_loss, ev.actual.service_loss)}${row("exfil left", ev.predicted.exfil, ev.actual.exfil)}</div>
         <p class="muted">Latency error: raw simulator <b>${pct(ev.latency_mape_raw, 1)}</b> → calibrated twin <b>${pct(ev.latency_mape_calibrated, 1)}</b></p>`);
    }
    await wait(950);
  }
  const s = run.summary;
  if (s.chosen && s.chosen !== "no_op") $("#kpi-inc").innerHTML =
    kpi("Detected", s.detected, "bad") + kpi("Detection delay", s.detection_delay_ticks + " ticks", "good") + kpi("False alarms", s.false_alarms, s.false_alarms ? "warn" : "good") +
    kpi("Response", s.chosen, "good") + kpi("Latency MAPE", pct(s.latency_mape_calibrated, 1), "", "calibrated");
}

/* ---------------------------------------------------------------- audit */
async function loadAudit() {
  let h; try { h = await api("/api/history"); } catch (e) { $("#audit-list").innerHTML = `<div class="error">${esc(e.message)}</div>`; return; }
  const mon = h.fidelity.filter((r) => r.phase === "monitor");
  if (mon.length) lineChart($("#chart-fid"), { series: [
    { name: "raw simulator", vals: mon.map((r) => r.raw.latency_mape), color: "var(--amber)", showLegend: true },
    { name: "calibrated twin", vals: mon.map((r) => r.calibrated.latency_mape), color: "var(--cyan)", showLegend: true, width: 2.4 }],
    yFmt: (v) => pct(v), label: "latency error over time" });
  else $("#chart-fid").innerHTML = `<div class="empty">No fidelity data yet. Run an incident first.</div>`;
  const ver = h.fidelity.filter((r) => r.phase === "verify");
  $("#tbl-verify").innerHTML = ver.length ? `<tr><th>Action</th><th>Svc loss p→a</th><th>Exfil p→a</th><th>MAPE</th></tr>` + ver.slice().reverse().map((r) =>
    `<tr><td class="mono">${esc(r.action)}</td><td class="num">${pct(r.predicted.service_loss, 1)} → ${pct(r.actual.service_loss, 1)}</td>
     <td class="num">${pct(r.predicted.exfil, 1)} → ${pct(r.actual.exfil, 1)}</td><td class="num">${pct(r.fidelity.latency_mape, 1)}</td></tr>`).join("")
    : `<tr><td class="muted">No verified actions yet.</td></tr>`;
  $("#audit-list").innerHTML = h.audit.length ? h.audit.slice().reverse().map((a) => {
    const status = a.status || "";
    const cls = status.startsWith("failed") ? "BLOCKED" : status.includes("rollback") ? "ESCALATE" : "APPROVED";
    const cmds = (a.apply || a.rollback || []).map((c) => esc(c.join(" "))).join("\n");
    return `<details class="audit-item"><summary><span class="badge ${cls}">${esc(status.toUpperCase().slice(0, 28))}</span><b>${esc(a.action)}</b>
      <span class="muted">${esc(new Date(a.ts * 1000).toLocaleString())}</span>${a.dry_run ? '<span class="pill cy">DRY-RUN</span>' : '<span class="pill bad">LIVE</span>'}</summary>
      <p class="muted small">${esc(a.reason || "")}</p><div class="term">${cmds || "(no commands)"}</div></details>`;
  }).join("") : `<div class="empty">No actions recorded yet.</div>`;
}

/* ---------------------------------------------------------------- boot */
showTab(location.hash.slice(1));
initMap().catch((e) => { document.body.insertAdjacentHTML("afterbegin", `<div class="error" style="margin:16px">Failed to load topology: ${esc(e.message)}</div>`); });
