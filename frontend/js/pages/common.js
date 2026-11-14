// Shared bits for M2 pages: i18n-aware list loading, selects, history, errors.
import { newIdempotencyKey } from "../api.js";
import { commodity, fmtQty } from "../format.js";
import { errorMessage, fmtDateTime, t } from "../i18n.js";
import { el, loadInto, toast } from "../ui/dom.js";

export const COMMODITIES = ["potato", "tomato", "rice", "jute"];
export const UNITS = ["kg", "quintal", "tonne"];
export const WB_DISTRICTS = [
  "Alipurduar", "Bankura", "Birbhum", "Cooch Behar", "Dakshin Dinajpur", "Darjeeling", "Hooghly",
  "Howrah", "Jalpaiguri", "Jhargram", "Kalimpong", "Kolkata", "Malda", "Murshidabad", "Nadia",
  "North 24 Parganas", "Paschim Bardhaman", "Paschim Medinipur", "Purba Bardhaman",
  "Purba Medinipur", "Purulia", "South 24 Parganas", "Uttar Dinajpur",
];

export function list(container, fetcher, render, emptyKey) {
  return loadInto(container, fetcher, render, {
    emptyText: t(emptyKey),
    loadingText: t("common.loading"),
    retryText: t("common.retry"),
    errorText: errorMessage,
  });
}

export const fail = (err) => toast(errorMessage(err), "error");
export const done = (key, vars) => toast(t(key, vars), "ok");

function select(name, values, labelFn, { blank, value } = {}) {
  const s = el(
    "select",
    { class: "select", name },
    blank ? el("option", { value: "", text: t(blank) }) : null,
    values.map((v) => el("option", { value: v, text: labelFn(v) })),
  );
  if (value !== undefined) s.value = value;
  return s;
}

export const commoditySelect = (opts) => select("commodity", COMMODITIES, commodity, opts);
export const unitSelect = (opts) => select("unit", UNITS, (u) => t(`units.${u}`), opts);
export const districtSelect = (opts) => select("district", WB_DISTRICTS, (d) => d, opts);

export function input(name, attrs = {}) {
  return el("input", { class: "input", name, ...attrs });
}

/** Read a form's named controls into an object (empty strings → null). */
export function formData(form) {
  const out = {};
  for (const [k, v] of new FormData(form).entries()) out[k] = v === "" ? null : v;
  return out;
}

export function historyList(entries, kind) {
  return el(
    "ul",
    { class: "history" },
    entries.map((h) => {
      const who = t(`parties.${h.by}`);
      const what = h.action ? t(`history.${h.action}`) : t(`status_${kind}.${h.status}`);
      const extra = h.qty_kg ? ` · ${fmtQty(h.qty_kg)}` : "";
      const note = h.note ? ` — “${h.note}”` : "";
      return el("li", { text: `${fmtDateTime(h.at)} · ${who}: ${what}${extra}${note}` });
    }),
  );
}

export function contactBlock(party) {
  if (!party?.email) return null;
  return el(
    "div",
    { class: "contact" },
    `${t("common.contact")}: ${party.name}${party.org_name ? ` (${party.org_name})` : ""} · `,
    el("a", { href: `mailto:${party.email}`, text: party.email }),
  );
}

export { newIdempotencyKey };
