// Farmer: my listings, incoming purchase requests, orders.
import { api } from "../api.js";
import { commodity, demoBadge, fmtDate, fmtQtyBoth, priceBlock, statusBadge, todayISO } from "../format.js";
import { t } from "../i18n.js";
import { actionButton, el, field } from "../ui/dom.js";
import { mountShell } from "../ui/shell.js";
import { setupTabs } from "../ui/tabs.js";
import { commoditySelect, done, fail, input, list, newIdempotencyKey, unitSelect } from "./common.js";
import { orderCard, requestCard } from "./deals.js";

const me = await mountShell({ role: "farmer" });
const panel = document.getElementById("panel");
let idemKey = newIdempotencyKey();
let reloadList = null;

async function listingForm(reload) {
  const farms = (await api("/farms")).data;
  if (!farms.length) {
    return el("div", { class: "alert alert--info" }, t("sell.need_farm"), " ", el("a", { href: "/farmer/farms.html", text: t("nav.farms") }));
  }
  const farm = el("select", { class: "select", name: "farm_id" }, farms.map((f) => el("option", { value: f.id, text: `${f.name} · ${f.district}` })));
  const crop = commoditySelect();
  const variety = input("variety", { maxlength: "60" });
  const grade = input("grade", { maxlength: "30" });
  const qty = input("qty", { type: "number", min: "0.001", step: "any", required: true });
  const unit = unitSelect({ value: "quintal" });
  const harvest = input("harvest_date", { type: "date" });
  const from = input("available_from", { type: "date", required: true, value: todayISO() });
  const until = input("available_until", { type: "date" });
  const price = input("asking_price_per_quintal", { type: "number", min: "1", step: "0.01", required: true });
  const note = input("note", { maxlength: "500" });
  const publish = el("input", { type: "checkbox", name: "publish", checked: true });
  const form = el(
    "form",
    { class: "form-grid" },
    field(t("sell.farm"), farm),
    field(t("common.crop"), crop),
    field(t("sell.variety"), variety),
    field(t("sell.grade"), grade),
    el("div", { class: "inline-fields" }, field(t("common.quantity"), qty), field(t("common.unit"), unit)),
    field(t("sell.asking_price"), price, t("sell.price_hint")),
    field(t("sell.harvest_date"), harvest),
    field(t("sell.available_from"), from),
    field(t("sell.available_until"), until),
    field(t("common.note"), note),
    el("label", { class: "row span-2" }, publish, t("sell.publish_now")),
    el("button", { class: "btn btn--primary span-2", type: "submit", text: t("sell.create") }),
  );
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    if (!form.reportValidity()) return;
    try {
      await api("/listings", {
        method: "POST",
        idempotencyKey: idemKey,
        body: {
          farm_id: farm.value,
          commodity: crop.value,
          variety: variety.value || null,
          grade: grade.value || null,
          qty: qty.value,
          unit: unit.value,
          harvest_date: harvest.value || null,
          available_from: from.value,
          available_until: until.value || null,
          asking_price_per_quintal: price.value,
          note: note.value || null,
          publish: publish.checked,
        },
      });
      idemKey = newIdempotencyKey();
      done("sell.created");
      form.reset();
      from.value = todayISO();
      reload();
    } catch (err) {
      fail(err);
    }
  });
  return form;
}

function listingCard(l, reload) {
  const post = (action) => api(`/listings/${l.id}/${action}`, { method: "POST" });
  const actions = [];
  if (l.status === "draft") {
    actions.push(actionButton(t("sell.publish"), async () => (await post("publish"), reload()), { kind: "primary", onError: fail }));
  }
  if (["draft", "active", "partially_fulfilled"].includes(l.status)) {
    actions.push(
      actionButton(
        t("sell.cancel"),
        async () => {
          if (!confirm(t("sell.confirm_cancel"))) return;
          await post("cancel");
          reload();
        },
        { kind: "danger", onError: fail },
      ),
    );
  }
  let priceEdit = null;
  if (!["sold", "expired", "cancelled"].includes(l.status)) {
    const price = input("price", { type: "number", min: "1", step: "0.01", value: String(l.asking_price_paise_per_quintal / 100) });
    const form = el("form", { class: "row" }, field(t("sell.asking_price"), price), el("button", { class: "btn", type: "submit", text: t("common.save") }));
    form.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      try {
        await api(`/listings/${l.id}`, { method: "PATCH", body: { asking_price_per_quintal: price.value } });
        done("common.saved");
        reload();
      } catch (err) {
        fail(err);
      }
    });
    priceEdit = el("details", { class: "panel" }, el("summary", { text: t("sell.edit_price") }), el("div", { class: "panel__body" }, form));
  }
  return el(
    "li",
    { class: "card stack" },
    el(
      "div",
      { class: "item__head" },
      el("strong", { text: `${commodity(l.commodity)}${l.variety ? ` · ${l.variety}` : ""}${l.grade ? ` · ${l.grade}` : ""}` }),
      el("span", { class: "row" }, demoBadge(l.is_demo), statusBadge("listing", l.status)),
    ),
    el(
      "dl",
      { class: "dl" },
      el("dt", { text: t("sell.remaining") }),
      el("dd", { text: `${fmtQtyBoth(l.remaining_kg, l.display_unit)} / ${fmtQtyBoth(l.qty_kg, l.display_unit)}` }),
      el("dt", { text: t("sell.available_from") }),
      el("dd", { text: fmtDate(l.available_from) }),
      l.available_until ? [el("dt", { text: t("sell.available_until") }), el("dd", { text: fmtDate(l.available_until) })] : null,
      el("dt", { text: t("common.district") }),
      el("dd", { text: l.district }),
    ),
    priceBlock("prices.asking", l.asking_price_paise_per_quintal),
    actions.length ? el("div", { class: "item__actions" }, actions) : null,
    priceEdit,
  );
}

async function show(tab) {
  const host = el("div");
  if (tab === "listings") {
    const load = () => list(host, async () => (await api("/listings/mine")).data, (rows) => el("ul", { class: "item-list" }, rows.map((l) => listingCard(l, load))), "sell.empty_listings");
    const formHost = el("div", { class: "panel__body" });
    panel.replaceChildren(el("details", { class: "panel" }, el("summary", { text: t("sell.new_listing") }), formHost), host);
    reloadList = load;
    load();
    formHost.replaceChildren(await listingForm(load).catch(() => el("p", { text: t("errors.generic") })));
  } else if (tab === "requests") {
    panel.replaceChildren(host);
    const load = () => list(host, async () => (await api("/purchase-requests")).data, (rows) => el("ul", { class: "item-list" }, rows.map((r) => requestCard(r, "farmer", load))), "deals.empty_requests");
    reloadList = load;
    load();
  } else {
    panel.replaceChildren(host);
    const load = () => list(host, async () => (await api("/orders")).data, (rows) => el("ul", { class: "item-list" }, rows.map((o) => orderCard(o, "farmer", load))), "orders.empty");
    reloadList = load;
    load();
  }
}

if (me.status === "active") {
  const tabs = setupTabs(show);
  document.documentElement.addEventListener("langchange", () => show(tabs.current()));
  document.addEventListener("irminsul:ws", (ev) => {
    if (ev.detail.type === "notification") reloadList?.();
  });
}
