/* AACP interactive demo: tabs, theme, findings, selector, trap and portfolio views.
   The Problem Studio (tab 1) lives in studio.js; shared helpers in common.js. */
(() => {
  "use strict";
  const { $, $$, el, api, toast, seg, ALGO_NAMES, TASKS, FEATURES, FAM_COLORS, FAM_NAMES, algoColor, fmtMs, fmtNum } = window.AACP;
  const S = { meta: null, findings: null, selection: null, hiddenFams: new Set(), bnbX: "above_lp", greedyX: "assortativity", gapProto: "cv", treeTask: "certified" };

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
    const path = new Set(), sel = window.Studio.trace(S.treeTask);
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
    $("#treeNote").textContent = sel ? `Red path: the kernel of your studio problem → ${sel.choice}` : "Define a problem in the studio to trace its path.";
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
    try { S.meta = await api("/api/meta"); } catch (e) { toast("Server not reachable: " + e.message, "err"); return; }
    window.Studio.init(S.meta);
    window.addEventListener("aacp:analysis", () => { if (S.treeSvgReady) drawTree(); });
  }
  boot();
})();
