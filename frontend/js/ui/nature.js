const NS = "http://www.w3.org/2000/svg";

const rng = (seed) => () => {
  seed = (seed + 0x6d2b79f5) | 0;
  let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
  t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
  return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
};

function svgEl(tag, attrs, parent) {
  const node = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) if (v !== undefined) node.setAttribute(k, v);
  parent?.appendChild(node);
  return node;
}

const f = (n) => n.toFixed(1);
const op = (n) => Math.max(0, Math.min(1, n)).toFixed(2);
const mix = (a, b, t) => a.map((v, i) => Math.round(v + (b[i] - v) * t));
const rgb = (c, a = 1) => `rgb(${c[0]} ${c[1]} ${c[2]} / ${op(a)})`;
let uid = 0;

const defs = (svg) => svg.querySelector(":scope > defs") || svgEl("defs", {}, svg);

function blur(svg, sd) {
  const id = `nb${++uid}`;
  const node = svgEl("filter", { id, x: "-50%", y: "-50%", width: "200%", height: "200%" }, defs(svg));
  svgEl("feGaussianBlur", { stdDeviation: sd }, node);
  return `url(#${id})`;
}

function glow(svg, sd) {
  const id = `ng${++uid}`;
  const node = svgEl("filter", { id, x: "-150%", y: "-150%", width: "400%", height: "400%" }, defs(svg));
  svgEl("feGaussianBlur", { stdDeviation: sd, result: "b" }, node);
  const m = svgEl("feMerge", {}, node);
  svgEl("feMergeNode", { in: "b" }, m);
  svgEl("feMergeNode", { in: "SourceGraphic" }, m);
  return `url(#${id})`;
}

function grad(svg, type, stops, attrs = {}) {
  const id = `ngr${++uid}`;
  const g = svgEl(type, { id, ...attrs }, defs(svg));
  for (const [o, c, a] of stops) svgEl("stop", { offset: o, "stop-color": c, "stop-opacity": a }, g);
  return `url(#${id})`;
}

export function meadow(svg, o = {}) {
  const W = o.w || 1440;
  const H = o.h || 900;
  const R = rng(o.seed || 1);
  const L = o.light || { x: W * 0.62, y: H * 0.45 };
  const gy = o.ground || H * 0.62;
  const dens = o.density ?? 1;
  svg.replaceChildren();
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("preserveAspectRatio", o.par || "xMidYMax slice");
  const g = (x) => gy + 34 * Math.cos((x / W) * Math.PI * 1.3 + (o.phase || 0)) - 46 * Math.sin((x / W) * Math.PI);
  const bright = (x, y) => Math.max(0, 1 - Math.hypot((x - L.x) * 0.85, (y - L.y) * 1.5) / (W * 0.48));
  const DARK = [9, 22, 14];
  const MID = [40, 74, 38];
  const LIGHT = [170, 204, 110];
  const col = (b, j = 0) => {
    const t = Math.min(1, Math.max(0, Math.pow(b, 1.2) + j));
    return t < 0.5 ? mix(DARK, MID, t * 2) : mix(MID, LIGHT, (t - 0.5) * 2);
  };
  const nearLight = () => Math.min(W - 8, Math.max(8, L.x + (R() + R() + R() - 1.5) * W * 0.34));

  svgEl("rect", { width: W, height: H, fill: "#040706" }, svg);
  svgEl("ellipse", { cx: L.x, cy: L.y, rx: W * 0.5, ry: H * 0.58, fill: grad(svg, "radialGradient", [[0, "#4f8a74", 0.55], [0.45, "#1f4036", 0.35], [1, "#040706", 0]]) }, svg);

  if (o.rays) {
    const src = o.rays;
    const rays = svgEl("g", { filter: blur(svg, 12), class: "rays" }, svg);
    const lg = grad(svg, "linearGradient", [[0, "#e4f7ec", 0.2], [1, "#e4f7ec", 0]], { x1: "0.8", y1: "0", x2: "0.3", y2: "1" });
    for (let i = 0; i < 7; i++) {
      const a = src.x - 60 + R() * 120;
      const top = 20 + R() * 40;
      const tx = src.x - W * (0.28 + i * 0.07) + (R() - 0.5) * 80;
      const spread = 80 + R() * 160;
      svgEl("polygon", { points: `${f(a)},${src.y} ${f(a + top)},${src.y} ${f(tx + spread)},${H} ${f(tx)},${H}`, fill: lg, opacity: op(0.35 + R() * 0.65) }, rays);
    }
  }

  const mist = svgEl("g", { filter: blur(svg, 30), class: "mist" }, svg);
  for (let i = 0; i < 6; i++) {
    svgEl("ellipse", { cx: f(L.x + (R() - 0.5) * W * 0.6), cy: f(gy - 60 + R() * 90), rx: f(150 + R() * 260), ry: f(40 + R() * 70), fill: "#86bcaa", opacity: op(0.05 + R() * 0.09) }, mist);
  }

  let d = `M0 ${H} L0 ${f(g(0))}`;
  for (let x = 0; x <= W; x += 30) d += ` L${x} ${f(g(x))}`;
  svgEl("path", { d: `${d} L${W} ${H} Z`, fill: "#07110b" }, svg);

  const moss = svgEl("g", {}, svg);
  for (let i = 0; i < 2200 * dens; i++) {
    const x = R() * W;
    const top = g(x);
    const y = top + Math.pow(R(), 2.4) * (H - top);
    const b = bright(x, y);
    svgEl("circle", { cx: f(x), cy: f(y), r: f((1 + R() * 2.6) * (0.6 + b)), fill: rgb(col(b, (R() - 0.5) * 0.25), 0.55 + R() * 0.45) }, moss);
  }

  const grass = svgEl("g", { fill: "none", "stroke-linecap": "round" }, svg);
  for (let i = 0; i < 1700 * dens; i++) {
    const x = R() * W;
    const y = g(x) + Math.pow(R(), 1.6) * (H - g(x)) * 0.9;
    const b = bright(x, y);
    const h = (14 + R() * 70) * (0.55 + b * 0.9);
    const bend = (R() - 0.5) * 26;
    svgEl("path", { d: `M${f(x)} ${f(y)}Q${f(x + bend * 0.4)} ${f(y - h * 0.6)} ${f(x + bend)} ${f(y - h)}`, stroke: rgb(col(b, 0.05 + (R() - 0.5) * 0.2), 0.85), "stroke-width": f(0.7 + R() * 1.6) }, grass);
  }

  const flowers = svgEl("g", { class: "flowers" }, svg);
  const gl = glow(svg, 3);
  for (let i = 0; i < (o.umbels || 0); i++) {
    const x = nearLight();
    const base = g(x) + 10;
    const hgt = 140 + R() * 230;
    const top = base - hgt;
    const lean = (R() - 0.5) * 40;
    const b = Math.max(0.4, bright(x, top));
    svgEl("path", { d: `M${f(x)} ${f(base)}Q${f(x + lean * 0.3)} ${f(base - hgt / 2)} ${f(x + lean)} ${f(top)}`, stroke: "rgb(150 178 120 / .55)", "stroke-width": 1.2, fill: "none" }, flowers);
    const u = svgEl("g", { transform: `translate(${f(x + lean)} ${f(top)})`, opacity: op(0.55 + b * 0.45) }, flowers);
    const spokes = 12 + ((R() * 8) | 0);
    const r = 14 + R() * 20;
    const c = R() > 0.5 ? "#efe7b8" : "#f4f1e6";
    for (let k = 0; k < spokes; k++) {
      const a = Math.PI + (k / (spokes - 1)) * Math.PI;
      const ex = Math.cos(a) * r;
      const ey = Math.sin(a) * r * 0.55 - r * 0.1;
      svgEl("line", { x1: 0, y1: f(r * 0.5), x2: f(ex), y2: f(ey), stroke: "rgb(205 214 165 / .6)", "stroke-width": 0.6 }, u);
      for (let m = 0; m < 5; m++) svgEl("circle", { cx: f(ex + (R() - 0.5) * 4), cy: f(ey + (R() - 0.5) * 3), r: 1.1, fill: c }, u);
    }
  }

  for (let i = 0; i < (o.daisies ?? 40); i++) {
    const x = nearLight();
    const base = g(x) + R() * 30;
    const stem = 14 + R() * 80;
    const y = base - stem;
    const b = bright(x, y);
    const s = 2.5 + R() * 5.5 * (0.6 + b);
    svgEl("path", { d: `M${f(x)} ${f(base)}Q${f(x + (R() - 0.5) * 10)} ${f(base - stem / 2)} ${f(x)} ${f(y)}`, stroke: rgb(col(b * 0.8)), "stroke-width": 1, fill: "none" }, flowers);
    const head = svgEl("g", { transform: `translate(${f(x)} ${f(y)})`, opacity: op(0.35 + b * 0.65), filter: b > 0.55 ? gl : undefined }, flowers);
    for (let k = 0; k < 10; k++) svgEl("ellipse", { cx: 0, cy: f(-s * 0.55), rx: f(s * 0.22), ry: f(s * 0.55), fill: "#eef2e4", transform: `rotate(${k * 36})` }, head);
    svgEl("circle", { r: f(s * 0.28), fill: "#e8c25a" }, head);
  }

  const tiny = ["#e9b949", "#f3efe0", "#8d8fe0", "#d9805a", "#e9b949"];
  for (let i = 0; i < (o.tiny ?? 120); i++) {
    const x = nearLight();
    const y = g(x) - R() * 60 + 24;
    svgEl("circle", { cx: f(x), cy: f(y), r: f(1.4 + R() * 2.4), fill: tiny[(R() * tiny.length) | 0], opacity: op(0.3 + bright(x, y) * 0.7) }, flowers);
  }

  for (const [px, py, pr] of o.puffs || []) {
    const base = g(px) + 12;
    svgEl("path", { d: `M${f(px)} ${f(base)}Q${f(px + 10)} ${f((base + py) / 2)} ${f(px)} ${f(py)}`, stroke: "rgb(150 172 140 / .5)", "stroke-width": 1, fill: "none" }, flowers);
    const p = svgEl("g", { transform: `translate(${f(px)} ${f(py)})`, opacity: 0.8 }, flowers);
    for (let k = 0; k < 52; k++) {
      const a = R() * Math.PI * 2;
      const r = pr * (0.7 + R() * 0.3);
      const x2 = Math.cos(a) * r;
      const y2 = Math.sin(a) * r;
      svgEl("line", { x1: 0, y1: 0, x2: f(x2), y2: f(y2), stroke: "rgb(235 240 230 / .4)", "stroke-width": 0.6 }, p);
      svgEl("circle", { cx: f(x2), cy: f(y2), r: 1.2, fill: "rgb(246 248 240 / .75)" }, p);
    }
    svgEl("circle", { r: 3, fill: "rgb(220 226 210 / .6)" }, p);
  }

  const ff = svgEl("g", {}, svg);
  for (let i = 0; i < (o.fireflies ?? 70); i++) {
    const dot = svgEl("circle", { class: "ff", cx: f(L.x + (R() - 0.5) * W * 0.9), cy: f(R() * (gy - 40)), r: f(0.6 + R() * 1.5), fill: R() > 0.3 ? "#f2f6ea" : "#cfe7a0" }, ff);
    dot.style.animationDelay = `${(-R() * 6).toFixed(2)}s`;
    dot.style.animationDuration = `${(3 + R() * 4).toFixed(1)}s`;
  }
  svgEl("rect", { width: W, height: H, fill: grad(svg, "radialGradient", [[0.5, "#000", 0], [1, "#000", 0.7]], { cx: "0.55", cy: "0.45", r: "0.75" }) }, svg);
}

const leafPath = (x0, y0, ang, len, wid) => {
  const c = Math.cos(ang);
  const s = Math.sin(ang);
  const tx = x0 + c * len;
  const ty = y0 + s * len;
  const mx = x0 + c * len * 0.5;
  const my = y0 + s * len * 0.5;
  const nx = -s * wid;
  const ny = c * wid;
  return `M${f(x0)} ${f(y0)}Q${f(mx + nx)} ${f(my + ny)} ${f(tx)} ${f(ty)}Q${f(mx - nx)} ${f(my - ny)} ${f(x0)} ${f(y0)}Z`;
};

export function fern(svg, o) {
  const W = o.w || 1440;
  const H = o.h || 900;
  svg.replaceChildren();
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("preserveAspectRatio", o.par || "xMidYMid slice");
  if (o.bg) svgEl("rect", { width: W, height: H, fill: o.bg }, svg);
  for (const fr of o.fronds) {
    const N = 42;
    const step = fr.len / N;
    const pts = [];
    let x = fr.x;
    let y = fr.y;
    let a = fr.angle;
    for (let i = 0; i <= N; i++) {
      pts.push([x, y, a]);
      x += Math.cos(a) * step;
      y += Math.sin(a) * step;
      a += fr.curl / N;
    }
    let d = "";
    for (let i = 3; i < N; i++) {
      const t = i / N;
      const [px, py, pa] = pts[i];
      const lp = fr.len * 0.27 * Math.pow(1 - t, 0.85) * (0.45 + 0.55 * Math.sin((Math.min(1, t * 2.2) * Math.PI) / 2));
      for (const side of [-1, 1]) {
        const b = pa + side * (Math.PI / 2 - 0.5);
        const k = Math.max(3, Math.round(lp / 11));
        d += leafPath(px, py, b, lp, lp * 0.12);
        for (let j = 0; j < k; j++) {
          const u = (j + 0.5) / k;
          const qx = px + Math.cos(b) * lp * u;
          const qy = py + Math.sin(b) * lp * u;
          const s = Math.max(1.8, lp * 0.27 * (1 - u * 0.7));
          d += leafPath(qx, qy, b + 0.8, s, s * 0.5) + leafPath(qx, qy, b - 0.8, s, s * 0.5);
        }
      }
    }
    const end = pts[N];
    const fill = grad(svg, "linearGradient", [[0, fr.c1 || "#14301c", 1], [0.6, fr.c2 || "#3f6f35", 1], [1, fr.c3 || "#7ea457", 1]], { gradientUnits: "userSpaceOnUse", x1: f(fr.x), y1: f(fr.y), x2: f(end[0]), y2: f(end[1]) });
    const grp = svgEl("g", { opacity: fr.op ?? 1, filter: fr.blur ? blur(svg, fr.blur) : undefined, class: fr.sway ? "sway" : undefined }, svg);
    svgEl("path", { d, fill }, grp);
    svgEl("path", { d: `M${pts.map((p) => `${f(p[0])} ${f(p[1])}`).join("L")}`, stroke: fill, "stroke-width": f(Math.max(1.5, fr.len / 170)), fill: "none", "stroke-linecap": "round" }, grp);
  }
}

export function leaves(svg, o) {
  const W = o.w || 1440;
  const H = o.h || 900;
  svg.replaceChildren();
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("preserveAspectRatio", "xMidYMid slice");
  for (const lf of o.items) {
    const fill = grad(svg, "linearGradient", [[0, lf.c1 || "#16291e", 1], [1, lf.c2 || "#3f6a4a", 1]], { x1: "0", y1: "0", x2: "1", y2: "1" });
    const grp = svgEl("g", { opacity: lf.op ?? 0.8, filter: lf.blur ? blur(svg, lf.blur) : undefined }, svg);
    svgEl("path", { d: leafPath(lf.x, lf.y, lf.angle, lf.len, lf.len * (lf.w || 0.2)), fill }, grp);
    svgEl("path", { d: `M${f(lf.x)} ${f(lf.y)}L${f(lf.x + Math.cos(lf.angle) * lf.len)} ${f(lf.y + Math.sin(lf.angle) * lf.len)}`, stroke: "rgb(190 220 180 / .18)", "stroke-width": 2 }, grp);
  }
}

export function ambient() {
  if (document.querySelector(".ambient") || document.body.classList.contains("scene")) return;
  const svg = svgEl("svg", { class: "ambient", "aria-hidden": "true" });
  document.body.prepend(svg);
  leaves(svg, {
    items: [
      { x: 1560, y: 60, len: 620, angle: 2.5, w: 0.22, blur: 22, op: 0.5 },
      { x: -120, y: 900, len: 560, angle: -0.7, w: 0.24, blur: 26, op: 0.45 },
      { x: 1500, y: 980, len: 480, angle: 3.7, w: 0.2, blur: 30, op: 0.35 },
    ],
  });
}

export function paintScene(svg) {
  meadow(svg, { seed: 17, light: { x: 980, y: 430 }, ground: 600, density: 0.6, daisies: 30, tiny: 90, fireflies: 60, rays: { x: 1040, y: -80 } });
}

const ICONS = {
  "arrow-ur": "M7 17L17 7M9 7h8v8",
  "arrow-r": "M5 12h14M13 6l6 6-6 6",
  "arrow-l": "M19 12H5M11 6l-6 6 6 6",
  link: "M10 14a4 4 0 0 0 5.66 0l3-3a4 4 0 0 0-5.66-5.66l-1 1M14 10a4 4 0 0 0-5.66 0l-3 3a4 4 0 0 0 5.66 5.66l1-1",
  snow: "M12 3v18M4.2 7.5l15.6 9M4.2 16.5l15.6-9M9.5 4.5L12 7l2.5-2.5M9.5 19.5L12 17l2.5 2.5",
  sprout: "M12 21v-9M12 12c-4 0-6-3-6-7 4 0 6 3 6 7zM12 14c0-4 2.5-6.5 6.5-6.5 0 4-2.5 6.5-6.5 6.5z",
  wave: "M3 15c2.5-2 4.5-2 7 0s4.5 2 7 0 3-1.5 4-1.5M3 19.5c2.5-2 4.5-2 7 0s4.5 2 7 0 3-1.5 4-1.5M12 3v7M9.5 7.5L12 10l2.5-2.5",
  harvest: "M5 20h14M7 20c0-6 2-10 5-13 3 3 5 7 5 13M12 7V3",
  store: "M3 10l9-6 9 6v10H3zM8 20v-6h8v6",
  check: "M5 12l4.5 4.5L19 7",
  split: "M12 21v-7M12 14L6 7M12 14l6-7M4 4h4v4M20 4h-4v4",
  therm: "M10 14V5a2 2 0 0 1 4 0v9a4 4 0 1 1-4 0zM12 14v3",
  shield: "M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6zM8.5 12l2.5 2.5 4.5-5",
  sigil: "M12 22V7M12 15l-4.5-3.5M12 12l4.5-3.5M12 9l-3-3M12 9l3-3M12 22c-2.5 0-4 .6-5.5.6M12 22c2.5 0 4 .6 5.5.6M12 2.5a9 9 0 1 0 .01 0",
};

export function sprite() {
  if (document.getElementById("nature-sprite")) return;
  const s = svgEl("svg", { id: "nature-sprite", width: 0, height: 0, "aria-hidden": "true", class: "sr-only" });
  const d = svgEl("defs", {}, s);
  for (const [k, path] of Object.entries(ICONS)) {
    const sym = svgEl("symbol", { id: `i-${k}`, viewBox: "0 0 24 24" }, d);
    svgEl("path", { d: path, fill: "none", stroke: "currentColor", "stroke-width": 1.6, "stroke-linecap": "round", "stroke-linejoin": "round" }, sym);
  }
  document.body.prepend(s);
}

export function icon(name, cls = "i") {
  const s = svgEl("svg", { class: cls, "aria-hidden": "true", focusable: "false" });
  svgEl("use", { href: `#i-${name}` }, s);
  return s;
}
