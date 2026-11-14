// Chart.js 4.4.1 from jsDelivr with SRI (hash computed from the CDN file, 2026-11-14).
import { el } from "./dom.js";

const CHART = {
  src: "https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.js",
  sri: "sha384-dug+JxfBvklEQdJ4AYuBBAIScUz0bVN73xpy273gcAwHjb3qI0fXmuYNaNfdyYJG",
};
let loading = null;

export function loadChart() {
  if (window.Chart) return Promise.resolve(window.Chart);
  loading ??= new Promise((resolve, reject) => {
    const s = el("script", { src: CHART.src, integrity: CHART.sri, crossorigin: "anonymous" });
    s.addEventListener("load", () => resolve(window.Chart));
    s.addEventListener("error", () => {
      loading = null;
      reject(new Error("chart_unavailable"));
    });
    document.head.append(s);
  });
  return loading;
}
