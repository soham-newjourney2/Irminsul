const still = () => matchMedia("(prefers-reduced-motion: reduce)").matches;

export function reveal(root = document) {
  document.documentElement.classList.add("js");
  const nodes = root.querySelectorAll(".reveal");
  if (still() || !("IntersectionObserver" in window)) {
    nodes.forEach((n) => n.classList.add("in"));
    return;
  }
  const io = new IntersectionObserver(
    (entries) => {
      for (const en of entries) {
        if (!en.isIntersecting) continue;
        en.target.classList.add("in");
        io.unobserve(en.target);
      }
    },
    { rootMargin: "0px 0px -8% 0px", threshold: 0.12 },
  );
  nodes.forEach((n) => io.observe(n));
}

export function tilt(nodes, max = 7) {
  if (still() || matchMedia("(hover: none)").matches) return;
  for (const node of nodes) {
    node.classList.add("tilt");
    node.addEventListener("pointermove", (e) => {
      const r = node.getBoundingClientRect();
      const x = (e.clientX - r.left) / r.width - 0.5;
      const y = (e.clientY - r.top) / r.height - 0.5;
      node.style.setProperty("--rx", `${(-y * max).toFixed(2)}deg`);
      node.style.setProperty("--ry", `${(x * max).toFixed(2)}deg`);
      node.style.setProperty("--gx", `${((x + 0.5) * 100).toFixed(1)}%`);
      node.style.setProperty("--gy", `${((y + 0.5) * 100).toFixed(1)}%`);
    });
    node.addEventListener("pointerleave", () => {
      node.style.setProperty("--rx", "0deg");
      node.style.setProperty("--ry", "0deg");
    });
  }
}

export function countUp(nodes) {
  for (const node of nodes) {
    const target = Number(node.dataset.count);
    if (!Number.isFinite(target) || still()) {
      node.textContent = String(target);
      continue;
    }
    node.textContent = "0";
    const io = new IntersectionObserver(([en]) => {
      if (!en.isIntersecting) return;
      io.disconnect();
      const t0 = performance.now();
      const step = (now) => {
        const k = Math.min(1, (now - t0) / 1100);
        node.textContent = String(Math.round(target * (1 - Math.pow(1 - k, 3))));
        if (k < 1) requestAnimationFrame(step);
      };
      requestAnimationFrame(step);
    });
    io.observe(node);
  }
}
