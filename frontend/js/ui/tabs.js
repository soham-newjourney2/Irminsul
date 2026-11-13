// Tabs keyed by data-tab; the active tab is kept in location.hash.
export function setupTabs(onChange) {
  const tabs = [...document.querySelectorAll("[role=tab][data-tab]")];
  const names = tabs.map((t) => t.dataset.tab);
  let current = names.includes(location.hash.slice(1)) ? location.hash.slice(1) : names[0];

  function select(name) {
    current = name;
    for (const tab of tabs) tab.setAttribute("aria-selected", String(tab.dataset.tab === name));
    history.replaceState(null, "", `#${name}`);
    onChange(name);
  }

  for (const tab of tabs) tab.addEventListener("click", () => select(tab.dataset.tab));
  select(current);
  return { current: () => current, select };
}
