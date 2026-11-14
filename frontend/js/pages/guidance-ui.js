// Sourced guidance card (planning §4.5): always shows source, date and "not expert-reviewed".
import { api } from "../api.js";
import { currentLang, t } from "../i18n.js";
import { el } from "../ui/dom.js";

const pick = (obj) => (obj ? obj[currentLang()] ?? obj.en ?? [] : []);

export async function guidanceCard(key) {
  if (!key) return null;
  const [crop, disease] = key.split(".");
  let g;
  try {
    g = (await api(`/advisories/guidance/${crop}/${disease}`)).data;
  } catch {
    return el("div", { class: "alert alert--info", text: t("guidance.none") });
  }
  const e = g.entry;
  const list = (titleKey, items) =>
    items.length ? el("div", {}, el("strong", { text: t(titleKey) }), el("ul", { class: "history" }, items.map((x) => el("li", { text: x })))) : null;
  return el(
    "section",
    { class: "card stack" },
    el("div", { class: "item__head" }, el("h3", { text: pick(e.name) || e.disease }), el("span", { class: "badge", dataset: { tone: "warn" }, text: t("guidance.not_reviewed") })),
    list("guidance.symptoms", pick(e.symptoms)),
    list("guidance.conditions", pick(e.favourable_conditions)),
    list("guidance.cultural", pick(e.cultural_measures)),
    e.resistant_varieties?.length
      ? el("p", {}, el("strong", { text: `${t("guidance.varieties")}: ` }), e.resistant_varieties.join(", "), e.resistant_varieties_note ? el("span", { class: "hint", text: ` — ${t("guidance.varieties_note")}` }) : null)
      : null,
    e.chemical_names_in_source?.length
      ? el("p", { class: "hint" }, `${t("guidance.chemicals")}: ${e.chemical_names_in_source.join(", ")}. ${t("guidance.chemicals_note")}`)
      : null,
    el(
      "p",
      { class: "hint" },
      `${t("guidance.source")}: `,
      ...e.sources.flatMap((s, i) => [i ? "; " : "", el("a", { href: s.url, target: "_blank", rel: "noopener noreferrer", text: s.org }), ` (${t("guidance.retrieved")} ${s.retrieved})`]),
    ),
    currentLang() !== "en" ? el("p", { class: "hint", text: t("guidance.translation_draft") }) : null,
  );
}
