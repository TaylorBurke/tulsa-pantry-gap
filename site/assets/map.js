/* Tulsa Pantry Gap Map: tract choropleth + pantries + bus routes, with toggles for
   the time window, the map layer and the waiting assumption. Data comes from
   site/data/*.geojson (written by analysis/story.py). Tap or click a tract or a
   pantry for details; every value on the map is also in the table view below it. */
(function () {
  const $ = (s) => document.querySelector(s);
  const fmt = d3.format(",");
  const pct = (v) => (v == null ? "n/a" : Math.round(v * 100) + "%");
  const state = { win: "saturday", layer: "gap", wait: "planned", sel: null };
  const WIN = window.PANTRY_GAP.windows;      // labels, from build_site.py
  const RANK = window.PANTRY_GAP.ranking;     // top-10 GEOIDs per window
  const W = 900;
  const ROOT = window.PANTRY_GAP.dataRoot || "";   // "../" for pages in a subfolder
  const on = (sel, fn) => { const el = $(sel); if (el) el.onclick = fn; };

  // Layers. Bins are fixed so colors mean the same thing in every window.
  const LAYERS = {
    gap: {
      title: "Number of people in poverty in each high-need tract who can't reach an open pantry within 30 min",
      // The gap is high need + low access, so only high-need tracts are filled.
      value: (p) => (p.high_need ? p[`poor_no_access_${state.win}_${state.wait}`] : "out"),
      bins: [1, 100, 300, 600], labels: ["0 people", "1–99", "100–299", "300–599", "600+ people"],
      zeroIsNone: true,
    },
    noaccess: {
      title: "Share of residents who can't reach an open pantry within 30 min",
      value: (p) => 1 - p[`share_${state.win}_${state.wait}`],
      bins: [0.0005, 0.25, 0.5, 0.75], labels: ["0%", "<25%", "25–50%", "50–75%", "75%+"],
      zeroIsNone: true,
    },
    need: {
      title: "Need index (poverty, no car, SNAP), quarters of Tulsa County tracts",
      value: (p) => p.need_pctl,
      bins: [0.25, 0.5, 0.75], labels: ["Lowest", "", "", "Highest quarter"],
      zeroIsNone: false,
    },
  };

  function cls(layer, v) {
    if (v === "out") return "out";
    if (v == null || Number.isNaN(v)) return "none";
    const L = LAYERS[layer];
    const i = d3.bisectRight(L.bins, v);
    if (L.zeroIsNone) return i === 0 ? "none" : "q" + i;
    return "q" + (i + 1);
  }

  Promise.all([
    d3.json(ROOT + "data/tracts.geojson"), d3.json(ROOT + "data/pantries.geojson"),
    d3.json(ROOT + "data/routes.geojson"), d3.json(ROOT + "data/places.json"),
  ]).then(([tracts, pantries, routes, places]) => draw(tracts, pantries, routes, places))
    .catch((e) => { $("#map").textContent = "The map could not load. The tables below have every value."; console.error(e); });

  function draw(tracts, pantries, routes, places) {
    // Optional: a fixed frame (mapAspect = height / width) with the county fitted
    // inside it, instead of a frame as tall as the county.
    const ASPECT = window.PANTRY_GAP.mapAspect;
    let proj, H;
    if (ASPECT) {
      H = Math.round(W * ASPECT);
      proj = d3.geoMercator().fitSize([W, H], tracts);
    } else {
      proj = d3.geoMercator().fitWidth(W, tracts);
      const [[, y0], [, y1]] = d3.geoPath(proj).bounds(tracts);
      H = Math.ceil(y1 - y0) + 4;
    }
    const path = d3.geoPath(proj);
    const svg = d3.select("#map").append("svg").attr("viewBox", `0 0 ${W} ${H}`)
      .attr("role", "img").attr("aria-labelledby", "map-title map-sub");
    const g = svg.append("g");
    const gT = g.append("g"), gR = g.append("g"), gTop = g.append("g"), gL = g.append("g"),
      gP = g.append("g"), gRank = g.append("g");

    const tSel = gT.selectAll("path").data(tracts.features).join("path")
      .attr("class", "tract").attr("d", path)
      .on("click", (ev, d) => select({ kind: "tract", d }));
    gR.selectAll("path").data(routes.features).join("path").attr("class", "route").attr("d", path);
    gL.selectAll("text").data(places).join("text").attr("class", "place-label")
      .attr("x", (d) => proj([d.lon, d.lat])[0]).attr("y", (d) => proj([d.lon, d.lat])[1]).text((d) => d.name);
    const pts = pantries.features.filter((f) => f.properties.general);
    const pSel = gP.selectAll("circle").data(pts).join("circle")
      .attr("cx", (d) => proj(d.geometry.coordinates)[0]).attr("cy", (d) => proj(d.geometry.coordinates)[1])
      .on("click", (ev, d) => { ev.stopPropagation(); select({ kind: "pantry", d }); });

    // Zoom & pan (pinch on phones). Markers and labels keep their screen size.
    let k = 1;
    const zoom = d3.zoom().scaleExtent([1, 10]).translateExtent([[0, 0], [W, H]])
      .on("zoom", (ev) => { k = ev.transform.k; g.attr("transform", ev.transform); sizeMarks(); });
    svg.call(zoom).on("dblclick.zoom", null);
    // Optional: open zoomed onto the high-need tracts, where the gaps are; Reset shows the county.
    if (window.PANTRY_GAP.focusHighNeed) {
      const hn = { type: "FeatureCollection", features: tracts.features.filter((f) => f.properties.high_need) };
      const [[x0, y0], [x1, y1]] = path.bounds(hn);
      const kk = Math.min(4, 0.92 / Math.max((x1 - x0) / W, (y1 - y0) / H));
      svg.call(zoom.transform, d3.zoomIdentity.translate(W / 2 - kk * (x0 + x1) / 2, H / 2 - kk * (y0 + y1) / 2).scale(kk));
    }
    on("#zin", () => svg.transition().call(zoom.scaleBy, 1.6));
    on("#zout", () => svg.transition().call(zoom.scaleBy, 1 / 1.6));
    on("#zreset", () => svg.transition().call(zoom.transform, d3.zoomIdentity));

    function sizeMarks() {
      const r = 4.2 / Math.sqrt(k);
      pSel.attr("r", (d) => (d.properties[`open_${state.win}`] ? r * 1.3 : r * 0.9));
      gL.selectAll("text").style("font-size", `${11 / k}px`).style("stroke-width", `${3 / k}px`);
      gRank.selectAll("text").style("font-size", `${11 / k}px`).style("stroke-width", `${3 / k}px`);
    }

    function render() {
      const L = LAYERS[state.layer];
      tSel.attr("fill", (d) => `var(--${cls(state.layer, L.value(d.properties))})`)
        .classed("out", (d) => cls(state.layer, L.value(d.properties)) === "out")
        .classed("sel", (d) => !!state.sel && state.sel.kind === "tract" && state.sel.d === d);
      pSel.attr("class", (d) => "pantry " + (!d.properties.hours_listed ? "unlisted"
        : d.properties[`open_${state.win}`] ? "open" : "closed"))
        .sort((a, b) => (a.properties[`open_${state.win}`] ? 1 : 0) - (b.properties[`open_${state.win}`] ? 1 : 0));
      // Top-10 gap tracts for this window: outline + rank number.
      const top = RANK[state.win];
      const topF = tracts.features.filter((f) => top.includes(f.properties.GEOID));
      gTop.selectAll("path").data(topF, (d) => d.properties.GEOID).join("path")
        .attr("d", path).attr("fill", "none").attr("class", "tract top").style("pointer-events", "none");
      gRank.selectAll("text").data(topF, (d) => d.properties.GEOID).join("text").attr("class", "rank-label")
        .attr("x", (d) => path.centroid(d)[0]).attr("y", (d) => path.centroid(d)[1] + 4)
        .text((d) => top.indexOf(d.properties.GEOID) + 1);
      sizeMarks();
      legend();
      if ($("#map-sub")) $("#map-sub").textContent = `${WIN[state.win].label}. ${L.title}. ` +
        (state.wait === "planned" ? "Riders time their trip to the bus schedule." : "Riders walk up without checking the schedule.");
      document.querySelectorAll("[data-win-panel]").forEach((el) => { el.hidden = el.dataset.winPanel !== state.win; });
      if (state.sel) info(state.sel); else infoDefault();
      table();
      // Let the rest of the page follow the same input (one switch drives everything).
      document.dispatchEvent(new CustomEvent("pantrygap:render", { detail: { ...state, sel: undefined } }));
    }

    function legend() {
      const L = LAYERS[state.layer];
      const steps = L.zeroIsNone ? ["none", "q1", "q2", "q3", "q4"] : ["q1", "q2", "q3", "q4"];
      const ramp = steps.map((s, i) => `<span><i style="background:var(--${s})${s === "none" ? ";box-shadow:inset 0 0 0 1px var(--axis)" : ""}"></i>${L.labels[i] || "&nbsp;"}</span>`).join("");
      $("#legend").innerHTML = `<div class="legend-title">${L.title}</div><div class="ramp">${ramp}</div>` +
        (state.layer === "gap" ? `<span class="item"><i class="k-out"></i>Not high need (outline only)</span>` : "") +
        `<span class="item"><i class="k-dot open"></i>Pantry open (${WIN[state.win].short})</span>` +
        `<span class="item"><i class="k-dot closed"></i>Not open then</span>` +
        `<span class="item"><i class="k-line"></i>Bus route</span>` +
        `<span class="item"><i class="k-ring"></i>Top 10 gap tracts (numbered)</span>`;
    }

    function infoDefault() {
      $("#info").innerHTML = `<h4>Tap a tract or a pantry</h4><div class="sub">Details show here.</div>` +
        `<p class="note">Numbered outlines are the ten high-need tracts with the most people in poverty and no open pantry within 30 minutes in this window. Pinch or use the buttons to zoom.</p>`;
    }

    function info(s) {
      const p = s.d.properties;
      if (s.kind === "pantry") {
        const open = ["weekday_day", "weekday_evening", "saturday"].filter((w) => p[`open_${w}`]).map((w) => WIN[w].short);
        const who = { zip: "ZIP codes", school_district: "these school districts:", county: "residents of county", place: "residents of" }[p.restriction_rule] || "";
        const restr = p.restriction_rule && p.restriction_areas ? `<p class="note">Eligibility: serves ${who} ${esc(p.restriction_areas.replaceAll(";", ", "))}.</p>` : "";
        $("#info").innerHTML = `<h4>${esc(p.name)}</h4><div class="sub">${esc(p.address)}, ${esc(p.city)}</div>` +
          `<div class="hours">${p.hours_listed ? esc(p.hours) : "Hours not listed in the public finder."}</div>` +
          open.map((o) => `<span class="flag">Open ${esc(o.toLowerCase())}</span>`).join("") + restr +
          `<p class="note">Hours as listed in the Food Bank of Eastern Oklahoma's public Food Finder. Call before going.</p>`;
        return;
      }
      const rows = ["weekday_day", "weekday_evening", "saturday"].map((w) =>
        `<dt>${WIN[w].short}</dt><dd>${pct(p[`share_${w}_${state.wait}`])}</dd>`).join("");
      const moe = (v, m) => `${pct(v)} <small>±${Math.round(m * 100)}</small>`;
      $("#info").innerHTML = `<h4>${esc(p.label)}</h4><div class="sub">Census tract ${esc(p.NAME)} · ${fmt(p.pop)} residents</div>` +
        `<dl><dt>In poverty</dt><dd>${moe(p.poverty_rate, p.poverty_rate_moe)}</dd>` +
        `<dt>Households without a car</dt><dd>${moe(p.no_vehicle_rate, p.no_vehicle_rate_moe)}</dd>` +
        `<dt>Households on SNAP</dt><dd>${moe(p.snap_rate, p.snap_rate_moe)}</dd>` +
        `<dt>Need</dt><dd>${p.high_need ? "Top quarter" : "Top " + Math.max(1, Math.round((1 - p.need_pctl) * 100)) + "%"}</dd>` +
        `<div class="sep"></div><dt><strong>Residents who can reach an open pantry in 30 min</strong></dt><dd></dd>${rows}` +
        `<div class="sep"></div><dt>People in poverty without one, ${esc(WIN[state.win].short.toLowerCase())}</dt><dd>${fmt(Math.round(p[`poor_no_access_${state.win}_${state.wait}`]))}</dd></dl>` +
        (p.n_shaky_components > 0 ? `<p class="note">${p.n_shaky_components} of the 3 need measures have wide margins of error here (90% margins shown as ±); treat this tract's rank loosely.</p>` : "") +
        (p.usda_lila_half ? `<p class="note">USDA also flags this tract as low-income and low-access (over ½ mile to any SNAP store).</p>` : "");
    }

    function select(s) { state.sel = s; render(); }
    svg.on("click", (ev) => { if (ev.target.tagName === "svg") { state.sel = null; render(); } });

    function table() {
      if (!$("#tract-table")) return;
      const key = `poor_no_access_${state.win}_${state.wait}`;
      const rows = tracts.features.map((f) => f.properties).sort((a, b) => b[key] - a[key]);
      $("#tract-table tbody").innerHTML = rows.map((p) =>
        `<tr data-geoid="${p.GEOID}" tabindex="0"><td class="where">${esc(p.label)}<small>Tract ${esc(p.NAME)}</small></td>` +
        `<td class="num">${pct(p.poverty_rate)}</td><td class="num">${pct(p.no_vehicle_rate)}</td><td class="num">${pct(p.snap_rate)}</td>` +
        `<td class="num">${pct(p[`share_${state.win}_${state.wait}`])}</td>` +
        `<td class="num">${fmt(Math.round(p[key]))}</td></tr>`).join("");
      $("#tract-table-win").textContent = WIN[state.win].short.toLowerCase();
    }
    const byId = new Map(tracts.features.map((f) => [f.properties.GEOID, f]));
    function pick(ev) {
      const tr = ev.target.closest && ev.target.closest("tr[data-geoid]");
      if (!tr) return;
      if (ev.type === "keydown" && ev.key !== "Enter" && ev.key !== " ") return;
      ev.preventDefault();
      select({ kind: "tract", d: byId.get(tr.dataset.geoid) });
      (document.getElementById("map-fig") || document.getElementById("map")).scrollIntoView({
        behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" });
    }
    document.addEventListener("click", pick);
    document.addEventListener("keydown", pick);

    // Any element with data-ctl is a control group; a page may repeat a group
    // (the board shows the window switch twice), so every copy stays in sync.
    function sync() {
      document.querySelectorAll("[data-ctl]").forEach((grp) => grp.querySelectorAll("button[data-v]")
        .forEach((x) => x.setAttribute("aria-pressed", String(x.dataset.v === state[grp.dataset.ctl]))));
    }
    document.querySelectorAll("[data-ctl]").forEach((grp) => {
      grp.addEventListener("click", (ev) => {
        const b = ev.target.closest("button[data-v]");
        if (!b) return;
        state[grp.dataset.ctl] = b.dataset.v;
        sync();
        render();
      });
    });
    const initWin = document.querySelector('[data-ctl="win"] button[aria-pressed="true"]');
    if (initWin) state.win = initWin.dataset.v;
    sync();
    window.__rerender = render;
    render();
  }

  function esc(s) {
    return String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  }
})();
