import { HOME } from "../auth.js";
import { currentLang, setLang, t } from "../i18n.js";
import { chain3d } from "../ui/chain3d.js";
import { countUp, reveal, tilt } from "../ui/motion.js";
import { fern, icon, meadow } from "../ui/nature.js";
import { mountShell } from "../ui/shell.js";
import { tree3d } from "../ui/tree3d.js";

const me = await mountShell({ public: true });
if (me) location.replace(HOME[me.role]);

const $ = (id) => document.getElementById(id);

for (const node of document.querySelectorAll("[data-icon]")) node.append(icon(node.dataset.icon));
for (const node of document.querySelectorAll("[data-d]")) node.style.setProperty("--d", node.dataset.d);

meadow($("hero-art"), {
  seed: 11,
  light: { x: 960, y: 420 },
  ground: 560,
  daisies: 46,
  tiny: 150,
  fireflies: 110,
  rays: { x: 980, y: -80 },
  puffs: [
    [600, 120, 26],
    [548, 250, 19],
    [660, 300, 15],
  ],
});
meadow($("story-art"), { seed: 29, light: { x: 1060, y: 470 }, ground: 600, daisies: 26, tiny: 110, umbels: 10, fireflies: 50, rays: { x: 1380, y: -100 }, phase: 1.2 });
fern($("fern-art"), {
  w: 1440,
  h: 1700,
  bg: "#0a100d",
  fronds: [
    { x: 1560, y: 120, len: 900, angle: 2.05, curl: 0.5, op: 0.45, sway: true },
    { x: -80, y: 760, len: 800, angle: -0.45, curl: 0.65, blur: 2, op: 0.5, sway: true },
    { x: 180, y: -100, len: 640, angle: 1.05, curl: -0.5, blur: 7, op: 0.35 },
    { x: 1500, y: 1150, len: 700, angle: 3.55, curl: -0.55, blur: 3, op: 0.45 },
    { x: 420, y: 1780, len: 760, angle: -1.15, curl: -0.4, blur: 12, op: 0.5 },
    { x: 1000, y: 1800, len: 620, angle: -1.9, curl: 0.5, blur: 5, op: 0.35 },
  ],
});

tree3d($("tree3d"), { seed: 7 });
chain3d($("chain3d"), [
  { icon: "harvest", key: "events.created" },
  { icon: "store", key: "events.booking_confirmed" },
  { icon: "snow", key: "events.checked_in" },
  { icon: "therm", key: "events.observation_summary" },
  { icon: "split", key: "events.split" },
]);

const STORIES = [
  { n: 1, href: "/farmer/batches.html" },
  { n: 2, href: "/storage/freshtrack.html" },
  { n: 3, href: "/emergency.html" },
];
let at = 0;
let timer = 0;

function show(i) {
  at = (i + STORIES.length) % STORIES.length;
  const s = STORIES[at];
  $("slide").classList.add("out");
  setTimeout(() => {
    for (const [id, part] of [["s-a", "a"], ["s-em", "em"], ["s-d", "d"], ["s-l", "link"]]) {
      $(id).dataset.i18n = `landing.s${s.n}_${part}`;
      $(id).textContent = t($(id).dataset.i18n);
    }
    $("s-link").href = s.href;
    $("count").textContent = `0${at + 1} / 0${STORIES.length}`;
    $("slide").classList.remove("out");
  }, 260);
  const bar = $("bar");
  bar.classList.remove("run");
  void bar.offsetWidth;
  bar.classList.add("run");
  clearTimeout(timer);
  if (!matchMedia("(prefers-reduced-motion: reduce)").matches) timer = setTimeout(() => show(at + 1), 7000);
}

$("prev").addEventListener("click", () => show(at - 1));
$("next").addEventListener("click", () => show(at + 1));
show(0);

const langs = $("foot-langs");
const markLang = () => {
  for (const b of langs.querySelectorAll("[data-lang]")) b.setAttribute("aria-pressed", String(b.dataset.lang === currentLang()));
};
langs.addEventListener("click", async (e) => {
  const b = e.target.closest("[data-lang]");
  if (!b) return;
  await setLang(b.dataset.lang);
  const select = document.querySelector(".app-header select");
  if (select) select.value = b.dataset.lang;
});
document.documentElement.addEventListener("langchange", markLang);
markLang();

reveal();
tilt(document.querySelectorAll(".reason, .stat"));
countUp(document.querySelectorAll("[data-count]"));
