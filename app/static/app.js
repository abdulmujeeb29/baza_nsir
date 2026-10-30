"use strict";

const EXAMPLES = [
  { q: "Which district has the highest poverty rate?" },
  { q: "Compare poverty and electricity access across Western Province districts." },
  { q: "Which districts have poverty above 40% and the lowest internet access at home?" },
  { q: "How does health insurance coverage in Nyanza compare to the national average?" },
  { q: "What is the unemployment rate in Rwanda?" },
  { q: "Why is poverty high in Nyamagabe and where is it furthest behind?", mode: "investigate" },
  { q: "What is the HIV prevalence in Musanze?" },
];
const PLACEHOLDER = {
  en: "Ask anything about Rwanda's districts, people, jobs or services...",
  rw: "Urugero: Ni akahe karere gafite ubukene bwinshi?",
};
const TOOL_LABEL = {
  plan: "PLAN", search_catalog: "SEARCH", describe_table: "READ TABLE", run_sql: "QUERY", make_chart: "CHART",
  search_nisr_catalog: "NISR CATALOGUE", verify: "VERIFY", translate: "TRANSLATE",
};

const $ = (id) => document.getElementById(id);
const state = { lang: "en", mode: "ask", ask: null, brief: null, catalog: null };

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function storage(key, value) {
  try {
    if (value === undefined) return localStorage.getItem(key);
    localStorage.setItem(key, value);
  } catch (_) { /* storage can be unavailable */ }
  return null;
}

/* ---------- Streaming ---------- */

async function streamPost(url, body, onEvent) {
  const response = await fetch(url, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
  if (!response.ok || !response.body) {
    let message = "The server could not answer. Please try again.";
    try { message = (await response.json()).error || message; } catch (_) { /* keep default */ }
    if (response.status === 422) message = "Please write a question between 2 and 500 characters.";
    onEvent({ type: "error", error: message });
    return;
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let cut;
    while ((cut = buffer.indexOf("\n\n")) >= 0) {
      const chunk = buffer.slice(0, cut);
      buffer = buffer.slice(cut + 2);
      const line = chunk.split("\n").find((l) => l.startsWith("data:"));
      if (line) onEvent(JSON.parse(line.slice(5)));
    }
  }
}

/* ---------- Agent trace ---------- */

function makeTrace(listEl, planEl, clockEl) {
  const started = performance.now();
  listEl.innerHTML = "";
  planEl.innerHTML = "";
  planEl.hidden = true;
  const tick = setInterval(() => { clockEl.textContent = ((performance.now() - started) / 1000).toFixed(1) + "s"; }, 100);
  let last = null;
  return {
    add(event) {
      if (event.type === "plan") {
        planEl.innerHTML = event.steps.map((s) => `<li>${esc(s)}</li>`).join("");
        planEl.hidden = false;
        return;
      }
      if (last) last.classList.remove("live");
      const li = document.createElement("li");
      li.className = "live";
      const t = ((performance.now() - started) / 1000).toFixed(1);
      li.innerHTML = `<span class="t">${t}s · ${esc(TOOL_LABEL[event.tool] || String(event.tool).toUpperCase())}</span>${esc(event.detail)}`;
      listEl.appendChild(li);
      last = li;
      li.scrollIntoView({ block: "nearest" });
    },
    finish(ok) {
      clearInterval(tick);
      if (last) { last.classList.remove("live"); if (ok) last.classList.add("done-ok"); }
    },
  };
}

/* ---------- Rich answer text with number frames ---------- */

function richText(text, tags) {
  let html = "";
  let cursor = 0;
  (tags || []).forEach((tag, i) => {
    const at = text.indexOf(tag.text, cursor);
    if (at < 0) return;
    html += esc(text.slice(cursor, at));
    const cls = tag.match === "unmatched" ? "num bad" : tag.match === "derived" ? "num derived" : "num";
    const label = tag.match === "unmatched" ? "NOT IN DATA" : tag.match === "derived" ? "DERIVED ✓" : tag.match === "context" ? "COUNT ✓" : `${tag.ref || "NISR"} ✓`;
    html += `<span class="${cls}" style="--i:${i}" data-ref="${esc(label)}">${esc(tag.text)}</span>`;
    cursor = at + tag.text.length;
  });
  html += esc(text.slice(cursor));
  const out = [];
  let list = [];
  const flush = () => { if (list.length) { out.push(`<ul>${list.join("")}</ul>`); list = []; } };
  for (const raw of html.split("\n")) {
    const line = raw.trim();
    if (!line) continue;
    if (/^[-•*]\s+/.test(line)) { list.push(`<li>${line.replace(/^[-•*]\s+/, "")}</li>`); continue; }
    flush();
    if (/^(Where to act|Aho gukora|Aho guhera)/i.test(line)) out.push(`<div class="act">${line}</div>`);
    else out.push(`<p>${line}</p>`);
  }
  flush();
  return out.join("");
}

function scan(el) {
  el.classList.remove("scanned", "scanning");
  void el.offsetWidth;
  el.classList.add("scanning");
  setTimeout(() => { el.classList.remove("scanning"); el.classList.add("scanned"); }, 450);
}

function badgeFor(v) {
  if (!v) return { cls: "none", text: "NOT CHECKED" };
  if (v.status === "verified" && v.checked > 0) return { cls: "ok", text: `✓ VERIFIED AGAINST NISR DATA · ${v.checked} NUMBER${v.checked === 1 ? "" : "S"}` };
  if (v.status === "verified") return { cls: "none", text: "NO NUMBERS TO CHECK" };
  return { cls: "warn", text: "⚠ NOT FOUND IN DATA: " + v.unmatched.join(", ") };
}

/* ---------- Documents (answer or brief) and language switching ---------- */

function makeDoc(result, els) {
  const doc = { result, els, texts: { en: result.answer_text_en || result.answer_text }, shown: result.language || "en" };
  doc.texts[doc.shown] = result.answer_text;
  return doc;
}

function paintDoc(doc, status) {
  const r = doc.result;
  doc.els.text.innerHTML = richText(doc.texts[doc.shown], r.number_tags);
  doc.els.text.lang = doc.shown === "rw" ? "rw" : "en";
  scan(doc.els.text);
  const b = badgeFor(r.verification);
  doc.els.badge.className = "badge mono " + b.cls;
  doc.els.badge.textContent = b.text;
  const parts = [`${r.latency_s}S`, `${r.citations.length} TABLE${r.citations.length === 1 ? "" : "S"}`];
  if (r.verification && r.verification.self_corrected && r.verification.status === "verified") parts.push("SELF-CORRECTED ONCE");
  if (doc.shown === "rw") parts.push("KINYARWANDA · SAME NUMBERS");
  doc.els.meta.textContent = status || parts.join(" · ");
}

async function switchLanguage(doc, target) {
  if (!doc || doc.shown === target) return;
  if (doc.texts[target]) { doc.shown = target; paintDoc(doc); return; }
  paintDoc(doc, target === "rw" ? "GUHINDURA MU KINYARWANDA..." : "TRANSLATING...");
  try {
    const response = await fetch("/api/translate", { method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ text: doc.texts.en, target }) });
    const body = await response.json().catch(() => null);
    if (!response.ok || !body || body.error) throw new Error((body && body.error) || "Could not translate the answer.");
    if (body.language !== target) throw new Error(body.note || "The translation changed a number, so the English answer is kept.");
    doc.texts[target] = body.answer_text;
    doc.shown = target;
    paintDoc(doc);
  } catch (error) {
    paintDoc(doc);
    showError(doc.els.error, error.message || "Network error while translating.");
  }
}

function sourcesHtml(citations) {
  if (!citations || !citations.length) return "<li>No NISR table was needed for this answer.</li>";
  return citations.map((c) => `<li><strong>${esc(c.survey)} ${esc(c.year)}</strong>, ${esc(c.nisr_table_ref)}: ${esc(c.title.replace(/^Table [^:]+:\s*/, ""))}.
    <a href="${esc(c.source_file_url)}" target="_blank" rel="noopener">Excel</a> · <a href="${esc(c.report_page_url)}" target="_blank" rel="noopener">Report</a></li>`).join("");
}

function sqlHtml(sql) {
  return (sql || []).map((q, i) => `<p class="label mono">Q${i + 1}</p><pre><code>${esc(q)}</code></pre>`).join("")
    || "<p class=\"empty\">No query was run.</p>";
}

function showError(el, message) { el.textContent = message; el.hidden = false; }

/* ---------- Tables and charts ---------- */

function fmt(v) {
  if (typeof v === "number") return Number.isInteger(v) ? v.toLocaleString("en-US") : v.toLocaleString("en-US", { maximumFractionDigits: 2 });
  return v === null || v === undefined ? "" : String(v);
}

function tableHtml(table) {
  if (!table || !table.columns || !table.rows.length) return "<p class=\"empty\" style=\"padding:10px\">No rows.</p>";
  const head = table.columns.map((c) => `<th scope="col">${esc(c.replace(/_/g, " "))}</th>`).join("");
  const body = table.rows.map((r) => "<tr>" + r.map((v) => `<td class="${typeof v === "number" ? "num-cell" : ""}">${esc(fmt(v))}</td>`).join("") + "</tr>").join("");
  return `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
}

function toCSV(table) {
  const cell = (v) => { const s = v === null || v === undefined ? "" : String(v); return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
  return [table.columns.map(cell).join(","), ...table.rows.map((r) => r.map(cell).join(","))].join("\n");
}

const VEGA_CONFIG = {
  background: null,
  view: { stroke: null },
  font: "Manrope",
  title: { color: "#f2ede4", fontSize: 13, font: "Manrope", fontWeight: 600, anchor: "start" },
  axis: { labelColor: "rgba(242,237,228,0.62)", titleColor: "rgba(242,237,228,0.4)", gridColor: "rgba(242,237,228,0.06)", domainColor: "rgba(242,237,228,0.16)",
    tickColor: "rgba(242,237,228,0.16)", labelFont: "Manrope", titleFont: "Manrope", labelFontSize: 11, titleFontSize: 10 },
  legend: { labelColor: "rgba(242,237,228,0.62)", titleColor: "rgba(242,237,228,0.62)", labelFont: "Manrope", titleFont: "Manrope" },
};

const VEGA_SCRIPTS = [
  "https://cdn.jsdelivr.net/npm/vega@5.30.0/build/vega.min.js",
  "https://cdn.jsdelivr.net/npm/vega-lite@5.21.0/build/vega-lite.min.js",
  "https://cdn.jsdelivr.net/npm/vega-embed@6.26.0/build/vega-embed.min.js",
];
let vegaReady = null;

// Chart libraries load in the background, in order, so a slow CDN never blocks the app itself.
function loadVega() {
  if (!vegaReady) {
    vegaReady = VEGA_SCRIPTS.reduce((chain, src) => chain.then(() => new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.src = src;
      s.onload = resolve;
      s.onerror = reject;
      document.head.appendChild(s);
    })), Promise.resolve());
  }
  return vegaReady;
}

function embed(el, spec) {
  el.innerHTML = "";
  el.dataset.pending = "1";
  const token = (el._token = (el._token || 0) + 1);
  loadVega().then(() => {
    if (el._token !== token) return;
    delete el.dataset.pending;
    return vegaEmbed(el, { ...spec, config: VEGA_CONFIG }, { actions: { export: true, source: false, compiled: false, editor: false }, renderer: "svg" });
  }).catch(() => { el.innerHTML = ""; });
}

function chartSpec(chart) {
  const spec = JSON.parse(JSON.stringify(chart.spec));
  const n = spec.data.values.length;
  if (chart.type === "barh") spec.height = { step: n > 15 ? 16 : 24 };
  spec.mark = { ...spec.mark, cornerRadiusEnd: 2, color: "#5b86ff" };
  return spec;
}

function mapSpec(map) {
  const shapes = { url: "/rwanda_districts.geojson", format: { type: "json", property: "features" } };
  return {
    $schema: "https://vega.github.io/schema/vega-lite/v5.json", title: map.title.toUpperCase(), width: "container", height: 380,
    projection: { type: "mercator" },
    layer: [
      { data: shapes, mark: { type: "geoshape", fill: "#1c1c1c", stroke: "#0a0a0a", strokeWidth: 1 } },
      {
        data: shapes,
        transform: [
          { lookup: "properties.district", from: { data: { values: map.values }, key: map.district_field, fields: [map.value_field] } },
          { filter: `datum['${map.value_field}'] != null` },
        ],
        mark: { type: "geoshape", stroke: "#0a0a0a", strokeWidth: 1 },
        encoding: {
          color: { field: map.value_field, type: "quantitative", title: map.title, scale: { range: ["#13234f", "#3d6bff", "#cfe0ff"] } },
          tooltip: [{ field: "properties.district", title: "District" }, { field: map.value_field, title: map.title, format: ",.2f" }],
        },
      },
    ],
  };
}

/* ---------- Hero motion ---------- */

let motion = null;
function setBusy(busy, label) {
  if (motion) motion.setEnergy(busy ? 1 : 0);
  const stage = document.querySelector(".motion-stage");
  if (stage) stage.classList.toggle("busy", busy);
  const status = $("stage-status");
  if (status) status.textContent = label;
}

/* ---------- Ask view ---------- */

function showViz(kind) {
  const r = state.ask && state.ask.result;
  document.querySelectorAll("#viz-tabs button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.viz === kind)));
  $("map-note").hidden = kind !== "map";
  if (!r) return;
  if (kind === "map" && r.map) embed($("chart"), mapSpec(r.map));
  else if (r.chart && r.chart.spec) embed($("chart"), chartSpec(r.chart));
  else $("chart").innerHTML = "";
}

function renderAnswer(r) {
  state.ask = makeDoc(r, { text: $("answer-text"), badge: $("badge"), meta: $("meta"), error: $("error") });
  paintDoc(state.ask);
  $("caveats").innerHTML = (r.caveats || []).map((c) => `<li>${esc(c)}</li>`).join("");
  const pointers = r.catalog_pointers || [];
  $("pointers").hidden = !pointers.length;
  $("pointer-list").innerHTML = pointers.map((p) => `<li><a href="${esc(p.url)}" target="_blank" rel="noopener">${esc(p.title)}</a> <span class="meta mono">${esc(p.years)}</span></li>`).join("");
  $("data-table").innerHTML = tableHtml(r.table_rows);
  $("data-table").hidden = $("table-tools").hidden = !r.table_rows;
  $("sources").innerHTML = sourcesHtml(r.citations);
  $("sql").innerHTML = sqlHtml(r.sql);
  const hasMap = Boolean(r.map && r.map.values.length >= 2);
  $("viz-tabs").hidden = !(hasMap && r.chart);
  $("answer").hidden = false;
  showViz(hasMap && (!r.chart || r.map.values.length >= 15) ? "map" : "chart");
}

async function ask(question) {
  question = question.trim();
  if (question.length < 2) return;
  $("question").value = question;
  $("error").hidden = true;
  $("answer").hidden = true;
  $("workspace").hidden = false;
  $("ask-button").disabled = true;
  setBusy(true, state.mode === "investigate" ? "Investigating" : "Thinking");
  const trace = makeTrace($("trace"), $("plan"), $("trace-clock"));
  let ok = false;
  try {
    await streamPost("/api/ask/stream", { question, lang: state.lang, mode: state.mode }, (event) => {
      if (event.type === "step" || event.type === "plan") trace.add(event);
      else if (event.type === "result") { ok = true; renderAnswer(event.result); }
      else if (event.type === "error") showError($("error"), event.error);
    });
    const url = new URL(window.location);
    url.searchParams.set("q", question);
    if (state.mode === "investigate") url.searchParams.set("mode", "investigate"); else url.searchParams.delete("mode");
    history.replaceState(null, "", url.pathname + url.search + "#ask");
  } catch (_) {
    showError($("error"), "Network error. Check your connection and try again.");
  } finally {
    trace.finish(ok);
    $("ask-button").disabled = false;
    setBusy(false, ok ? "Verified · ready" : "Ready");
  }
}

/* ---------- District brief view ---------- */

async function loadDistricts() {
  const districts = await (await fetch("/api/districts")).json();
  const byProvince = {};
  districts.forEach((d) => { (byProvince[d.province] = byProvince[d.province] || []).push(d.district); });
  $("district-picker").innerHTML = Object.entries(byProvince).map(([p, names]) => `<div class="province">
      <h2 class="label mono">${esc(p.toUpperCase())}</h2>
      ${names.map((n) => `<button type="button" class="chip" data-district="${esc(n)}">${esc(n)}</button>`).join("")}</div>`).join("");
}

async function runBrief(district) {
  document.querySelectorAll("#district-picker .chip").forEach((c) => c.classList.toggle("selected", c.dataset.district === district));
  $("brief-error").hidden = true;
  $("brief-doc").hidden = true;
  $("brief-workspace").hidden = false;
  const trace = makeTrace($("brief-trace"), $("brief-plan"), $("brief-clock"));
  let ok = false;
  try {
    await streamPost("/api/brief/stream", { district, lang: state.lang }, (event) => {
      if (event.type === "step" || event.type === "plan") trace.add(event);
      else if (event.type === "result") { ok = true; renderBrief(event.result); }
      else if (event.type === "error") showError($("brief-error"), event.error);
    });
  } catch (_) {
    showError($("brief-error"), "Network error. Check your connection and try again.");
  } finally {
    trace.finish(ok);
  }
}

function renderBrief(r) {
  $("brief-name").textContent = r.brief_district;
  state.brief = makeDoc(r, { text: $("brief-text"), badge: $("brief-badge"), meta: $("brief-meta"), error: $("brief-error") });
  paintDoc(state.brief);
  $("brief-sources").innerHTML = sourcesHtml(r.citations);
  $("brief-sql").innerHTML = sqlHtml(r.sql);
  $("brief-doc").hidden = false;
  $("brief-doc").scrollIntoView({ behavior: "smooth", block: "start" });
}

/* ---------- Data gaps view ---------- */

async function loadGaps() {
  let g;
  try { g = await (await fetch("/api/gaps")).json(); } catch (_) { return; }
  const stat = (v, k) => `<div class="stat"><div class="v">${esc(v)}</div><div class="k">${esc(k)}</div></div>`;
  $("gap-stats").innerHTML = stat(g.total, "QUESTIONS ASKED") + stat(g.answered, "ANSWERED + VERIFIED") + stat(g.gaps, "DATA GAPS") + stat(g.kinyarwanda, "IN KINYARWANDA");
  $("gap-list").innerHTML = g.recent_gaps.map((e) => `<li><div class="q">${esc(e.question)}</div>
      <div class="p mono">${e.pointers.length ? "→ " + e.pointers.map((p) => esc(p.title)).join(" · ") : "NO NISR SOURCE FOUND"}</div></li>`).join("")
    || "<li class=\"empty\">No gaps yet. Ask something the tables do not cover, for example HIV prevalence in Musanze.</li>";
  const bars = (items) => {
    const max = Math.max(1, ...items.map((i) => i[1]));
    return items.map(([name, n]) => `<li>${esc(name)} · ${n}<div class="bar" style="width:${(n / max) * 100}%"></div></li>`).join("") || "<li class=\"empty\">Nothing yet.</li>";
  };
  $("gap-pointers").innerHTML = bars(g.top_pointers);
  $("gap-tables").innerHTML = bars(g.top_tables);
}

/* ---------- Catalogue ---------- */

async function loadCatalog() {
  if (!state.catalog) {
    try { state.catalog = await (await fetch("/api/catalog")).json(); } catch (_) { state.catalog = []; }
  }
  renderCatalog($("catalog-filter").value);
}

function renderCatalog(filter) {
  const words = (filter || "").toLowerCase().split(/\s+/).filter(Boolean);
  const shown = (state.catalog || []).filter((t) => words.every((w) => JSON.stringify(t).toLowerCase().includes(w)));
  $("catalog-list").innerHTML = shown.map((t) => `<div class="catalog-item">
      <p><span class="tag">${esc(t.survey)} ${esc(t.year)}</span><span class="tag">${esc(t.nisr_table_ref)}</span><span class="tag">${esc(t.geography_levels)}</span></p>
      <h2>${esc(t.title.replace(/^Table [^:]+:\s*/, ""))}</h2>
      <p>${esc(t.notes)}</p>
      <p class="mono" style="font-size:11px"><code>${esc(t.table_id)}</code> · <a href="${esc(t.source_file_url)}" target="_blank" rel="noopener">Excel</a> · <a href="${esc(t.report_page_url)}" target="_blank" rel="noopener">Report</a></p></div>`).join("")
    || "<p class=\"empty\">No table matches this filter.</p>";
}

/* ---------- Routing and controls ---------- */

const VIEWS = ["ask", "brief", "gaps", "catalog", "about"];

function route() {
  const view = (location.hash || "#ask").slice(1);
  const name = VIEWS.includes(view) ? view : "ask";
  VIEWS.forEach((v) => { $("view-" + v).hidden = v !== name; });
  document.querySelectorAll("nav a").forEach((a) => {
    if (a.dataset.view === name) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  });
  if (name === "catalog") loadCatalog();
  if (name === "gaps") loadGaps();
  if (name === "brief" && !$("district-picker").children.length) loadDistricts();
}

function setSeg(groupId, attr, value) {
  document.querySelectorAll(`#${groupId} button`).forEach((b) => b.setAttribute("aria-checked", String(b.dataset[attr] === value)));
}

function setLang(value) {
  state.lang = value === "rw" ? "rw" : "en";
  setSeg("lang", "lang", state.lang);
  $("question").placeholder = PLACEHOLDER[state.lang];
  document.documentElement.lang = state.lang === "rw" ? "rw" : "en";
  storage("baza-lang", state.lang);
}

function setMode(value) {
  state.mode = value === "investigate" ? "investigate" : "ask";
  setSeg("mode", "mode", state.mode);
}

function init() {
  const params = new URLSearchParams(location.search);
  if (params.get("embed") === "1") document.body.classList.add("embed");
  $("examples").innerHTML = EXAMPLES.map((e, i) => `<button type="button" class="chip" data-i="${i}">${e.mode ? "⌕ " : ""}${esc(e.q)}</button>`).join("");
  $("examples").addEventListener("click", (e) => {
    const chip = e.target.closest(".chip");
    if (!chip) return;
    const ex = EXAMPLES[Number(chip.dataset.i)];
    setMode(ex.mode || "ask");
    ask(ex.q);
  });
  $("ask-form").addEventListener("submit", (e) => { e.preventDefault(); ask($("question").value); });
  $("question").addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ask($("question").value); } });
  $("mode").addEventListener("click", (e) => { if (e.target.dataset.mode) setMode(e.target.dataset.mode); });
  $("lang").addEventListener("click", (e) => {
    if (!e.target.dataset.lang) return;
    setLang(e.target.dataset.lang);
    $("error").hidden = true;
    $("brief-error").hidden = true;
    switchLanguage(state.ask, state.lang);
    switchLanguage(state.brief, state.lang);
  });
  $("viz-tabs").addEventListener("click", (e) => { if (e.target.dataset.viz) showViz(e.target.dataset.viz); });
  $("download").addEventListener("click", () => {
    const r = state.ask && state.ask.result;
    if (!r || !r.table_rows) return;
    const link = document.createElement("a");
    link.href = URL.createObjectURL(new Blob([toCSV(r.table_rows)], { type: "text/csv" }));
    link.download = "baza-nisr-result.csv";
    link.click();
    URL.revokeObjectURL(link.href);
  });
  $("district-picker").addEventListener("click", (e) => { const c = e.target.closest(".chip"); if (c) runBrief(c.dataset.district); });
  $("print-brief").addEventListener("click", () => window.print());
  $("catalog-filter").addEventListener("input", (e) => renderCatalog(e.target.value));
  $("embed-code").textContent = `<script src="${location.origin}/embed.js" defer></script>`;
  if (window.BazaMotion && $("hero-motion")) motion = window.BazaMotion.attach($("hero-motion"), { word: "baza" });
  window.addEventListener("hashchange", route);
  setLang(params.get("lang") || storage("baza-lang") || "en");
  setMode(params.get("mode") || "ask");
  route();
  loadVega().catch(() => {});
  const q = params.get("q");
  if (q) ask(q);
}

window.Baza = { richText, badgeFor, tableHtml, toCSV, esc };
document.addEventListener("DOMContentLoaded", init);
