// Storage operator: facilities (capacity, status), zones.
import { api } from "../api.js";
import { commodity, demoBadge } from "../format.js";
import { t } from "../i18n.js";
import { el, field } from "../ui/dom.js";
import { locationPicker } from "../ui/map.js";
import { mountShell } from "../ui/shell.js";
import { COMMODITIES, commoditySelect, districtSelect, done, fail, input, list, unitSelect } from "./common.js";
import { capacityMeter, liveMeters } from "./facility-ui.js";

const me = await mountShell({ role: "storage_operator" });
const root = document.getElementById("root");
const meters = liveMeters();

function commodityChecks(selected = []) {
  return el(
    "fieldset",
    { class: "field" },
    el("legend", { text: t("storage.commodities") }),
    el("div", { class: "row" }, COMMODITIES.map((c) => el("label", { class: "row" }, el("input", { type: "checkbox", name: "commodities", value: c, checked: selected.includes(c) }), commodity(c)))),
  );
}
const checked = (form) => [...form.querySelectorAll("input[name=commodities]:checked")].map((i) => i.value);

function createForm(reload) {
  const name = input("name", { required: true, maxlength: "120" });
  const district = districtSelect({ blank: "common.choose" });
  district.required = true;
  const address = input("address", { maxlength: "300" });
  const cap = input("capacity", { type: "number", min: "0.001", step: "any", required: true });
  const unit = unitSelect({ value: "tonne" });
  const contactEmail = input("contact_email", { type: "email", required: true, inputmode: "email", maxlength: "254", autocapitalize: "none" });
  const lat = input("lat", { type: "number", step: "any", required: true });
  const lng = input("lng", { type: "number", step: "any", required: true });
  const picker = el("div", { class: "span-2" });
  const checks = commodityChecks(["potato"]);
  const form = el(
    "form",
    { class: "form-grid" },
    field(t("storage.facility_name"), name),
    field(t("common.district"), district),
    field(t("storage.address"), address),
    field(t("storage.contact_email"), contactEmail),
    el("div", { class: "inline-fields" }, field(t("storage.capacity"), cap), field(t("common.unit"), unit)),
    el("div", { class: "span-2" }, checks),
    field(t("map.lat"), lat),
    field(t("map.lng"), lng),
    picker,
    el("button", { class: "btn btn--primary span-2", type: "submit", text: t("storage.create_facility") }),
  );
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    if (!form.reportValidity()) return;
    try {
      await api("/storage/facilities", {
        method: "POST",
        body: {
          name: name.value,
          district: district.value,
          address: address.value || null,
          location: { lat: Number(lat.value), lng: Number(lng.value) },
          commodities: checked(form),
          capacity: cap.value,
          capacity_unit: unit.value,
          contact_email: contactEmail.value.trim().toLowerCase(),
        },
      });
      done("storage.facility_created");
      form.reset();
      reload();
    } catch (err) {
      fail(err);
    }
  });
  queueMicrotask(() => locationPicker(picker, lat, lng));
  return form;
}

function editForm(f, reload) {
  const cap = input("capacity", { type: "number", min: "0.001", step: "any", value: String(f.capacity_kg / 1000) });
  const unit = unitSelect({ value: "tonne" });
  const status = el("select", { class: "select", name: "status" }, ["active", "inactive"].map((s) => el("option", { value: s, text: t(`storage.status_${s}`) })));
  status.value = f.status;
  const contactEmail = input("contact_email", { type: "email", maxlength: "254", autocapitalize: "none", value: f.contact_email ?? "" });
  const checks = commodityChecks(f.commodities);
  const form = el(
    "form",
    { class: "stack" },
    el("div", { class: "inline-fields" }, field(t("storage.capacity"), cap), field(t("common.unit"), unit)),
    field(t("storage.status"), status),
    field(t("storage.contact_email"), contactEmail),
    checks,
    el("button", { class: "btn btn--primary", type: "submit", text: t("common.save") }),
  );
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    try {
      await api(`/storage/facilities/${f.id}`, {
        method: "PATCH",
        body: { capacity: cap.value, capacity_unit: unit.value, status: status.value, contact_email: contactEmail.value.trim().toLowerCase() || null, commodities: checked(form) },
      });
      done("common.saved");
      reload();
    } catch (err) {
      fail(err);
    }
  });
  return form;
}

function zonesBlock(f) {
  const host = el("div");
  const load = () => list(host, async () => (await api(`/storage/facilities/${f.id}/zones`)).data, (rows) => el("ul", { class: "history" }, rows.map((z) => el("li", { text: `${z.name} · ${t(`storage.zone_${z.kind}`)}${z.commodity ? ` · ${commodity(z.commodity)}` : ""}` }))), "storage.no_zones");
  const name = input("name", { required: true, maxlength: "60" });
  const kind = el("select", { class: "select", name: "kind" }, ["cold", "ambient"].map((k) => el("option", { value: k, text: t(`storage.zone_${k}`) })));
  const crop = commoditySelect({ blank: "common.any" });
  const profile = el("select", { class: "select", name: "rule_profile" }, el("option", { value: "", text: t("freshtrack.profile_default") }));
  api("/freshtrack/rules").then(({ data }) => {
    const fill = () => {
      profile.replaceChildren(el("option", { value: "", text: t("freshtrack.profile_default") }), ...Object.entries(data.profiles).filter(([, p]) => !crop.value || p.commodity === crop.value).map(([id, p]) => el("option", { value: id, text: `${t(`freshtrack.profile_${id}`)}${p.verified ? "" : ` (${t("badges.unverified_source")})`}` })));
    };
    crop.addEventListener("change", fill);
    fill();
  }).catch(() => {});
  const form = el("form", { class: "stack" }, field(t("storage.zone_name"), name), el("div", { class: "inline-fields" }, field(t("storage.zone_kind"), kind), field(t("common.crop"), crop)), field(t("freshtrack.profile"), profile, t("freshtrack.profile_hint")), el("button", { class: "btn", type: "submit", text: t("storage.add_zone") }));
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    if (!form.reportValidity()) return;
    try {
      await api(`/storage/facilities/${f.id}/zones`, { method: "POST", body: { name: name.value, kind: kind.value, commodity: crop.value || null, rule_profile: profile.value || null } });
      form.reset();
      load();
    } catch (err) {
      fail(err);
    }
  });
  load();
  return el("details", { class: "panel" }, el("summary", { text: t("storage.zones") }), el("div", { class: "panel__body stack" }, host, form));
}

function facilityCard(f, reload) {
  const meter = capacityMeter(f);
  meters.register(f.id, meter);
  return el(
    "li",
    { class: "card stack" },
    el(
      "div",
      { class: "item__head" },
      el("strong", { text: f.name }),
      el("span", { class: "row" }, demoBadge(f.is_demo), el("span", { class: "badge", dataset: { tone: f.status === "active" ? "ok" : "muted" }, text: t(`storage.status_${f.status}`) })),
    ),
    el("p", { class: "muted", text: `${f.district} · ${f.commodities.map(commodity).join(", ")}` }),
    meter,
    el("details", { class: "panel" }, el("summary", { text: t("storage.edit") }), el("div", { class: "panel__body" }, editForm(f, reload))),
    zonesBlock(f),
  );
}

function render() {
  const host = el("div");
  const load = () => {
    meters.clear();
    return list(host, async () => (await api("/storage/facilities/mine")).data, (rows) => el("ul", { class: "item-list" }, rows.map((f) => facilityCard(f, load))), "storage.no_facilities");
  };
  root.replaceChildren(
    el("h1", { text: t("storage.my_facilities") }),
    el("details", { class: "panel" }, el("summary", { text: t("storage.add_facility") }), el("div", { class: "panel__body" }, createForm(load))),
    host,
  );
  load();
}

if (me.status === "active") {
  render();
  document.documentElement.addEventListener("langchange", render);
}
