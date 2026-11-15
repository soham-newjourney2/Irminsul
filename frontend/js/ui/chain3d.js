import { t } from "../i18n.js";
import { el } from "./dom.js";
import { icon } from "./nature.js";

const FACES = ["front", "back", "right", "left", "top", "bottom"];

export function chain3d(host, steps) {
  const rig = el("div", { class: "c3d__rig" });
  steps.forEach((step, i) => {
    const cube = el("div", { class: "c3d__cube" });
    cube.style.setProperty("--i", i);
    for (const face of FACES) {
      const node = el("div", { class: `c3d__face c3d__face--${face}` });
      if (face === "front") node.append(icon(step.icon), el("span", { "data-i18n": step.key, text: t(step.key) }));
      if (face === "top") node.append(el("b", { text: String(i + 1).padStart(2, "0") }));
      cube.append(node);
    }
    const slot = el("div", { class: "c3d__slot" }, cube);
    slot.style.setProperty("--i", i);
    rig.append(slot);
    if (i < steps.length - 1) {
      const link = el("div", { class: "c3d__link" });
      link.style.setProperty("--i", i);
      rig.append(link);
    }
  });
  host.replaceChildren(el("div", { class: "c3d__stage" }, rig));
  host.style.setProperty("--n", steps.length);

  host.addEventListener("pointermove", (e) => {
    const r = host.getBoundingClientRect();
    host.style.setProperty("--px", ((e.clientX - r.left) / r.width - 0.5).toFixed(3));
    host.style.setProperty("--py", ((e.clientY - r.top) / r.height - 0.5).toFixed(3));
  });
  host.addEventListener("pointerleave", () => {
    host.style.setProperty("--px", 0);
    host.style.setProperty("--py", 0);
  });
}
