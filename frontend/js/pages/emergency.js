// Emergency coordination: simulated flood scenario, exposure map, relocation proposals.
import { api } from "../api.js";
import { commodity, fmtMoney, fmtNum, fmtQty } from "../format.js";
import { errorMessage, fmtDateTime, t } from "../i18n.js";
import { actionButton, el, errorState, field, loadingState } from "../ui/dom.js";
import { createMap } from "../ui/map.js";
import { mountShell } from "../ui/shell.js";
import { done, fail, input } from "./common.js";

const me = await mountShell({});
const root = document.getElementById("root");
const canConfirm = me.role === "storage_operator" || me.role === "admin";

function plotMap(ctx, exp, plans, rain) {
  const { L, map } = ctx;
  const ring = exp.event.geometry.coordinates[0].map(([lng, lat]) => [lat, lng]);
  const poly = L.polygon(ring, { color: "#b42318", weight: 2, fillOpacity: 0.15, dashArray: "6 4" }).addTo(map);
  poly.bindPopup(el("div", {}, el("strong", { text: exp.event.name }), el("br"), t("emergency.simulated_label")));
  const pts = [];
  for (const f of exp.farms) {
    L.circleMarker([f.location.lat, f.location.lng], { radius: 7, color: "#2f6b3a", fillOpacity: 0.8 }).addTo(map).bindPopup(el("div", { text: `${t("emergency.farm")}: ${f.name}` }));
    pts.push([f.location.lat, f.location.lng]);
  }
  for (const f of exp.facilities) {
    L.circleMarker([f.location.lat, f.location.lng], { radius: 9, color: "#b42318", fillOpacity: 0.8 }).addTo(map).bindPopup(el("div", { text: `${t("emergency.exposed_store")}: ${f.name}` }));
    pts.push([f.location.lat, f.location.lng]);
  }
  const seen = new Set();
  for (const p of plans) {
    for (const o of p.options) {
      if (seen.has(o.facility_id)) continue;
      seen.add(o.facility_id);
      L.circleMarker([o.location.lat, o.location.lng], { radius: 8, color: "#1d5fa8", fillOpacity: 0.7 }).addTo(map).bindPopup(el("div", { text: `${t("emergency.candidate")}: ${o.name}` }));
      pts.push([o.location.lat, o.location.lng]);
    }
  }
  for (const r of rain) {
    L.circleMarker([r.location.lat, r.location.lng], { radius: 4 + Math.min(10, r.next_3_days_mm / 20), color: "#5b7fa6", weight: 1, fillOpacity: 0.3 })
      .addTo(map)
      .bindPopup(el("div", { text: t("emergency.rain_popup", { name: r.name, mm: fmtNum(r.next_3_days_mm, 1) }) }));
  }
  map.fitBounds([...ring, ...pts], { padding: [20, 20], maxZoom: 10 });
}

function planCard(p, reload) {
  const rows = p.options.map((o) =>
    el(
      "tr",
      {},
      el("td", { text: String(o.rank) }),
      el("td", {}, el("strong", { text: o.name }), el("div", { class: "hint", text: o.district })),
      el("td", { class: "num" }, `${fmtNum(o.distance_km, 1)} km`, o.distance_source === "osrm" ? null : el("span", { class: "badge", dataset: { tone: "info" }, text: t("badges.estimate") })),
      el("td", { class: "num", text: fmtQty(o.free_kg, "tonne") }),
      el("td", { class: "num", text: o.fit_pct != null ? `${fmtNum(o.fit_pct, 0)}%` : "—" }),
      el("td", { class: "num", text: o.cost_paise != null ? fmtMoney(o.cost_paise) : "—" }),
      el(
        "td",
        {},
        canConfirm && p.status === "proposed"
          ? actionButton(
              t("emergency.confirm"),
              async () => {
                if (!confirm(t("emergency.confirm_q", { name: o.name }))) return;
                await api(`/emergencies/relocations/${p.id}/confirm`, { method: "POST", body: { facility_id: o.facility_id } });
                done("emergency.confirmed");
                reload();
              },
              { kind: "primary", onError: fail },
            )
          : null,
      ),
    ),
  );
  return el(
    "li",
    { class: "card stack" },
    el(
      "div",
      { class: "item__head" },
      el("strong", { text: `${commodity(p.commodity)} · ${fmtQty(p.qty_kg, "tonne")} · ${p.from_facility}` }),
      el("span", { class: "row" }, el("span", { class: "badge", dataset: { tone: "info" }, text: t("badges.simulated") }), el("span", { class: "badge", dataset: { tone: p.status === "confirmed" ? "ok" : p.status === "expired" ? "muted" : "warn" }, text: t(`emergency.plan_${p.status}`) })),
    ),
    el("p", { class: "hint", text: t("emergency.urgency", { n: p.urgency }) }),
    p.options.length
      ? el(
          "div",
          { class: "table-wrap" },
          el(
            "table",
            { class: "table" },
            el("thead", {}, el("tr", {}, ["#", "emergency.store", "net.distance", "emergency.free", "emergency.fit", "emergency.cost", ""].map((k) => el("th", { text: k === "#" || !k ? k : t(k) })))),
            el("tbody", {}, rows),
          ),
        )
      : el("div", { class: "alert alert--warn", text: t("emergency.no_options") }),
    p.status === "confirmed" ? el("p", { class: "contact", text: t("emergency.request_sent") }) : null,
  );
}

async function showEvent(host, ev) {
  host.replaceChildren(loadingState(t("common.loading")));
  const rate = input("rate", { type: "number", min: "0", step: "0.01", placeholder: t("net.rate_placeholder") });
  const load = async () => {
    try {
      const qs = rate.value ? `?rate_per_km_per_quintal=${encodeURIComponent(rate.value)}` : "";
      const [exp, plans, rain] = await Promise.all([
        api(`/emergencies/${ev.id}/exposure`).then((r) => r.data),
        api(`/emergencies/${ev.id}/relocations${qs}`),
        api("/aquasentinel/observations").then((r) => r.data).catch(() => []),
      ]);
      const mapEl = el("div", { class: "map" });
      const closeBtn = me.role === "admin" && ev.status === "active"
        ? actionButton(t("emergency.close"), async () => (await api(`/emergencies/${ev.id}/close`, { method: "POST" }), done("emergency.closed"), render()), { onError: fail })
        : null;
      host.replaceChildren(
        el("div", { class: "alert alert--warn" }, el("strong", { text: t("emergency.simulated_label") }), el("p", { text: exp.event.note })),
        el("p", { class: "muted", text: t("emergency.summary", { farms: exp.farms.length, stores: exp.facilities.length, lots: exp.stored_lots.length, upcoming: exp.upcoming_bookings.length, time: fmtDateTime(exp.event.created_at) }) }),
        mapEl,
        el("p", { class: "hint", text: t("emergency.legend") }),
        el("h2", { text: t("emergency.relocations") }),
        el("p", { class: "hint", text: `${plans.meta.ranking} ${plans.meta.urgency_assumption}` }),
        el("div", { class: "row" }, field(t("net.rate"), rate, plans.meta.cost), el("button", { class: "btn", type: "button", text: t("emergency.update_costs"), onclick: load })),
        plans.data.length ? el("ul", { class: "item-list" }, plans.data.map((p) => planCard(p, load))) : el("div", { class: "state", text: t("emergency.no_lots") }),
        closeBtn,
      );
      const ctx = await createMap(mapEl);
      if (ctx) plotMap(ctx, exp, plans.data, rain);
    } catch (err) {
      host.replaceChildren(errorState(errorMessage(err), load, t("common.retry")));
    }
  };
  load();
}

async function render() {
  root.replaceChildren(loadingState(t("common.loading")));
  const events = await api("/emergencies").then((r) => r.data).catch(() => []);
  if (!events.length) {
    root.replaceChildren(el("h1", { text: t("emergency.title") }), el("div", { class: "state", text: t("emergency.none") }));
    return;
  }
  const select = el("select", { class: "select" }, events.map((e) => el("option", { value: e.id, text: `${e.name} · ${t(`emergency.status_${e.status}`)} · ${fmtDateTime(e.created_at)}` })));
  const host = el("div", { class: "stack" });
  select.addEventListener("change", () => showEvent(host, events.find((e) => e.id === select.value)));
  root.replaceChildren(el("h1", { text: t("emergency.title") }), field(t("emergency.event"), select), host);
  showEvent(host, events[0]);
}

if (me.status === "active") {
  render();
  document.documentElement.addEventListener("langchange", render);
}
