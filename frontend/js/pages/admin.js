import { api } from "../api.js";
import { errorMessage, fmtDateTime, t } from "../i18n.js";
import { el, emptyState, errorState, loadingState, toast } from "../ui/dom.js";
import { mountShell } from "../ui/shell.js";

await mountShell({ role: "admin" });

const panel = document.getElementById("panel");
const tabs = [...document.querySelectorAll("[role=tab]")];
const usersFilter = document.getElementById("users-filter");
const statusFilter = document.getElementById("status-filter");
let current = "pending";
let controller;

function badge(status) {
  return el("span", { class: "badge", dataset: { status }, text: t(`status.${status}`) });
}

function userItem(u, { actions }) {
  const details = el(
    "dl",
    { class: "dl" },
    el("dt", { text: t("home.email") }),
    el("dd", { text: u.email }),
    el("dt", { text: t("home.role") }),
    el("dd", { text: t(`roles.${u.role}`) }),
    u.org ? [el("dt", { text: t("home.org") }), el("dd", { text: u.org.name })] : null,
    el("dt", { text: t("admin.registered") }),
    el("dd", { text: fmtDateTime(u.created_at) }),
  );
  const li = el(
    "li",
    { class: "card" },
    el("div", { class: "item__head" }, el("strong", { text: u.name }), badge(u.status)),
    details,
  );
  if (actions && u.status === "pending") li.append(decisionControls(u));
  return li;
}

function decisionControls(u) {
  const reason = el("input", {
    class: "input",
    maxlength: "300",
    placeholder: t("admin.reject_reason"),
    "aria-label": t("admin.reject_reason"),
  });
  const approve = el("button", { class: "btn btn--primary", type: "button", text: t("admin.approve") });
  const reject = el("button", { class: "btn btn--danger", type: "button", text: t("admin.reject") });
  const box = el("div", { class: "stack item__actions" }, reason, el("div", { class: "row" }, approve, reject));

  async function decide(kind) {
    approve.disabled = reject.disabled = true;
    try {
      const body = kind === "reject" ? { reason: reason.value.trim() || null } : undefined;
      await api(`/admin/users/${u.id}/${kind}`, { method: "POST", body });
      toast(t(kind === "approve" ? "admin.approved_toast" : "admin.rejected_toast", { name: u.name }));
      load();
    } catch (err) {
      toast(errorMessage(err), "error");
      approve.disabled = reject.disabled = false;
    }
  }
  approve.addEventListener("click", () => decide("approve"));
  reject.addEventListener("click", () => {
    if (confirm(t("admin.confirm_reject", { name: u.name }))) decide("reject");
  });
  return box;
}

function auditItem(row) {
  const key = `audit.${row.action}`;
  const label = t(key) === key ? row.action : t(key);
  return el(
    "li",
    { class: "card" },
    el("div", { class: "item__head" }, el("strong", { text: label }), el("span", { class: "muted", text: fmtDateTime(row.created_at) })),
    el(
      "dl",
      { class: "dl" },
      el("dt", { text: t("admin.actor") }),
      el("dd", { text: row.actor_id }),
      el("dt", { text: t("admin.target") }),
      el("dd", { text: `${row.target_type} ${row.target_id}` }),
      row.details?.reason ? [el("dt", { text: t("admin.reason") }), el("dd", { text: row.details.reason })] : null,
    ),
  );
}

async function load() {
  controller?.abort();
  controller = new AbortController();
  const { signal } = controller;
  panel.replaceChildren(loadingState(t("common.loading")));
  usersFilter.hidden = current !== "users";
  try {
    if (current === "audit") {
      const { data } = await api("/admin/audit-logs?limit=100", { signal });
      panel.replaceChildren(
        data.length ? el("ul", { class: "item-list" }, data.map(auditItem)) : emptyState(t("admin.empty_audit")),
      );
      return;
    }
    const status = current === "pending" ? "pending" : statusFilter.value;
    const qs = new URLSearchParams({ limit: "100", ...(status ? { status } : {}) });
    const { data } = await api(`/admin/users?${qs}`, { signal });
    const emptyKey = current === "pending" ? "admin.empty_pending" : "admin.empty_users";
    panel.replaceChildren(
      data.length
        ? el("ul", { class: "item-list" }, data.map((u) => userItem(u, { actions: current === "pending" })))
        : emptyState(t(emptyKey)),
    );
  } catch (err) {
    if (err.name === "AbortError") return;
    panel.replaceChildren(errorState(errorMessage(err), load, t("common.retry")));
  }
}

for (const tab of tabs) {
  tab.addEventListener("click", () => {
    current = tab.dataset.tab;
    for (const other of tabs) other.setAttribute("aria-selected", String(other === tab));
    load();
  });
}
statusFilter.addEventListener("change", load);
document.documentElement.addEventListener("langchange", load);
load();
