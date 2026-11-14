// Notification bell + WebSocket client. Other modules listen for "irminsul:ws" events.
import { api } from "../api.js";
import { commodity, fmtQty } from "../format.js";
import { fmtDateTime, t } from "../i18n.js";
import { el, toast } from "./dom.js";

let items = [];
let unread = 0;
let countEl;
let panel;
let socket;
let retry = 1000;

export function notificationText(n) {
  const p = { ...n.params };
  if (p.commodity) p.commodity = commodity(p.commodity);
  if (p.kind) p.kind = t(`freshtrack.kind_${p.kind}`);
  if (p.severity) p.severity = t(`severity.${p.severity}`);
  if (p.qty_kg !== undefined) p.qty = fmtQty(p.qty_kg);
  return t(`notifications.${n.kind}`, p);
}

function renderCount() {
  countEl.hidden = unread === 0;
  countEl.textContent = unread > 99 ? "99+" : String(unread);
}

function renderPanel() {
  const list = items.length
    ? el(
        "ul",
        {},
        items.map((n) =>
          el(
            "li",
            { dataset: { unread: String(!n.read) } },
            n.link ? el("a", { href: n.link, text: notificationText(n) }) : notificationText(n),
            el("div", { class: "hint", text: fmtDateTime(n.created_at) }),
          ),
        ),
      )
    : el("p", { class: "muted", text: t("notifications.empty") });
  const markAll = el("button", { class: "btn", type: "button", text: t("notifications.mark_all") });
  markAll.addEventListener("click", async () => {
    await api("/notifications/read", { method: "POST", body: {} }).catch(() => {});
    items = items.map((n) => ({ ...n, read: true }));
    unread = 0;
    renderCount();
    renderPanel();
  });
  panel.replaceChildren(el("div", { class: "row item__head" }, el("strong", { text: t("notifications.title") }), markAll), list);
}

async function refresh() {
  try {
    const res = await api("/notifications?limit=20");
    items = res.data;
    unread = res.meta.unread;
    renderCount();
    if (!panel.hidden) renderPanel();
  } catch {
    /* bell stays as is */
  }
}

function connect() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  socket = new WebSocket(`${proto}://${location.host}/ws`);
  socket.addEventListener("open", () => {
    retry = 1000;
    refresh();
  });
  socket.addEventListener("message", (ev) => {
    let msg;
    try {
      msg = JSON.parse(ev.data);
    } catch {
      return;
    }
    if (msg.type === "notification") {
      items = [msg.data, ...items].slice(0, 20);
      unread += 1;
      renderCount();
      if (!panel.hidden) renderPanel();
      toast(notificationText(msg.data), "info");
    }
    document.dispatchEvent(new CustomEvent("irminsul:ws", { detail: msg }));
  });
  socket.addEventListener("close", () => {
    setTimeout(connect, retry);
    retry = Math.min(retry * 2, 30000);
  });
}

/** Bell button for the header (active users only). */
export function bell() {
  countEl = el("span", { class: "bell__count", hidden: true });
  const button = el(
    "button",
    { class: "btn bell", type: "button", "aria-haspopup": "true", "aria-expanded": "false", "data-i18n-aria-label": "notifications.title" },
    "🔔",
    countEl,
  );
  panel = el("div", { class: "notif-panel", hidden: true });
  button.addEventListener("click", () => {
    panel.hidden = !panel.hidden;
    button.setAttribute("aria-expanded", String(!panel.hidden));
    if (!panel.hidden) renderPanel();
  });
  document.addEventListener("click", (ev) => {
    if (!panel.hidden && !panel.contains(ev.target) && !button.contains(ev.target)) {
      panel.hidden = true;
      button.setAttribute("aria-expanded", "false");
    }
  });
  document.documentElement.addEventListener("langchange", () => {
    if (!panel.hidden) renderPanel();
  });
  refresh();
  connect();
  return { button, panel };
}
