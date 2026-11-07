/* Board edition: the window switch drives the wall of pantry sheets too.
   map.js owns the state and fires "pantrygap:render"; this file re-sorts the wall
   (FLIP animation: pantries open in the window rise to the front) and keeps the
   theme toggle. Reduced motion: the wall re-sorts instantly. */
(function () {
  const root = document.documentElement;
  const KEY = "tpg-theme";
  const btn = document.getElementById("theme");
  const isDark = () => (root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches);
  const label = () => { if (btn) btn.textContent = isDark() ? "Lights on" : "Lights off"; };
  try { const t = localStorage.getItem(KEY); if (t) root.dataset.theme = t; } catch (e) {}
  label();
  if (btn) btn.addEventListener("click", () => {
    root.dataset.theme = isDark() ? "light" : "dark";
    try { localStorage.setItem(KEY, root.dataset.theme); } catch (e) {}
    label();
    if (window.__rerender) window.__rerender();
  });

  const list = document.getElementById("wall-list");
  const count = document.getElementById("wall-count");
  const cards = list ? [...list.children] : [];
  const WIN = window.PANTRY_GAP.windows;
  const still = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
  let lastWin = null;

  function arrange(win) {
    const key = win.replace(/_([a-z])/g, (_, c) => c.toUpperCase());   // weekday_evening -> weekdayEvening
    const first = new Map(cards.map((c) => [c, c.getBoundingClientRect()]));
    cards.forEach((c) => {
      const open = c.dataset[key] === "1";
      c.dataset.open = open ? "1" : "0";
      c.querySelector(".state").textContent = c.dataset.listed === "0" ? "Hours not listed"
        : open ? `Open ${WIN[win].short}` : `Not open ${WIN[win].short}`;
    });
    const rank = (c) => (c.dataset.open === "1" ? 0 : c.dataset.listed === "1" ? 1 : 2);
    [...cards].sort((a, b) => rank(a) - rank(b) || cards.indexOf(a) - cards.indexOf(b)).forEach((c) => list.appendChild(c));
    const nOpen = cards.filter((c) => c.dataset.open === "1").length;
    if (count) count.textContent = `${nOpen} of ${cards.length} sheets open: ${WIN[win].label.toLowerCase()}`;
    if (still() || lastWin === null) return;
    cards.forEach((c) => {
      const a = first.get(c), b = c.getBoundingClientRect();
      const dx = a.left - b.left, dy = a.top - b.top;
      if (!dx && !dy) return;
      c.animate([{ translate: `${dx}px ${dy}px` }, { translate: "0 0" }], { duration: 420, easing: "cubic-bezier(.2,.7,.2,1)" });
    });
  }

  document.addEventListener("pantrygap:render", (ev) => {
    if (ev.detail.win !== lastWin) { arrange(ev.detail.win); lastWin = ev.detail.win; }
  });

  // The switch at the bottom of the page brings the reader back up to the map.
  document.querySelectorAll('.close [data-ctl="win"] button').forEach((b) => b.addEventListener("click", () => {
    document.getElementById("map-fig").scrollIntoView({ behavior: still() ? "auto" : "smooth", block: "start" });
  }));
})();
