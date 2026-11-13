// Tiny DOM helpers. Always set text via textContent (never innerHTML with data).

export function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else if (k.startsWith("on") && typeof v === "function") node.addEventListener(k.slice(2), v);
    else if (k === "dataset") Object.assign(node.dataset, v);
    else node.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    node.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return node;
}

export function loadingState(label) {
  return el("div", { class: "state", role: "status" }, el("div", { class: "spinner" }), label);
}

export function emptyState(label) {
  return el("div", { class: "state" }, label);
}

export function errorState(message, onRetry, retryLabel) {
  return el(
    "div",
    { class: "alert alert--error", role: "alert" },
    el("p", { text: message }),
    onRetry ? el("button", { class: "btn", type: "button", onclick: onRetry, text: retryLabel }) : null,
  );
}

let toastTimer;
export function toast(message, kind = "ok") {
  document.querySelector(".toast")?.remove();
  const node = el("div", { class: `toast alert alert--${kind}`, role: "status" }, message);
  document.body.append(node);
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => node.remove(), 4000);
}
