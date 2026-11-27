/* Problem Studio: define a custom problem, get a live algorithm recommendation, race the portfolio. */
(() => {
  "use strict";
  const A = window.AACP;
  const { $, $$, esc, el, api, toast, busy, seg, setSeg, download, store, ALGO_NAMES, TASKS, FEATURES, FAM_COLORS, FAM_NAMES, algoColor, fmtMs, fmtNum, fmtVal } = A;
  const W = 1000, H = 680;
  const RACE_ORDER = ["greedy", "matching", "nt_flow", "lp_round", "bnb", "td_dp", "ilp"];
  const SENSE_WORD = { vertex_cover: ["Minimum", "cost", "size"], independent_set: ["Maximum", "value", "size"], clique: ["Maximum", "value", "size"] };
  const SOL_WORD = { vertex_cover: "in the cover", independent_set: "in the set", clique: "in the clique" };

  const st = {
    meta: null, kind: "vertex_cover", weighted: false, nodes: [], edges: [], edgeSet: new Set(),
    tool: "select", selected: null, undo: [], redo: [], version: 0, title: "Untitled problem",
    analysis: null, anError: null, anSeq: 0, anTimer: null, task: "certified",
    race: null, pollTimer: null, shown: null, drag: null, story: null,
  };

  // ----------------------------------------------------------- definition
  const key = (i, j) => (i < j ? `${i}-${j}` : `${j}-${i}`);
  function snapshot() { return JSON.stringify({ k: st.kind, w: st.weighted, n: st.nodes, e: st.edges, t: st.title }); }
  function restore(s) {
    const d = JSON.parse(s);
    st.kind = d.k; st.weighted = d.w; st.nodes = d.n; st.edges = d.e; st.title = d.t;
    st.edgeSet = new Set(st.edges.map(([i, j]) => key(i, j)));
    st.selected = null;
  }
  function mutate(fn, { analyse = true } = {}) {
    st.undo.push(snapshot()); if (st.undo.length > 80) st.undo.shift();
    st.redo = [];
    fn();
    changed(analyse);
  }
  function changed(analyse = true) {
    st.version++;
    syncControls(); draw(); renderStats(); renderInspector();
    if (analyse) scheduleAnalysis();
    markRaceStale();
  }
  function undo() { if (!st.undo.length) return; st.redo.push(snapshot()); restore(st.undo.pop()); changed(); }
  function redo() { if (!st.redo.length) return; st.undo.push(snapshot()); restore(st.redo.pop()); changed(); }

  function nextLabel() {
    const used = new Set(st.nodes.map((n) => n.label));
    let i = st.nodes.length;
    while (used.has("v" + i)) i++;
    return "v" + i;
  }
  function addNode(x, y) {
    let idx;
    mutate(() => { st.nodes.push({ x, y, label: nextLabel(), w: 1, c: 0 }); idx = st.nodes.length - 1; st.selected = idx; });
    return idx;
  }
  function toggleEdge(i, j) {
    if (i === j) return;
    mutate(() => {
      const k = key(i, j);
      if (st.edgeSet.has(k)) { st.edgeSet.delete(k); st.edges = st.edges.filter(([a, b]) => key(a, b) !== k); }
      else { st.edgeSet.add(k); st.edges.push(i < j ? [i, j] : [j, i]); }
    });
  }
  function deleteNode(i) {
    mutate(() => {
      st.nodes.splice(i, 1);
      st.edges = st.edges.filter(([a, b]) => a !== i && b !== i).map(([a, b]) => [a > i ? a - 1 : a, b > i ? b - 1 : b]);
      st.edgeSet = new Set(st.edges.map(([a, b]) => key(a, b)));
      st.selected = null; st.shown = null;
    });
  }
  function loadDefinition(d, { title, story = null, keepKind = false } = {}) {
    mutate(() => {
      if (!keepKind && d.kind) st.kind = d.kind;
      const n = d.labels ? d.labels.length : d.n;
      const lay = d.layout || [];
      st.nodes = Array.from({ length: n }, (_, i) => ({
        x: lay[i] ? 40 + lay[i][0] * 920 : 60 + Math.random() * 880,
        y: lay[i] ? 30 + lay[i][1] * 620 : 50 + Math.random() * 580,
        label: d.labels ? String(d.labels[i]) : "v" + i,
        w: d.weights ? +d.weights[i] : 1,
        c: (d.require || []).includes(i) ? 1 : (d.forbid || []).includes(i) ? -1 : 0,
      }));
      st.edges = (d.edges || []).map(([a, b]) => (a < b ? [a, b] : [b, a]));
      st.edgeSet = new Set(st.edges.map(([a, b]) => key(a, b)));
      st.weighted = !!d.weights;
      st.selected = null; st.shown = null;
      st.title = title || st.title; st.story = story;
    });
  }
  function apiBody() {
    return {
      kind: st.kind, n: st.nodes.length, edges: st.edges,
      weights: st.weighted ? st.nodes.map((n) => n.w) : null,
      require: st.nodes.flatMap((n, i) => (n.c === 1 ? [i] : [])),
      forbid: st.nodes.flatMap((n, i) => (n.c === -1 ? [i] : [])),
      labels: st.nodes.map((n) => n.label),
    };
  }

  // --------------------------------------------------------------- canvas
  const svg = () => $("#graph");
  function toSvg(ev) {
    const s = svg(), p = s.createSVGPoint();
    p.x = ev.clientX; p.y = ev.clientY;
    const q = p.matrixTransform(s.getScreenCTM().inverse());
    return [Math.max(12, Math.min(W - 12, q.x)), Math.max(12, Math.min(H - 12, q.y))];
  }
  function radius() {
    const n = st.nodes.length;
    return Math.max(4, Math.min(13, 15 - n / 10));
  }
  function nodeR(nd, base, maxw) {
    return st.weighted ? base * (0.65 + 0.7 * Math.sqrt(nd.w / maxw)) : base;
  }
  function nearestNode(x, y, within = 22) {
    let best = null, bd = within * within;
    st.nodes.forEach((n, i) => { const d = (n.x - x) ** 2 + (n.y - y) ** 2; if (d < bd) { bd = d; best = i; } });
    return best;
  }
  function draw() {
    const s = svg(); s.innerHTML = "";
    s.setAttribute("class", "tool-" + st.tool);
    $("#emptyState").hidden = st.nodes.length > 0;
    const base = radius(), maxw = Math.max(1e-9, ...st.nodes.map((n) => n.w));
    const showLabels = st.nodes.length <= 45;
    const sol = st.shown ? st.shown.set : null;
    const hit = el("g", { class: "hits" }, s), eg = el("g", {}, s), ng = el("g", {}, s), lg = el("g", { class: "labels" }, s);
    st.edges.forEach(([a, b], ei) => {
      const A1 = st.nodes[a], B1 = st.nodes[b];
      const inside = sol && st.kind === "clique" && sol.has(a) && sol.has(b);
      const cov = sol && st.kind === "vertex_cover" && (sol.has(a) || sol.has(b));
      el("line", { class: "e" + (inside ? " kin" : "") + (cov ? " cov" : ""), x1: A1.x, y1: A1.y, x2: B1.x, y2: B1.y }, eg);
      el("line", { class: "ehit", "data-e": ei, x1: A1.x, y1: A1.y, x2: B1.x, y2: B1.y }, hit);
    });
    st.nodes.forEach((nd, i) => {
      const r = nodeR(nd, base, maxw);
      const g = el("g", { class: "nd" + (sol && sol.has(i) ? " in" : "") + (i === st.selected ? " sel" : "") + (nd.c === 1 ? " req" : nd.c === -1 ? " forb" : ""), "data-i": i, transform: `translate(${nd.x.toFixed(1)} ${nd.y.toFixed(1)})` }, ng);
      if (nd.c) el("circle", { class: "ring", r: r + 4.5 }, g);
      el("circle", { class: "v", r, "data-i": i }, g);
      if (nd.c === -1) el("line", { class: "slash", x1: -r * 0.7, y1: r * 0.7, x2: r * 0.7, y2: -r * 0.7 }, g);
      if (st.weighted && r >= 9 && st.nodes.length <= 40) el("text", { class: "wt", y: 3.5, "text-anchor": "middle" }, g).textContent = fmtVal(nd.w);
      if (showLabels) el("text", { class: "lbl", x: nd.x, y: nd.y + r + 13, "text-anchor": "middle" }, lg).textContent = nd.label;
    });
    st.rubber = el("line", { class: "rubber", x1: 0, y1: 0, x2: 0, y2: 0, visibility: "hidden" }, s);
    const n = st.nodes.length, m = st.edges.length;
    $("#graphCaption").innerHTML = n ? `${esc(st.title)} <span class="mono">· n = ${n} · m = ${m}${st.weighted ? " · weighted" : ""}</span>` : "Draw, generate, or pick a scenario.";
    $("#lgSol").textContent = SOL_WORD[st.kind];
  }
  function initCanvas() {
    const s = svg();
    s.addEventListener("pointerdown", (ev) => {
      if (ev.button !== 0) return;
      const [x, y] = toSvg(ev);
      const t = ev.target, ni = t.closest && t.closest("[data-i]") ? +t.closest("[data-i]").dataset.i : null;
      const ei = t.dataset && t.dataset.e != null ? +t.dataset.e : null;
      if (st.tool === "erase") {
        if (ni != null) deleteNode(ni);
        else if (ei != null) { const [a, b] = st.edges[ei]; toggleEdge(a, b); }
        return;
      }
      if (st.tool === "connect") {
        if (ni == null) return;
        st.drag = { mode: "connect", from: ni };
        st.rubber.setAttribute("x1", st.nodes[ni].x); st.rubber.setAttribute("y1", st.nodes[ni].y);
        st.rubber.setAttribute("x2", x); st.rubber.setAttribute("y2", y); st.rubber.setAttribute("visibility", "visible");
        s.setPointerCapture(ev.pointerId);
        return;
      }
      if (ni != null) {
        st.drag = { mode: "move", i: ni, x0: x, y0: y, moved: false, snap: snapshot() };
        st.selected = ni; renderInspector(); draw();
        s.setPointerCapture(ev.pointerId);
      } else if (st.tool === "add") {
        addNode(x, y);
      } else {
        st.selected = null; renderInspector(); draw();
      }
    });
    s.addEventListener("pointermove", (ev) => {
      if (!st.drag) return hover(ev);
      const [x, y] = toSvg(ev);
      if (st.drag.mode === "connect") {
        const j = nearestNode(x, y);
        st.rubber.setAttribute("x2", j != null ? st.nodes[j].x : x); st.rubber.setAttribute("y2", j != null ? st.nodes[j].y : y);
      } else if (st.drag.mode === "move") {
        if (!st.drag.moved && Math.hypot(x - st.drag.x0, y - st.drag.y0) < 3) return;
        st.drag.moved = true;
        st.nodes[st.drag.i].x = x; st.nodes[st.drag.i].y = y;
        draw();
      }
    });
    const end = (ev) => {
      if (!st.drag) return;
      const d = st.drag; st.drag = null;
      if (d.mode === "connect") {
        st.rubber.setAttribute("visibility", "hidden");
        const [x, y] = toSvg(ev); const j = nearestNode(x, y);
        if (j != null && j !== d.from) toggleEdge(d.from, j);
      } else if (d.mode === "move" && d.moved) {
        st.undo.push(d.snap); st.redo = []; // positions only: no re-analysis
      }
    };
    s.addEventListener("pointerup", end);
    s.addEventListener("pointercancel", end);
    s.addEventListener("pointerleave", () => ($("#graphTip").hidden = true));
  }
  function hover(ev) {
    const tip = $("#graphTip"), t = ev.target.closest && ev.target.closest("[data-i]");
    if (!t) { tip.hidden = true; return; }
    const i = +t.dataset.i, nd = st.nodes[i];
    const deg = st.edges.reduce((s, [a, b]) => s + (a === i || b === i), 0);
    const cons = nd.c === 1 ? " · must choose" : nd.c === -1 ? " · must not" : "";
    const inS = st.shown ? (st.shown.set.has(i) ? ` · ${SOL_WORD[st.kind]}` : "") : "";
    tip.innerHTML = `${esc(nd.label)} · deg ${deg}${st.weighted ? " · " + (st.kind === "vertex_cover" ? "cost " : "value ") + fmtVal(nd.w) : ""}${cons}${inS}`;
    const b = t.getBoundingClientRect(), rr = $("#graphWrap").getBoundingClientRect();
    tip.style.left = b.left - rr.left + b.width / 2 + "px"; tip.style.top = b.top - rr.top + "px"; tip.hidden = false;
  }
  function setTool(t) {
    st.tool = t;
    $$("#tools button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.tool === t)));
    svg().setAttribute("class", "tool-" + t);
  }

  // ------------------------------------------------------------- controls
  function syncControls() {
    setSeg($("#kindSeg"), st.kind);
    const k = st.meta.kinds[st.kind];
    $("#kindDef").innerHTML = `${esc(k.definition)} <span class="muted">${esc(k.reduction)}</span>`;
    $("#weighted").checked = st.weighted; $("#randWeights").disabled = !st.weighted;
    $("#story").hidden = !st.story; $("#story").textContent = st.story || "";
    $("#undoBtn").disabled = !st.undo.length; $("#redoBtn").disabled = !st.redo.length;
    $("#raceBtn").disabled = !st.nodes.length || !!st.anError || isRacing();
  }
  function renderStats() {
    const req = st.nodes.filter((n) => n.c === 1).length, forb = st.nodes.filter((n) => n.c === -1).length;
    $("#defStats").innerHTML = `<dt>vertices</dt><dd>${st.nodes.length}</dd><dt>edges</dt><dd>${st.edges.length}</dd>
      <dt>must choose</dt><dd>${req}</dd><dt>must not</dt><dd>${forb}</dd>`;
  }
  function renderInspector() {
    const i = st.selected, has = i != null && st.nodes[i];
    $("#inspEmpty").hidden = !!has; $("#inspBody").hidden = !has;
    if (!has) return;
    const nd = st.nodes[i];
    if (document.activeElement !== $("#inspLabel")) $("#inspLabel").value = nd.label;
    if (document.activeElement !== $("#inspWeight")) $("#inspWeight").value = nd.w;
    $("#inspWeightRow").hidden = !st.weighted;
    $("#inspWeightRow").firstChild.textContent = st.kind === "vertex_cover" ? "Cost " : "Value ";
    setSeg($("#inspCons"), String(nd.c));
    const deg = st.edges.reduce((s, [a, b]) => s + (a === i || b === i), 0);
    $("#inspDeg").textContent = `degree ${deg}`;
  }
  function initControls() {
    seg($("#kindSeg"), Object.entries(st.meta.kinds).map(([k, v]) => [k, v.label]), st.kind, (k) => mutate(() => { st.kind = k; st.shown = null; }));
    for (const sc of st.meta.scenarios) $("#scenario").add(new Option(`${sc.title} (${st.meta.kinds[sc.kind].label.toLowerCase()})`, sc.id));
    $("#scenario").onchange = async (e) => {
      const sc = st.meta.scenarios.find((x) => x.id === e.target.value); if (!sc) return;
      try {
        const lay = await api("/api/layout", { n: sc.labels.length, edges: sc.edges });
        loadDefinition({ ...sc, layout: lay.layout }, { title: sc.title, story: sc.story });
        if (!st.quietLoad) toast(`Loaded "${sc.title}". The analysis updates on its own; press Race to check it.`);
        st.quietLoad = false;
      } catch (err) { toast(err.message, "err"); }
    };
    $("#weighted").onchange = (e) => mutate(() => { st.weighted = e.target.checked; });
    $("#randWeights").onclick = () => mutate(() => st.nodes.forEach((n) => (n.w = 1 + Math.floor(Math.random() * 10))));
    $$("#inputTabs button").forEach((b) => (b.onclick = () => {
      $$("#inputTabs button").forEach((x) => x.setAttribute("aria-selected", String(x === b)));
      $$(".pane").forEach((p) => (p.hidden = p.id !== "pane-" + b.dataset.pane));
      if (b.dataset.pane === "draw" && st.tool === "select" && !st.nodes.length) setTool("add");
    }));
    $$("#tools button").forEach((b) => (b.onclick = () => setTool(b.dataset.tool)));
    $("#undoBtn").onclick = undo; $("#redoBtn").onclick = redo;
    $("#clearBtn").onclick = () => { if (st.nodes.length && !confirm("Remove all vertices and edges?")) return; mutate(() => { st.nodes = []; st.edges = []; st.edgeSet = new Set(); st.selected = null; st.shown = null; st.title = "Untitled problem"; st.story = null; }); setTool("add"); };
    $("#relayout").onclick = (e) => busy(e.currentTarget, async () => {
      if (!st.nodes.length) return;
      const lay = await api("/api/layout", { n: st.nodes.length, edges: st.edges });
      mutate(() => lay.layout.forEach(([x, y], i) => { st.nodes[i].x = 40 + x * 920; st.nodes[i].y = 30 + y * 620; }), { analyse: false });
    });
    // generate
    const pres = $("#presets");
    for (const p of st.meta.presets) {
      const b = document.createElement("button");
      b.className = "chip"; b.textContent = p.label;
      b.onclick = () => busy(b, async () => { syncBuilder(p); await generate(p.family, p.n, p.params, p.label); });
      pres.appendChild(b);
    }
    const fam = $("#family");
    for (const [k, f] of Object.entries(st.meta.families)) fam.add(new Option(f.label, k));
    fam.onchange = () => renderParamFields(fam.value);
    $("#nRange").oninput = (e) => ($("#nOut").textContent = e.target.value);
    $("#dice").onclick = () => ($("#seed").value = Math.floor(Math.random() * 9999));
    $("#generate").onclick = (e) => busy(e.currentTarget, async () => {
      const params = {}; $$("#paramFields input").forEach((i) => (params[i.dataset.key] = +i.value));
      await generate(fam.value, +$("#nRange").value, params, st.meta.families[fam.value].label);
    });
    renderParamFields(fam.value);
    // text
    $("#parseBtn").onclick = (e) => busy(e.currentTarget, async () => {
      const d = await api("/api/parse", { text: $("#defText").value });
      loadDefinition(d, { title: "Problem from text", keepKind: true });
    });
    $("#toText").onclick = () => { $("#defText").value = toText(); };
    // file
    $("#exportDef").onclick = () => download(slug(st.title) + ".aacp.json", JSON.stringify(exportJson(), null, 1));
    $("#importDef").onchange = async (e) => {
      const f = e.target.files[0]; if (!f) return; e.target.value = "";
      try { importJson(JSON.parse(await f.text())); toast(`Opened ${f.name}`); } catch (err) { toast("Could not open file: " + err.message, "err"); }
    };
    // inspector
    $("#inspLabel").oninput = (e) => { if (st.selected == null) return; st.nodes[st.selected].label = e.target.value.slice(0, 40) || "?"; draw(); };
    $("#inspLabel").onchange = () => scheduleAnalysis();
    $("#inspWeight").onchange = (e) => {
      const v = +e.target.value; if (st.selected == null) return;
      if (!(v > 0)) { toast("Costs and values must be positive numbers", "err"); e.target.value = st.nodes[st.selected].w; return; }
      const i = st.selected; mutate(() => (st.nodes[i].w = v));
    };
    seg($("#inspCons"), [["0", "Free"], ["1", "Must choose"], ["-1", "Must not"]], "0", (v) => { const i = st.selected; if (i == null) return; mutate(() => (st.nodes[i].c = +v)); });
    $("#inspDelete").onclick = () => st.selected != null && deleteNode(st.selected);
    // analysis goal + race
    seg($("#taskSeg"), Object.entries(TASKS).map(([k, t]) => [k, t.label]), st.task, (t) => { st.task = t; renderAnalysis(); if (st.race) renderRace(); window.dispatchEvent(new Event("aacp:analysis")); });
    $("#taskDesc").innerHTML = TASKS[st.task].desc;
    const tg = $("#algoToggles");
    for (const a of RACE_ORDER) {
      const lab = document.createElement("label"); lab.className = "algo-toggle"; lab.style.setProperty("--c", algoColor(a));
      lab.innerHTML = `<input type="checkbox" value="${a}" checked><span>${a}</span>`; lab.title = ALGO_NAMES[a];
      tg.appendChild(lab);
    }
    $("#raceBtn").onclick = startRace;
    $("#cancelBtn").onclick = cancelRace;
    $("#clearHistory").onclick = () => { store.set("aacp-history", []); renderHistory(); };
    // keyboard
    document.addEventListener("keydown", (e) => {
      if (!$("#tab-play").classList.contains("active")) return;
      const tag = (e.target.tagName || "").toLowerCase();
      if (["input", "textarea", "select"].includes(tag)) return;
      const k = e.key.toLowerCase();
      if ((e.ctrlKey || e.metaKey) && k === "z") { e.preventDefault(); e.shiftKey ? redo() : undo(); return; }
      if ((e.ctrlKey || e.metaKey) && k === "y") { e.preventDefault(); redo(); return; }
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      if (k === "s") setTool("select"); else if (k === "a") setTool("add"); else if (k === "c") setTool("connect"); else if (k === "x") setTool("erase");
      else if ((k === "delete" || k === "backspace") && st.selected != null) { e.preventDefault(); deleteNode(st.selected); }
      else if (k === "escape") { st.selected = null; st.shown = null; renderInspector(); draw(); }
      else if (k === "r" && !$("#raceBtn").disabled) startRace();
    });
  }
  function renderParamFields(fam, values = {}) {
    const box = $("#paramFields"); box.innerHTML = "";
    for (const [k, [lo, hi, def]] of Object.entries(st.meta.families[fam].params)) {
      const isInt = ["m", "k", "blocks"].includes(k), v = values[k] ?? def;
      const lab = document.createElement("label"); lab.className = "field";
      lab.innerHTML = `${k} <output>${v}</output><input type="range" data-key="${k}" min="${lo}" max="${hi}" step="${isInt ? 1 : (hi - lo) / 100}" value="${v}">`;
      const inp = $("input", lab); inp.oninput = () => ($("output", lab).textContent = isInt ? inp.value : (+inp.value).toFixed(3));
      box.appendChild(lab);
    }
  }
  function syncBuilder(p) { $("#family").value = p.family; $("#nRange").value = p.n; $("#nOut").textContent = p.n; renderParamFields(p.family, p.params); }
  async function generate(family, n, params, label) {
    const g = await api("/api/generate", { family, n, params, seed: +$("#seed").value || 1 });
    loadDefinition({ n: g.n, edges: g.edges, layout: g.layout, weights: st.weighted ? Array(g.n).fill(1) : null }, { title: label, keepKind: true });
  }
  const slug = (s) => s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "problem";
  function exportJson() {
    return { format: "aacp-problem", version: 1, title: st.title, kind: st.kind, weighted: st.weighted,
      nodes: st.nodes.map((n) => ({ label: n.label, x: Math.round(n.x), y: Math.round(n.y), w: n.w, c: n.c })), edges: st.edges };
  }
  function importJson(d) {
    if (d.format !== "aacp-problem" || !Array.isArray(d.nodes) || !Array.isArray(d.edges)) throw new Error("not an AACP problem file");
    if (d.nodes.length > st.meta.max_nodes) throw new Error(`more than ${st.meta.max_nodes} vertices`);
    if (!st.meta.kinds[d.kind]) throw new Error(`unknown problem kind ${d.kind}`);
    const n = d.nodes.length;
    const edges = d.edges.filter(([a, b]) => Number.isInteger(a) && Number.isInteger(b) && a >= 0 && b >= 0 && a < n && b < n && a !== b);
    mutate(() => {
      st.kind = d.kind; st.weighted = !!d.weighted; st.title = String(d.title || "Imported problem").slice(0, 80); st.story = null;
      st.nodes = d.nodes.map((x, i) => ({ label: String(x.label ?? "v" + i).slice(0, 40), x: +x.x || 100, y: +x.y || 100, w: +x.w > 0 ? +x.w : 1, c: [1, -1].includes(x.c) ? x.c : 0 }));
      st.edges = edges.map(([a, b]) => (a < b ? [a, b] : [b, a])); st.edgeSet = new Set(st.edges.map(([a, b]) => key(a, b)));
      st.edges = [...st.edgeSet].map((k) => k.split("-").map(Number));
      st.selected = null; st.shown = null;
    });
  }
  function toText() {
    const L = st.nodes.map((n) => n.label.replace(/[\s:,#]/g, "_"));
    const lines = [`# ${st.title} (${st.meta.kinds[st.kind].label})`];
    st.edges.forEach(([a, b]) => lines.push(`${L[a]} ${L[b]}`));
    st.nodes.forEach((n, i) => {
      const parts = []; if (st.weighted) parts.push(fmtVal(n.w)); if (n.c === 1) parts.push("require"); if (n.c === -1) parts.push("forbid");
      const deg = st.edges.some(([a, b]) => a === i || b === i);
      if (parts.length || !deg) lines.push(`${L[i]}: ${parts.join(" ")}`.trim());
    });
    return lines.join("\n");
  }

  // ------------------------------------------------------------- analysis
  function scheduleAnalysis() {
    clearTimeout(st.anTimer);
    if (!st.nodes.length) { st.analysis = null; st.anError = null; renderAnalysis(); syncControls(); return; }
    $("#anStatus").textContent = "analysing…"; $("#anStatus").className = "an-status busy";
    st.anTimer = setTimeout(runAnalysis, 320);
  }
  async function runAnalysis() {
    const seq = ++st.anSeq;
    try {
      const a = await api("/api/analyze", apiBody());
      if (seq !== st.anSeq) return;
      st.analysis = a; st.anError = null;
      $("#anStatus").textContent = `updated · ${fmtMs(a.analysis_ms)}`; $("#anStatus").className = "an-status";
      if (!a.trivial && !a.ehm_ready) setTimeout(() => seq === st.anSeq && runAnalysis(), 2500);
    } catch (e) {
      if (seq !== st.anSeq) return;
      st.analysis = null; st.anError = e.message;
      $("#anStatus").textContent = "needs attention"; $("#anStatus").className = "an-status err";
    }
    renderAnalysis(); syncControls();
    window.dispatchEvent(new Event("aacp:analysis"));
  }
  function renderPipeline(a) {
    const p = $("#pipeline");
    if (!a) { p.innerHTML = ""; return; }
    const r = a.reduction, steps = [];
    steps.push(`<div class="pstep"><b>${esc(r.label)}</b><span>n ${r.n} · m ${r.m}${r.weighted ? " · weighted" : ""}</span></div>`);
    if (r.kind === "clique") steps.push(`<div class="pstep"><b>Complement</b><span>vertex cover · m ${r.vc_m}</span></div>`);
    else if (r.kind === "independent_set") steps.push(`<div class="pstep"><b>Cover = V ∖ S</b><span>vertex cover · m ${r.vc_m}</span></div>`);
    const fixed = r.forced_in.length + r.forced_out.length;
    if (fixed) steps.push(`<div class="pstep"><b>Constraints</b><span>${fixed} vertices fixed</span></div>`);
    steps.push(`<div class="pstep kern"><b>Kernel</b><span>n ${r.kernel_n} · m ${r.kernel_m}</span></div>`);
    p.innerHTML = steps.join('<i class="parrow">→</i>');
  }
  function renderAnalysis() {
    $("#taskDesc").innerHTML = TASKS[st.task].desc;
    const body = $("#anBody");
    if (st.anError) { renderPipeline(null); body.innerHTML = `<div class="an-error"><b>This definition cannot be solved yet.</b><p>${esc(st.anError)}</p></div>`; return; }
    const a = st.analysis;
    renderPipeline(a);
    if (!a) { body.innerHTML = `<p class="muted">The analysis updates as you edit the problem.</p>`; $("#anStatus").textContent = "idle"; return; }
    const warn = (a.warnings || []).map((w) => `<li>${esc(w)}</li>`).join("");
    if (a.trivial) { body.innerHTML = `<div class="consensus"><div class="pick-label">Verdict</div><p class="trivial">${esc(a.consensus.message)}</p></div>${warn ? `<ul class="warns">${warn}</ul>` : ""}`; return; }
    const T = a.tasks[st.task], c = T.consensus, pick = c.choice, info = st.meta.algorithms[pick];
    const conf = Math.round(c.confidence * 100);
    const voteCard = (v) => {
      let detail = "";
      if (v.source === "tree") detail = `${T.tree.steps.length}-step rule · leaf won ${Math.round(T.tree.purity * 100)}%`;
      if (v.source === "ehm") detail = `predicted ${st.task === "budgeted" ? "×" + T.ehm.pred[v.choice].toFixed(3) : fmtMs(T.ehm.pred[v.choice] * 1000)}`;
      if (v.source === "knn") detail = `${v.support} of ${v.of} nearest graphs`;
      return `<div class="vote${v.choice === pick ? " agree" : ""}"><span class="vsrc">${esc(v.label)}</span><b style="color:${algoColor(v.choice)}">${esc(v.choice)}</b><span class="vdet">${detail}</span></div>`;
    };
    let html = `<div class="consensus">
        <div class="pick-label">Best bet for “${esc(TASKS[st.task].label)}”</div>
        <div class="pick-row"><div class="pick" style="color:${algoColor(pick)}">${pick}</div>
          <div class="conf" title="65% vote agreement + 35% leaf purity, discounted when extrapolating"><div class="conf-n">${conf}%</div><div class="conf-bar"><i style="width:${conf}%"></i></div><div class="conf-l">confidence</div></div></div>
        <div class="pick-sub"><span class="unit-badge">Unit ${info.unit}</span>${esc(ALGO_NAMES[pick])} · <span class="muted">${esc(info.bound)}</span></div>
        <div class="votes">${c.votes.map(voteCard).join("")}</div>
      </div>`;
    if (warn) html += `<ul class="warns">${warn}</ul>`;
    if (T.ehm) {
      const pred = T.ehm.pred, algs = Object.keys(pred).sort((x, y) => pred[x] - pred[y]);
      const isRatio = st.task === "budgeted";
      const lo = isRatio ? 1 : 1e-4, hi = isRatio ? Math.max(1.6, ...Object.values(pred)) : 60;
      const pos = (v) => isRatio ? ((Math.min(v, hi) - lo) / (hi - lo)) * 100 : ((Math.log10(Math.max(v, lo)) - Math.log10(lo)) / (Math.log10(hi) - Math.log10(lo))) * 100;
      html += `<h3 class="mini-title">Runtime model · predicted ${isRatio ? "ratio within 50 ms" : "PAR10 time"}</h3><div class="predbars">` +
        algs.map((al) => `<div class="pb${al === pick ? " on" : ""}"><span>${al}</span><div class="pbt"><i style="width:${Math.max(2, pos(pred[al]))}%;background:${algoColor(al)}"></i></div><em>${isRatio ? "×" + pred[al].toFixed(3) : fmtMs(pred[al] * 1000)}</em></div>`).join("") + `</div>`;
    } else html += `<p class="tiny muted">Runtime model is warming up (trains in the background at startup)…</p>`;
    html += `<details class="an-more" open><summary>Why: the regret tree's path</summary><ol class="because">`;
    T.tree.steps.forEach((s, i) => {
      const [name, why] = FEATURES[s.feature] || [s.feature, ""];
      const lo = Math.min(s.value, s.threshold), hi = Math.max(s.value, s.threshold), span = hi - lo || Math.abs(hi) || 1, d0 = lo - span * 0.6, d1 = hi + span * 0.6;
      const px = (v) => ((v - d0) / (d1 - d0)) * 100, side = s.left ? `left:0;width:${px(s.threshold)}%` : `left:${px(s.threshold)}%;right:0`;
      html += `<li style="--i:${i}"><div class="cond">${name} <span class="mono">= ${fmtNum(s.value)} ${s.left ? "≤" : ">"} ${fmtNum(s.threshold)}</span></div>
        <div class="numline"><div class="track"></div><div class="side" style="${side}"></div><div class="thr" style="left:${px(s.threshold)}%"></div><div class="val" style="left:${px(s.value)}%"></div></div><div class="why">${why}</div></li>`;
    });
    const lw = Object.entries(T.tree.leaf_winners).map(([al, k]) => `${al} ${k}`).join(" · ");
    html += `<li class="leaf" style="--i:${T.tree.steps.length}"><div class="cond">Leaf: <b>${T.tree.leaf_n}</b> training graphs; the tree runs <b>${T.tree.choice}</b>. Who actually won there: <span class="mono">${esc(lw)}</span>.</div></li></ol></details>`;
    html += `<details class="an-more"><summary>Most similar benchmark graphs</summary><table class="nn"><tr><th>family</th><th>n</th><th>m</th><th>winner</th><th>dist.</th></tr>` +
      T.neighbours.slice(0, 6).map((nb) => `<tr><td><i class="fdot" style="background:${FAM_COLORS[nb.family]}"></i>${FAM_NAMES[nb.family]}</td><td>${nb.n}</td><td>${nb.m}</td><td style="color:${nb.winner ? algoColor(nb.winner) : "inherit"}">${nb.winner || "unsolved"}</td><td>${nb.distance.toFixed(2)}</td></tr>`).join("") + `</table></details>`;
    html += `<details class="an-more"><summary>Where this kernel sits in the benchmark</summary><div class="pcts">` +
      Object.entries(a.percentiles).map(([f, p]) => `<div class="pct${(a.ood || []).includes(f) ? " ood" : ""}" title="${esc((FEATURES[f] || [f, ""])[1])}"><span>${(FEATURES[f] || [f])[0]}</span><div class="pctt"><i style="left:${(p * 100).toFixed(0)}%"></i></div><em>${fmtNum(a.features[f])}</em></div>`).join("") + `</div></details>`;
    body.innerHTML = html;
  }

  // ----------------------------------------------------------------- race
  const isRacing = () => st.race && st.race.job.status === "running";
  async function startRace() {
    if (isRacing() || !st.nodes.length) return;
    const algorithms = $$("#algoToggles input:checked").map((i) => i.value);
    if (!algorithms.length) return toast("Select at least one algorithm to race.", "err");
    const btn = $("#raceBtn");
    await busy(btn, async () => {
      const job = await api("/api/race", { ...apiBody(), algorithms, budget: +$("#budget").value });
      const picks = st.analysis && !st.analysis.trivial ? Object.fromEntries(Object.entries(st.analysis.tasks).map(([t, v]) => [t, v.consensus.choice])) : {};
      st.race = { job, version: st.version, picks, def: apiBody(), title: st.title, saved: false };
      st.shown = null; draw(); renderRace(); poll();
    });
    syncControls();
  }
  async function poll() {
    clearTimeout(st.pollTimer);
    if (!st.race) return;
    try {
      st.race.job = await api("/api/race/" + st.race.job.id);
    } catch (e) { toast(e.message, "err"); st.race.job.status = "error"; }
    renderRace();
    if (isRacing()) st.pollTimer = setTimeout(poll, 140);
    else finishRace();
  }
  async function cancelRace() { if (!isRacing()) return; try { await api(`/api/race/${st.race.job.id}/cancel`, {}); } catch (e) { toast(e.message, "err"); } }
  function markRaceStale() {
    const stale = st.race && st.race.version !== st.version;
    $("#raceCard").classList.toggle("stale", !!stale);
    $("#solutionCard").classList.toggle("stale", !!stale);
  }
  function winnerFor(task, results) {
    const ok = results.filter((r) => r.status === "ok" && r.feasible);
    if (task === "certified") {
      const pr = ok.filter((r) => r.proved); if (!pr.length) return null;
      const best = Math.min(...pr.map((r) => r.cover_weight));
      return pr.filter((r) => r.cover_weight <= best + 1e-9).sort((a, b) => a.time_ms - b.time_ms)[0];
    }
    if (task === "optimum") {
      if (!ok.length) return null;
      const pr = ok.filter((r) => r.proved);
      const target = pr.length ? Math.min(...pr.map((r) => r.cover_weight)) : Math.min(...ok.map((r) => r.cover_weight));
      return ok.filter((r) => r.cover_weight <= target + 1e-9).sort((a, b) => a.time_ms - b.time_ms)[0];
    }
    const fast = ok.filter((r) => r.time_ms <= st.meta.budget_ms);
    return fast.sort((a, b) => a.cover_weight - b.cover_weight || a.time_ms - b.time_ms)[0] || null;
  }
  function renderRace() {
    const R = st.race; if (!R) return;
    const job = R.job, res = Object.fromEntries(job.results.map((r) => [r.algorithm, r]));
    $("#raceCard").dataset.status = job.status; $("#raceCard").dataset.job = job.id;
    $("#cancelBtn").hidden = !isRacing();
    const tmin = 0.05, tmax = job.budget * 1000;
    const lx = (ms) => Math.max(0, Math.min(100, ((Math.log10(Math.max(ms, tmin)) - Math.log10(tmin)) / (Math.log10(tmax) - Math.log10(tmin))) * 100));
    const sc = $("#raceScale"); sc.innerHTML = "";
    for (let v = 0.1; v <= tmax * 1.001; v *= 10) { const s = document.createElement("span"); s.style.left = lx(v) + "%"; s.textContent = fmtMs(v); sc.appendChild(s); }
    const done = job.status !== "running", win = done ? winnerFor(st.task, job.results) : null, pick = R.picks[st.task];
    const best = job.results.filter((r) => r.status === "ok").reduce((m, r) => Math.min(m, r.cover_weight), Infinity);
    const sense = SENSE_WORD[R.def.kind];
    const list = $("#raceList"); list.innerHTML = "";
    job.algorithms.forEach((a, i) => {
      const r = res[a], li = document.createElement("li");
      li.className = "race-row" + (r ? "" : job.current === a ? " running" : " queued"); li.dataset.alg = a;
      li.style.setProperty("--c", algoColor(a)); li.style.setProperty("--i", 0);
      if (st.shown && st.shown.alg === a) li.classList.add("selected");
      const state = !r ? (job.current === a ? "running…" : job.status === "running" ? "queued" : "not run") : r.status === "ok" ? fmtMs(r.time_ms) : r.status;
      const w = r ? (r.status === "ok" ? lx(r.time_ms) : r.status === "timeout" ? 100 : 0) : 0;
      const gap = r && r.status === "ok" && isFinite(best) ? (r.cover_weight - best) : null;
      const obj = r && r.status === "ok" ? `${sense[0] === "Minimum" ? "" : ""}${fmtVal(r.objective)}` : "—";
      li.innerHTML = `<div><div class="alg-name"><span class="sw"></span>${a}${a === pick ? ' <span class="rec-tag">PICK</span>' : ""}${win && win.algorithm === a ? ' <span class="trophy" title="winner for this goal">★</span>' : ""}</div>
          <div class="alg-para">${esc(r && r.reason ? r.reason : ALGO_NAMES[a])}</div></div>
        <div class="bar-track"><div class="bar${r && r.status === "timeout" ? " timeout" : ""}${!r && job.current === a ? " live" : ""}" style="width:${w}%"></div><span class="bar-label" style="left:${w}%">${esc(state)}</span></div>
        <div class="race-stats">
          <span class="size" title="objective (${sense[1]})">${obj}</span>
          <span class="ratio${gap === 0 ? " opt" : ""}" title="gap to the best ${sense[1]} found">${gap == null ? "" : gap === 0 ? "best" : (R.def.kind === "vertex_cover" ? "+" : "−") + fmtVal(gap)}</span>
          <span class="stamp${r && r.proved ? "" : r && ["timeout", "cancelled", "skipped", "error"].includes(r.status) ? " to" : " none"}" style="animation-delay:0ms">${r && r.proved ? "proved optimal" : r ? r.status : "·"}</span>
        </div>`;
      if (r && r.solution) li.onclick = () => showSolution(a);
      list.appendChild(li);
    });
    const sumEl = $("#raceSummary");
    if (!done) sumEl.innerHTML = `<span class="muted">Running ${job.current || ""}… ${job.results.length}/${job.algorithms.length} done</span>`;
    else if (job.status === "cancelled") sumEl.innerHTML = `<span class="bad">Cancelled</span> after ${job.results.length} algorithm(s).`;
    else if (!win) sumEl.innerHTML = `<span class="bad">No algorithm met “${TASKS[st.task].label}” within the budget.</span>`;
    else if (!pick) sumEl.innerHTML = `Winner for “${TASKS[st.task].label}”: <b>${win.algorithm}</b>.`;
    else if (win.algorithm === pick) sumEl.innerHTML = `<span class="ok">✓ The live pick, <b>${pick}</b>, won “${TASKS[st.task].label}”.</span>`;
    else {
      const c = res[pick];
      let why = "it was not selected for the race";
      if (c) {
        if (st.task === "budgeted") why = c.status === "ok" && c.time_ms <= st.meta.budget_ms ? `${fmtVal(Math.abs(c.cover_weight - win.cover_weight))} worse` : "it missed the 50 ms budget";
        else { const reached = st.task === "certified" ? c.proved && Math.abs(c.cover_weight - win.cover_weight) < 1e-9 : c.status === "ok" && Math.abs(c.cover_weight - win.cover_weight) < 1e-9; why = reached ? `+${fmtMs(c.time_ms - win.time_ms)} slower` : "it did not reach the goal"; }
      }
      sumEl.innerHTML = `Winner: <b>${win.algorithm}</b>. The pick <b>${pick}</b> lost: ${why}.`;
    }
    markRaceStale();
  }
  function finishRace() {
    const R = st.race; if (!R || R.saved) return;
    R.saved = true;
    syncControls();
    renderSolution();
    if (R.job.best && R.version === st.version) showSolution(R.job.best.algorithm, R.job.best.solution);
    if (R.job.status === "done") {
      const winners = Object.fromEntries(Object.keys(TASKS).map((t) => { const w = winnerFor(t, R.job.results); return [t, w ? w.algorithm : null]; }));
      const hist = store.get("aacp-history", []);
      hist.unshift({ t: Date.now(), title: R.title, kind: R.def.kind, n: R.def.n, m: R.def.edges.length, weighted: !!R.def.weights,
        picks: R.picks, winners, objective: R.job.best ? R.job.best.objective : null,
        def: R.def.n <= 150 ? { ...R.def, layout: st.nodes.map((nd) => [(nd.x - 40) / 920, (nd.y - 30) / 620]) } : null });
      store.set("aacp-history", hist.slice(0, 15));
      renderHistory();
    }
  }
  function showSolution(alg, sol) {
    const r = st.race && st.race.job.results.find((x) => x.algorithm === alg);
    const solution = sol || (r && r.solution);
    if (!solution) return;
    if (st.race.version !== st.version) { toast("The problem changed since this race; re-run it to see current solutions."); return; }
    st.shown = { alg, set: new Set(solution) };
    draw(); renderRace();
    const k = st.race.def.kind, wsum = solution.reduce((s, v) => s + (st.weighted ? st.nodes[v].w : 1), 0);
    $("#coverNote").innerHTML = `Showing <b>${alg}</b>'s solution: <b>${solution.length}</b> vertices ${SOL_WORD[k]}${st.weighted ? `, total ${SENSE_WORD[k][1]} <b>${fmtVal(wsum)}</b>` : ""}${r && r.proved ? ", proved optimal" : ""}. ${k === "clique" ? "Highlighted edges form the clique." : k === "vertex_cover" ? "Dark edges are covered." : ""}`;
  }
  function renderSolution() {
    const R = st.race, box = $("#solutionBody");
    if (!R || !R.job.best) { box.innerHTML = `<p class="muted">${R && R.job.status === "cancelled" ? "The race was cancelled before any solution was found." : "Race the portfolio to get a verified solution."}</p>`; return; }
    const b = R.job.best, k = R.def.kind, sw = SENSE_WORD[k], labels = R.def.labels;
    const metric = R.def.weights ? sw[1] : sw[2];
    const names = b.solution.map((v) => labels[v]);
    const shownNames = names.slice(0, 60).map((x) => `<span class="schip">${esc(x)}</span>`).join("") + (names.length > 60 ? `<span class="schip more">+${names.length - 60} more</span>` : "");
    const by = R.job.results.find((r) => r.algorithm === b.algorithm);
    box.innerHTML = `<div class="sol-head"><div><div class="pick-label">${sw[0]} ${metric}</div><div class="sol-val">${fmtVal(b.objective)}</div></div>
        <div class="sol-badges"><span class="badge ${b.certified ? "good" : "warn"}">${b.certified ? "✓ certified optimal" : "best found, not certified"}</span><span class="badge good">✓ verified feasible</span></div></div>
      <p class="tiny muted">${b.size} vertices ${SOL_WORD[k]}, found by <b>${b.algorithm}</b> in ${fmtMs(by.time_ms)}. Verification rechecks every edge and constraint on the original problem, not the kernel.</p>
      <div class="schips">${shownNames || '<span class="muted">(empty set)</span>'}</div>
      <div class="row wrap">
        <button class="btn ghost" id="solShow">Show on graph</button>
        <button class="btn ghost" id="solCopy">Copy names</button>
        <button class="btn ghost" id="solJson">Download report (.json)</button>
        <button class="btn ghost" id="solCsv">Race table (.csv)</button>
      </div>`;
    $("#solShow").onclick = () => showSolution(b.algorithm, b.solution);
    $("#solCopy").onclick = async () => { try { await navigator.clipboard.writeText(names.join("\n")); toast("Copied " + names.length + " names"); } catch (_) { toast("Clipboard not available in this browser", "err"); } };
    $("#solJson").onclick = () => download(slug(R.title) + "-solution.json", JSON.stringify({ problem: { title: R.title, ...R.def }, reduction: R.job.reduction, best: { ...b, labels: names }, race: R.job.results.map(({ solution, ...rest }) => rest), live_picks: R.picks }, null, 1));
    $("#solCsv").onclick = () => {
      const rows = [["algorithm", "status", "time_ms", "objective", "size", "proved", "feasible"]].concat(R.job.results.map((r) => [r.algorithm, r.status, r.time_ms.toFixed(3), r.objective ?? "", r.size ?? "", !!r.proved, r.feasible ?? ""]));
      download(slug(R.title) + "-race.csv", rows.map((r) => r.join(",")).join("\n"), "text/csv");
    };
  }
  function renderHistory() {
    const hist = store.get("aacp-history", []), t = $("#histTable");
    if (!hist.length) { t.innerHTML = `<tr><td class="muted">Races you run are listed here, so you can see how often the live pick wins.</td></tr>`; $("#histScore").textContent = ""; return; }
    const scored = hist.filter((h) => h.picks[st.task] && h.winners[st.task]);
    const hits = scored.filter((h) => h.picks[st.task] === h.winners[st.task]).length;
    $("#histScore").innerHTML = scored.length ? `The live pick won <b>${hits} of ${scored.length}</b> recent races for “${TASKS[st.task].label}”.` : "";
    t.innerHTML = `<tr><th>problem</th><th>n / m</th><th>pick</th><th>winner</th><th></th><th></th></tr>` + hist.map((h, i) => {
      const p = h.picks[st.task], w = h.winners[st.task], ok = p && w && p === w;
      return `<tr><td>${esc(h.title)}<span class="muted"> · ${esc(st.meta.kinds[h.kind].label)}${h.weighted ? " · w" : ""}</span></td><td class="mono">${h.n} / ${h.m}</td>
        <td style="color:${p ? algoColor(p) : "inherit"}">${p || "—"}</td><td style="color:${w ? algoColor(w) : "inherit"}">${w || "—"}</td><td>${p && w ? (ok ? '<span class="okc">✓</span>' : '<span class="badc">✗</span>') : ""}</td>
        <td>${h.def ? `<button class="btn ghost tiny-btn" data-h="${i}">Load</button>` : ""}</td></tr>`;
    }).join("");
    $$("button[data-h]", t).forEach((b) => (b.onclick = () => { const h = hist[+b.dataset.h]; loadDefinition(h.def, { title: h.title }); }));
  }

  // ----------------------------------------------------------------- init
  function init(meta) {
    st.meta = meta;
    initCanvas(); initControls();
    changed(false); renderHistory();
    window.addEventListener("aacp:analysis", renderHistory);
    // a friendly start: the patch-plan scenario shows costs, constraints and reductions at once
    const first = meta.scenarios.find((s) => s.id === "patching");
    if (first) { st.quietLoad = true; $("#scenario").value = first.id; $("#scenario").dispatchEvent(new Event("change")); }
  }
  window.Studio = { init, trace: (task) => (st.analysis && !st.analysis.trivial ? st.analysis.tasks[task].tree : null), state: st };
})();
