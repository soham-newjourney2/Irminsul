const TAU = Math.PI * 2;

function rng(seed) {
  return () => {
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const norm = (v) => {
  const l = Math.hypot(v[0], v[1], v[2]) || 1;
  return [v[0] / l, v[1] / l, v[2] / l];
};

function grow(seed) {
  const R = rng(seed);
  const pts = [];
  const add = (x, y, z, kind, size) => pts.push({ x, y, z, kind, size, ph: R() * TAU });

  function branch(p, dir, len, depth) {
    const end = [p[0] + dir[0] * len, p[1] + dir[1] * len, p[2] + dir[2] * len];
    const steps = Math.max(2, Math.round(len * (depth < 2 ? 46 : 26)));
    for (let i = 0; i < steps; i++) {
      const t = i / steps;
      const w = (depth < 1 ? 0.05 : 0.02) * (1 - t * 0.5);
      add(p[0] + (end[0] - p[0]) * t + (R() - 0.5) * w, p[1] + (end[1] - p[1]) * t, p[2] + (end[2] - p[2]) * t + (R() - 0.5) * w, "bark", 1.4 - depth * 0.15);
    }
    if (depth >= 5) {
      for (let k = 0; k < 16; k++) add(end[0] + (R() - 0.5) * 0.2, end[1] + (R() - 0.4) * 0.15, end[2] + (R() - 0.5) * 0.2, R() > 0.88 ? "spark" : "leaf", 0.6 + R() * 0.8);
      return;
    }
    const kids = depth === 0 ? 3 : R() < 0.4 ? 3 : 2;
    for (let k = 0; k < kids; k++) {
      const v = [R() - 0.5, R() - 0.5, R() - 0.5];
      const dot = v[0] * dir[0] + v[1] * dir[1] + v[2] * dir[2];
      const perp = norm([v[0] - dir[0] * dot, v[1] - dir[1] * dot, v[2] - dir[2] * dot]);
      const tilt = 0.45 + R() * 0.45;
      const nd = norm([dir[0] * Math.cos(tilt) + perp[0] * Math.sin(tilt), dir[1] * Math.cos(tilt) + perp[1] * Math.sin(tilt) + 0.22, dir[2] * Math.cos(tilt) + perp[2] * Math.sin(tilt)]);
      branch(end, nd, len * (0.66 + R() * 0.12), depth + 1);
    }
  }

  branch([0, -1, 0], [0, 1, 0], 0.62, 0);
  for (let r = 0; r < 7; r++) {
    const a = (r / 7) * TAU + R() * 0.4;
    for (let i = 0; i < 26; i++) {
      const t = i / 26;
      add(Math.cos(a) * t * 0.7, -1 - Math.sin(t * 2.2) * 0.04, Math.sin(a) * t * 0.7, "root", 1 - t * 0.6);
    }
  }
  return pts;
}

function sprite(color) {
  const c = document.createElement("canvas");
  c.width = c.height = 32;
  const g = c.getContext("2d");
  const r = g.createRadialGradient(16, 16, 0, 16, 16, 16);
  r.addColorStop(0, color);
  r.addColorStop(0.35, color.replace(/[\d.]+\)$/, "0.45)"));
  r.addColorStop(1, color.replace(/[\d.]+\)$/, "0)"));
  g.fillStyle = r;
  g.fillRect(0, 0, 32, 32);
  return c;
}

export function tree3d(canvas, { seed = 7, scale = 1 } = {}) {
  const ctx = canvas.getContext("2d");
  if (!ctx) return () => {};
  const pts = grow(seed);
  const SPR = {
    bark: sprite("rgba(246, 218, 150, 1)"),
    root: sprite("rgba(200, 170, 110, 1)"),
    leaf: sprite("rgba(196, 248, 206, 1)"),
    spark: sprite("rgba(245, 250, 225, 1)"),
  };
  const motes = Array.from({ length: 46 }, () => ({ x: (Math.random() - 0.5) * 1.6, y: Math.random() * 1.4 - 0.2, z: (Math.random() - 0.5) * 1.6, v: 0.0001 + Math.random() * 0.00025, ph: Math.random() * TAU }));
  const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
  let w = 0;
  let h = 0;
  let dpr = 1;
  let angle = 0.6;
  let yaw = 0;
  let tilt = 0;
  let px = 0;
  let py = 0;
  let raf = 0;
  let last = 0;
  let born = 0;
  let visible = true;

  const resize = () => {
    dpr = Math.min(2, devicePixelRatio || 1);
    w = canvas.clientWidth;
    h = canvas.clientHeight;
    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);
    if (still) draw(0);
  };

  function project(x, y, z, cosA, sinA, cosT, sinT) {
    const x1 = x * cosA - z * sinA;
    const z1 = x * sinA + z * cosA;
    const y1 = y * cosT - z1 * sinT;
    const z2 = y * sinT + z1 * cosT;
    const s = (Math.min(w, h * 1.1) * 0.62 * scale) / (z2 + 3.2);
    return [w / 2 + x1 * s * 2.4, h * 0.47 - y1 * s * 2.4, s, z2];
  }

  function draw(time) {
    if (!born) born = time || 1;
    const intro = still ? 1 : Math.min(1, (time - born) / 1800);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    ctx.globalCompositeOperation = "lighter";
    const cosA = Math.cos(angle + yaw);
    const sinA = Math.sin(angle + yaw);
    const cosT = Math.cos(0.12 + tilt);
    const sinT = Math.sin(0.12 + tilt);
    for (const p of pts) {
      const [sx, sy, s, z] = project(p.x, p.y, p.z, cosA, sinA, cosT, sinT);
      const depth = Math.max(0.15, 1 - (z + 1) * 0.32);
      let a = depth * (p.kind === "leaf" ? 0.62 : p.kind === "spark" ? 1 : 0.85);
      if (p.kind !== "bark" && p.kind !== "root") a *= 0.65 + 0.35 * Math.sin(time * 0.0016 + p.ph);
      const r = p.size * s * (p.kind === "leaf" ? 0.052 : p.kind === "spark" ? 0.045 : 0.046);
      ctx.globalAlpha = Math.max(0, Math.min(1, a * intro));
      ctx.drawImage(SPR[p.kind], sx - r, sy - r, r * 2, r * 2);
    }
    for (const m of motes) {
      const y = ((m.y + time * m.v) % 1.6) - 0.3;
      const [sx, sy, s] = project(m.x + Math.sin(time * 0.0005 + m.ph) * 0.05, y, m.z, cosA, sinA, cosT, sinT);
      const fade = Math.sin(((y + 0.3) / 1.6) * Math.PI);
      ctx.globalAlpha = 0.6 * fade * intro;
      const r = s * 0.03;
      ctx.drawImage(SPR.spark, sx - r, sy - r, r * 2, r * 2);
    }
    ctx.globalAlpha = 1;
    ctx.globalCompositeOperation = "source-over";
  }

  function frame(time) {
    raf = 0;
    if (!visible || document.hidden) return;
    const dt = last ? Math.min(64, time - last) : 16;
    last = time;
    angle += dt * 0.00011;
    yaw += (px * 0.35 - yaw) * 0.04;
    tilt += (py * 0.1 - tilt) * 0.04;
    draw(time);
    raf = requestAnimationFrame(frame);
  }

  const start = () => {
    if (!raf && !still) {
      last = 0;
      raf = requestAnimationFrame(frame);
    }
  };
  const onMove = (e) => {
    const r = canvas.getBoundingClientRect();
    px = Math.max(-1, Math.min(1, ((e.clientX - r.left) / r.width - 0.5) * 2));
    py = Math.max(-1, Math.min(1, ((e.clientY - r.top) / r.height - 0.5) * 2));
  };
  const io = new IntersectionObserver(([en]) => {
    visible = en.isIntersecting;
    if (visible) start();
  });
  const ro = new ResizeObserver(resize);
  io.observe(canvas);
  ro.observe(canvas);
  addEventListener("pointermove", onMove, { passive: true });
  document.addEventListener("visibilitychange", start);
  resize();
  if (still) draw(0);
  else start();

  return () => {
    cancelAnimationFrame(raf);
    io.disconnect();
    ro.disconnect();
    removeEventListener("pointermove", onMove);
    document.removeEventListener("visibilitychange", start);
  };
}
