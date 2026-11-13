// Purchase-request and order cards, shared by farmer (sell) and distributor (deals) pages.
import { api } from "../api.js";
import { commodity, fmtDate, fmtMoney, fmtQtyBoth, priceBlock, statusBadge } from "../format.js";
import { t } from "../i18n.js";
import { actionButton, el, field } from "../ui/dom.js";
import { contactBlock, done, fail, historyList, input, unitSelect } from "./common.js";

function counterForm(r, reload) {
  const price = input("price_per_quintal", {
    type: "number",
    min: "1",
    step: "0.01",
    required: true,
    value: String(r.offered_price_paise_per_quintal / 100),
  });
  const qty = input("qty", { type: "number", min: "0.001", step: "any", placeholder: t("deals.qty_optional") });
  const unit = unitSelect({ value: r.display_unit });
  const note = input("note", { maxlength: "500" });
  const form = el(
    "form",
    { class: "stack" },
    field(t("deals.counter_price"), price),
    el("div", { class: "inline-fields" }, field(t("common.quantity"), qty), field(t("common.unit"), unit)),
    field(t("common.note"), note),
    el("button", { class: "btn btn--primary", type: "submit", text: t("deals.send_counter") }),
  );
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const body = { price_per_quintal: price.value, note: note.value || null };
    if (qty.value) Object.assign(body, { qty: qty.value, unit: unit.value });
    try {
      await api(`/purchase-requests/${r.id}/counter`, { method: "POST", body });
      done("deals.countered");
      reload();
    } catch (err) {
      fail(err);
    }
  });
  return el("details", { class: "panel" }, el("summary", { text: t("deals.counter") }), el("div", { class: "panel__body" }, form));
}

/** side: "farmer" | "distributor" */
export function requestCard(r, side, reload) {
  const other = r.counterparty;
  const who = other ? `${other.name}${other.org_name ? ` · ${other.org_name}` : ""}${other.district ? ` · ${other.district}` : ""}` : "—";
  const myTurn = r.awaiting === side;
  const post = (action, body = {}) => api(`/purchase-requests/${r.id}/${action}`, { method: "POST", body });

  const actions = el("div", { class: "item__actions" });
  if (myTurn) {
    actions.append(
      actionButton(
        t("deals.accept"),
        async () => {
          await post("accept");
          done("deals.accepted");
          reload();
        },
        { kind: "primary", onError: fail },
      ),
    );
  }
  if (side === "farmer" && myTurn) {
    actions.append(
      actionButton(
        t("deals.reject"),
        async () => {
          if (!confirm(t("deals.confirm_reject"))) return;
          await post("reject");
          reload();
        },
        { kind: "danger", onError: fail },
      ),
    );
  }
  if (side === "distributor" && ["pending", "countered"].includes(r.status)) {
    actions.append(
      actionButton(
        t("deals.withdraw"),
        async () => {
          if (!confirm(t("deals.confirm_withdraw"))) return;
          await post("withdraw");
          reload();
        },
        { kind: "danger", onError: fail },
      ),
    );
  }

  return el(
    "li",
    { class: "card stack" },
    el(
      "div",
      { class: "item__head" },
      el("strong", { text: `${commodity(r.commodity)}${r.variety ? ` · ${r.variety}` : ""}` }),
      statusBadge("request", r.status),
    ),
    el("p", { class: "muted", text: who }),
    el(
      "dl",
      { class: "dl" },
      el("dt", { text: t("common.quantity") }),
      el("dd", { text: fmtQtyBoth(r.qty_kg, r.display_unit) }),
      el("dt", { text: t("deals.delivery") }),
      el("dd", { text: t(`deals.mode_${r.delivery_mode}`) }),
      r.needed_by ? [el("dt", { text: t("deals.needed_by") }), el("dd", { text: fmtDate(r.needed_by) })] : null,
    ),
    el(
      "div",
      { class: "row" },
      priceBlock("prices.offered", r.offered_price_paise_per_quintal),
      priceBlock("prices.asking", r.asking_price_paise_per_quintal),
    ),
    r.awaiting ? el("p", { class: "hint", text: myTurn ? t("deals.your_turn") : t("deals.their_turn") }) : null,
    contactBlock(other),
    historyList(r.history, "request"),
    actions.childElementCount ? actions : null,
    myTurn ? counterForm(r, reload) : null,
  );
}

const ORDER_ACTIONS = {
  farmer: { confirmed: ["dispatch", "cancel"], delivered: ["close"] },
  distributor: { confirmed: ["cancel"], dispatched: ["deliver"], delivered: ["close"] },
};

export function orderCard(o, side, reload) {
  const other = side === "farmer" ? o.distributor : o.farmer;
  const actions = (ORDER_ACTIONS[side][o.status] ?? []).map((action) =>
    actionButton(
      t(`orders.${action}`),
      async () => {
        if (action === "cancel" && !confirm(t("orders.confirm_cancel"))) return;
        await api(`/orders/${o.id}/${action}`, { method: "POST", body: {} });
        done(`orders.done_${action}`);
        reload();
      },
      { kind: action === "cancel" ? "danger" : "primary", onError: fail },
    ),
  );
  return el(
    "li",
    { class: "card stack" },
    el(
      "div",
      { class: "item__head" },
      el("strong", { text: `${commodity(o.commodity)}${o.variety ? ` · ${o.variety}` : ""} · ${o.district}` }),
      statusBadge("order", o.status),
    ),
    el(
      "dl",
      { class: "dl" },
      el("dt", { text: t("common.quantity") }),
      el("dd", { text: fmtQtyBoth(o.qty_kg, o.display_unit) }),
      el("dt", { text: t("orders.total") }),
      el("dd", { text: fmtMoney(o.total_paise) }),
      el("dt", { text: t("deals.delivery") }),
      el("dd", { text: t(`deals.mode_${o.delivery_mode}`) }),
    ),
    priceBlock("prices.agreed", o.agreed_price_paise_per_quintal, true),
    o.batch_id ? el("a", { href: `/batch.html?id=${o.batch_id}`, text: t("chain.trace") }) : null,
    el("p", { class: "hint", text: t("orders.offline_payment") }),
    contactBlock(other),
    historyList(o.history, "order"),
    actions.length ? el("div", { class: "item__actions" }, actions) : null,
  );
}
