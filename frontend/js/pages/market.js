// Distributor: search listings (filters + radius + map) and send purchase requests.
import { api } from "../api.js";
import { commodity, demoBadge, fmtDate, fmtQtyBoth, priceBlock } from "../format.js";
import { t } from "../i18n.js";
import { el, field } from "../ui/dom.js";
import { createMap, myLocation } from "../ui/map.js";
import { mountShell } from "../ui/shell.js";
import { commoditySelect, districtSelect, done, fail, input, list, newIdempotencyKey, unitSelect } from "./common.js";

const me = await mountShell({ role: "distributor" });
const root = document.getElementById("root");
let mapCtx = null;
let markers = [];
let near = null;

function requestForm(l) {
  let key = newIdempotencyKey();
  const qty = input("qty", { type: "number", min: "0.001", step: "any", required: true });
  const unit = unitSelect({ value: l.display_unit });
  const price = input("price_per_quintal", { type: "number", min: "1", step: "0.01", required: true, value: String(l.asking_price_paise_per_quintal / 100) });
  const mode = el("select", { class: "select", name: "delivery_mode" }, ["pickup", "delivery"].map((m) => el("option", { value: m, text: t(`deals.mode_${m}`) })));
  const neededBy = input("needed_by", { type: "date" });
  const note = input("note", { maxlength: "500" });
  const form = el(
    "form",
    { class: "stack" },
    el("div", { class: "inline-fields" }, field(t("common.quantity"), qty), field(t("common.unit"), unit)),
    field(t("market.your_price"), price, t("sell.price_hint")),
    el("div", { class: "inline-fields" }, field(t("deals.delivery"), mode), field(t("deals.needed_by"), neededBy)),
    field(t("common.note"), note),
    el("button", { class: "btn btn--primary", type: "submit", text: t("market.send_request") }),
  );
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    if (!form.reportValidity()) return;
    try {
      await api("/purchase-requests", {
        method: "POST",
        idempotencyKey: key,
        body: {
          listing_id: l.id,
          qty: qty.value,
          unit: unit.value,
          price_per_quintal: price.value,
          delivery_mode: mode.value,
          needed_by: neededBy.value || null,
          note: note.value || null,
        },
      });
      key = newIdempotencyKey();
      done("market.request_sent");
      form.closest("details").open = false;
    } catch (err) {
      fail(err);
    }
  });
  return form;
}

function listingCard(l) {
  return el(
    "li",
    { class: "card stack", id: `lst-${l.id}` },
    el(
      "div",
      { class: "item__head" },
      el("strong", { text: `${commodity(l.commodity)}${l.variety ? ` · ${l.variety}` : ""}${l.grade ? ` · ${l.grade}` : ""}` }),
      el("span", { class: "row" }, demoBadge(l.is_demo), el("span", { class: "muted", text: `${l.district}${l.distance_km != null ? ` · ${l.distance_km} km` : ""}` })),
    ),
    el("p", { class: "muted", text: l.farmer?.name ?? "" }),
    el(
      "dl",
      { class: "dl" },
      el("dt", { text: t("market.available") }),
      el("dd", { text: fmtQtyBoth(l.remaining_kg, l.display_unit) }),
      el("dt", { text: t("sell.available_from") }),
      el("dd", { text: fmtDate(l.available_from) }),
      l.harvest_date ? [el("dt", { text: t("sell.harvest_date") }), el("dd", { text: fmtDate(l.harvest_date) })] : null,
    ),
    priceBlock("prices.asking", l.asking_price_paise_per_quintal),
    l.is_mine ? null : el("details", { class: "panel" }, el("summary", { text: t("market.make_offer") }), el("div", { class: "panel__body" }, requestForm(l))),
  );
}

function plot(rows) {
  if (!mapCtx) return;
  for (const m of markers) m.remove();
  markers = rows.map((l) => {
    const popup = el("div", {}, el("strong", { text: commodity(l.commodity) }), el("br"), fmtQtyBoth(l.remaining_kg, l.display_unit));
    const m = mapCtx.L.marker([l.location.lat, l.location.lng]).addTo(mapCtx.map).bindPopup(popup);
    m.on("click", () => document.getElementById(`lst-${l.id}`)?.scrollIntoView({ behavior: "smooth", block: "center" }));
    return m;
  });
  if (rows.length) mapCtx.map.fitBounds(rows.map((l) => [l.location.lat, l.location.lng]), { maxZoom: 11, padding: [24, 24] });
}

async function render() {
  const crop = commoditySelect({ blank: "common.all_crops" });
  const district = districtSelect({ blank: "common.all_districts" });
  const radius = input("radius_km", { type: "number", min: "1", max: "500", value: "50" });
  const maxPrice = input("max_price", { type: "number", min: "1", step: "0.01" });
  const sort = el("select", { class: "select", name: "sort" }, ["newest", "price", "distance"].map((s) => el("option", { value: s, text: t(`market.sort_${s}`) })));
  const nearLabel = el("span", { class: "hint", text: near ? t("market.near_set") : t("market.near_unset") });
  const locate = el("button", { class: "btn", type: "button", text: t("map.use_my_location") });
  const form = el(
    "form",
    { class: "form-grid card" },
    field(t("common.crop"), crop),
    field(t("common.district"), district),
    field(t("market.max_price"), maxPrice),
    field(t("market.sort"), sort),
    el("div", { class: "stack" }, locate, nearLabel),
    field(t("market.radius"), radius),
    el("button", { class: "btn btn--primary span-2", type: "submit", text: t("market.search") }),
  );
  const mapEl = el("div", { class: "map" });
  const results = el("div");
  root.replaceChildren(el("h1", { text: t("market.title") }), form, mapEl, results);
  mapCtx = await createMap(mapEl);

  const search = async () => {
    const qs = new URLSearchParams({ sort: sort.value, limit: "100" });
    if (crop.value) qs.set("commodity", crop.value);
    if (district.value) qs.set("district", district.value);
    if (maxPrice.value) qs.set("max_price_per_quintal", maxPrice.value);
    if (near) {
      qs.set("near", `${near.lat},${near.lng}`);
      qs.set("radius_km", radius.value || "50");
    } else if (sort.value === "distance") {
      qs.set("sort", "newest");
    }
    const rows = await list(results, async () => (await api(`/listings?${qs}`)).data, (r) => el("ul", { class: "item-list" }, r.map(listingCard)), "market.empty");
    plot(rows ?? []);
  };
  locate.addEventListener("click", async () => {
    try {
      near = await myLocation();
      nearLabel.textContent = t("market.near_set");
      search();
    } catch {
      nearLabel.textContent = t("map.location_failed");
    }
  });
  form.addEventListener("submit", (ev) => {
    ev.preventDefault();
    search();
  });
  search();
}

if (me.status === "active") {
  render();
  document.documentElement.addEventListener("langchange", render);
}
