// Farmer: crop photo screening — "possible condition", never a diagnosis.
import { api, apiUpload, newIdempotencyKey } from "../api.js";
import { commodity, fmtNum } from "../format.js";
import { errorMessage, fmtDateTime, t } from "../i18n.js";
import { el, field } from "../ui/dom.js";
import { mountShell } from "../ui/shell.js";
import { batchSelect } from "./chain-ui.js";
import { fail, list } from "./common.js";
import { guidanceCard } from "./guidance-ui.js";

const me = await mountShell({ role: "farmer" });
const root = document.getElementById("root");
const SUPPORTED = ["potato", "tomato"];
const MAX_EDGE = 512;

/** Client-side resize to ~512 px JPEG; the server re-validates everything. */
async function resize(file) {
  const bitmap = await createImageBitmap(file);
  const scale = Math.min(1, MAX_EDGE / Math.max(bitmap.width, bitmap.height));
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(bitmap.width * scale);
  canvas.height = Math.round(bitmap.height * scale);
  canvas.getContext("2d").drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  bitmap.close();
  return new Promise((resolve, reject) => canvas.toBlob((b) => (b ? resolve(b) : reject(new Error("encode"))), "image/jpeg", 0.85));
}

const pct = (p) => `${fmtNum(p * 100, 0)}%`;

function resultCard(r) {
  const head =
    r.status === "ok"
      ? el("div", { class: "alert alert--warn" }, el("strong", { text: t(r.top[0].healthy ? "screen.looks_healthy" : "screen.possible", { name: t(`diseases.${r.top[0].disease}`) }) }), el("p", { text: t("screen.not_diagnosis") }))
      : el("div", { class: "alert alert--info" }, el("strong", { text: t("screen.unsure_title") }), el("p", { text: t(`screen.unsure_${r.reason}`, { crop: commodity(r.crop) }) }), el("p", { text: t("screen.unsure_next") }));
  return el(
    "section",
    { class: "card stack" },
    el("div", { class: "item__head" }, el("h2", { text: t("screen.result") }), el("span", { class: "badge", dataset: { tone: "info" }, text: t("badges.ai_possible") })),
    head,
    el(
      "table",
      { class: "table" },
      el("thead", {}, el("tr", {}, el("th", { text: t("screen.condition") }), el("th", { text: t("screen.probability") }))),
      el("tbody", {}, r.top.map((c) => el("tr", {}, el("td", { text: t(`diseases.${c.disease}`) }), el("td", { text: pct(c.probability) })))),
    ),
    el("p", { class: "hint", text: t("screen.meta", { threshold: pct(r.threshold), status: t(`screen.threshold_${r.threshold_status}`), model: r.model_version }) }),
    el("ul", { class: "history" }, r.limitations.map((k) => el("li", { text: t(`screen.lim_${k}`) }))),
    el("p", { class: "hint", text: t("screen.model_facts") }),
  );
}

async function render() {
  const crop = el("select", { class: "select", name: "crop" }, ["potato", "tomato", "rice", "jute"].map((c) => el("option", { value: c, text: SUPPORTED.includes(c) ? commodity(c) : `${commodity(c)} — ${t("screen.not_supported_short")}` })));
  const fileInput = el("input", { class: "input", type: "file", name: "image", accept: "image/jpeg,image/png,image/webp", capture: "environment", required: true });
  const preview = el("img", { alt: "", hidden: true, class: "preview-img" });
  const batches = await api("/batches").then((r) => r.data).catch(() => []);
  const batch = batchSelect(batches);
  const submit = el("button", { class: "btn btn--primary", type: "submit", text: t("screen.submit") });
  const out = el("div", { class: "stack" });
  const unsupported = el("div", { class: "alert alert--info", hidden: true, text: t("screen.crop_not_supported") });
  const form = el(
    "form",
    { class: "stack card" },
    el("div", { class: "alert alert--info", text: t("screen.tips") }),
    field(t("common.crop"), crop),
    unsupported,
    field(t("screen.photo"), fileInput, t("screen.photo_hint")),
    preview,
    field(t("chain.link_batch"), batch, t("chain.link_hint")),
    submit,
  );
  crop.addEventListener("change", () => {
    const ok = SUPPORTED.includes(crop.value);
    unsupported.hidden = ok;
    submit.disabled = !ok;
  });
  let blob = null;
  fileInput.addEventListener("change", async () => {
    const f = fileInput.files?.[0];
    if (!f) return;
    try {
      blob = await resize(f);
      preview.src = URL.createObjectURL(blob);
      preview.hidden = false;
    } catch {
      blob = null;
      fail({ code: "invalid_image" });
    }
  });
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    if (!blob) return fail({ code: "invalid_image" });
    submit.disabled = true;
    const fd = new FormData();
    fd.append("crop", crop.value);
    fd.append("image", blob, "leaf.jpg");
    if (batch.value) fd.append("batch_id", batch.value);
    try {
      const { data } = await apiUpload("/crop-screenings", fd, { idempotencyKey: newIdempotencyKey() });
      out.replaceChildren(resultCard(data));
      const g = data.status === "ok" && !data.top[0].healthy ? await guidanceCard(data.guidance_key) : null;
      if (g) out.append(g);
      else if (data.status === "ok" && !data.top[0].healthy) out.append(el("div", { class: "alert alert--info", text: t("guidance.none") }));
      loadHistory();
    } catch (err) {
      out.replaceChildren(el("div", { class: "alert alert--error", text: errorMessage(err) }));
    } finally {
      submit.disabled = false;
    }
  });

  const historyHost = el("div");
  const loadHistory = () =>
    list(historyHost, async () => (await api("/crop-screenings?limit=20")).data, (rows) =>
      el(
        "ul",
        { class: "item-list" },
        rows.map((r) =>
          el(
            "li",
            { class: "card row" },
            el("img", { src: `/api/v1/crop-screenings/${r.id}/image`, alt: "", width: "64", height: "64", class: "thumb" }),
            el("div", {}, el("strong", { text: r.status === "ok" ? t(`diseases.${r.top[0].disease}`) : t("screen.unsure_title") }), el("div", { class: "hint", text: `${commodity(r.crop)} · ${fmtDateTime(r.created_at)}` })),
          ),
        ),
      ), "screen.empty");

  root.replaceChildren(el("h1", { text: t("screen.title") }), form, out, el("h2", { text: t("screen.history") }), historyHost);
  loadHistory();
}

if (me.status === "active") {
  render();
  document.documentElement.addEventListener("langchange", render);
}
