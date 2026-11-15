// Farmer: forecast + sourced crop advisories for a farm.
import { api } from "../api.js";
import { commodity, fmtDate, fmtNum } from "../format.js";
import { errorMessage, fmtDateTime, t } from "../i18n.js";
import { el, errorState, field, loadingState } from "../ui/dom.js";
import { mountShell } from "../ui/shell.js";
import { guidanceCard } from "./guidance-ui.js";

const me = await mountShell({ role: "farmer" });
const root = document.getElementById("root");
const TONE = { critical: "danger", warning: "warn", info: "info" };

function forecastCard(w) {
  return el(
    "section",
    { class: "card stack" },
    el(
      "div",
      { class: "item__head" },
      el("h2", { text: t("weather.forecast") }),
      el(
        "span",
        { class: "row" },
        el("span", { class: "badge", dataset: { tone: "info" }, text: t("badges.forecast") }),
        w.stale ? el("span", { class: "badge", dataset: { tone: "warn" }, text: t("badges.stale") }) : null,
        w.cached ? el("span", { class: "badge", text: t("badges.cached_at", { time: fmtDateTime(w.fetched_at) }) }) : null,
      ),
    ),
    el(
      "div",
      { class: "table-wrap" },
      el(
        "table",
        { class: "table" },
        el("thead", {}, el("tr", {}, el("th", { text: t("weather.date") }), el("th", { class: "num", text: t("weather.rain") }), el("th", { class: "num", text: t("weather.tmax") }), el("th", { class: "num", text: t("weather.tmin") }))),
        el(
          "tbody",
          {},
          w.daily.map((d) =>
            el("tr", {}, el("td", { text: fmtDate(d.date) }), el("td", { class: "num", text: `${fmtNum(d.precipitation_mm ?? 0, 1)} mm` }), el("td", { class: "num", text: `${fmtNum(d.temp_max_c, 1)} °C` }), el("td", { class: "num", text: `${fmtNum(d.temp_min_c, 1)} °C` })),
          ),
        ),
      ),
    ),
    el("p", { class: "hint", text: `${w.attribution} · ${t("weather.fetched", { time: fmtDateTime(w.fetched_at) })}` }),
  );
}

function evidenceText(a) {
  const e = a.evidence;
  if (a.rule_id === "heavy_rain") return t("advisory.rain_evidence", { mm: fmtNum(e.precipitation_mm, 1), date: fmtDate(e.date), threshold: e.threshold_mm });
  const c = e.condition;
  const cond = [c.rh_min !== undefined ? `RH ≥ ${c.rh_min}%` : null, `${c.temp_min}–${c.temp_max} °C`].filter(Boolean).join(", ");
  return t("advisory.hours_evidence", { n: e.matching_hours, window: e.window_hours, cond, rain: fmtNum(e.rain_mm_in_window, 1) });
}

async function advisoryCard(a) {
  const title = a.rule_id === "heavy_rain" ? t(`advisory.rain_${a.label}`) : t("advisory.risk", { disease: t(`diseases.${a.disease}`), crop: commodity(a.crop) });
  const card = el(
    "li",
    { class: "card stack" },
    el(
      "div",
      { class: "item__head" },
      el("strong", { text: title }),
      el("span", { class: "row" }, el("span", { class: "badge", dataset: { tone: TONE[a.severity] ?? "info" }, text: t(`severity.${a.severity}`) }), a.verified ? null : el("span", { class: "badge", dataset: { tone: "warn" }, text: t("badges.unverified") })),
    ),
    el("p", { text: evidenceText(a) }),
    a.rule_id === "heavy_rain" ? null : el("p", { text: t("advisory.action") }),
    el("p", { class: "hint" }, `${t("guidance.source")}: `, el("a", { href: a.source.urls[0], target: "_blank", rel: "noopener noreferrer", text: a.source.org }), ` — “${a.source.quote}”`),
    el("details", {}, el("summary", { class: "hint", text: `${t("advisory.assumptions")} (${t("common.english_source")})` }), el("ul", { class: "history" }, a.assumptions.map((x) => el("li", { text: x })))),
  );
  if (a.guidance_key) {
    const holder = el("details", {}, el("summary", { text: t("advisory.open_guidance") }));
    holder.addEventListener("toggle", async () => {
      if (holder.open && holder.childElementCount === 1) holder.append((await guidanceCard(a.guidance_key)) ?? "");
    }, { once: false });
    card.append(holder);
  }
  return card;
}

async function show(host, farmId) {
  host.replaceChildren(loadingState(t("common.loading")));
  try {
    const [w, adv] = await Promise.all([api(`/weather?farm_id=${farmId}`), api(`/advisories?farm_id=${farmId}&crops=potato,tomato`)]);
    const cards = await Promise.all(adv.data.map(advisoryCard));
    host.replaceChildren(
      forecastCard(w.data),
      el("h2", { text: t("advisory.title") }),
      el("p", { class: "hint", text: t("advisory.disclaimer") }),
      cards.length ? el("ul", { class: "item-list" }, cards) : el("div", { class: "state", text: t("advisory.none") }),
    );
  } catch (err) {
    host.replaceChildren(errorState(errorMessage(err), () => show(host, farmId), t("common.retry")));
  }
}

async function render() {
  const farms = await api("/farms").then((r) => r.data).catch(() => []);
  if (!farms.length) {
    root.replaceChildren(el("h1", { text: t("weather.title") }), el("div", { class: "alert alert--info" }, t("sell.need_farm"), " ", el("a", { href: "/farmer/farms.html", text: t("nav.farms") })));
    return;
  }
  const farm = el("select", { class: "select" }, farms.map((f) => el("option", { value: f.id, text: `${f.name} · ${f.district}` })));
  const host = el("div", { class: "stack" });
  farm.addEventListener("change", () => show(host, farm.value));
  root.replaceChildren(el("h1", { text: t("weather.title") }), el("div", { class: "row" }, field(t("sell.farm"), farm)), host);
  show(host, farm.value);
}

if (me.status === "active") {
  render();
  document.documentElement.addEventListener("langchange", render);
}
