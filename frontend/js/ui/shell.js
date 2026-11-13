// Shared shell: header, role nav, language switcher, connectivity, pending gate.
import { api } from "../api.js";
import { HOME, getMe, logout } from "../auth.js";
import { LANGS, apply, initI18n, setLang, t } from "../i18n.js";
import { el } from "./dom.js";
import { bell } from "./notify.js";

// Nav grows as milestones add pages. Keys are locale keys.
const NAV = {
  farmer: [
    { href: "/farmer/", key: "nav.home" },
    { href: "/farmer/farms.html", key: "nav.farms" },
    { href: "/farmer/batches.html", key: "nav.batches" },
    { href: "/farmer/sell.html", key: "nav.sell" },
    { href: "/farmer/storage.html", key: "nav.storage" },
  ],
  distributor: [
    { href: "/distributor/", key: "nav.home" },
    { href: "/distributor/market.html", key: "nav.market" },
    { href: "/distributor/deals.html", key: "nav.deals" },
  ],
  storage_operator: [
    { href: "/storage/", key: "nav.home" },
    { href: "/storage/facilities.html", key: "nav.facilities" },
    { href: "/storage/bookings.html", key: "nav.bookings" },
  ],
  admin: [{ href: "/admin/", key: "nav.approvals" }],
};

const LANG_LABEL = { en: "English", bn: "বাংলা", hi: "हिन्दी" };

function connIndicator() {
  const node = el("span", { class: "conn", "aria-live": "polite" });
  const update = () => {
    const online = navigator.onLine;
    node.dataset.state = online ? "online" : "offline";
    node.dataset.i18n = online ? "common.online" : "common.offline";
    node.textContent = t(node.dataset.i18n);
  };
  addEventListener("online", update);
  addEventListener("offline", update);
  update();
  return node;
}

function langSelect(me) {
  const select = el(
    "select",
    { class: "select select--compact", "data-i18n-aria-label": "common.language" },
    LANGS.map((l) => el("option", { value: l, text: LANG_LABEL[l] })),
  );
  select.value = document.documentElement.lang || "en";
  select.addEventListener("change", async () => {
    await setLang(select.value);
    if (me) api("/users/me", { method: "PATCH", body: { language: select.value } }).catch(() => {});
  });
  return select;
}

function renderHeader(me) {
  const host = document.getElementById("app-header");
  if (!host) return;
  const links = (me && me.status === "active" ? NAV[me.role] : []) ?? [];
  const here = location.pathname;
  const notifications = me && me.status === "active" ? bell() : null;
  host.className = "app-header";
  host.replaceChildren(
    el(
      "div",
      { class: "app-header__inner" },
      el("a", { class: "brand", href: me ? HOME[me.role] : "/", "data-i18n": "app.name" }),
      links.length
        ? el(
            "nav",
            { class: "nav", "data-i18n-aria-label": "nav.label" },
            links.map((l) =>
              el("a", {
                href: l.href,
                "data-i18n": l.key,
                "aria-current": here === l.href ? "page" : null,
              }),
            ),
          )
        : null,
      el(
        "div",
        { class: "header-tools" },
        connIndicator(),
        notifications?.button,
        langSelect(me),
        me
          ? el("button", {
              class: "btn",
              type: "button",
              "data-i18n": "common.logout",
              onclick: logout,
            })
          : null,
      ),
      notifications?.panel,
    ),
  );
}

function showPending(me) {
  const main = document.getElementById("app-main");
  if (main) main.hidden = true;
  const box = el(
    "main",
    { class: "container narrow stack", id: "pending-view" },
    el("h1", { "data-i18n": "pending.title" }),
    el("div", { class: "alert alert--warn" }, el("p", { "data-i18n": "pending.body" })),
    el(
      "dl",
      { class: "dl card" },
      el("dt", { "data-i18n": "home.role" }),
      el("dd", { "data-i18n": `roles.${me.role}` }),
      el("dt", { "data-i18n": "home.org" }),
      el("dd", { text: me.org?.name ?? "—" }),
      el("dt", { "data-i18n": "home.status" }),
      el("dd", {}, el("span", { class: "badge", dataset: { status: me.status }, "data-i18n": `status.${me.status}` })),
    ),
  );
  document.getElementById("app-header")?.after(box);
}

/**
 * Mount the shell. `role` restricts the page; `public: true` allows anonymous visitors.
 * Returns the current user (or null on public pages) once i18n is applied.
 */
export async function mountShell({ role = null, public: isPublic = false } = {}) {
  let me = null;
  try {
    me = await getMe();
  } catch {
    me = null; // network/DB errors: render the page in a logged-out state
  }
  if (!me && !isPublic) {
    location.replace(`/login.html?next=${encodeURIComponent(location.pathname)}`);
    return new Promise(() => {});
  }
  if (me && role && me.role !== role) {
    location.replace(HOME[me.role]);
    return new Promise(() => {});
  }
  await initI18n(me?.language);
  renderHeader(me);
  if (me && role && me.status !== "active") showPending(me);
  apply();
  return me;
}
