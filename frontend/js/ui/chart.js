// Chart.js 4.4.1 from jsDelivr with SRI (hash computed from the CDN file, 2026-11-14).
import { el } from "./dom.js";

const CHART = {
  src: "https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.js",
  sri: "sha384-dug+JxfBvklEQdJ4AYuBBAIScUz0bVN73xpy273gcAwHjb3qI0fXmuYNaNfdyYJG",
};
let loading = null;

function theme(Chart) {
  const css = getComputedStyle(document.documentElement);
  Chart.defaults.color = css.getPropertyValue("--c-text-muted").trim() || "#a1ada6";
  Chart.defaults.borderColor = "rgba(255, 255, 255, 0.07)";
  Chart.defaults.font.family = css.getPropertyValue("--font-sans").trim() || "sans-serif";
  Chart.defaults.plugins.tooltip.backgroundColor = "rgba(12, 18, 15, 0.94)";
  Chart.defaults.plugins.tooltip.borderColor = "rgba(255, 255, 255, 0.12)";
  Chart.defaults.plugins.tooltip.borderWidth = 1;
  if (matchMedia("(prefers-reduced-motion: reduce)").matches) Chart.defaults.animation = false;
  return Chart;
}

export function loadChart() {
  if (window.Chart) return Promise.resolve(window.Chart);
  loading ??= new Promise((resolve, reject) => {
    const s = el("script", { src: CHART.src, integrity: CHART.sri, crossorigin: "anonymous" });
    s.addEventListener("load", () => resolve(theme(window.Chart)));
    s.addEventListener("error", () => {
      loading = null;
      reject(new Error("chart_unavailable"));
    });
    document.head.append(s);
  });
  return loading;
}
