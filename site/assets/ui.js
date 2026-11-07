/* Page chrome: theme toggle and current-section highlight. No data logic here. */
(function () {
  const root = document.documentElement;
  const KEY = "tpg-theme";
  try { const t = localStorage.getItem(KEY); if (t) root.dataset.theme = t; } catch (e) {}
  const btn = document.getElementById("theme");
  if (btn) btn.addEventListener("click", () => {
    const dark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    root.dataset.theme = dark ? "light" : "dark";
    try { localStorage.setItem(KEY, root.dataset.theme); } catch (e) {}
    if (window.__rerender) window.__rerender();
  });
  const links = [...document.querySelectorAll(".nav-links a[href^='#']")];
  const secs = links.map((a) => document.querySelector(a.getAttribute("href")));
  function onScroll() {
    let cur = -1;
    secs.forEach((s, i) => { if (s && s.getBoundingClientRect().top < innerHeight * 0.35) cur = i; });
    links.forEach((a, i) => a.classList.toggle("on", i === cur));
  }
  addEventListener("scroll", onScroll, { passive: true });
  onScroll();
})();
