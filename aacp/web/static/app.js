/* AACP interactive demo — front-end logic (vanilla JS, no build step). */
(() => {
  "use strict";
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const { el } = window.Charts;

  // ------------------------------------------------------------ vocabulary
  const ALGO_NAMES = {
    td_dp: "Tree-decomposition DP", bnb: "Branch & bound", ilp: "Integer LP",
    greedy: "Max-degree greedy", matching: "Matching 2-approx", lp_round: "LP rounding",
    nt_flow: "König / NT max-flow",
  };
  const TASKS = {
    certified: { label: "Prove optimal", desc: "Minimise the time until an optimal cover is <b>certified</b>. Timeouts and uncertified answers pay a 10× penalty (PAR10)." },
    optimum: { label: "Fastest optimum", desc: "Minimise the time until the cover <b>is</b> optimal, proven or not. A lucky heuristic can win here." },
    budgeted: { label: "Best in 50 ms", desc: "Hard real-time budget: the <b>smallest cover</b> that finishes within 50 ms." },
  };
  const FEATURES = {
    n: ["Vertices", "Instance size n."],
    m: ["Edges", "Instance size m."],
    density: ["Density", "Fraction of possible edges present."],
    avg_deg: ["Average degree", "Sparse graphs are settled by B&B's degree-0/1/2 reductions."],
    deg_cv: ["Degree variation", "High variation means hubs; greedy is safe when hubs dominate."],
    clustering: ["Clustering", "How often two neighbours are themselves adjacent. Zero for bipartite graphs."],
    assortativity: ["Assortativity", "Do high-degree vertices connect to each other? Greedy errs when they do."],
    tw_ub: ["Treewidth bound", "The DP costs O(2^tw · n), so this is its exponent."],
    lap_gap: ["Spectral gap λ₂", "Small λ₂ ⇒ sparse cuts ⇒ small separators ⇒ low treewidth (Cheeger)."],
    is_bipartite: ["Bipartite", "If yes, König's theorem makes max-flow exact."],
    deg_skew: ["Degree skew", "Asymmetry of the degree distribution."],
    bip_spec: ["Spectral bipartiteness", "2 − λ_max of the normalised Laplacian; 0 means bipartite."],
    degeneracy: ["Degeneracy", "Largest k such that a k-core exists."],
    sandwich_gap: ["Sandwich gap", "Greedy's cover over the best cheap lower bound: how much search remains."],
    lp_half_frac: ["LP half-integral share", "Share of vertices at ½ in the LP optimum; rounding pays for these."],
  };
  const SHOW_FEATURES = ["n", "m", "density", "avg_deg", "clustering", "assortativity", "deg_cv", "tw_ub", "lap_gap", "is_bipartite", "sandwich_gap", "lp_half_frac"];
  const FAM_COLORS = { er: "#4e79a7", ba: "#f28e2b", ws: "#59a14f", plc: "#e15759", rgg: "#76b7b2", ktree: "#d4b03a", bipartite: "#b07aa1", sbm: "#ff9da7", trap: "#9c755f" };
  const FAM_NAMES = { er: "Erdős–Rényi", ba: "Barabási–Albert", ws: "Watts–Strogatz", plc: "Holme–Kim", rgg: "geometric", ktree: "k-tree", bipartite: "bipartite", sbm: "block model", trap: "greedy trap" };
  const algoColor = (a) => `var(--a-${a})`;
  const fmtMs = (ms) => ms == null ? "—" : ms < 1 ? ms.toFixed(2) + " ms" : ms < 100 ? ms.toFixed(1) + " ms" : ms < 10000 ? Math.round(ms) + " ms" : (ms / 1000).toFixed(1) + " s";
  const fmtNum = (v) => typeof v !== "number" ? String(v) : Number.isInteger(v) ? String(v) : Math.abs(v) >= 100 ? v.toFixed(0) : Math.abs(v) >= 10 ? v.toFixed(1) : v.toFixed(3);

  // ----------------------------------------------------------------- state
  const S = { meta: null, graph: null, run: null, task: "certified", shown: null, findings: null, selection: null, hiddenFams: new Set(), bnbX: "above_lp", greedyX: "assortativity", gapProto: "cv", treeTask: "certified" };

  async function api(path, body) {
    const res = await fetch(path, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {});
    const data = await res.json().catch(() => ({ error: `HTTP ${res.status}` }));
    if (!res.ok || data.error) throw new Error(data.error || `HTTP ${res.status}`);
    return data;
  }
  function toast(msg) {
    const t = $("#toast"); t.textContent = msg; t.hidden = false;
    clearTimeout(toast._t); toast._t = setTimeout(() => (t.hidden = true), 4200);
  }
  async function busy(btn, fn) {
    btn.classList.add("busy"); btn.disabled = true;
    try { return await fn(); } catch (e) { toast(e.message); } finally { btn.classList.remove("busy"); btn.disabled = false; }
  }
  function seg(container, options, current, onChange) {
    container.innerHTML = "";
    container.setAttribute("role", "radiogroup");
    for (const [val, label] of options) {
      const b = document.createElement("button");
      b.type = "button"; b.setAttribute("role", "radio"); b.textContent = label;
      b.setAttribute("aria-checked", String(val === current));
      b.onclick = () => { $$("button", container).forEach((x) => x.setAttribute("aria-checked", "false")); b.setAttribute("aria-checked", "true"); onChange(val); };
      container.appendChild(b);
    }
  }

  // ------------------------------------------------------------ theme/tabs
  function initTheme() {
    let t = null;
    try { t = localStorage.getItem("aacp-theme"); } catch (_) {}
    if (!t) t = matchMedia("(prefers-color-scheme: dark)").matches ? "blueprint" : "notebook";
    document.documentElement.dataset.theme = t;
    $("#themeToggle").onclick = () => {
      const nt = document.documentElement.dataset.theme === "notebook" ? "blueprint" : "notebook";
      document.documentElement.dataset.theme = nt;
      try { localStorage.setItem("aacp-theme", nt); } catch (_) {}
    };
  }
  function initTabs() {
    const show = (name) => {
      $$(".tab").forEach((t) => t.setAttribute("aria-selected", String(t.dataset.tab === name)));
      $$(".panel").forEach((p) => p.classList.toggle("active", p.id === "tab-" + name));
      $$(`#tab-${name} .reveal`).forEach((r) => { r.style.animation = "none"; void r.offsetWidth; r.style.animation = ""; });
      if (name === "findings") loadFindings();
      if (name === "selector") loadSelector();
      if (name === "trap" && !S.trap) loadTrap();
      if (name === "portfolio") loadPortfolio();
      try { history.replaceState(null, "", "#" + name); } catch (_) {}
    };
    $$(".tab").forEach((t) => (t.onclick = () => show(t.dataset.tab)));
    const h = location.hash.slice(1);
    if (h && $(`#tab-${h}`)) show(h);
  }

  // ------------------------------------------------------------ playground
  function initPlayground() {
    const pres = $("#presets");
    for (const p of S.meta.presets) {
      const b = document.createElement("button");
      b.className = "chip"; b.textContent = p.label; b.setAttribute("aria-pressed", "false");
      b.onclick = () => busy(b, async () => {
        $$(".chip", pres).forEach((c) => c.setAttribute("aria-pressed", "false"));
        b.setAttribute("aria-pressed", "true");
        syncBuilder(p);
        setGraph(await api("/api/generate", { family: p.family, n: p.n, params: p.params, seed: +$("#seed").value || 1 }));
      });
      pres.appendChild(b);
    }
    const fam = $("#family");
    for (const [k, f] of Object.entries(S.meta.families)) fam.add(new Option(f.label, k));
    fam.onchange = () => renderParamFields(fam.value);
    $("#nRange").oninput = (e) => ($("#nOut").textContent = e.target.value);
    $("#dice").onclick = () => ($("#seed").value = Math.floor(Math.random() * 9999));
    $("#generate").onclick = (e) => busy(e.currentTarget, async () => {
      $$(".chip", pres).forEach((c) => c.setAttribute("aria-pressed", "false"));
      const params = {};
      $$("#paramFields input").forEach((i) => (params[i.dataset.key] = +i.value));
      setGraph(await api("/api/generate", { family: fam.value, n: +$("#nRange").value, params, seed: +$("#seed").value || 1 }));
    });
    $("#parse").onclick = (e) => busy(e.currentTarget, async () => {
      $$(".chip", pres).forEach((c) => c.setAttribute("aria-pressed", "false"));
      setGraph(await api("/api/parse", { text: $("#edgeText").value }));
    });
    $("#edgeFile").onchange = async (e) => {
      const f = e.target.files[0]; if (!f) return;
      $("#edgeText").value = await f.text();
      $("#paste").open = true; $("#parse").click();
    };
    renderParamFields(fam.value);
    seg($("#taskSeg"), Object.entries(TASKS).map(([k, t]) => [k, t.label]), S.task, (t) => { S.task = t; renderVerdict(); if (S.run) renderRace(); });
    $("#taskDesc").innerHTML = TASKS[S.task].desc;
    $("#runAll").onclick = (e) => busy(e.currentTarget, runAll);
  }
  function renderParamFields(fam, values = {}) {
    const box = $("#paramFields"); box.innerHTML = "";
    for (const [key, [lo, hi, def]] of Object.entries(S.meta.families[fam].params)) {
      const isInt = ["m", "k", "blocks"].includes(key);
      const v = values[key] ?? def;
      const lab = document.createElement("label"); lab.className = "field";
      lab.innerHTML = `${key} <output>${v}</output><input type="range" data-key="${key}" min="${lo}" max="${hi}" step="${isInt ? 1 : (hi - lo) / 100}" value="${v}">`;
      const inp = $("input", lab);
      inp.oninput = () => ($("output", lab).textContent = isInt ? inp.value : (+inp.value).toFixed(3));
      box.appendChild(lab);
    }
  }
  function syncBuilder(p) {
    $("#family").value = p.family; $("#nRange").value = p.n; $("#nOut").textContent = p.n;
    renderParamFields(p.family, p.params);
  }

  function setGraph(g) {
    S.graph = g; S.run = null; S.shown = null;
    $("#emptyState").hidden = true; $("#raceCard").hidden = true; $("#runAll").disabled = false;
    const src = g.source;
    const what = src.kind === "generated" ? `${S.meta.families[src.family].label}` : "Your graph";
    $("#graphCaption").innerHTML = `${what} <span class="mono">· n = ${g.n} · m = ${g.m}${src.seed != null ? ` · seed ${src.seed}` : ""}</span>`;
    $("#analysisTime").textContent = `Features + selector: ${fmtMs(g.analysis_ms)}`;
    renderFeatures(); drawGraph(); renderVerdict(); $("#coverNote").textContent = "";
    if (S.treeSvgReady) drawTree();
  }

  function renderFeatures() {
    const f = S.graph.features, used = new Set(S.graph.selection[S.task].steps.map((s) => s.feature));
    const dl = $("#featureList"); dl.innerHTML = "";
    for (const k of SHOW_FEATURES) {
      const [name, why] = FEATURES[k] || [k, ""];
      const dt = document.createElement("dt"); dt.textContent = name; dt.title = why;
      const dd = document.createElement("dd");
      dd.textContent = k === "is_bipartite" ? (f[k] ? "yes" : "no") : fmtNum(f[k]);
      if (used.has(k)) { dd.classList.add("hl"); dt.title += "  (used by the selector for this graph)"; }
      dl.append(dt, dd);
    }
  }

  // --------------------------------------------------------------- graph
  function drawGraph() {
    const g = S.graph, svg = $("#graph"); svg.innerHTML = "";
    const W = 1000, H = 680, P = { x: 40, y: 30 };
    const pos = g.layout.map(([x, y]) => [P.x + x * (W - 2 * P.x), P.y + y * (H - 2 * P.y)]);
    const r = Math.max(3.2, Math.min(9, 11 - g.n / 30));
    const adj = Array.from({ length: g.n }, () => []);
    const eg = el("g", {}, svg), vg = el("g", {}, svg);
    const lines = g.edges.map(([u, v], i) => { adj[u].push([v, i]); adj[v].push([u, i]); return el("line", { class: "e", x1: W / 2, y1: H / 2, x2: W / 2, y2: H / 2 }, eg); });
    const dots = pos.map((_, i) => el("circle", { class: "v", r, cx: W / 2, cy: H / 2, "data-i": i }, vg));
    S.gfx = { lines, dots, adj, pos };
    // entrance tween
    const t0 = performance.now(), dur = g.m > 4000 ? 0 : 750;
    const step = (now) => {
      const k = dur ? Math.min(1, (now - t0) / dur) : 1, e = 1 - Math.pow(1 - k, 3);
      const P2 = pos.map(([x, y]) => [W / 2 + (x - W / 2) * e, H / 2 + (y - H / 2) * e]);
      dots.forEach((d, i) => { d.setAttribute("cx", P2[i][0].toFixed(1)); d.setAttribute("cy", P2[i][1].toFixed(1)); });
      g.edges.forEach(([u, v], i) => { const l = lines[i]; l.setAttribute("x1", P2[u][0].toFixed(1)); l.setAttribute("y1", P2[u][1].toFixed(1)); l.setAttribute("x2", P2[v][0].toFixed(1)); l.setAttribute("y2", P2[v][1].toFixed(1)); });
      if (k < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
    const tip = $("#graphTip"), labels = g.source.labels;
    vg.addEventListener("mouseover", (ev) => {
      const i = ev.target.dataset && ev.target.dataset.i; if (i == null) return;
      svg.classList.add("dim"); dots[i].classList.add("hot");
      for (const [, ei] of adj[i]) lines[ei].classList.add("hot");
      const inCover = S.shown && S.shownSet.has(+i);
      tip.innerHTML = `${labels ? labels[i] : "v" + i} · degree ${adj[i].length}${S.shown ? (inCover ? " · in cover" : " · not in cover") : ""}`;
      const b = ev.target.getBoundingClientRect(), rr = svg.parentElement.getBoundingClientRect();
      tip.style.left = b.left - rr.left + b.width / 2 + "px"; tip.style.top = b.top - rr.top + "px"; tip.hidden = false;
    });
    vg.addEventListener("mouseout", (ev) => {
      const i = ev.target.dataset && ev.target.dataset.i; if (i == null) return;
      svg.classList.remove("dim"); dots[i].classList.remove("hot");
      for (const [, ei] of adj[i]) lines[ei].classList.remove("hot");
      tip.hidden = true;
    });
  }
  function showCover(alg) {
    const r = S.run && S.run.results.find((x) => x.algorithm === alg);
    S.shown = r && r.cover ? alg : null;
    S.shownSet = new Set(r && r.cover ? r.cover : []);
    S.gfx.dots.forEach((d, i) => d.classList.toggle("in", S.shownSet.has(i)));
    $$(".race-row").forEach((row) => row.classList.toggle("selected", row.dataset.alg === S.shown));
    $("#coverNote").innerHTML = S.shown
      ? `Showing <b>${alg}</b>'s cover: <b>${r.cover.length}</b> vertices. Every edge touches at least one highlighted vertex${r.proved ? ", and the algorithm proved no smaller cover exists" : ""}.`
      : r ? `${alg} timed out and returned no cover.` : "";
  }

  // ------------------------------------------------------------- verdict
  function renderVerdict() {
    $("#taskDesc").innerHTML = TASKS[S.task].desc;
    if (!S.graph) return;
    renderFeatures();
    const sel = S.graph.selection[S.task], a = sel.choice, info = S.meta.algorithms[a];
    const body = $("#verdictBody");
    const lc = sel.leaf_cost[a];
    const costTxt = S.task === "budgeted" ? `average ratio ${lc.toFixed(3)} × OPT` : `average PAR10 cost ${fmtMs(lc * 1000)}`;
    let html = `<div class="pick-label">The selector says run</div>
      <div class="pick" style="color:${algoColor(a)}">${a}</div>
      <div class="pick-sub"><span class="unit-badge">Unit ${info.unit}</span>${ALGO_NAMES[a]} · <span class="muted">${info.bound}</span></div>
      <div class="pick-label" style="margin-bottom:6px">Because</div><ol class="because">`;
    sel.steps.forEach((s, i) => {
      const [name, why] = FEATURES[s.feature] || [s.feature, ""];
      const op = s.left ? "≤" : ">";
      const lo = Math.min(s.value, s.threshold), hi = Math.max(s.value, s.threshold);
      const span = hi - lo || Math.abs(hi) || 1, d0 = lo - span * 0.6, d1 = hi + span * 0.6;
      const px = (v) => ((v - d0) / (d1 - d0)) * 100;
      const side = s.left ? `left:0;width:${px(s.threshold)}%` : `left:${px(s.threshold)}%;right:0`;
      html += `<li style="--i:${i}"><div class="cond">${name} <span class="mono">= ${fmtNum(s.value)} ${op} ${fmtNum(s.threshold)}</span></div>
        <div class="numline"><div class="track"></div><div class="side" style="${side}"></div><div class="thr" style="left:${px(s.threshold)}%"></div><div class="val" style="left:${px(s.value)}%"></div></div>
        <div class="why">${why}</div></li>`;
    });
    html += `<li class="leaf" style="--i:${sel.steps.length}"><div class="cond">In training, <b>${sel.leaf_n}</b> graphs landed in this leaf. Running <b>${a}</b> on them gave the lowest total cost (${costTxt}).</div></li></ol>`;
    body.innerHTML = html;
  }

  // ---------------------------------------------------------------- race
  async function runAll() {
    const g = S.graph;
    S.run = await api("/api/run", { n: g.n, edges: g.edges, budget: +$("#budget").value });
    renderRace();
  }
  function winnerFor(task, run) {
    const R = run.results;
    if (task === "certified") return R.filter((r) => r.proved).sort((a, b) => a.time_ms - b.time_ms)[0];
    if (task === "optimum") {
      const target = run.opt ?? run.best;
      return R.filter((r) => r.size === target).sort((a, b) => a.time_ms - b.time_ms)[0];
    }
    const ok = R.filter((r) => r.status === "ok" && r.time_ms <= S.meta.budget_ms);
    return ok.sort((a, b) => a.size - b.size || a.time_ms - b.time_ms)[0];
  }
  function renderRace() {
    const run = S.run, choice = S.graph.selection[S.task].choice;
    $("#raceCard").hidden = false;
    const tmin = 0.05, tmax = run.budget * 1000;
    const lx = (ms) => Math.max(0, Math.min(100, ((Math.log10(Math.max(ms, tmin)) - Math.log10(tmin)) / (Math.log10(tmax) - Math.log10(tmin))) * 100));
    const sc = $("#raceScale"); sc.innerHTML = "";
    for (let v = 0.1; v <= tmax * 1.001; v *= 10) { const s = document.createElement("span"); s.style.left = lx(v) + "%"; s.textContent = fmtMs(v); sc.appendChild(s); }
    const win = winnerFor(S.task, run);
    const list = $("#raceList"); list.innerHTML = "";
    const order = [...run.results].sort((a, b) => (a.status === "ok" ? 0 : 1) - (b.status === "ok" ? 0 : 1) || a.time_ms - b.time_ms);
    order.forEach((r, i) => {
      const li = document.createElement("li");
      li.className = "race-row"; li.dataset.alg = r.algorithm; li.style.setProperty("--i", i); li.style.setProperty("--c", algoColor(r.algorithm));
      const timeout = r.status !== "ok";
      const isOpt = r.ratio != null && Math.abs(r.ratio - 1) < 1e-9 && run.opt != null;
      li.innerHTML = `
        <div><div class="alg-name"><span class="sw"></span>${r.algorithm}${r.algorithm === choice ? ' <span class="rec-tag">PICK</span>' : ""}${win && win.algorithm === r.algorithm ? ' <span class="trophy" title="winner for this goal">★</span>' : ""}</div>
          <div class="alg-para">${ALGO_NAMES[r.algorithm]}</div></div>
        <div class="bar-track"><div class="bar${timeout ? " timeout" : ""}"></div><span class="bar-label" style="left:0">${timeout ? "timed out" : fmtMs(r.time_ms)}</span></div>
        <div class="race-stats">
          <span class="size" title="cover size">${r.size ?? "—"}</span>
          <span class="ratio${isOpt ? " opt" : ""}" title="size / optimum">${r.ratio != null ? "×" + r.ratio.toFixed(3) : ""}</span>
          <span class="stamp${r.proved ? "" : timeout ? " to" : " none"}">${r.proved ? "proved optimal" : timeout ? "timeout" : "·"}</span>
        </div>`;
      li.onclick = () => showCover(r.algorithm);
      list.appendChild(li);
      requestAnimationFrame(() => requestAnimationFrame(() => {
        const w = timeout ? 100 : lx(r.time_ms);
        $(".bar", li).style.width = w + "%"; $(".bar-label", li).style.left = w + "%";
      }));
    });
    const sumEl = $("#raceSummary");
    if (!win) sumEl.innerHTML = `<span class="bad">No algorithm met this goal within the budget.</span>`;
    else if (win.algorithm === choice) sumEl.innerHTML = `<span class="ok">✓ The selector's pick, <b>${choice}</b>, won.</span>`;
    else {
      const c = run.results.find((r) => r.algorithm === choice);
      let d = "";
      if (S.task === "budgeted") d = c.status === "ok" && c.time_ms <= S.meta.budget_ms ? `${c.size - win.size} more vertices` : "it missed the 50 ms budget";
      else d = (S.task === "certified" ? c.proved : c.size === (run.opt ?? run.best)) ? `+${fmtMs(c.time_ms - win.time_ms)} slower` : "it did not reach the goal";
      sumEl.innerHTML = `Winner: <b>${win.algorithm}</b>. The pick <b>${choice}</b> lost: ${d}.`;
    }
    showCover(S.shown && run.results.find((r) => r.algorithm === S.shown) ? S.shown : (win || run.results.find((r) => r.algorithm === choice)).algorithm);
  }

  // ------------------------------------------------------------- findings
  async function loadFindings() {
    if (!S.findings) {
      try { S.findings = await api("/api/findings"); } catch (e) { return toast("Could not load findings: " + e.message); }
      const lg = $("#famLegend");
      for (const fam of Object.keys(FAM_COLORS)) {
        const b = document.createElement("button"); b.className = "fam"; b.style.setProperty("--c", FAM_COLORS[fam]);
        b.innerHTML = `<i></i>${FAM_NAMES[fam]}`;
        b.onclick = () => { S.hiddenFams.has(fam) ? S.hiddenFams.delete(fam) : S.hiddenFams.add(fam); b.classList.toggle("off"); drawFindings(); };
        lg.appendChild(b);
      }
      seg($("#bnbX"), [["n", "x = n (size)"], ["k", "x = k (cover size)"], ["above_lp", "x = k − LP* (gap)"]], S.bnbX, (v) => { S.bnbX = v; drawFindings(); });
      seg($("#greedyX"), [["clustering", "clustering"], ["assortativity", "assortativity"], ["deg_cv", "degree variation"]], S.greedyX, (v) => { S.greedyX = v; drawFindings(); });
    }
    drawFindings();
  }
  function drawFindings() {
    const F = S.findings, hid = (d) => S.hiddenFams.has(d.family), col = (d) => FAM_COLORS[d.family];
    const rho = (v) => `<span class="rho">ρ = ${v.toFixed(2)}</span>`;
    const xl = { n: "n (vertices)", k: "k (optimal cover size)", above_lp: "k − LP* (above-LP gap)" };
    Charts.scatter($("#chartBnb"), {
      data: F.bnb.points.map((d) => ({ ...d, nodes: Math.max(1, d.nodes) })), x: (d) => d[S.bnbX], y: (d) => d.nodes, yLog: true,
      xLabel: xl[S.bnbX], yLabel: "search nodes (log)", color: col, hidden: hid,
      tip: (d) => `${FAM_NAMES[d.family]} · n=${d.n}<br>k=${d.k} · gap=${d.above_lp.toFixed(1)} · ${d.nodes} nodes`,
      refs: S.bnbX === "k" ? [{ fn: (k) => Math.pow(1.4656, k), label: "worst case 1.4656^k", lx: 150, ly: 30 }] : [],
    });
    $("#bnbRho").innerHTML = `Nodes vs n ${rho(F.bnb.rho.n)}, vs k ${rho(F.bnb.rho.k)}, vs <b>k − LP*</b> ${rho(F.bnb.rho.above_lp)}. The gap above the LP bound measures how much search is really needed. Toggle the x-axis to compare.`;
    const budgetMs = F.budget * 1000;
    Charts.scatter($("#chartIlp"), {
      data: F.ilp.points.map((d) => ({ ...d, ms: d.ok ? Math.max(d.time * 1000, 0.5) : budgetMs })),
      x: (d) => Math.max(d.gap, 0) + 0.5, xLog: true, y: (d) => d.ms, yLog: true,
      xLabel: "OPT − LP* + ½ (integrality gap, log)", yLabel: "time ms (log)", color: col, hidden: hid, hollow: (d) => !d.ok,
      tip: (d) => `${FAM_NAMES[d.family]} · n=${d.n}<br>gap ${d.gap.toFixed(1)} · ${d.ok ? fmtMs(d.time * 1000) : "timed out"}`,
      refs: [{ y: budgetMs, label: "5 s budget: hollow = timeout" }],
    });
    $("#ilpRho").innerHTML = `Time tracks the integrality gap ${rho(F.ilp.rho.gap)} far more than size ${rho(F.ilp.rho.n)}. 94% of solved ILPs close at the root node: ILP wins exactly when the LP is tight.`;
    Charts.scatter($("#chartDp"), {
      data: F.dp.points.map((d) => ({ ...d, ms: d.ok ? Math.max(d.time * 1000, 0.5) : budgetMs * 1.6, twc: Math.min(d.tw, 60) })),
      x: (d) => d.twc, y: (d) => d.ms, yLog: true, xDomain: [0, 61], yDomain: [0.5, 20000],
      xLabel: "treewidth upper bound (min-degree heuristic; ≥ 60 shown at 60)", yLabel: "time ms (log)",
      color: col, hidden: hid, hollow: (d) => !d.ok,
      tip: (d) => `${FAM_NAMES[d.family]} · tw ≤ ${d.tw}<br>${d.ok ? fmtMs(d.time * 1000) : "gave up (out of budget)"}`,
      refs: [{ x: 19.5, label: "cliff at tw = 20", ly: 250 }, { y: budgetMs * 1.6, label: "hollow row = gave up (2²³ state budget)" }],
    });
    const gl = { clustering: "clustering coefficient", assortativity: "degree assortativity", deg_cv: "degree coefficient of variation" };
    Charts.scatter($("#chartGreedy"), {
      data: F.greedy.points.map((d) => ({ ...d, yc: Math.min(d.ratio, 1.155) })), x: (d) => d[S.greedyX], y: (d) => d.yc,
      xLabel: gl[S.greedyX], yLabel: "greedy / OPT (capped at 1.155)",
      color: col, hidden: hid, yDomain: [0.99, 1.16],
      tip: (d) => `${FAM_NAMES[d.family]}<br>ratio ${d.ratio.toFixed(3)} · C=${d.clustering.toFixed(2)} · r=${d.assortativity.toFixed(2)}`,
    });
    const gr = F.greedy.rho;
    $("#greedyRho").innerHTML = `The opposite. Greedy is <b>best</b> at high clustering ${rho(gr.clustering)}; its error follows assortativity ${rho(gr.assortativity)} and degree uniformity ${rho(gr.deg_cv)}. With hubs, taking the max-degree vertex is a forced move.`;
  }

  // ------------------------------------------------------------- selector
  async function loadSelector() {
    if (!S.selection) {
      try { S.selection = await api("/api/selection"); } catch (e) { return toast(e.message); }
      seg($("#treeTaskSeg"), Object.entries(TASKS).map(([k, t]) => [k, t.label]), S.treeTask, (t) => { S.treeTask = t; drawTree(); });
      seg($("#gapProto"), [["cv", "5-fold CV"], ["lofo", "unseen families"]], S.gapProto, (p) => { S.gapProto = p; drawGap(); });
    }
    S.treeSvgReady = true;
    drawTree(); drawGap();
  }
  function drawTree() {
    const tree = S.meta.trees[S.treeTask], svg = $("#treeSvg"); svg.innerHTML = "";
    const leaves = [];
    (function walk(n, d) { n.depth = d; if (n.choice) leaves.push(n); else { walk(n.left, d + 1); walk(n.right, d + 1); } })(tree, 0);
    const maxD = Math.max(...leaves.map((l) => l.depth));
    const colW = 168, W = Math.max(940, leaves.length * colW + 40), rowH = 112, H = maxD * rowH + 100;
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    leaves.forEach((l, i) => (l.x = 20 + colW / 2 + i * ((W - 40 - colW) / Math.max(1, leaves.length - 1))));
    (function place(n) { if (!n.choice) { place(n.left); place(n.right); n.x = (n.left.x + n.right.x) / 2; } n.y = 40 + n.depth * rowH; })(tree);
    const path = new Set(), sel = S.graph ? S.graph.selection[S.treeTask] : null;
    if (sel) { sel.steps.forEach((s) => path.add(s.node)); path.add(sel.leaf); }
    const links = el("g", {}, svg), nodes = el("g", {}, svg);
    (function draw(n) {
      const on = path.has(n.id);
      if (!n.choice) {
        for (const [c, lab] of [[n.left, "yes"], [n.right, "no"]]) {
          const lit = on && path.has(c.id);
          el("path", { class: "link" + (lit ? " on" : ""), d: `M${n.x},${n.y + 22} C${n.x},${(n.y + c.y) / 2} ${c.x},${(n.y + c.y) / 2} ${c.x},${c.y - 22}` }, links);
          el("text", { class: "elabel", x: (n.x + c.x) / 2 + (c === n.left ? -10 : 10), y: (n.y + c.y) / 2, "text-anchor": c === n.left ? "end" : "start" }, links).textContent = lab;
        }
        const g = el("g", { class: "node" + (on ? " on" : "") }, nodes);
        const label = `${(FEATURES[n.feature] || [n.feature])[0]} ≤ ${fmtNum(n.threshold)}`;
        const w = Math.max(150, label.length * 7.6 + 24);
        el("rect", { class: "nbox", x: n.x - w / 2, y: n.y - 22, width: w, height: 44, rx: 9 }, g);
        el("text", { class: "ntext", x: n.x, y: n.y - 2, "text-anchor": "middle" }, g).textContent = label;
        el("text", { class: "nsub", x: n.x, y: n.y + 14, "text-anchor": "middle" }, g).textContent = `${n.n} training graphs`;
        draw(n.left); draw(n.right);
      } else {
        const g = el("g", { class: "node leaf" + (on ? " on" : ""), style: `--c:${algoColor(n.choice)}` }, nodes);
        el("rect", { class: "nbox", x: n.x - 70, y: n.y - 22, width: 140, height: 50, rx: 10 }, g);
        el("text", { class: "ntext", x: n.x, y: n.y + 1, "text-anchor": "middle", style: `fill:${algoColor(n.choice)}` }, g).textContent = n.choice;
        el("text", { class: "nsub", x: n.x, y: n.y + 18, "text-anchor": "middle" }, g).textContent = `n = ${n.n}`;
      }
    })(tree);
    $("#treeNote").textContent = sel ? `Red path: your playground graph → ${sel.choice}` : "Generate a graph in the playground to trace its path.";
  }
  function drawGap() {
    const rows = S.selection.results.filter((r) => r.features === "all" && r.protocol === S.gapProto);
    const MODELS = [["tree", "CART (accuracy)", "var(--ink-3)"], ["forest", "Forest (accuracy)", "var(--ink-3)"], ["cost_tree", "Regret tree", "var(--accent)"], ["cost_forest", "Regret forest", "var(--accent)"], ["ehm", "EHM (runtime)", "var(--a-lp_round)"]];
    const groups = Object.entries(TASKS).map(([t, info]) => ({
      label: info.label,
      items: MODELS.map(([m, lab, c]) => ({ label: lab, color: c, value: (rows.find((r) => r.task === t && r.model === m) || {}).gap_closed })),
    }));
    Charts.hbars($("#chartGap"), { groups, domain: [-1, 1], marks: [{ v: 0, label: "single best" }, { v: 1, label: "oracle" }] });
  }

  // ------------------------------------------------------------------ trap
  function initTrap() {
    const k = $("#kRange"), nz = $("#noiseRange");
    k.oninput = () => ($("#kOut").textContent = k.value);
    nz.oninput = () => ($("#noiseOut").textContent = nz.value + "%");
    k.onchange = nz.onchange = () => loadTrap();
    $("#trapPlay").onclick = () => trapPlay();
    $("#trapStep").onclick = () => { trapStop(); trapStep(); };
    $("#trapReset").onclick = () => { trapStop(); renderTrap(); };
  }
  async function loadTrap() {
    trapStop();
    try { S.trap = await api("/api/trap", { k: +$("#kRange").value, noise: +$("#noiseRange").value / 100, seed: 3 }); } catch (e) { return toast(e.message); }
    renderTrap();
  }
  function renderTrap() {
    const T = S.trap, svg = $("#trapSvg"); svg.innerHTML = "";
    const W = 1000, yR = 90, yL = 430, nR = T.R.length;
    const blocks = [...new Set(T.R.map((r) => r.block))];
    const gapPx = 6, usable = W - 80 - gapPx * (blocks.length - 1);
    const sp = usable / Math.max(nR - 1, 1), pos = {};
    let x = 40, prevB = null;
    const blockSpan = {};
    T.R.forEach((r) => {
      if (prevB !== null && r.block !== prevB) x += gapPx;
      pos[r.node] = [x, yR]; (blockSpan[r.block] ||= [x, x])[1] = x; prevB = r.block; x += sp;
    });
    const lsp = (W - 80) / Math.max(T.k - 1, 1);
    T.L.forEach((v, i) => (pos[v] = [40 + i * lsp, yL]));
    el("text", { class: "rowlabel", x: 0, y: yR - 34 }, svg).textContent = "R  (decoys)";
    el("text", { class: "rowlabel", x: 0, y: yL + 46 }, svg).textContent = "L  (the optimal cover)";
    for (const b of blocks) {
      const [a, z] = blockSpan[b];
      if (z - a > 14 || b <= 6) el("text", { class: "blabel", x: (a + z) / 2, y: yR - 14 }, svg).textContent = `R${b}`;
    }
    const r = Math.max(3, Math.min(9, 560 / (nR + 10)));
    const eg = el("g", {}, svg), vg = el("g", {}, svg);
    const inc = {};
    S.trapEdges = T.edges.map(([u, v]) => {
      const l = el("line", { class: "e", x1: pos[u][0], y1: pos[u][1], x2: pos[v][0], y2: pos[v][1] }, eg);
      (inc[u] ||= []).push(l); (inc[v] ||= []).push(l); return l;
    });
    const opt = new Set(T.opt_cover);
    S.trapDots = {};
    for (const v of Object.keys(pos)) S.trapDots[v] = el("circle", { class: "v" + (opt.has(+v) ? " opt" : ""), cx: pos[v][0], cy: pos[v][1], r: +v < T.k ? r + 2 : r }, vg);
    S.trapInc = inc; S.trapI = 0;
    $("#greedyCount").textContent = "0"; $("#optCount").textContent = T.opt_cover.length;
    $("#trapRatio").textContent = "–"; $("#ratioFill").style.width = "0";
    const max = Math.max(3.5, T.bound + 0.4);
    $("#ratioMark").style.left = `${((T.bound - 1) / (max - 1)) * 100}%`;
    S.trapMax = max;
    $("#trapBound").innerHTML = `Dashed green = an optimal cover (${T.opt_cover.length}). Tick on the bar = H(k) − 1 = ${T.bound.toFixed(2)}, the exact-trap prediction.`;
    $("#trapPlay").textContent = "▶ Play greedy";
  }
  function trapStep() {
    const T = S.trap; if (!T || S.trapI >= T.greedy_order.length) return false;
    const v = T.greedy_order[S.trapI++];
    S.trapDots[v].classList.add("in");
    for (const l of S.trapInc[v] || []) { if (!l.classList.contains("covered")) { l.classList.add("flash"); setTimeout(() => { l.classList.remove("flash"); l.classList.add("covered"); }, 260); } }
    const ratio = S.trapI / T.opt_cover.length;
    $("#greedyCount").textContent = S.trapI;
    $("#trapRatio").textContent = S.trapI === T.greedy_order.length ? "×" + T.ratio.toFixed(2) : "…";
    $("#ratioFill").style.width = `${Math.min(100, (Math.max(ratio, 1) - 1) / (S.trapMax - 1) * 100)}%`;
    return S.trapI < T.greedy_order.length;
  }
  function trapPlay() {
    if (S.trapTimer) { trapStop(); return; }
    if (!S.trap) return;
    if (S.trapI >= S.trap.greedy_order.length) renderTrap();
    const dt = Math.max(35, Math.min(380, 6500 / S.trap.greedy_order.length));
    $("#trapPlay").textContent = "❚❚ Pause";
    S.trapTimer = setInterval(() => { if (!trapStep()) trapStop(); }, dt);
  }
  function trapStop() { clearInterval(S.trapTimer); S.trapTimer = null; $("#trapPlay").textContent = "▶ Play greedy"; }

  // ------------------------------------------------------------- portfolio
  async function loadPortfolio() {
    if (!S.findings) { try { S.findings = await api("/api/findings"); } catch (e) { return toast(e.message); } }
    const grid = $("#algoGrid"); if (grid.childElementCount) return;
    S.findings.portfolio.forEach((p, i) => {
      const c = document.createElement("article");
      c.className = "card algo-card reveal"; c.style.setProperty("--c", algoColor(p.algorithm)); c.style.setProperty("--d", i);
      c.innerHTML = `<span class="unit-badge" style="color:${algoColor(p.algorithm)}">Unit ${p.unit}</span><span class="unit-badge" style="color:var(--ink-3)">${p.exact ? "exact" : "approximate"}</span>
        <h3 style="margin-top:10px">${p.algorithm}</h3><div class="para">${p.paradigm}</div>
        <div class="bound">guarantee: ${p.bound}</div>
        <div class="algo-stats">
          <div><b>${(p.solved * 100).toFixed(0)}%</b>solved in 5 s</div>
          <div><b>${fmtMs(p.median_ms)}</b>median time</div>
          <div><b>${p.exact ? "100%" : (p.optimal * 100).toFixed(0) + "%"}</b>optimal</div>
          <div><b>×${p.mean_ratio.toFixed(3)}</b>mean ratio</div>
          <div><b>×${p.max_ratio.toFixed(2)}</b>worst ratio</div>
        </div>`;
      grid.appendChild(c);
    });
  }

  // ------------------------------------------------------------------ boot
  async function boot() {
    initTheme(); initTabs(); initTrap();
    try { S.meta = await api("/api/meta"); } catch (e) { toast("Server not reachable: " + e.message); return; }
    initPlayground();
    const first = $$("#presets .chip")[3];
    if (first) first.click();
  }
  boot();
})();
