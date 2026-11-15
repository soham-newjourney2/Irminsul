// Explainable FreshTrack alert cards, shared by operator, farmer and admin views.
import { api } from "../api.js";
import { fmtNum } from "../format.js";
import { fmtDateTime, t } from "../i18n.js";
import { actionButton, el, field } from "../ui/dom.js";
import { done, fail, input } from "./common.js";

const TONE = { critical: "danger", warning: "warn", info: "info" };
const STATUS_TONE = { open: "danger", acknowledged: "warn", resolved: "muted" };

export function explain(a) {
  const p = a.profile ?? {};
  const band =
    a.metric === "temp_c" && p.temp_min_c != null
      ? `${fmtNum(p.temp_min_c, 1)}–${fmtNum(p.temp_max_c, 1)} °C`
      : a.metric === "rh_pct" && (p.rh_min != null || p.rh_max != null)
        ? `${p.rh_min ?? "—"}–${p.rh_max ?? "—"} %`
        : "—";
  const vars = {
    threshold: a.threshold != null ? fmtNum(a.threshold, 1) : "—",
    peak: a.peak != null ? fmtNum(a.peak, 1) : "—",
    minutes: fmtNum(a.duration_min, 0),
    band,
    profile: p.id ? t(`freshtrack.profile_${p.id}`) : (p.label ?? "—"),
    start: fmtDateTime(a.started_at),
    latest: fmtDateTime(a.latest_at),
    mean: a.details?.mean != null ? fmtNum(a.details.mean, 2) : "—",
    sigma: a.details?.sigma ?? 3,
    reasons: (a.details?.reasons ?? []).map((r) => t(`freshtrack.reason_${r}`)).join(", "),
  };
  return t(`freshtrack.explain_${a.kind}`, vars);
}

export function alertCard(a, { canAct = false, reload } = {}) {
  const actions = [];
  if (canAct && a.status === "open") {
    actions.push(
      actionButton(
        t("freshtrack.acknowledge"),
        async () => {
          await api(`/freshtrack/alerts/${a.id}/acknowledge`, { method: "POST", body: {} });
          done("freshtrack.acknowledged");
          reload?.();
        },
        { kind: "primary", onError: fail },
      ),
    );
  }
  let resolveForm = null;
  if (canAct && a.status !== "resolved") {
    const findings = input("findings", { required: true, minlength: "5", maxlength: "1000" });
    const action = input("corrective_action", { required: true, minlength: "5", maxlength: "1000" });
    const form = el(
      "form",
      { class: "stack" },
      a.condition_active ? el("div", { class: "alert alert--warn", text: t("freshtrack.still_active") }) : null,
      field(t("freshtrack.findings"), findings, t("freshtrack.findings_hint")),
      field(t("freshtrack.corrective_action"), action, t("freshtrack.corrective_hint")),
      el("button", { class: "btn btn--primary", type: "submit", text: t("freshtrack.resolve"), disabled: a.condition_active }),
    );
    form.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      if (!form.reportValidity()) return;
      try {
        await api(`/freshtrack/alerts/${a.id}/resolve`, { method: "POST", body: { findings: findings.value, corrective_action: action.value } });
        done("freshtrack.resolved_toast");
        reload?.();
      } catch (err) {
        fail(err);
      }
    });
    resolveForm = el("details", { class: "panel" }, el("summary", { text: t("freshtrack.inspect_and_resolve") }), el("div", { class: "panel__body" }, form));
  }
  const src = a.profile?.source;
  return el(
    "li",
    { class: "card stack" },
    el(
      "div",
      { class: "item__head" },
      el("strong", { text: `${t(`freshtrack.kind_${a.kind}`)} · ${a.facility_name ?? ""} · ${a.zone_name ?? ""}` }),
      el(
        "span",
        { class: "row" },
        a.simulated ? el("span", { class: "badge", dataset: { tone: "info" }, text: t("badges.simulated") }) : null,
        el("span", { class: "badge", dataset: { tone: TONE[a.severity] ?? "info" }, text: t(`severity.${a.severity}`) }),
        el("span", { class: "badge", dataset: { tone: STATUS_TONE[a.status] }, text: t(`freshtrack.status_${a.status}`) }),
      ),
    ),
    el("p", { text: explain(a) }),
    el("p", { class: "hint", text: t(`freshtrack.inspect_${a.kind}`) }),
    a.condition_active ? null : el("p", { class: "hint", text: t("freshtrack.cleared", { time: a.cleared_at ? fmtDateTime(a.cleared_at) : "—" }) }),
    src
      ? el(
          "p",
          { class: "hint" },
          `${t("guidance.source")}: `,
          el("a", { href: src.url, target: "_blank", rel: "noopener noreferrer", text: src.org }),
          src.pages ? ` (p. ${src.pages})` : "",
          a.profile.verified ? null : el("span", { class: "badge", dataset: { tone: "warn" }, text: t("badges.unverified_source") }),
        )
      : null,
    a.inspection
      ? el("div", { class: "contact" }, `${t("freshtrack.inspection")}: ${a.inspection.findings} → ${a.inspection.corrective_action}`)
      : null,
    actions.length ? el("div", { class: "item__actions" }, actions) : null,
    resolveForm,
  );
}
