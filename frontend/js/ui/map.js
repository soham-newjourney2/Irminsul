// Leaflet 1.9.4 from unpkg with SRI (hashes verified against the CDN files), OSM tiles.
import { t } from "../i18n.js";
import { el } from "./dom.js";

const LEAFLET = {
  css: "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css",
  cssSri: "sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=",
  js: "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js",
  jsSri: "sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=",
};
export const WB_CENTER = [23.2, 88.1];

let loading = null;

export function loadLeaflet() {
  if (window.L) return Promise.resolve(window.L);
  loading ??= new Promise((resolve, reject) => {
    document.head.append(
      el("link", { rel: "stylesheet", href: LEAFLET.css, integrity: LEAFLET.cssSri, crossorigin: "" }),
    );
    const script = el("script", { src: LEAFLET.js, integrity: LEAFLET.jsSri, crossorigin: "" });
    script.addEventListener("load", () => resolve(window.L));
    script.addEventListener("error", () => {
      loading = null;
      reject(new Error("leaflet_unavailable"));
    });
    document.head.append(script);
  });
  return loading;
}

/** Returns {L, map} or null (with a message in the container) when the map cannot load. */
export async function createMap(container, { center = WB_CENTER, zoom = 7 } = {}) {
  try {
    const L = await loadLeaflet();
    const map = L.map(container).setView(center, zoom);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      referrerPolicy: "strict-origin-when-cross-origin",
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    }).addTo(map);
    // Maps inside closed <details> or detached nodes start at 0×0; fix size once visible.
    new ResizeObserver(() => map.invalidateSize()).observe(container);
    return { L, map };
  } catch {
    container.replaceChildren(el("div", { class: "state", text: t("map.unavailable") }));
    return null;
  }
}

export function myLocation() {
  return new Promise((resolve, reject) => {
    if (!navigator.geolocation) return reject(new Error("no_geolocation"));
    navigator.geolocation.getCurrentPosition(
      (pos) => resolve({ lat: pos.coords.latitude, lng: pos.coords.longitude }),
      () => reject(new Error("geolocation_denied")),
      { enableHighAccuracy: false, timeout: 10000 },
    );
  });
}

/**
 * Location picker: map click or "use my location" fills the lat/lng inputs.
 * The inputs stay editable, so it still works when the map cannot load.
 */
export async function locationPicker(container, latInput, lngInput, onChange = () => {}) {
  const mapEl = el("div", { class: "map map--small" });
  const locate = el("button", { class: "btn", type: "button", text: t("map.use_my_location") });
  container.replaceChildren(mapEl, el("p", { class: "hint", text: t("map.pick_hint") }), locate);
  const ctx = await createMap(mapEl);
  let marker = null;

  function set(lat, lng, pan = false) {
    latInput.value = lat.toFixed(5);
    lngInput.value = lng.toFixed(5);
    if (ctx) {
      marker ??= ctx.L.marker([lat, lng]).addTo(ctx.map);
      marker.setLatLng([lat, lng]);
      if (pan) ctx.map.setView([lat, lng], 12);
    }
    onChange({ lat, lng });
  }

  ctx?.map.on("click", (e) => set(e.latlng.lat, e.latlng.lng));
  locate.addEventListener("click", async () => {
    try {
      const p = await myLocation();
      set(p.lat, p.lng, true);
    } catch {
      locate.textContent = t("map.location_failed");
    }
  });
  if (latInput.value && lngInput.value) set(Number(latInput.value), Number(lngInput.value), true);
  return { set };
}
