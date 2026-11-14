// Storage operator: zone readings chart with the cited safe band, manual entry, alerts.
import { api, newIdempotencyKey } from "../api.js";
import { commodity, fmtNum } from "../format.js";
import { errorMessage, fmtDateTime, t } from "../i18n.js";
import { el, errorState, field, loadingState } from "../ui/dom.js";
import { loadChart } from "../ui/chart.js";
import { mountShell } from "../ui/shell.js";
import { done, fail, input, list } from "./common.js";
import { alertCard } from "./freshtrack-ui.js";

const me = await mountShell({ role: "storage_operator" });
const root = document.getElementById("root");
let chart = null;

function profileCard(p) {
  if (!p) return el("div", { class: "alert alert--info", text: t("freshtrack.no_profile") });
  const band = p.temp_min_c != null ? `${fmtNum(p.temp_min_c, 1)}–${fmtNum(p.temp_max_c, 1)} °C` : t("freshtrack.no_temp_band");
  const rh = p.rh_min != null || p.rh_max != null ? `${p.rh_min ?? "—"}–${p.rh_max ?? "—"} % RH` : t("freshtrack.no_rh_band");
  return el(
    "div",
    { class: "card stack" },
    el("div", { class: "item__head" }, el("strong", { text: `${t("freshtrack.safe_band")}: ${p.label}` }), p.verified ? el("span", { class: "badge", dataset: { tone: "ok" }, text: t("badges.cited") }) : el("span", { class: "badge", dataset: { tone: "warn" }, text: t("badges.unverified_source") })),
    el("p", { text: `${band} · ${rh}` }),
    el("p", { class: "hint" }, `${t("guidance.source")}: `, el("a", { href: p.source.url, target: "_blank", rel: "noopener noreferrer", text: p.source.org }), p.source.pages ? ` (p. ${p.source.pages})` : "", p.source.quote ? ` — “${p.source.quote}”` : ""),
    p.verification_note ? el("p", { class: "hint", text: p.verification_note }) : null,
  );
}

async function drawChart(canvas, data) {
  const Chart = await loadChart();
  chart?.destroy();
  const labels = data.readings.map((r) => fmtDateTime(r.observed_at));
  const p = data.profile ?? {};
  const datasets = [
    { label: t("freshtrack.temp"), data: data.readings.map((r) => r.temp_c), borderWidth: 2, pointRadius: data.readings.map((r) => (r.source === "simulated" ? 1 : 3)), yAxisID: "y" },
    { label: t("freshtrack.rh"), data: data.readings.map((r) => r.rh_pct), borderWidth: 1, borderDash: [4, 3], pointRadius: 0, yAxisID: "y1" },
  ];
  if (p.temp_min_c != null) {
    datasets.push(
      { label: t("freshtrack.band_max"), data: labels.map(() => p.temp_max_c), borderWidth: 1, pointRadius: 0, borderColor: "rgba(180,35,24,.6)", fill: false, yAxisID: "y" },
      { label: t("freshtrack.band_min"), data: labels.map(() => p.temp_min_c), borderWidth: 1, pointRadius: 0, borderColor: "rgba(29,95,168,.6)", backgroundColor: "rgba(31,122,58,.10)", fill: "-1", yAxisID: "y" },
    );
  }
  chart = new Chart(canvas, {
    type: "line",
    data: { labels, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      scales: { y: { title: { display: true, text: "°C" } }, y1: { position: "right", min: 0, max: 100, grid: { drawOnChartArea: false }, title: { display: true, text: "% RH" } } },
    },
  });
}

function readingForm(zoneId, reload) {
  let key = newIdempotencyKey();
  const temp = input("temp", { type: "number", step: "0.1", inputmode: "decimal" });
  const unit = el("select", { class: "select" }, ["C", "F"].map((u) => el("option", { value: u, text: `°${u}` })));
  const rh = input("rh", { type: "number", min: "0", max: "100", step: "0.1", inputmode: "decimal" });
  const note = input("note", { maxlength: "300" });
  const form = el(
    "form",
    { class: "form-grid card" },
    el("div", { class: "inline-fields" }, field(t("freshtrack.temp"), temp), field(t("common.unit"), unit)),
    field(t("freshtrack.rh"), rh),
    field(t("common.note"), note),
    el("button", { class: "btn btn--primary span-2", type: "submit", text: t("freshtrack.add_reading") }),
  );
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    if (!temp.value && !rh.value) return fail({ code: "validation_error" });
    try {
      const { data } = await api("/freshtrack/observations", {
        method: "POST",
        idempotencyKey: key,
        body: { zone_id: zoneId, temp: temp.value ? Number(temp.value) : null, temp_unit: unit.value, rh_pct: rh.value ? Number(rh.value) : null, note: note.value || null },
      });
      key = newIdempotencyKey();
      done(data.alerts.length ? "freshtrack.reading_with_alert" : "freshtrack.reading_saved");
      form.reset();
      reload();
    } catch (err) {
      fail(err);
    }
  });
  return form;
}

async function showZone(host, zone) {
  host.replaceChildren(loadingState(t("common.loading")));
  try {
    const { data } = await api(`/freshtrack/observations?zone_id=${zone.id}&hours=24`);
    const canvas = el("canvas", { role: "img", "aria-label": t("freshtrack.chart_label", { zone: zone.name }) });
    const alertsHost = el("div");
    const reload = () => showZone(host, zone);
    host.replaceChildren(
      profileCard(data.profile),
      el("p", { class: "hint", text: data.last_reading_at ? t("freshtrack.last_reading", { time: fmtDateTime(data.last_reading_at) }) : t("freshtrack.no_readings") }),
      data.readings.length ? el("div", { class: "chart-box" }, canvas) : null,
      data.readings.some((r) => r.source === "simulated") ? el("p", { class: "hint" }, el("span", { class: "badge", dataset: { tone: "info" }, text: t("badges.simulated") }), ` ${t("freshtrack.simulated_note")}`) : null,
      el("h2", { text: t("freshtrack.manual_reading") }),
      readingForm(zone.id, reload),
      el("h2", { text: t("freshtrack.alerts") }),
      alertsHost,
    );
    if (data.readings.length) drawChart(canvas, data).catch(() => host.append(el("p", { class: "hint", text: t("prices.chart_unavailable") })));
    list(alertsHost, async () => (await api(`/freshtrack/alerts?zone_id=${zone.id}`)).data, (rows) => el("ul", { class: "item-list" }, rows.map((a) => alertCard(a, { canAct: true, reload }))), "freshtrack.no_alerts");
  } catch (err) {
    host.replaceChildren(errorState(errorMessage(err), () => showZone(host, zone), t("common.retry")));
  }
}

async function render() {
  const facilities = (await api("/storage/facilities/mine").catch(() => ({ data: [] }))).data;
  const zones = (await Promise.all(facilities.map((f) => api(`/storage/facilities/${f.id}/zones`).then((r) => r.data.map((z) => ({ ...z, facility: f.name }))).catch(() => [])))).flat();
  if (!zones.length) {
    root.replaceChildren(el("h1", { text: t("freshtrack.title") }), el("div", { class: "alert alert--info" }, t("freshtrack.need_zone"), " ", el("a", { href: "/storage/facilities.html", text: t("nav.facilities") })));
    return;
  }
  const select = el("select", { class: "select" }, zones.map((z) => el("option", { value: z.id, text: `${z.facility} · ${z.name}${z.commodity ? ` · ${commodity(z.commodity)}` : ""}` })));
  const host = el("div", { class: "stack" });
  const pick = () => showZone(host, zones.find((z) => z.id === select.value));
  select.addEventListener("change", pick);
  root.replaceChildren(el("h1", { text: t("freshtrack.title") }), el("p", { class: "muted", text: t("freshtrack.intro") }), field(t("freshtrack.zone"), select), host);
  pick();
  document.addEventListener("irminsul:ws", (ev) => {
    if (ev.detail.type === "notification" && ev.detail.data.kind.startsWith("freshtrack.")) pick();
  });
}

if (me.status === "active") {
  render();
  document.documentElement.addEventListener("langchange", render);
}
