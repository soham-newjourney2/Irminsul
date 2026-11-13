// Capacity meter + booking cards shared by farmer storage and operator pages.
import { api } from "../api.js";
import { commodity, fmtDate, fmtQty, fmtQtyBoth, statusBadge } from "../format.js";
import { t } from "../i18n.js";
import { actionButton, el, field } from "../ui/dom.js";
import { done, fail, historyList, input, unitSelect } from "./common.js";

/** Meter element with an `update(capacity)` method for live WebSocket updates. */
export function capacityMeter(f) {
  const occ = el("div", { class: "meter__occupied" });
  const res = el("div", { class: "meter__reserved" });
  const bar = el("div", { class: "meter", role: "img" }, occ, res);
  const legend = el("div", { class: "meter-legend" });
  const node = el("div", { class: "stack" }, bar, legend);
  node.update = (c) => {
    const cap = Math.max(c.capacity_kg, 1);
    occ.style.width = `${(100 * c.occupied_kg) / cap}%`;
    res.style.width = `${(100 * c.reserved_kg) / cap}%`;
    const label = t("storage.meter", {
      free: fmtQty(c.free_kg, "tonne"),
      capacity: fmtQty(c.capacity_kg, "tonne"),
    });
    bar.setAttribute("aria-label", label);
    legend.replaceChildren(
      el("span", { text: label }),
      el("span", { text: `${t("storage.occupied")}: ${fmtQty(c.occupied_kg, "tonne")}` }),
      el("span", { text: `${t("storage.reserved")}: ${fmtQty(c.reserved_kg, "tonne")}` }),
    );
  };
  node.update(f);
  return node;
}

/** Keep meters live: register(id, meter) and they update on facility.capacity messages. */
export function liveMeters() {
  const meters = new Map();
  document.addEventListener("irminsul:ws", (ev) => {
    if (ev.detail.type !== "facility.capacity") return;
    for (const m of meters.get(ev.detail.data.id) ?? []) m.update(ev.detail.data);
  });
  return {
    register(id, meter) {
      if (!meters.has(id)) meters.set(id, new Set());
      meters.get(id).add(meter);
    },
    clear: () => meters.clear(),
  };
}

function datesForm(submitLabel, initial, onSubmit) {
  const qty = input("qty", { type: "number", min: "0.001", step: "any", required: true, value: initial.qty ?? "" });
  const unit = unitSelect({ value: initial.unit ?? "quintal" });
  const start = input("start_date", { type: "date", required: true, value: initial.start ?? "" });
  const end = input("end_date", { type: "date", required: true, value: initial.end ?? "" });
  const note = input("note", { maxlength: "500" });
  const extra = initial.extra ?? [];
  const form = el(
    "form",
    { class: "stack" },
    ...extra,
    el("div", { class: "inline-fields" }, field(t("common.quantity"), qty), field(t("common.unit"), unit)),
    el("div", { class: "inline-fields" }, field(t("storage.start_date"), start), field(t("storage.end_date"), end)),
    field(t("common.note"), note),
    el("button", { class: "btn btn--primary", type: "submit", text: submitLabel }),
  );
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    if (!form.reportValidity()) return;
    await onSubmit({ qty: qty.value, unit: unit.value, start_date: start.value, end_date: end.value, note: note.value || null }, form);
  });
  return form;
}

export { datesForm };

const FARMER_ACTIONS = { requested: ["cancel"], changes_requested: ["cancel"], accepted: ["cancel"] };
const OPERATOR_ACTIONS = {
  requested: ["accept", "request-changes", "reject"],
  changes_requested: ["reject"],
  accepted: ["check-in"],
  checked_in: ["release"],
};
const NEEDS_NOTE = new Set(["request-changes", "reject"]);

/** role: "farmer" | "storage_operator". zonesFor(facilityId) → Promise<zones> (operator only). */
export function bookingCard(b, role, reload, zonesFor) {
  const act = (action, body = {}) => api(`/storage/bookings/${b.id}/${action}`, { method: "POST", body });
  const actions = el("div", { class: "item__actions" });
  const forms = [];

  for (const action of (role === "farmer" ? FARMER_ACTIONS : OPERATOR_ACTIONS)[b.status] ?? []) {
    if (NEEDS_NOTE.has(action)) {
      const note = input("note", { maxlength: "500", placeholder: t("common.note") });
      const form = el("form", { class: "stack" }, field(t("storage.reason"), note), el("button", { class: "btn btn--danger", type: "submit", text: t(`bookings.${action}`) }));
      form.addEventListener("submit", async (ev) => {
        ev.preventDefault();
        try {
          await act(action, { note: note.value || null });
          done(`bookings.done_${action}`);
          reload();
        } catch (err) {
          fail(err);
        }
      });
      forms.push(el("details", { class: "panel" }, el("summary", { text: t(`bookings.${action}`) }), el("div", { class: "panel__body" }, form)));
    } else if (action === "check-in") {
      const zone = el("select", { class: "select", name: "zone_id" }, el("option", { value: "", text: t("bookings.no_zone") }));
      zonesFor?.(b.facility.id).then((zones) => zone.append(...zones.map((z) => el("option", { value: z.id, text: z.name }))));
      const form = el("form", { class: "stack" }, field(t("bookings.zone"), zone), el("button", { class: "btn btn--primary", type: "submit", text: t("bookings.check-in") }));
      form.addEventListener("submit", async (ev) => {
        ev.preventDefault();
        try {
          await act("check-in", { zone_id: zone.value || null });
          done("bookings.done_check-in");
          reload();
        } catch (err) {
          fail(err);
        }
      });
      forms.push(el("details", { class: "panel", open: true }, el("summary", { text: t("bookings.check-in") }), el("div", { class: "panel__body" }, form)));
    } else {
      actions.append(
        actionButton(
          t(`bookings.${action}`),
          async () => {
            if (action === "cancel" && !confirm(t("bookings.confirm_cancel"))) return;
            await act(action);
            done(`bookings.done_${action}`);
            reload();
          },
          { kind: action === "cancel" ? "danger" : "primary", onError: fail },
        ),
      );
    }
  }
  if (role === "farmer" && b.status === "changes_requested") {
    const form = datesForm(t("bookings.resubmit"), { qty: String(b.qty_kg), unit: "kg", start: b.start_date, end: b.end_date }, async (body) => {
      try {
        await act("resubmit", body);
        done("bookings.done_resubmit");
        reload();
      } catch (err) {
        fail(err);
      }
    });
    forms.push(el("details", { class: "panel", open: true }, el("summary", { text: t("bookings.resubmit") }), el("div", { class: "panel__body" }, form)));
  }

  const party = role === "farmer" ? null : b.farmer;
  const contact =
    role === "farmer"
      ? b.facility.contact_phone
        ? el("div", { class: "contact" }, `${t("common.contact")}: ${b.facility.name} · `, el("a", { href: `tel:${b.facility.contact_phone}`, text: b.facility.contact_phone }))
        : null
      : party?.phone
        ? el("div", { class: "contact" }, `${t("common.contact")}: ${party.name} · `, el("a", { href: `tel:${party.phone}`, text: party.phone }))
        : null;

  return el(
    "li",
    { class: "card stack" },
    el(
      "div",
      { class: "item__head" },
      el("strong", { text: `${commodity(b.commodity)} · ${fmtQtyBoth(b.qty_kg, b.display_unit)}` }),
      statusBadge("booking", b.status),
    ),
    el(
      "dl",
      { class: "dl" },
      el("dt", { text: t("storage.facility") }),
      el("dd", { text: `${b.facility.name} · ${b.facility.district}` }),
      role !== "farmer" && b.farmer ? [el("dt", { text: t("roles.farmer") }), el("dd", { text: b.farmer.name })] : null,
      el("dt", { text: t("storage.period") }),
      el("dd", { text: `${fmtDate(b.start_date)} – ${fmtDate(b.end_date)}` }),
      b.zone_name ? [el("dt", { text: t("bookings.zone") }), el("dd", { text: b.zone_name })] : null,
    ),
    contact,
    historyList(b.history, "booking"),
    actions.childElementCount ? actions : null,
    ...forms,
  );
}
