/* Shared vocabulary and helpers for the AACP demo (window.AACP). */
(() => {
  "use strict";
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  const ALGO_NAMES = {
    td_dp: "Tree-decomposition DP", bnb: "Branch & bound", ilp: "Integer LP",
    greedy: "Greedy (deg / cost)", matching: "Matching / local ratio", lp_round: "LP rounding",
    nt_flow: "König / NT max-flow",
  };
  const TASKS = {
    certified: { label: "Prove optimal", desc: "Minimise the time until an optimal solution is <b>certified</b>. Timeouts and uncertified answers pay a 10× penalty (PAR10)." },
    optimum: { label: "Fastest optimum", desc: "Minimise the time until the solution <b>is</b> optimal, proven or not. A lucky heuristic can win." },
    budgeted: { label: "Best in 50 ms", desc: "Hard real-time budget: the <b>best solution</b> that finishes within 50 ms." },
  };
  const FEATURES = {
    n: ["Vertices", "Instance size n (of the kernel)."],
    m: ["Edges", "Instance size m (of the kernel)."],
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
  const FAM_COLORS = { er: "#4e79a7", ba: "#f28e2b", ws: "#59a14f", plc: "#e15759", rgg: "#76b7b2", ktree: "#d4b03a", bipartite: "#b07aa1", sbm: "#ff9da7", trap: "#9c755f" };
  const FAM_NAMES = { er: "Erdős–Rényi", ba: "Barabási–Albert", ws: "Watts–Strogatz", plc: "Holme–Kim", rgg: "geometric", ktree: "k-tree", bipartite: "bipartite", sbm: "block model", trap: "greedy trap" };
  const algoColor = (a) => `var(--a-${a})`;
  const fmtMs = (ms) => ms == null ? "—" : ms < 1 ? ms.toFixed(2) + " ms" : ms < 100 ? ms.toFixed(1) + " ms" : ms < 10000 ? Math.round(ms) + " ms" : (ms / 1000).toFixed(1) + " s";
  const fmtNum = (v) => typeof v !== "number" ? String(v) : Number.isInteger(v) ? String(v) : Math.abs(v) >= 100 ? v.toFixed(0) : Math.abs(v) >= 10 ? v.toFixed(1) : v.toFixed(3);
  const fmtVal = (v) => Number.isInteger(v) ? String(v) : (+v.toFixed(2)).toString();

  async function api(path, body) {
    let res;
    try {
      res = await fetch(path, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {});
    } catch (_) { throw new Error("The demo server is not reachable. Is `python -m aacp serve` still running?"); }
    const data = await res.json().catch(() => ({ error: `HTTP ${res.status}` }));
    if (!res.ok || data.error) throw new Error(data.error || `HTTP ${res.status}`);
    return data;
  }
  function toast(msg, kind = "") {
    const t = $("#toast"); t.textContent = msg; t.className = "toast " + kind; t.hidden = false;
    clearTimeout(toast._t); toast._t = setTimeout(() => (t.hidden = true), 4800);
  }
  async function busy(btn, fn) {
    btn.classList.add("busy"); btn.disabled = true;
    try { return await fn(); } catch (e) { toast(e.message, "err"); } finally { btn.classList.remove("busy"); btn.disabled = false; }
  }
  function seg(container, options, current, onChange) {
    container.innerHTML = "";
    container.setAttribute("role", "radiogroup");
    for (const [val, label] of options) {
      const b = document.createElement("button");
      b.type = "button"; b.setAttribute("role", "radio"); b.textContent = label; b.dataset.val = val;
      b.setAttribute("aria-checked", String(val === current));
      b.onclick = () => { $$("button", container).forEach((x) => x.setAttribute("aria-checked", "false")); b.setAttribute("aria-checked", "true"); onChange(val); };
      container.appendChild(b);
    }
  }
  function setSeg(container, val) { $$("button", container).forEach((b) => b.setAttribute("aria-checked", String(b.dataset.val === String(val)))); }
  function download(name, text, type = "application/json") {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([text], { type }));
    a.download = name; document.body.appendChild(a); a.click();
    setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 500);
  }
  const store = {
    get(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch (_) { return d; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (_) {} },
  };

  window.AACP = { $, $$, esc, el: window.Charts.el, api, toast, busy, seg, setSeg, download, store,
    ALGO_NAMES, TASKS, FEATURES, FAM_COLORS, FAM_NAMES, algoColor, fmtMs, fmtNum, fmtVal };
})();
