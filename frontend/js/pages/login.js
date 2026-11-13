import { api } from "../api.js";
import { HOME, safeNext } from "../auth.js";
import { errorMessage, t } from "../i18n.js";
import { mountShell } from "../ui/shell.js";

const me = await mountShell({ public: true });
if (me) location.replace(HOME[me.role]);

const form = document.getElementById("login-form");
const errorBox = document.getElementById("form-error");
const submit = form.querySelector("button[type=submit]");

function showError(message) {
  errorBox.textContent = message;
  errorBox.hidden = false;
}

form.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  errorBox.hidden = true;
  const phone = form.phone.value.trim();
  const password = form.password.value;
  if (!phone || !password) return showError(t("validation.required"));

  submit.disabled = true;
  try {
    const { data } = await api("/auth/login", { method: "POST", body: { phone, password } });
    location.replace(safeNext(HOME[data.role]));
  } catch (err) {
    showError(errorMessage(err));
    submit.disabled = false;
  }
});
