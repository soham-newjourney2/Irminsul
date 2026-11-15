// data-i18n keys + locale JSON. Numbers/dates via Intl.

export const LANGS = ["en", "bn", "hi"];
const INTL_TAG = { en: "en-IN", bn: "bn-IN", hi: "hi-IN" };
const STORE_KEY = "irminsul.lang";

let lang = "en";
let dict = {};
let fallback = {};
const cache = {};

function stored() {
  try {
    return localStorage.getItem(STORE_KEY);
  } catch {
    return null;
  }
}

function remember(l) {
  try {
    localStorage.setItem(STORE_KEY, l);
  } catch {
    /* storage unavailable */
  }
}

async function load(l) {
  if (!cache[l]) {
    const res = await fetch(`/locales/${l}.json`);
    cache[l] = res.ok ? await res.json() : {};
  }
  return cache[l];
}

function lookup(d, key) {
  return key.split(".").reduce((o, k) => (o && typeof o === "object" ? o[k] : undefined), d);
}

function pickLang(preferred) {
  const browser = (navigator.language || "en").slice(0, 2);
  return [preferred, stored(), browser].find((l) => LANGS.includes(l)) ?? "en";
}

export const currentLang = () => lang;

export function t(key, vars = {}) {
  const raw = lookup(dict, key) ?? lookup(fallback, key);
  if (typeof raw !== "string") return key;
  return raw.replace(/\{(\w+)\}/g, (_, k) => (k in vars ? String(vars[k]) : `{${k}}`));
}

export function has(key) {
  return typeof (lookup(dict, key) ?? lookup(fallback, key)) === "string";
}

export function apply(root = document) {
  for (const el of root.querySelectorAll("[data-i18n]")) el.textContent = t(el.dataset.i18n);
  for (const attr of ["placeholder", "title", "aria-label"]) {
    const data = `i18n${attr.replace(/(^|-)(\w)/g, (_, __, c) => c.toUpperCase())}`;
    for (const el of root.querySelectorAll(`[data-i18n-${attr}]`)) {
      el.setAttribute(attr, t(el.dataset[data]));
    }
  }
}

export async function setLang(l) {
  lang = LANGS.includes(l) ? l : "en";
  remember(lang);
  fallback = await load("en");
  dict = lang === "en" ? fallback : await load(lang);
  document.documentElement.lang = lang;
  apply();
  // Pages that render text with t() re-render on this event.
  document.documentElement.dispatchEvent(new CustomEvent("langchange", { detail: { lang } }));
}

export async function initI18n(preferred) {
  await setLang(pickLang(preferred));
}

export function errorMessage(err) {
  const key = `errors.${err?.code}`;
  return has(key) ? t(key) : t("errors.generic");
}

export function fmtDateTime(value) {
  return new Intl.DateTimeFormat(INTL_TAG[lang], { dateStyle: "medium", timeStyle: "short" }).format(
    new Date(value),
  );
}

export function fmtNumber(value, opts = {}) {
  return new Intl.NumberFormat(INTL_TAG[lang], opts).format(value);
}
