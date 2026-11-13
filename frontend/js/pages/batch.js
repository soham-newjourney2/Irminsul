// Authenticated batch view: timeline, chain verification, QR, split, corrections.
import { api } from "../api.js";
import { commodity, demoBadge, fmtDate, fmtQtyBoth } from "../format.js";
import { errorMessage, t } from "../i18n.js";
import { el, errorState, field, loadingState } from "../ui/dom.js";
import { mountShell } from "../ui/shell.js";
import { done, fail, input, unitSelect } from "./common.js";
import { batchStatusBadge, chainStatus, timeline } from "./chain-ui.js";

const me = await mountShell({});
const root = document.getElementById("root");
const batchId = new URLSearchParams(location.search).get("id");

function qrBlock(b) {
  const img = el("img", { src: `/api/v1/batches/${b.id}/qr.png`, alt: t("chain.qr_alt", { code: b.batch_code }), width: "220", height: "220" });
  const link = el("a", { target: "_blank", rel: "noopener" });
  api(`/batches/${b.id}/qr`).then(({ data }) => {
    link.href = data.url;
    link.textContent = t("chain.public_page");
  }).catch(() => {});
  return el(
    "section",
    { class: "card stack" },
    el("h2", { text: t("chain.qr_title") }),
    el("p", { class: "muted", text: t("chain.qr_hint") }),
    img,
    el("div", { class: "row" }, link, el("button", { class: "btn", type: "button", text: t("chain.print"), onclick: () => print() })),
  );
}

function splitForm(b, reload) {
  const parts = input("parts", { required: true, placeholder: "6, 4", pattern: "^\\s*\\d+(\\.\\d+)?(\\s*,\\s*\\d+(\\.\\d+)?)+\\s*$" });
  const unit = unitSelect({ value: b.display_unit });
  const form = el(
    "form",
    { class: "stack" },
    el("div", { class: "inline-fields" }, field(t("chain.split_parts"), parts, t("chain.split_hint")), field(t("common.unit"), unit)),
    el("button", { class: "btn btn--primary", type: "submit", text: t("chain.split") }),
  );
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    if (!form.reportValidity()) return;
    try {
      await api(`/batches/${b.id}/split`, { method: "POST", body: { parts: parts.value.split(",").map((s) => s.trim()), unit: unit.value } });
      done("chain.split_done");
      reload();
    } catch (err) {
      fail(err);
    }
  });
  return el("details", { class: "panel" }, el("summary", { text: t("chain.split") }), el("div", { class: "panel__body" }, form));
}

function correctionForm(b, e, reload) {
  if (e.type === "correction") return null;
  const reason = input("reason", { required: true, minlength: "3", maxlength: "300" });
  const key = input("key", { maxlength: "40", placeholder: "qty_kg" });
  const value = input("value", { maxlength: "200" });
  const form = el(
    "form",
    { class: "stack" },
    field(t("storage.reason"), reason),
    el("div", { class: "inline-fields" }, field(t("chain.field"), key), field(t("chain.value"), value)),
    el("button", { class: "btn", type: "submit", text: t("chain.add_correction") }),
  );
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    if (!form.reportValidity()) return;
    const corrected = key.value ? { [key.value]: Number.isNaN(Number(value.value)) || value.value === "" ? value.value : Number(value.value) } : {};
    try {
      await api(`/batches/${b.id}/events/${e.seq}/correct`, { method: "POST", body: { reason: reason.value, corrected } });
      done("chain.correction_done");
      reload();
    } catch (err) {
      fail(err);
    }
  });
  return el("details", {}, el("summary", { class: "hint", text: t("chain.correct") }), form);
}

async function load() {
  if (!batchId) {
    root.replaceChildren(errorState(t("errors.not_found")));
    return;
  }
  root.replaceChildren(loadingState(t("common.loading")));
  let b;
  try {
    b = (await api(`/batches/${batchId}`)).data;
  } catch (err) {
    root.replaceChildren(errorState(errorMessage(err), load, t("common.retry")));
    return;
  }
  const statusHost = el("div");
  const verifyBtn = el("button", { class: "btn", type: "button", text: t("chain.verify_now") });
  const runVerify = async () => {
    verifyBtn.disabled = true;
    try {
      statusHost.replaceChildren(chainStatus((await api(`/batches/${b.id}/verify`)).data));
    } catch (err) {
      fail(err);
    } finally {
      verifyBtn.disabled = false;
    }
  };
  verifyBtn.addEventListener("click", runVerify);

  const owner = b.is_mine;
  root.replaceChildren(
    el("div", { class: "item__head" }, el("h1", { text: b.batch_code }), el("span", { class: "row" }, demoBadge(b.is_demo), batchStatusBadge(b.status))),
    el(
      "dl",
      { class: "dl card" },
      el("dt", { text: t("common.crop") }),
      el("dd", { text: `${commodity(b.commodity)}${b.variety ? ` · ${b.variety}` : ""}` }),
      el("dt", { text: t("common.quantity") }),
      el("dd", { text: fmtQtyBoth(b.qty_kg, b.display_unit) }),
      el("dt", { text: t("sell.harvest_date") }),
      el("dd", { text: fmtDate(b.harvest_date) }),
      el("dt", { text: t("common.district") }),
      el("dd", { text: b.district }),
      el("dt", { text: t("chain.custodian") }),
      el("dd", { text: b.custodian.name ?? t(`chain.custodian_${b.custodian.type}`) }),
      b.parent ? [el("dt", { text: t("chain.split_from") }), el("dd", {}, el("a", { href: `/batch.html?id=${b.parent.id}`, text: b.parent.batch_code }))] : null,
      b.children.length
        ? [el("dt", { text: t("chain.split_into") }), el("dd", {}, b.children.flatMap((c, i) => [i ? ", " : "", el("a", { href: `/batch.html?id=${c.id}`, text: c.batch_code })]))]
        : null,
    ),
    el("section", { class: "stack" }, el("div", { class: "row" }, el("h2", { text: t("chain.integrity") }), verifyBtn), statusHost),
    owner || me.role === "admin" ? qrBlock(b) : null,
    owner && b.status === "active" ? splitForm(b, load) : null,
    el("h2", { text: t("chain.timeline") }),
    timeline(b.events, { showHashes: true, extra: owner || me.role === "admin" ? (e) => correctionForm(b, e, load) : null }),
  );
  runVerify();
}

if (me.status === "active") {
  load();
  document.documentElement.addEventListener("langchange", load);
} else {
  root.replaceChildren(el("div", { class: "alert alert--warn", text: t("errors.account_pending") }));
}
