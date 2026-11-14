// Farmer: discover cold storage on a map, request bookings, track them.
import { api } from "../api.js";
import { commodity, demoBadge, todayISO } from "../format.js";
import { t } from "../i18n.js";
import { el, field } from "../ui/dom.js";
import { createMap } from "../ui/map.js";
import { mountShell } from "../ui/shell.js";
import { commoditySelect, done, fail, list, newIdempotencyKey } from "./common.js";
import { bookingCard, capacityMeter, datesForm, liveMeters } from "./facility-ui.js";
import { batchSelect } from "./chain-ui.js";
import { alertCard } from "./freshtrack-ui.js";

const me = await mountShell({ role: "farmer" });
const root = document.getElementById("root");
const meters = liveMeters();
let mapCtx = null;
let markers = [];

let myBatches = [];

function bookForm(f, reloadBookings) {
  let key = newIdempotencyKey();
  const batch = batchSelect(myBatches);
  const crop = el("select", { class: "select", name: "commodity" }, f.commodities.map((c) => el("option", { value: c, text: commodity(c) })));
  return datesForm(t("storage.request_booking"), { start: todayISO(1), end: todayISO(60), extra: [field(t("common.crop"), crop), field(t("chain.link_batch"), batch, t("chain.link_hint"))] }, async (body, form) => {
    try {
      await api("/storage/bookings", { method: "POST", idempotencyKey: key, body: { ...body, facility_id: f.id, commodity: crop.value, batch_id: batch.value || null } });
      key = newIdempotencyKey();
      done("storage.booking_sent");
      form.closest("details").open = false;
      reloadBookings();
    } catch (err) {
      fail(err);
    }
  });
}

function facilityCard(f, reloadBookings) {
  const meter = capacityMeter(f);
  meters.register(f.id, meter);
  return el(
    "li",
    { class: "card stack", id: `fac-${f.id}` },
    el(
      "div",
      { class: "item__head" },
      el("strong", { text: f.name }),
      el("span", { class: "row" }, demoBadge(f.is_demo), el("span", { class: "muted", text: `${f.district}${f.distance_km != null ? ` · ${f.distance_km} km` : ""}` })),
    ),
    el("p", { class: "muted", text: `${f.org_name ?? ""} · ${f.commodities.map(commodity).join(", ")}` }),
    meter,
    el("details", { class: "panel" }, el("summary", { text: t("storage.book_here") }), el("div", { class: "panel__body" }, bookForm(f, reloadBookings))),
  );
}

function plot(rows) {
  if (!mapCtx) return;
  for (const m of markers) m.remove();
  markers = rows.map((f) => {
    const popup = el("div", {}, el("strong", { text: f.name }), el("br"), `${t("storage.free")}: ${(f.free_kg / 1000).toFixed(1)} t`);
    const m = mapCtx.L.marker([f.location.lat, f.location.lng]).addTo(mapCtx.map).bindPopup(popup);
    m.on("click", () => document.getElementById(`fac-${f.id}`)?.scrollIntoView({ behavior: "smooth", block: "center" }));
    return m;
  });
}

async function render() {
  const crop = commoditySelect({ blank: "common.all_crops" });
  const mapEl = el("div", { class: "map" });
  const facHost = el("div");
  const bookingsHost = el("div");
  const alertsHost = el("div");
  root.replaceChildren(
    el("h1", { text: t("storage.title") }),
    el("div", { class: "row" }, field(t("common.crop"), crop)),
    mapEl,
    facHost,
    el("h2", { text: t("freshtrack.my_alerts") }),
    alertsHost,
    el("h2", { text: t("storage.my_bookings") }),
    bookingsHost,
  );
  mapCtx = await createMap(mapEl);
  myBatches = await api("/batches").then((r) => r.data).catch(() => []);

  list(alertsHost, async () => (await api("/freshtrack/alerts?limit=20")).data, (rows) => el("ul", { class: "item-list" }, rows.map((a) => alertCard(a))), "freshtrack.no_my_alerts");
  const loadBookings = () =>
    list(bookingsHost, async () => (await api("/storage/bookings")).data, (rows) => el("ul", { class: "item-list" }, rows.map((b) => bookingCard(b, "farmer", loadBookings))), "storage.empty_bookings");
  const loadFacilities = async () => {
    meters.clear();
    const qs = new URLSearchParams(crop.value ? { commodity: crop.value } : {});
    const rows = await list(facHost, async () => (await api(`/storage/facilities?${qs}`)).data, (r) => el("ul", { class: "item-list" }, r.map((f) => facilityCard(f, loadBookings))), "storage.empty_facilities");
    plot(rows ?? []);
  };
  crop.addEventListener("change", loadFacilities);
  loadFacilities();
  loadBookings();
  document.addEventListener("irminsul:ws", (ev) => {
    if (ev.detail.type === "notification" && ev.detail.data.kind.startsWith("booking.")) loadBookings();
  });
}

if (me.status === "active") {
  render();
  document.documentElement.addEventListener("langchange", () => location.reload());
}
