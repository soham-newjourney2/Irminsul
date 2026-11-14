// Role home (farmer / distributor / storage operator). Module pages arrive in later milestones.
import { t } from "../i18n.js";
import { el } from "../ui/dom.js";
import { mountShell } from "../ui/shell.js";

const role = document.body.dataset.role;
const me = await mountShell({ role });

function render() {
  document.getElementById("welcome").textContent = t("home.welcome", { name: me.name });
  const badge = el("span", {
    class: "badge",
    dataset: { status: me.status, i18n: `status.${me.status}` },
    text: t(`status.${me.status}`),
  });
  const rows = [
    ["home.email", me.email],
    ["home.role", t(`roles.${me.role}`)],
    me.org ? ["home.org", me.org.name] : null,
    ["home.status", badge],
  ].filter(Boolean);
  document
    .getElementById("account")
    .replaceChildren(...rows.flatMap(([k, v]) => [el("dt", { "data-i18n": k, text: t(k) }), el("dd", {}, v)]));
}

if (me.status === "active") {
  render();
  document.documentElement.addEventListener("langchange", render);
}
