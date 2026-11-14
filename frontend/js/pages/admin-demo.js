// Admin demo panel: FreshTrack simulator controls. Every action is audited server-side.
import { api } from "../api.js";
import { t } from "../i18n.js";
import { actionButton, el, field } from "../ui/dom.js";
import { done, fail, input } from "./common.js";
import { alertCard } from "./freshtrack-ui.js";

export async function renderDemo(panel) {
  const facilities = (await api("/storage/facilities?limit=100").catch(() => ({ data: [] }))).data;
  const zones = (await Promise.all(facilities.map((f) => api(`/storage/facilities/${f.id}/zones`).then((r) => r.data.map((z) => ({ ...z, facility: f.name }))).catch(() => [])))).flat();
  if (!zones.length) {
    panel.replaceChildren(el("div", { class: "state", text: t("demo.no_zones") }), await floodSection());
    return;
  }
  const zone = el("select", { class: "select" }, zones.map((z) => el("option", { value: z.id, text: `${z.facility} · ${z.name}` })));
  const kind = el("select", { class: "select" }, ["temp_high", "temp_low", "rh_high", "rh_low", "implausible"].map((k) => el("option", { value: k, text: t(`freshtrack.kind_${k}`) })));
  const minutes = input("minutes", { type: "number", min: "5", max: "360", value: "45" });
  const ahead = input("ahead", { type: "number", min: "0", max: "240", value: "45" });
  const status = el("p", { class: "hint" });
  const out = el("div", { class: "stack" });

  const refresh = async () => {
    const s = (await api("/admin/demo/freshtrack/simulator")).data;
    status.textContent = t("demo.running", { n: s.running_zone_ids.length });
  };
  const post = (path, body) => api(`/admin/demo/freshtrack/${path}`, { method: "POST", body });

  panel.replaceChildren(
    el("div", { class: "alert alert--info", text: t("demo.intro") }),
    el(
      "section",
      { class: "card stack" },
      el("h2", { text: t("demo.freshtrack") }),
      field(t("freshtrack.zone"), zone),
      el(
        "div",
        { class: "row" },
        actionButton(t("demo.start"), async () => (await post("simulator/start", { zone_id: zone.value, interval_s: 60 }), done("demo.started"), refresh()), { kind: "primary", onError: fail }),
        actionButton(t("demo.stop"), async () => (await post("simulator/stop", { zone_id: zone.value }), done("demo.stopped"), refresh()), { onError: fail }),
      ),
      status,
      el("div", { class: "inline-fields" }, field(t("demo.kind"), kind), field(t("demo.minutes"), minutes)),
      actionButton(
        t("demo.inject"),
        async () => {
          const { data } = await post("inject", { zone_id: zone.value, kind: kind.value, minutes: Number(minutes.value) });
          out.replaceChildren(el("h3", { text: t("demo.result") }), data.length ? el("ul", { class: "item-list" }, data.map((a) => alertCard(a))) : el("p", { class: "hint", text: t("demo.no_alert_yet") }));
        },
        { kind: "danger", onError: fail },
      ),
      el("div", { class: "inline-fields" }, field(t("demo.minutes_ahead"), ahead, t("demo.minutes_ahead_hint"))),
      actionButton(
        t("demo.check_stale"),
        async () => {
          const { data } = await post(`check-stale?minutes_ahead=${Number(ahead.value) || 0}`, undefined);
          out.replaceChildren(el("p", { text: t("demo.stale_result", { n: data.stale_zones }) }));
        },
        { onError: fail },
      ),
    ),
    await floodSection(),
    out,
  );
  refresh().catch(() => {});
}

async function floodSection() {
  const scenarios = (await api("/admin/demo/flood/scenarios").catch(() => ({ data: [] }))).data;
  const sel = el("select", { class: "select" }, scenarios.map((s) => el("option", { value: s.id, text: t(`emergency.scenario_${s.id}`) })));
  const result = el("div");
  return el(
    "section",
    { class: "card stack" },
    el("h2", { text: t("demo.aquasentinel") }),
    el("p", { class: "hint", text: t("demo.flood_hint") }),
    field(t("demo.scenario"), sel),
    el(
      "div",
      { class: "row" },
      actionButton(
        t("demo.trigger_flood"),
        async () => {
          const { data } = await api("/admin/demo/flood/trigger", { method: "POST", body: { scenario_id: sel.value } });
          result.replaceChildren(el("p", { text: t("demo.flood_result", { farms: data.exposure_counts.farms, stores: data.exposure_counts.facilities, lots: data.exposure_counts.stored_lots }) }), el("a", { class: "btn btn--primary", href: "/emergency.html", text: t("demo.open_emergency") }));
        },
        { kind: "danger", onError: fail },
      ),
      actionButton(
        t("demo.weather_check"),
        async () => {
          const { data } = await api("/admin/demo/weather/check", { method: "POST" });
          result.replaceChildren(el("p", { text: t("demo.weather_result", { n: data.new_alerts }) }));
        },
        { onError: fail },
      ),
    ),
    result,
  );
}
