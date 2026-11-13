import { api } from "../api.js";
import { fmtNum } from "../format.js";
import { t } from "../i18n.js";
import { el, field } from "../ui/dom.js";
import { locationPicker } from "../ui/map.js";
import { mountShell } from "../ui/shell.js";
import { districtSelect, done, fail, input, list } from "./common.js";

const me = await mountShell({ role: "farmer" });
const root = document.getElementById("root");

function farmCard(f) {
  return el(
    "li",
    { class: "card" },
    el("div", { class: "item__head" }, el("strong", { text: f.name }), el("span", { class: "muted", text: f.district })),
    el(
      "dl",
      { class: "dl" },
      f.village ? [el("dt", { text: t("farms.village") }), el("dd", { text: f.village })] : null,
      f.area_acres ? [el("dt", { text: t("farms.area") }), el("dd", { text: `${fmtNum(f.area_acres, 2)} ${t("farms.acres")}` })] : null,
      el("dt", { text: t("farms.location") }),
      el("dd", { text: `${f.location.lat.toFixed(4)}, ${f.location.lng.toFixed(4)}` }),
    ),
  );
}

function render() {
  const lat = input("lat", { type: "number", step: "any", required: true, inputmode: "decimal" });
  const lng = input("lng", { type: "number", step: "any", required: true, inputmode: "decimal" });
  const pickerHost = el("div", { class: "span-2" });
  const name = input("name", { required: true, maxlength: "80" });
  const district = districtSelect({ blank: "common.choose" });
  district.required = true;
  const village = input("village", { maxlength: "80" });
  const area = input("area_acres", { type: "number", min: "0.01", step: "0.01" });
  const form = el(
    "form",
    { class: "form-grid" },
    field(t("farms.name"), name),
    field(t("common.district"), district),
    field(t("farms.village"), village),
    field(t("farms.area_acres"), area),
    field(t("map.lat"), lat),
    field(t("map.lng"), lng),
    pickerHost,
    el("button", { class: "btn btn--primary span-2", type: "submit", text: t("farms.save") }),
  );
  const listHost = el("div");
  const load = () => list(listHost, async () => (await api("/farms")).data, (rows) => el("ul", { class: "item-list" }, rows.map(farmCard)), "farms.empty");

  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    if (!form.reportValidity()) return;
    try {
      await api("/farms", {
        method: "POST",
        body: {
          name: name.value,
          district: district.value,
          village: village.value || null,
          area_acres: area.value || null,
          location: { lat: Number(lat.value), lng: Number(lng.value) },
        },
      });
      done("farms.saved");
      form.reset();
      load();
    } catch (err) {
      fail(err);
    }
  });

  root.replaceChildren(
    el("h1", { text: t("farms.title") }),
    el("details", { class: "panel" }, el("summary", { text: t("farms.add") }), el("div", { class: "panel__body" }, form)),
    listHost,
  );
  locationPicker(pickerHost, lat, lng);
  load();
}

if (me.status === "active") {
  render();
  document.documentElement.addEventListener("langchange", render);
}
