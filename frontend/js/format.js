// Display formatting. Quantities arrive as kg, money as paise.
import { currentLang, t } from "./i18n.js";
import { el } from "./ui/dom.js";

const TAG = { en: "en-IN", bn: "bn-IN", hi: "hi-IN" };
export const KG_PER_UNIT = { kg: 1, quintal: 100, tonne: 1000 };
const tag = () => TAG[currentLang()] ?? "en-IN";

export function fmtNum(value, digits = 3) {
  return new Intl.NumberFormat(tag(), { maximumFractionDigits: digits }).format(value);
}

export function fmtQty(kg, unit = "kg") {
  return `${fmtNum(kg / KG_PER_UNIT[unit])} ${t(`units.${unit}`)}`;
}

/** "2.5 quintal (250 kg)" — display unit plus canonical kg. */
export function fmtQtyBoth(kg, unit) {
  return unit === "kg" ? fmtQty(kg, "kg") : `${fmtQty(kg, unit)} (${fmtQty(kg, "kg")})`;
}

export function fmtMoney(paise) {
  return new Intl.NumberFormat(tag(), {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 2,
  }).format(paise / 100);
}

export const fmtPerQuintal = (paise) => t("units.per_quintal", { price: fmtMoney(paise) });

export function fmtDate(iso) {
  if (!iso) return "—";
  const d = iso.length === 10 ? new Date(`${iso}T00:00:00`) : new Date(iso);
  return new Intl.DateTimeFormat(tag(), { dateStyle: "medium" }).format(d);
}

export const commodity = (c) => t(`commodities.${c}`);

const TONE = {
  active: "ok",
  accepted: "ok",
  confirmed: "ok",
  delivered: "ok",
  checked_in: "ok",
  pending: "warn",
  requested: "warn",
  countered: "warn",
  changes_requested: "warn",
  reserved: "warn",
  partially_fulfilled: "warn",
  dispatched: "info",
  rejected: "danger",
  cancelled: "danger",
  expired: "danger",
  withdrawn: "danger",
  draft: "muted",
  sold: "muted",
  closed: "muted",
  released: "muted",
};

/** kind: listing | request | order | booking */
export function statusBadge(kind, status) {
  return el("span", { class: "badge", dataset: { tone: TONE[status] ?? "muted" }, text: t(`status_${kind}.${status}`) });
}

/** Asking vs agreed prices are always labelled differently. */
export function priceBlock(labelKey, paise, agreed = false) {
  return el(
    "div",
    { class: `price${agreed ? " price--agreed" : ""}` },
    el("span", { class: "price__label", text: t(labelKey) }),
    fmtPerQuintal(paise),
  );
}

export function demoBadge(isDemo) {
  return isDemo ? el("span", { class: "badge", dataset: { tone: "info" }, text: t("badges.demo") }) : null;
}

/** Today in local time as YYYY-MM-DD (for date inputs). */
export function todayISO(offsetDays = 0) {
  const d = new Date();
  d.setDate(d.getDate() + offsetDays);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
