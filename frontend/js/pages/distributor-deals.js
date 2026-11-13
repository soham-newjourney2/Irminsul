// Distributor: my purchase requests and orders.
import { api } from "../api.js";
import { el } from "../ui/dom.js";
import { mountShell } from "../ui/shell.js";
import { setupTabs } from "../ui/tabs.js";
import { list } from "./common.js";
import { orderCard, requestCard } from "./deals.js";

const me = await mountShell({ role: "distributor" });
const panel = document.getElementById("panel");
let reloadList = null;

function show(tab) {
  const host = el("div");
  panel.replaceChildren(host);
  reloadList =
    tab === "requests"
      ? () => list(host, async () => (await api("/purchase-requests")).data, (rows) => el("ul", { class: "item-list" }, rows.map((r) => requestCard(r, "distributor", reloadList))), "deals.empty_requests")
      : () => list(host, async () => (await api("/orders")).data, (rows) => el("ul", { class: "item-list" }, rows.map((o) => orderCard(o, "distributor", reloadList))), "orders.empty");
  reloadList();
}

if (me.status === "active") {
  const tabs = setupTabs(show);
  document.documentElement.addEventListener("langchange", () => show(tabs.current()));
  document.addEventListener("irminsul:ws", (ev) => {
    if (ev.detail.type === "notification") reloadList?.();
  });
}
