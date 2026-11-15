// Public QR verify page — no login, no personal data.
import { api } from "../api.js";
import { commodity, fmtQty } from "../format.js";
import { errorMessage, t } from "../i18n.js";
import { el, errorState, loadingState } from "../ui/dom.js";
import { mountShell } from "../ui/shell.js";
import { batchStatusBadge, chainStatus, timeline } from "./chain-ui.js";

await mountShell({ public: true });
const root = document.getElementById("root");
const token = new URLSearchParams(location.search).get("t");

async function load() {
  if (!token) {
    root.replaceChildren(el("h1", { text: t("verify.title") }), errorState(t("verify.no_code")));
    return;
  }
  root.replaceChildren(loadingState(t("common.loading")));
  try {
    const b = (await api(`/qr/${encodeURIComponent(token)}`)).data;
    const [year, month] = b.harvest_month.split("-");
    const harvest = new Intl.DateTimeFormat(document.documentElement.lang || "en", { month: "long", year: "numeric" }).format(new Date(Number(year), Number(month) - 1, 1));
    root.replaceChildren(
      el("h1", { text: t("verify.title") }),
      chainStatus(b.chain),
      b.is_demo ? el("div", { class: "alert alert--info", text: t("verify.demo") }) : null,
      el(
        "section",
        { class: "card stack" },
        el("div", { class: "item__head" }, el("strong", { text: b.batch_code }), batchStatusBadge(b.status)),
        el(
          "dl",
          { class: "dl" },
          el("dt", { text: t("common.crop") }),
          el("dd", { text: `${commodity(b.commodity)}${b.variety ? ` · ${b.variety}` : ""}` }),
          el("dt", { text: t("common.district") }),
          el("dd", { text: b.district }),
          el("dt", { text: t("verify.harvested") }),
          el("dd", { text: harvest }),
          el("dt", { text: t("common.quantity") }),
          el("dd", { text: fmtQty(b.qty_kg) }),
        ),
      ),
      el("h2", { text: t("chain.timeline") }),
      timeline(b.events),
      el("p", { class: "hint", text: t("verify.privacy") }),
    );
  } catch (err) {
    root.replaceChildren(el("h1", { text: t("verify.title") }), errorState(err.status === 404 ? t("verify.unknown") : errorMessage(err), load, t("common.retry")));
  }
}

load();
document.documentElement.addEventListener("langchange", load);
