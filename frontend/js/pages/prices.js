// Farmer: dated mandi prices, history chart (trend, not forecast), net realization.
import { api } from "../api.js";
import { commodity, fmtDate, fmtMoney, fmtPerQuintal, fmtQtyBoth, KG_PER_UNIT } from "../format.js";
import { errorMessage, t } from "../i18n.js";
import { el, errorState, field, loadingState } from "../ui/dom.js";
import { mountShell } from "../ui/shell.js";
import { districtSelect, input, list, unitSelect } from "./common.js";

const me = await mountShell({ role: "farmer" });
const root = document.getElementById("root");
const CHART = {
  src: "https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.js",
  sri: "sha384-dug+JxfBvklEQdJ4AYuBBAIScUz0bVN73xpy273gcAwHjb3qI0fXmuYNaNfdyYJG",
};
let chartLoading = null;
let chart = null;

function loadChart() {
  if (window.Chart) return Promise.resolve(window.Chart);
  chartLoading ??= new Promise((resolve, reject) => {
    const s = el("script", { src: CHART.src, integrity: CHART.sri, crossorigin: "anonymous" });
    s.addEventListener("load", () => resolve(window.Chart));
    s.addEventListener("error", () => {
      chartLoading = null;
      reject(new Error("chart_unavailable"));
    });
    document.head.append(s);
  });
  return chartLoading;
}

function freshnessBanner(meta) {
  if (!meta?.newest_arrival_date) return null;
  return el(
    "div",
    { class: "alert alert--warn" },
    el("strong", { text: t("prices.snapshot_title", { date: fmtDate(meta.newest_arrival_date) }) }),
    el("p", { text: t("prices.snapshot_body") }),
  );
}

function precisionNote(loc) {
  if (!loc?.location) return t("prices.no_position");
  return loc.precision === "district" ? t("prices.district_position") : t("prices.approx_position");
}

async function showHistory(host, crop, row) {
  host.replaceChildren(loadingState(t("common.loading")));
  try {
    const { data } = await api(`/mandi-prices/history?crop=${crop}&market_key=${encodeURIComponent(row.market_key)}&days=120`);
    const canvas = el("canvas", { "aria-label": t("prices.chart_label", { market: data.market }), role: "img" });
    host.replaceChildren(
      el("h3", { text: `${data.market} · ${data.district}` }),
      el("div", { class: "chart-box" }, canvas),
      el("p", { class: "hint", text: `${t("badges.trend")}: ${t("prices.trend_note")} · ${t("prices.aggregation")}` }),
    );
    try {
      const Chart = await loadChart();
      chart?.destroy();
      chart = new Chart(canvas, {
        type: "line",
        data: {
          labels: data.points.map((p) => p.date),
          datasets: [
            { label: t("prices.modal"), data: data.points.map((p) => p.modal_paise_per_quintal / 100), borderWidth: 2, pointRadius: 2 },
            { label: t("prices.trend_series"), data: data.points.map((p) => (p.trend_7obs_paise ?? null) && p.trend_7obs_paise / 100), borderDash: [6, 4], pointRadius: 0, borderWidth: 2 },
          ],
        },
        options: { responsive: true, maintainAspectRatio: false, interaction: { mode: "index", intersect: false }, scales: { y: { title: { display: true, text: t("prices.axis") } } } },
      });
    } catch {
      host.append(el("p", { class: "hint", text: t("prices.chart_unavailable") }));
    }
  } catch (err) {
    host.replaceChildren(errorState(errorMessage(err)));
  }
}

function pricesTable(rows, crop, chartHost) {
  return el(
    "div",
    { class: "table-wrap" },
    el(
      "table",
      { class: "table" },
      el("thead", {}, el("tr", {}, ["prices.market", "common.district", "prices.variety", "prices.modal", "prices.range", "prices.date", ""].map((k) => el("th", { class: k === "prices.modal" ? "num" : null, text: k ? t(k) : "" })))),
      el(
        "tbody",
        {},
        rows.map((r) =>
          el(
            "tr",
            {},
            el("td", { text: r.market }),
            el("td", { text: r.district }),
            el("td", { text: [r.commodity !== commodity(crop) ? r.commodity : null, r.variety].filter(Boolean).join(" · ") || "—" }),
            el("td", { class: "num", text: fmtPerQuintal(r.modal_price_paise_per_quintal) }),
            el("td", { text: `${fmtMoney(r.min_price_paise_per_quintal)}–${fmtMoney(r.max_price_paise_per_quintal)}` }),
            el("td", { text: fmtDate(r.arrival_date) }),
            el("td", {}, el("button", { class: "btn", type: "button", text: t("prices.history"), onclick: () => showHistory(chartHost, crop, r) })),
          ),
        ),
      ),
    ),
  );
}

function netForm(farms, cropSel, resultHost) {
  const farm = el("select", { class: "select" }, farms.map((f) => el("option", { value: f.id, text: `${f.name} · ${f.district}` })));
  const qty = input("qty", { type: "number", min: "0.001", step: "any", required: true });
  const unit = unitSelect({ value: "quintal" });
  const rate = input("rate", { type: "number", min: "0", step: "0.01", required: true, placeholder: t("net.rate_placeholder") });
  const fees = input("fees", { type: "number", min: "0", max: "100", step: "0.1", required: true, placeholder: "0" });
  const practical = input("practical", { type: "number", min: "1", max: "1000", step: "1", required: true });
  const form = el(
    "form",
    { class: "form-grid card" },
    el("p", { class: "span-2 hint", text: t("net.intro") }),
    field(t("sell.farm"), farm),
    el("div", { class: "inline-fields" }, field(t("common.quantity"), qty), field(t("common.unit"), unit)),
    field(t("net.rate"), rate, t("net.rate_hint")),
    field(t("net.fees"), fees, t("net.fees_hint")),
    field(t("net.practical"), practical, t("net.practical_hint")),
    el("button", { class: "btn btn--primary span-2", type: "submit", text: t("net.compare") }),
  );
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    if (!form.reportValidity()) return;
    resultHost.replaceChildren(loadingState(t("common.loading")));
    try {
      const { data, meta } = await api("/markets/net-realization", {
        method: "POST",
        body: {
          farm_id: farm.value,
          crop: cropSel.value,
          qty: qty.value,
          unit: unit.value,
          transport_rate_per_km_per_quintal: rate.value,
          fees_pct: Number(fees.value),
          practical_distance_km: Number(practical.value),
          max_markets: 5,
        },
      });
      resultHost.replaceChildren(netTable(data, meta, Number(qty.value) * KG_PER_UNIT[unit.value], unit.value));
    } catch (err) {
      resultHost.replaceChildren(errorState(errorMessage(err)));
    }
  });
  return form;
}

function netTable(rows, meta, qtyKg, unit) {
  if (!rows.length) return el("div", { class: "state", text: t("net.none") });
  const a = meta.assumptions;
  return el(
    "section",
    { class: "stack" },
    el("p", { class: "hint", text: t("net.assumptions", { qty: fmtQtyBoth(Math.round(qtyKg), unit), rate: fmtMoney(a.transport_rate_paise_per_km_per_quintal), fees: a.fees_pct, km: a.practical_distance_km }) }),
    el(
      "div",
      { class: "table-wrap" },
      el(
        "table",
        { class: "table" },
        el("thead", {}, el("tr", {}, ["prices.market", "net.distance", "prices.modal", "net.gross", "net.transport", "net.fees_col", "net.net"].map((k) => el("th", { class: k === "prices.market" ? null : "num", text: t(k) })))),
        el(
          "tbody",
          {},
          rows.map((r) =>
            el(
              "tr",
              {},
              el(
                "td",
                {},
                el("strong", { text: r.market.market }),
                el("div", { class: "hint", text: `${r.market.district} · ${fmtDate(r.market.arrival_date)} · ${precisionNote(r.market.market_location)}` }),
                r.beyond_practical_distance ? el("span", { class: "badge", dataset: { tone: "warn" }, text: t("net.too_far") }) : null,
              ),
              el("td", { class: "num" }, `${r.distance_km} km`, r.distance_source === "osrm" ? null : el("span", { class: "badge", dataset: { tone: "info" }, text: t("badges.estimate") })),
              el("td", { class: "num", text: fmtPerQuintal(r.market.modal_price_paise_per_quintal) }),
              el("td", { class: "num", text: fmtMoney(r.gross_paise) }),
              el("td", { class: "num", text: `− ${fmtMoney(r.transport_paise)}` }),
              el("td", { class: "num", text: `− ${fmtMoney(r.fees_paise)}` }),
              el("td", { class: "num" }, el("strong", { text: fmtMoney(r.net_paise) })),
            ),
          ),
        ),
      ),
    ),
    el("p", { class: "hint", text: t("net.disclaimer") }),
    el("p", { class: "hint", text: t("prices.osm_attribution") }),
  );
}

async function render() {
  const crop = el("select", { class: "select", name: "crop" }, ["potato", "tomato", "rice", "jute"].map((c) => el("option", { value: c, text: commodity(c) })));
  const district = districtSelect({ blank: "common.all_districts" });
  const banner = el("div");
  const tableHost = el("div");
  const chartHost = el("div", { class: "card stack" });
  chartHost.append(el("p", { class: "hint", text: t("prices.pick_market") }));
  const netHost = el("div", { class: "stack" });
  const farms = await api("/farms").then((r) => r.data).catch(() => []);
  const load = async () => {
    const qs = new URLSearchParams({ crop: crop.value, limit: "50", ...(district.value ? { district: district.value } : {}) });
    let meta = null;
    await list(tableHost, async () => {
      const res = await api(`/mandi-prices/latest?${qs}`);
      meta = res.meta;
      return res.data;
    }, (rows) => pricesTable(rows, crop.value, chartHost), "prices.empty");
    banner.replaceChildren(freshnessBanner(meta) ?? "");
  };
  crop.addEventListener("change", load);
  district.addEventListener("change", load);
  root.replaceChildren(
    el("h1", { text: t("prices.title") }),
    banner,
    el("div", { class: "row" }, field(t("common.crop"), crop), field(t("common.district"), district)),
    tableHost,
    chartHost,
    el("h2", { text: t("net.title") }),
    farms.length ? netForm(farms, crop, netHost) : el("div", { class: "alert alert--info" }, t("sell.need_farm"), " ", el("a", { href: "/farmer/farms.html", text: t("nav.farms") })),
    netHost,
    el("p", { class: "hint", text: t("prices.source_note") }),
  );
  load();
}

if (me.status === "active") {
  render();
  document.documentElement.addEventListener("langchange", render);
}
