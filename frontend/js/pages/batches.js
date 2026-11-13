// Farmer: create and list batches.
import { api } from "../api.js";
import { commodity, demoBadge, fmtDate, fmtQtyBoth, todayISO } from "../format.js";
import { t } from "../i18n.js";
import { el, field } from "../ui/dom.js";
import { mountShell } from "../ui/shell.js";
import { commoditySelect, done, fail, input, list, unitSelect } from "./common.js";
import { batchStatusBadge } from "./chain-ui.js";

const me = await mountShell({ role: "farmer" });
const root = document.getElementById("root");

function batchCard(b) {
  return el(
    "li",
    { class: "card stack" },
    el(
      "div",
      { class: "item__head" },
      el("strong", { text: b.batch_code }),
      el("span", { class: "row" }, demoBadge(b.is_demo), batchStatusBadge(b.status)),
    ),
    el(
      "dl",
      { class: "dl" },
      el("dt", { text: t("common.crop") }),
      el("dd", { text: `${commodity(b.commodity)}${b.variety ? ` · ${b.variety}` : ""}` }),
      el("dt", { text: t("common.quantity") }),
      el("dd", { text: fmtQtyBoth(b.qty_kg, b.display_unit) }),
      el("dt", { text: t("sell.harvest_date") }),
      el("dd", { text: fmtDate(b.harvest_date) }),
      el("dt", { text: t("chain.custodian") }),
      el("dd", { text: b.custodian.name ?? t(`chain.custodian_${b.custodian.type}`) }),
      b.parent ? [el("dt", { text: t("chain.split_from") }), el("dd", { text: b.parent.batch_code })] : null,
    ),
    el("a", { class: "btn", href: `/batch.html?id=${b.id}`, text: t("chain.open") }),
  );
}

async function createForm(reload) {
  const farms = (await api("/farms")).data;
  if (!farms.length) {
    return el("div", { class: "alert alert--info" }, t("sell.need_farm"), " ", el("a", { href: "/farmer/farms.html", text: t("nav.farms") }));
  }
  const farm = el("select", { class: "select" }, farms.map((f) => el("option", { value: f.id, text: `${f.name} · ${f.district}` })));
  const crop = commoditySelect();
  const variety = input("variety", { maxlength: "60" });
  const harvest = input("harvest_date", { type: "date", required: true, max: todayISO(), value: todayISO() });
  const qty = input("qty", { type: "number", min: "0.001", step: "any", required: true });
  const unit = unitSelect({ value: "quintal" });
  const form = el(
    "form",
    { class: "form-grid" },
    field(t("sell.farm"), farm),
    field(t("common.crop"), crop),
    field(t("sell.variety"), variety),
    field(t("sell.harvest_date"), harvest),
    el("div", { class: "inline-fields span-2" }, field(t("common.quantity"), qty), field(t("common.unit"), unit)),
    el("button", { class: "btn btn--primary span-2", type: "submit", text: t("chain.create") }),
  );
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    if (!form.reportValidity()) return;
    try {
      const { data } = await api("/batches", {
        method: "POST",
        body: { farm_id: farm.value, commodity: crop.value, variety: variety.value || null, harvest_date: harvest.value, qty: qty.value, unit: unit.value },
      });
      done("chain.created", { code: data.batch_code });
      form.reset();
      harvest.value = todayISO();
      reload();
    } catch (err) {
      fail(err);
    }
  });
  return form;
}

async function render() {
  const host = el("div");
  const formHost = el("div", { class: "panel__body" });
  const load = () => list(host, async () => (await api("/batches")).data, (rows) => el("ul", { class: "item-list" }, rows.map(batchCard)), "chain.empty");
  root.replaceChildren(
    el("h1", { text: t("chain.title") }),
    el("p", { class: "muted", text: t("chain.intro") }),
    el("details", { class: "panel" }, el("summary", { text: t("chain.new") }), formHost),
    host,
  );
  load();
  formHost.replaceChildren(await createForm(load).catch(() => el("p", { text: t("errors.generic") })));
}

if (me.status === "active") {
  render();
  document.documentElement.addEventListener("langchange", render);
}
