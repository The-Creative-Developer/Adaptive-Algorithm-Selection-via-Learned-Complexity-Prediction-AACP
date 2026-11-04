/* Tiny dependency-free SVG chart helpers for the AACP demo. */
(function () {
  const NS = "http://www.w3.org/2000/svg";

  function el(tag, attrs = {}, parent) {
    const e = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) if (v !== undefined && v !== null) e.setAttribute(k, v);
    if (parent) parent.appendChild(e);
    return e;
  }

  function scale(d0, d1, r0, r1, log) {
    if (log) {
      const l0 = Math.log10(d0), l1 = Math.log10(d1);
      const f = (v) => r0 + ((Math.log10(Math.max(v, d0)) - l0) / (l1 - l0)) * (r1 - r0);
      f.ticks = () => {
        const out = [];
        for (let p = Math.ceil(l0); p <= Math.floor(l1); p++) out.push(Math.pow(10, p));
        return out;
      };
      return f;
    }
    const f = (v) => r0 + ((v - d0) / (d1 - d0 || 1)) * (r1 - r0);
    f.ticks = (count = 6) => {
      const span = d1 - d0, step0 = span / count;
      const mag = Math.pow(10, Math.floor(Math.log10(step0 || 1)));
      const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => span / s <= count) || mag * 10;
      const out = [];
      for (let v = Math.ceil(d0 / step) * step; v <= d1 + 1e-9; v += step) out.push(+v.toFixed(10));
      return out;
    };
    return f;
  }

  function fmtTick(v) {
    if (v === 0) return "0";
    const a = Math.abs(v);
    if (a >= 1e6) return (v / 1e6).toFixed(0) + "M";
    if (a >= 1e3) return (v / 1e3).toFixed(a >= 1e4 ? 0 : 1).replace(".0", "") + "k";
    if (a >= 1) return String(+v.toFixed(2));
    if (a >= 0.01) return String(+v.toFixed(3));
    return v.toExponential(0);
  }

  function extent(vals, log, pad = 0.05) {
    let lo = Math.min(...vals), hi = Math.max(...vals);
    if (log) {
      lo = Math.pow(10, Math.floor(Math.log10(Math.max(lo, 1e-9))));
      hi = Math.pow(10, Math.ceil(Math.log10(Math.max(hi, lo * 10))));
      return [lo, hi];
    }
    const span = hi - lo || 1;
    return [lo - span * pad, hi + span * pad];
  }

  function frame(container, height) {
    container.innerHTML = "";
    const W = 640, H = height || 360, M = { t: 14, r: 18, b: 46, l: 58 };
    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: "xMidYMid meet" }, container);
    const tip = document.createElement("div");
    tip.className = "chart-tip"; tip.hidden = true;
    container.appendChild(tip);
    return { svg, tip, W, H, M };
  }

  function axes(svg, x, y, W, H, M, opt) {
    const g = el("g", { class: "axis" }, svg);
    for (const t of y.ticks(5)) {
      const yy = y(t);
      if (yy < M.t - 1 || yy > H - M.b + 1) continue;
      el("line", { class: "gridline", x1: M.l, x2: W - M.r, y1: yy, y2: yy }, g);
      el("text", { x: M.l - 8, y: yy + 4, "text-anchor": "end" }, g).textContent = fmtTick(t);
    }
    for (const t of x.ticks(7)) {
      const xx = x(t);
      if (xx < M.l - 1 || xx > W - M.r + 1) continue;
      el("line", { x1: xx, x2: xx, y1: H - M.b, y2: H - M.b + 5 }, g);
      el("text", { x: xx, y: H - M.b + 18, "text-anchor": "middle" }, g).textContent = fmtTick(t);
    }
    el("line", { x1: M.l, x2: W - M.r, y1: H - M.b, y2: H - M.b }, g);
    el("line", { x1: M.l, x2: M.l, y1: M.t, y2: H - M.b }, g);
    el("text", { class: "axis-title", x: (M.l + W - M.r) / 2, y: H - 8, "text-anchor": "middle" }, svg).textContent = opt.xLabel || "";
    el("text", { class: "axis-title", transform: `translate(15 ${(M.t + H - M.b) / 2}) rotate(-90)`, "text-anchor": "middle" }, svg).textContent = opt.yLabel || "";
  }

  /** scatter(container, {data, x:fn, y:fn, xLog, yLog, color:fn, hollow:fn, tip:fn, hidden:fn, refs:[], xDomain, yDomain}) */
  function scatter(container, o) {
    const { svg, tip, W, H, M } = frame(container, o.height);
    const pts = o.data.filter((d) => Number.isFinite(o.x(d)) && Number.isFinite(o.y(d)) && (!o.xLog || o.x(d) > 0) && (!o.yLog || o.y(d) > 0));
    const xd = o.xDomain || extent(pts.map(o.x), o.xLog);
    const yd = o.yDomain || extent(pts.map(o.y), o.yLog);
    const x = scale(xd[0], xd[1], M.l, W - M.r, o.xLog);
    const y = scale(yd[0], yd[1], H - M.b, M.t, o.yLog);
    axes(svg, x, y, W, H, M, o);
    for (const r of o.refs || []) {
      if (r.fn) {
        const n = 60, path = [];
        for (let i = 0; i <= n; i++) {
          const xv = o.xLog ? Math.pow(10, Math.log10(xd[0]) + (i / n) * (Math.log10(xd[1]) - Math.log10(xd[0]))) : xd[0] + (i / n) * (xd[1] - xd[0]);
          const yv = r.fn(xv);
          if (!Number.isFinite(yv) || yv < yd[0] || yv > yd[1]) continue;
          path.push(`${path.length ? "L" : "M"}${x(xv).toFixed(1)},${y(yv).toFixed(1)}`);
        }
        if (path.length) el("path", { class: "refline", d: path.join(""), fill: "none" }, svg);
      } else if (r.x !== undefined) {
        el("line", { class: "refline", x1: x(r.x), x2: x(r.x), y1: M.t, y2: H - M.b }, svg);
      } else if (r.y !== undefined) {
        el("line", { class: "refline", x1: M.l, x2: W - M.r, y1: y(r.y), y2: y(r.y) }, svg);
      }
      if (r.label) el("text", { class: "reflabel", x: r.lx ?? (r.x !== undefined ? x(r.x) + 6 : W - M.r - 4), y: r.ly ?? (r.y !== undefined ? y(r.y) - 6 : M.t + 14), "text-anchor": r.x !== undefined ? "start" : "end" }, svg).textContent = r.label;
    }
    const cid = "clip" + Math.random().toString(36).slice(2, 8);
    const cp = el("clipPath", { id: cid }, el("defs", {}, svg));
    el("rect", { x: M.l - 6, y: M.t - 6, width: W - M.l - M.r + 12, height: H - M.t - M.b + 12 }, cp);
    const g = el("g", { "clip-path": `url(#${cid})` }, svg);
    for (const d of pts) {
      const c = el("circle", { class: "pt" + (o.hollow && o.hollow(d) ? " hollow" : ""), cx: x(o.x(d)).toFixed(1), cy: y(o.y(d)).toFixed(1), r: o.r || 3.6, fill: o.color(d), stroke: o.hollow && o.hollow(d) ? o.color(d) : undefined, "fill-opacity": 0.78 }, g);
      if (o.hollow && o.hollow(d)) c.style.stroke = o.color(d);  // CSS would otherwise win over the attribute
      if (o.hidden && o.hidden(d)) c.style.opacity = 0.04;
      c.addEventListener("mouseenter", () => {
        tip.innerHTML = o.tip ? o.tip(d) : "";
        tip.hidden = false;
        const rect = container.getBoundingClientRect(), b = c.getBoundingClientRect();
        tip.style.left = b.left - rect.left + b.width / 2 + "px";
        tip.style.top = b.top - rect.top + "px";
      });
      c.addEventListener("mouseleave", () => (tip.hidden = true));
    }
    return { x, y };
  }

  /** hbars(container, {groups:[{label, items:[{label,value,color}]}], domain:[lo,hi], marks:[{v,label}]}) */
  function hbars(container, o) {
    container.innerHTML = "";
    const rowH = 19, gap = 14, labelW = 128, W = 640;
    const nRows = o.groups.reduce((s, g) => s + g.items.length, 0);
    const H = 30 + nRows * rowH + o.groups.length * (gap + 20) + 26;
    const svg = el("svg", { viewBox: `0 0 ${W} ${H}` }, container);
    const [lo, hi] = o.domain;
    const x = scale(lo, hi, labelW + 10, W - 70);
    const ax = el("g", { class: "axis" }, svg);
    for (const t of x.ticks(6)) {
      el("line", { class: "gridline", x1: x(t), x2: x(t), y1: 20, y2: H - 22 }, ax);
      el("text", { x: x(t), y: H - 6, "text-anchor": "middle" }, ax).textContent = fmtTick(t);
    }
    for (const m of o.marks || []) {
      el("line", { class: "refline", x1: x(m.v), x2: x(m.v), y1: 14, y2: H - 22 }, svg);
      el("text", { class: "reflabel", x: x(m.v), y: 12, "text-anchor": "middle" }, svg).textContent = m.label;
    }
    let yy = 26;
    o.groups.forEach((grp) => {
      el("text", { class: "axis-title", x: 0, y: yy + 12, style: "font-family: 'Fraunces', serif; font-size: 14px; fill: var(--ink)" }, svg).textContent = grp.label;
      yy += 20;
      grp.items.forEach((it, i) => {
        const v = Math.max(lo, Math.min(hi, it.value ?? 0));
        const x0 = x(Math.max(0, lo)), x1 = x(v);
        el("text", { x: labelW, y: yy + 13, "text-anchor": "end", style: "font: 11.5px 'IBM Plex Mono', monospace; fill: var(--ink-2)" }, svg).textContent = it.label;
        const r = el("rect", { x: Math.min(x0, x1), y: yy + 3, width: 0, height: rowH - 6, rx: 3, fill: it.color, opacity: it.value < 0 ? 0.45 : 0.9 }, svg);
        requestAnimationFrame(() => setTimeout(() => {
          r.style.transition = "width .8s cubic-bezier(.2,.8,.2,1), x .8s cubic-bezier(.2,.8,.2,1)";
          r.setAttribute("width", Math.abs(x1 - x0));
        }, 30 + i * 40));
        const txt = it.value == null ? "n/a" : (it.value < lo ? "≪ " : "") + it.value.toFixed(2);
        el("text", { x: Math.max(x0, x1) + 6, y: yy + 13, style: "font: 11.5px 'IBM Plex Mono', monospace; fill: var(--ink)" }, svg).textContent = txt;
        yy += rowH;
      });
      yy += gap;
    });
  }

  window.Charts = { scatter, hbars, el, fmtTick };
})();
