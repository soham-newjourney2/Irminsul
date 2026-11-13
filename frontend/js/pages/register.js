import { api } from "../api.js";
import { HOME } from "../auth.js";
import { currentLang, errorMessage, t } from "../i18n.js";
import { mountShell } from "../ui/shell.js";

const me = await mountShell({ public: true });
if (me) location.replace(HOME[me.role]);

const form = document.getElementById("register-form");
const errorBox = document.getElementById("form-error");
const orgField = document.getElementById("org-field");
const orgLabel = document.getElementById("org-label");
const submit = form.querySelector("button[type=submit]");

// UX-only checks; the server is the source of truth.
const PHONE = /^(\+?91|0)?[6-9]\d{9}$/;
const ORG_LABEL = {
  distributor: "register.org_name_distributor",
  storage_operator: "register.org_name_storage",
};

function syncRole() {
  const role = form.role.value;
  const key = ORG_LABEL[role];
  orgField.hidden = !key;
  form.org_name.required = Boolean(key);
  if (key) {
    orgLabel.dataset.i18n = key;
    orgLabel.textContent = t(key);
  }
}

function showError(message) {
  errorBox.textContent = message;
  errorBox.hidden = false;
  errorBox.scrollIntoView({ block: "nearest" });
}

form.addEventListener("change", (ev) => {
  if (ev.target.name === "role") syncRole();
});
syncRole();

form.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  errorBox.hidden = true;
  const role = form.role.value;
  const body = {
    role,
    name: form.name.value.trim(),
    phone: form.phone.value.replace(/[\s-]/g, ""),
    password: form.password.value,
    language: currentLang(),
    org_name: ORG_LABEL[role] ? form.org_name.value.trim() : null,
  };
  if (!body.name || (ORG_LABEL[role] && !body.org_name)) return showError(t("validation.required"));
  if (!PHONE.test(body.phone)) return showError(t("validation.phone"));
  if (body.password.length < 8) return showError(t("validation.password"));

  submit.disabled = true;
  try {
    const { data } = await api("/auth/register", { method: "POST", body });
    location.replace(HOME[data.role]);
  } catch (err) {
    showError(errorMessage(err));
    submit.disabled = false;
  }
});
