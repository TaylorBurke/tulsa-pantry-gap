"""Build site/brief/index.html: a two-page printable brief of the Pantry Gap Map.

Made to hand to the Food Bank (or anyone) on paper or as a PDF: the finding, two
static maps (weekday evening and Saturday), the biggest gaps, where a mobile
distribution would help most, and the method and caveats in short. Every number
comes from story.json through sitekit, like the web pages. tools/pdf.mjs prints
it to site/brief/tulsa-pantry-gap-brief.pdf.

The maps are plain SVG drawn here (no JavaScript), cropped to the Tulsa urban
area, which holds every high-need tract (asserted below).
"""
import datetime as dt
import json

import geopandas as gpd
import segno

from sitekit import (S, W, ORDER, P, CFG, C, PT, RANK, OPEN, POOR_HN, EVE, SAT, LEAD, SITING, AUTHOR,
                     AUTHOR_URL, REPO_URL, ROOT, e, pct, n, about, short_label, caveats_items, half_words)

OUT = ROOT / "site" / "brief"
OUT.mkdir(exist_ok=True)
SITE_URL = "https://tulsa-pantry-gap.pages.dev/"
CRS_M = "EPSG:32615"
MAP_WINDOWS = ["weekday_evening", "saturday"]
# Same fixed bins and ramp as the web map's "Gap" layer (map.js), so the two read alike.
BINS = [1, 100, 300, 600]
BIN_LABELS = ["0 people", "1–99", "100–299", "300–599", "600+ people"]
HN_SHARE = {w: W[w][P]["share_high_need"] for w in ORDER}

assert half_words(EVE) == half_words(SAT) == "about half"

# ---- maps ---------------------------------------------------------------------------
tracts = gpd.read_file(ROOT / "site" / "data" / "tracts.geojson").to_crs(CRS_M)
pantries = gpd.read_file(ROOT / "site" / "data" / "pantries.geojson").to_crs(CRS_M)
pantries = pantries[pantries.general & pantries.in_county]
routes = gpd.read_file(ROOT / "site" / "data" / "routes.geojson").to_crs(CRS_M)
places = json.loads((ROOT / "site" / "data" / "places.json").read_text())

hn = tracts[tracts.high_need]
assert len(hn) == C["high_need_tracts"]
PAD = 2500  # metres around the high-need tracts
x0, y0, x1, y1 = hn.total_bounds
x0, y0, x1, y1 = x0 - PAD, y0 - PAD, x1 + PAD, y1 + PAD
MW = 400  # svg units across
SC = MW / (x1 - x0)
MH = round((y1 - y0) * SC)


def pt(x, y):
    return (x - x0) * SC, (y1 - y) * SC


def xy(x, y):
    a, b = pt(x, y)
    return f"{a:.1f},{b:.1f}"


def ring(coords):
    return "M" + "L".join(xy(x, y) for x, y in coords) + "Z"


def poly_d(geom):
    geom = geom.simplify(40)
    polys = geom.geoms if geom.geom_type == "MultiPolygon" else [geom]
    return "".join(ring(p.exterior.coords) + "".join(ring(i.coords) for i in p.interiors) for p in polys)


def line_d(geom):
    geom = geom.simplify(40)
    lines = geom.geoms if geom.geom_type == "MultiLineString" else [geom]
    return "".join("M" + "L".join(xy(x, y) for x, y in l.coords) for l in lines)


def inside(g):
    return x0 <= g.x <= x1 and y0 <= g.y <= y1


def bin_class(t, w):
    if not t.high_need:
        return "out"
    v = getattr(t, f"poor_no_access_{w}_{P}")
    i = sum(v >= b for b in BINS)
    return "none" if i == 0 else f"q{i}"


def to_m(lons, lats):
    return gpd.GeoSeries(gpd.points_from_xy(lons, lats), crs="EPSG:4326").to_crs(CRS_M)


TRACT_D = [poly_d(g) for g in tracts.geometry]
ROUTE_D = "".join(line_d(g) for g in routes.geometry)
PLACE_PTS = to_m([p["lon"] for p in places], [p["lat"] for p in places])


def map_svg(w):
    fills = "".join(f'<path class="t {bin_class(t, w)}" d="{d}"/>' for t, d in zip(tracts.itertuples(), TRACT_D))
    open_p = pantries[pantries[f"open_{w}"]]
    dots = "".join('<circle class="p" cx="%.1f" cy="%.1f" r="3.4"/>' % pt(g.x, g.y)
                   for g in open_p.geometry if inside(g))
    sites = to_m([s["lon"] for s in SITING[w]["sites"]], [s["lat"] for s in SITING[w]["sites"]])
    marks = ""
    for i, g in enumerate(sites, 1):
        cx, cy = pt(g.x, g.y)
        marks += (f'<g class="site"><rect x="{cx - 6.5:.1f}" y="{cy - 6.5:.1f}" width="13" height="13" rx="2"/>'
                  f'<text x="{cx:.1f}" y="{cy + 3.4:.1f}">{i}</text></g>')
    near_site = lambda g: any(g.distance(s) < 2500 for s in sites)
    labels = "".join('<text class="pl" x="%.1f" y="%.1f">' % pt(g.x, g.y) + e(pl["name"]) + "</text>"
                     for pl, g in zip(places, PLACE_PTS) if inside(g) and not near_site(g))
    title = W[w]["label"]
    return (f'<figure class="map"><figcaption><strong>{e(title)}</strong>'
            f'<span>{OPEN[w]} of {PT["general_in_county"]} county pantries open · '
            f'{pct(HN_SHARE[w])} of high-need residents can reach one</span></figcaption>'
            f'<svg viewBox="0 0 {MW} {MH}" role="img" aria-label="{e(title)}: high-need tracts shaded by people '
            f'in poverty with no open pantry within {CFG["budget_min"]} minutes">'
            f'<rect class="bg" width="{MW}" height="{MH}"/>{fills}<path class="r" d="{ROUTE_D}"/>{labels}{dots}{marks}'
            f'</svg></figure>')


def legend():
    sw = "".join(f'<span class="k"><i class="sw {c}"></i>{lab}</span>'
                 for c, lab in zip(["none", "q1", "q2", "q3", "q4"], BIN_LABELS))
    return (f'<div class="legend"><span class="lt">Shading: number of people in poverty in each high-need tract who '
            f'can\'t reach an open pantry within {CFG["budget_min"]} min</span>{sw}'
            f'<span class="k"><i class="sw out"></i>Not high-need</span>'
            f'<span class="k"><i class="dot"></i>Pantry open</span>'
            f'<span class="k"><i class="sq">1</i>Mobile site, page 2</span>'
            f'<span class="k"><i class="ln"></i>Bus route</span></div>')


# ---- page 2 pieces --------------------------------------------------------------------
def gap_table():
    tr = tracts.set_index("GEOID")
    rows = []
    for r in RANK["saturday"]:
        t = tr.loc[r["GEOID"]]
        flag = ' <span class="flag">wide margins</span>' if r["shaky_components"] else ""
        rows.append(
            f'<tr><td class="rk">{r["rank"]}</td><td>{e(short_label(r["label"]))} <small>tract {e(str(r["tract"]))}{flag}</small></td>'
            f'<td class="num">{pct(r["poverty_rate"])}</td><td class="num">{pct(r["no_vehicle_rate"])}</td>'
            f'<td class="num">{pct(t[f"share_weekday_day_{P}"])}</td>'
            f'<td class="num">{pct(t[f"share_weekday_evening_{P}"])}</td>'
            f'<td class="num">{pct(r["share_access"])}</td>'
            f'<td class="num strong">{n(r["people_in_poverty_no_access"])}</td></tr>')
    sat_ids = {x["GEOID"] for x in RANK["saturday"]}
    also = [r for r in RANK["weekday_evening"] if r["GEOID"] not in sat_ids]
    also_txt = "; ".join(f'{e(short_label(r["label"]))} (tract {e(str(r["tract"]))}, {n(r["people_in_poverty_no_access"])})'
                         for r in also)
    return ('<table><thead><tr><th>#</th><th>Where (nearest arterials)</th><th class="num">Poverty</th>'
            '<th class="num">No car</th><th class="num grp" colspan="3">Share who can reach one<br>'
            '<span>Weekday · Evening · Sat</span></th><th class="num">People in poverty, none in reach on Sat</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table>'
            + (f'<p class="note">Also in the weekday-evening top ten (people in poverty with none in reach): {also_txt}.</p>'
               if also else ""))


def siting_col(w, head):
    sw = SITING[w]
    items = "".join(
        f'<li><strong>{e(s["stop_name"])}</strong> bus stop: {about(s["people_in_poverty_newly_within_budget"])} more '
        f'people in poverty within {CFG["budget_min"]} min, mostly around '
        f'{e(" · ".join(sorted({short_label(t["label"]) for t in s["main_tracts"]})))}.</li>'
        for s in sw["sites"])
    reach = sum(s["people_in_poverty_newly_within_budget"] for s in sw["sites"])
    return (f'<div><h3>{head}</h3><ol>{items}</ol><p class="note">Together: {about(reach)} of the '
            f'{about(sw["people_in_poverty_without_access"], "")} people in poverty countywide with no open pantry in reach.</p></div>')


qr = segno.make(SITE_URL, error="m").svg_inline(scale=2.4, border=0, dark="#1a1714")
fold = POOR_HN["saturday"] / POOR_HN["weekday_day"]
fold_words = "about ten times as many" if 8 <= fold <= 12 else f"{fold:.0f} times as many"
built = dt.date.fromisoformat(S["data_as_of"]).strftime("%B %-d, %Y")
caveats = "".join(f"<li><strong>{e(h)}.</strong> {e(d)}</li>" for h, d in caveats_items())
tiles = "".join(
    f'<div class="tile{"" if w == "weekday_day" else " hot"}"><span class="tl">{e(W[w]["label"])}</span>'
    f'<span class="tv">{pct(1 - HN_SHARE[w])}</span><span class="ts">of high-need residents can\'t reach an open pantry</span>'
    f'<span class="tn">{OPEN[w]} of {PT["general_in_county"]} pantries open · {about(POOR_HN[w], "≈")} people in poverty left out</span></div>'
    for w in ORDER)
r5 = [S["r5"][w]["planned_vs_r5_p5_agree"] for w in ORDER]

page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Pantry Gap Brief</title>
<meta name="description" content="Two-page brief: when Tulsa's food pantries are open, and who can reach one without a car.">
<link rel="icon" href="data:,">
<link rel="stylesheet" href="../assets/fonts/board-fonts.css"><link rel="stylesheet" href="brief.css">
</head><body>
<article class="page">
<header class="top"><p class="kicker">Tulsa Pantry Gap Map · Brief</p>
<p class="by">By {e(AUTHOR)} · Pantry data as of {built} · A personal project from public data, not a product of the Food Bank of Eastern Oklahoma</p></header>
<h1>After 5pm and on Saturdays, about half of Tulsa's highest-need neighborhoods can't reach an open pantry without a car.</h1>
<p class="dek">Tulsa County's {C["high_need_tracts"]} highest-need census tracts are home to {about(C["high_need_pop"], "")} people,
{about(C["high_need_poor"], "")} of them below the poverty line. Walking and riding the bus, {CFG["budget_min"]} minutes door to door,
almost all of them can get to an open food pantry on a weekday. Most pantries close by 5pm and few open on Saturday, so
{fold_words} people in poverty are left without one on a Saturday as on a weekday.</p>
<div class="tiles">{tiles}</div>
<div class="maps">{"".join(map_svg(w) for w in MAP_WINDOWS)}</div>
{legend()}
<div class="foot"><h2>How it's measured</h2>
<p>Trips start from every 2020 census block: walking at 3 mph (straight-line distance × {S["config"]["circuity"]}) plus scheduled
Tulsa Transit service with at most one transfer, from the published timetable. Riders who check the schedule wait
{CFG["planned_first_wait_min"]} minutes for the first bus. A full trip planner (R5) gives the same reachable-or-not answer for
{pct(min(r5))}–{pct(max(r5))} of residents. Supply is every general-public pantry on the Food Bank's public Food Finder, with its posted
hours; school, senior-only and meal programs are left out, and service-area rules are applied where a listing states them.</p>
<p>Maps show the Tulsa urban area, which holds all {C["high_need_tracts"]} high-need tracts. High-need: the top quarter of county
tracts on poverty, households without a car and SNAP use (2020–24 American Community Survey). Pantries: general-public pantries on the
Food Bank's public Food Finder with a regular session in the window.</p></div>
</article>

<article class="page">
<section><h2>Where the gap is biggest</h2>
<p>The ten high-need tracts with the most people in poverty who can't reach an open pantry on a Saturday. The clearest case is
{e(short_label(LEAD["label"]))}: on a weekday the nearest open pantry is {LEAD["weekday_day"]["nearest_km"]} km away. After 5pm it is
{LEAD["weekday_evening"]["nearest_km"]} km, and on a Saturday {LEAD["saturday"]["nearest_km"]} km.</p>
{gap_table()}</section>

<section><h2>Where a mobile distribution would help most</h2>
<p>A first screening, not a recommendation. These are the bus stops where one mobile distribution would put the most people in poverty
who have no open pantry today within {CFG["budget_min"]} minutes of one, picked one at a time so each adds to the ones before it. It doesn't
weigh parking, host sites, capacity or meal programs. They're the numbered squares on the maps.</p>
<div class="two">{siting_col("weekday_evening", "Weekday evenings")}{siting_col("saturday", "Saturdays")}</div></section>

<section class="method"><h2>What it can't tell you</h2><ul class="caveats two-col">{caveats}</ul></section>

<footer class="end"><div class="qr">{qr}</div><div><p><strong>Interactive map, every pantry's hours and the full method:</strong><br>
<a href="{SITE_URL}">{SITE_URL.removeprefix("https://").rstrip("/")}</a></p>
<p>Code and data pipeline: <a href="{REPO_URL}">{REPO_URL.removeprefix("https://")}</a><br>Contact: <a href="{AUTHOR_URL}">{AUTHOR_URL.removeprefix("https://").rstrip("/")}</a></p></div></footer>
</article>
</body></html>
"""
(OUT / "index.html").write_text(page)
print(f"wrote site/brief/index.html ({len(page) // 1024} kB)")
