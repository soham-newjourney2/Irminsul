// Timeline + chain-status rendering shared by the batch page and the public verify page.
import { commodity, fmtMoney, fmtQty } from "../format.js";
import { fmtDateTime, t } from "../i18n.js";
import { el } from "../ui/dom.js";

const BATCH_TONE = { active: "ok", in_storage: "info", in_transit: "info", delivered: "muted", split: "muted" };

export function batchStatusBadge(status) {
  return el("span", { class: "badge", dataset: { tone: BATCH_TONE[status] ?? "muted" }, text: t(`status_batch.${status}`) });
}

/** Human-readable details for an event payload (ids are skipped). */
export function detailLines(type, p = {}) {
  const lines = [];
  if (p.qty_kg !== undefined) lines.push(`${t("common.quantity")}: ${fmtQty(p.qty_kg)}${p.partial ? ` (${t("chain.partial")})` : ""}`);
  if (p.facility_name) lines.push(`${t("storage.facility")}: ${p.facility_name}`);
  if (p.district) lines.push(`${t("common.district")}: ${p.district}`);
  if (p.harvest_date) lines.push(`${t("sell.harvest_date")}: ${p.harvest_date}`);
  if (p.commodity) lines.push(`${t("common.crop")}: ${commodity(p.commodity)}${p.variety ? ` · ${p.variety}` : ""}`);
  if (p.asking_price_paise_per_quintal) lines.push(`${t("prices.asking")}: ${t("units.per_quintal", { price: fmtMoney(p.asking_price_paise_per_quintal) })}`);
  if (p.parent_code) lines.push(`${t("chain.split_from")}: ${p.parent_code}`);
  if (Array.isArray(p.children)) lines.push(`${t("chain.split_into")}: ${p.children.map((c) => `${c.code} (${fmtQty(c.qty_kg)})`).join(", ")}`);
  if (p.ref_seq !== undefined) lines.push(t("chain.corrects", { seq: p.ref_seq }));
  if (p.reason) lines.push(`${t("storage.reason")}: ${p.reason}`);
  if (p.corrected && Object.keys(p.corrected).length) {
    lines.push(`${t("chain.corrected_values")}: ${Object.entries(p.corrected).map(([k, v]) => `${k} = ${v}`).join(", ")}`);
  }
  if (type === "relocated") lines.push(`${t("emergency.moved")}: ${p.from_district ?? "?"} → ${p.to_district ?? "?"}${p.status ? ` (${t(`emergency.move_${p.status}`)})` : ""}`);
  if (p.simulated) lines.push(t("emergency.simulated_label"));
  if (p.kind) lines.push(`${t("freshtrack.condition")}: ${t(`freshtrack.kind_${p.kind}`)}${p.severity ? ` (${t(`severity.${p.severity}`)})` : ""}`);
  if (p.result) lines.push(`${t("freshtrack.inspection")}: ${t(`freshtrack.result_${p.result}`)}${p.corrective_action ? ` — ${p.corrective_action}` : ""}`);
  if (type === "observation_summary" && p.status) lines.push(`${t("freshtrack.summary")}: ${t(`freshtrack.summary_${p.status}`)}${p.temp_in_band_pct != null ? ` · ${p.temp_in_band_pct}% ${t("freshtrack.in_band")}` : ""}${p.readings ? ` · ${p.readings} ${t("freshtrack.readings")}` : ""}`);
  if (p.label) lines.push(`${t("chain.screening")}: ${p.label === "unsure" ? t("screen.unsure_title") : t(`diseases.${p.label}`)}${p.confidence !== undefined ? ` (${Math.round(p.confidence * 100)}%)` : ""}`);
  return lines;
}

/** events: [{seq, type, event_time, payload|details, actor_role?, hash?}] */
export function timeline(events, { showHashes = false, extra } = {}) {
  return el(
    "ol",
    { class: "item-list" },
    events.map((e) =>
      el(
        "li",
        { class: "card stack", id: `ev-${e.seq}` },
        el(
          "div",
          { class: "item__head" },
          el("strong", { text: `#${e.seq} · ${t(`events.${e.type}`)}` }),
          el("span", { class: "muted", text: fmtDateTime(e.event_time) }),
        ),
        e.actor_role ? el("p", { class: "hint", text: `${t("chain.by")}: ${t(`parties.${e.actor_role}`)}` }) : null,
        el("ul", { class: "history" }, detailLines(e.type, e.payload ?? e.details).map((line) => el("li", { text: line }))),
        showHashes && e.hash ? el("p", { class: "hint", text: `${t("chain.hash")}: ${e.hash.slice(0, 16)}…` }) : null,
        extra ? extra(e) : null,
      ),
    ),
  );
}

export function chainStatus(v) {
  if (v.valid) {
    return el("div", { class: "alert alert--ok", role: "status" }, el("strong", { text: `✓ ${t("chain.verified")}` }), el("p", { text: t("chain.verified_detail", { n: v.events, time: fmtDateTime(v.checked_at) }) }), el("p", { class: "hint", text: t("chain.verified_meaning") }));
  }
  return el(
    "div",
    { class: "alert alert--error", role: "alert" },
    el("strong", { text: `✕ ${t("chain.broken")}` }),
    el("p", { text: t("chain.broken_detail", { seq: v.first_invalid_seq ?? "?", reason: t(`chain.reason_${v.reason}`) }) }),
  );
}

/** Optional batch picker: only batches that can still be listed / stored. */
export function batchSelect(batches) {
  const open = batches.filter((b) => b.status === "active" || b.status === "in_storage");
  return el(
    "select",
    { class: "select", name: "batch_id" },
    el("option", { value: "", text: t("chain.no_batch") }),
    open.map((b) => el("option", { value: b.id, text: `${b.batch_code} · ${commodity(b.commodity)} · ${fmtQty(b.qty_kg, b.display_unit)}` })),
  );
}
