// Storage operator: booking decisions, check-in, release.
import { api } from "../api.js";
import { t } from "../i18n.js";
import { el, field } from "../ui/dom.js";
import { mountShell } from "../ui/shell.js";
import { list } from "./common.js";
import { bookingCard } from "./facility-ui.js";

const me = await mountShell({ role: "storage_operator" });
const root = document.getElementById("root");
const zoneCache = new Map();

function zonesFor(facilityId) {
  if (!zoneCache.has(facilityId)) {
    zoneCache.set(facilityId, api(`/storage/facilities/${facilityId}/zones`).then((r) => r.data).catch(() => []));
  }
  return zoneCache.get(facilityId);
}

const STATUSES = ["requested", "changes_requested", "accepted", "checked_in", "released", "rejected", "cancelled"];

function render() {
  const status = el(
    "select",
    { class: "select select--compact", name: "status" },
    el("option", { value: "", text: t("common.all") }),
    STATUSES.map((s) => el("option", { value: s, text: t(`status_booking.${s}`) })),
  );
  status.value = "requested";
  const host = el("div");
  const load = () => {
    const qs = new URLSearchParams(status.value ? { status: status.value } : {});
    return list(host, async () => (await api(`/storage/bookings?${qs}`)).data, (rows) => el("ul", { class: "item-list" }, rows.map((b) => bookingCard(b, "storage_operator", load, zonesFor))), "bookings.empty");
  };
  status.addEventListener("change", load);
  root.replaceChildren(el("h1", { text: t("bookings.title") }), el("div", { class: "row" }, field(t("storage.status"), status)), host);
  load();
  document.addEventListener("irminsul:ws", (ev) => {
    if (ev.detail.type === "notification" && ev.detail.data.kind.startsWith("booking.")) load();
  });
}

if (me.status === "active") {
  render();
  document.documentElement.addEventListener("langchange", () => location.reload());
}
