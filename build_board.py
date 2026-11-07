"""Build site/index.html: the bulletin-board edition (the default page) of the Pantry Gap Map.

The page is the board on a pantry's door: a typed notice, three hours sheets that
are the time-window switch, the live map on a pinned sheet, every county pantry's
posted hours with the conditions written on in marker, a clipboard of the worst
gaps, a flyer of mobile pantry stops and a stapled method packet. Every number
comes from story.json through sitekit; nothing here is typed by hand.
"""
from sitekit import (S, W, ORDER, P, CFG, C, PT, RANK, OPEN, POOR_HN, DAY, EVE, SAT, TOP_SAT, LEAD, HW, WALK,
                     SITING, PHOTOS, AUTHOR, AUTHOR_URL, REPO_URL, ROOT, e, pct, n, about, half_words,
                     short_label, window_js, rank_js, pantry_sheets, checks_items, caveats_items, src_links)

OUT = ROOT / "site"

SHEET = {
    "weekday_day": ("Weekdays", "Mon–Fri, 8am–5pm"),
    "weekday_evening": ("Evenings", "Mon–Fri, after 5pm"),
    "saturday": ("Saturday", "any time"),
}
assert half_words(EVE) == half_words(SAT) == "about half", "headline says 'about half' for both"


def tilt(i, spread=3):
    """Deterministic small rotation in degrees: hand-hung, but stable between builds."""
    return round(((i * 37) % (2 * spread + 1) - spread) * 0.45, 2)


def window_sheets(where):
    out = []
    for i, w in enumerate(ORDER):
        day, when = SHEET[w]
        pressed = "true" if w == "saturday" else "false"
        out.append(
            f'<button class="hours-sheet" data-v="{w}" aria-pressed="{pressed}" style="--r:{tilt(i + 2)}deg">'
            f'<span class="pin" aria-hidden="true"></span>'
            f'<span class="hs-day">{day}</span><span class="hs-when">{when}</span>'
            f'<span class="hs-count">{OPEN[w]}</span>'
            f'<span class="hs-of">of {PT["general_in_county"]} pantries open</span>'
            f'<span class="hs-reach">{pct(S["windows"][w][P]["share_high_need"])} of high-need residents can get to one</span>'
            f'</button>')
    return (f'<div class="hours" data-ctl="win" role="group" aria-label="{where}: when do you need a pantry?">'
            + "".join(out) + "</div>")


def wall():
    cards = []
    for i, p in enumerate(pantry_sheets()):
        hours = "".join(f"<li>{e(h)}</li>" for h in p["hours"]) or '<li class="none">No hours on the listing</li>'
        notes = "".join(f'<p class="marker" style="--r:{tilt(i + k, 2)}deg">{e(t)}</p>' for k, t in enumerate(p["notes"]))
        data = " ".join(f'data-{w.replace("_", "-")}="{int(p[f"open_{w}"])}"' for w in ORDER)
        fast = "f-tape" if i % 3 else "f-pin"
        cards.append(
            f'<li class="card {fast}" style="--r:{tilt(i)}deg" data-listed="{int(p["listed"])}" {data}>'
            f'<h3>{e(p["name"])}</h3><p class="addr">{e(p["address"])}, {e(p["city"])}</p>'
            f'<ul class="lines">{hours}</ul>{notes}<p class="state"></p></li>')
    return "".join(cards)


def clipboard(w):
    rows = []
    for r in RANK[w]:
        flag = ' <span class="marker small">wide margins</span>' if r["shaky_components"] else ""
        rows.append(
            f'<tr data-geoid="{r["GEOID"]}" tabindex="0"><td class="rk">{r["rank"]}</td>'
            f'<td class="where">{e(short_label(r["label"]))}<small>{e(r["label"].split(":")[0])} · tract {e(str(r["tract"]))}{flag}</small></td>'
            f'<td class="num">{pct(r["poverty_rate"])}<small>±{round(r["poverty_rate_moe"] * 100)}</small></td>'
            f'<td class="num">{pct(r["no_vehicle_rate"])}</td>'
            f'<td class="num">{pct(r["share_access"])}</td>'
            f'<td class="num strong">{n(r["people_in_poverty_no_access"])}</td></tr>')
    return (f'<div data-win-panel="{w}"{"" if w == "saturday" else " hidden"}>'
            f'<p class="clip-title">Biggest gaps: {e(W[w]["label"].lower())}</p>'
            '<div class="table-scroll"><table class="ruled"><thead><tr><th>#</th><th>Where (nearest arterials)</th>'
            '<th class="num">Poverty</th><th class="num">No car</th><th class="num">Can reach</th>'
            '<th class="num">People in poverty with none in reach</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div></div>')


def flyer(w, title, k):
    sw = SITING[w]
    tabs, items = [], []
    for s in sw["sites"]:
        served = sorted({short_label(t["label"]) for t in s["main_tracts"]})
        items.append(f'<li><strong>{e(s["stop_name"])}</strong> bus stop: {about(s["people_in_poverty_newly_within_budget"])} '
                     f'more people in poverty within {CFG["budget_min"]} minutes, mostly around {e(" · ".join(served))}.</li>')
        tabs.append(f'<span class="tab">{e(s["stop_name"])}</span>')
    reach = sum(s["people_in_poverty_newly_within_budget"] for s in sw["sites"])
    return (f'<article class="flyer" style="--r:{tilt(k)}deg"><span class="tape" aria-hidden="true"></span>'
            f'<p class="flyer-kicker">Draft, not a real schedule</p><h3>{title}</h3>'
            f'<p>Three bus stops where a mobile distribution would reach the most people in poverty who have no open '
            f'pantry within {CFG["budget_min"]} minutes today: {about(reach)} of '
            f'{about(sw["people_in_poverty_without_access"], "")}.</p>'
            f'<ol>{"".join(items)}</ol><div class="tabs" aria-hidden="true">{"".join(tabs)}</div></article>')


ph38 = PHOTOS["aero-stop-8005"]
checks = "".join(f'<li><span class="tick" aria-hidden="true"></span><strong>{e(h)}.</strong> {e(d)}</li>'
                 for h, d in checks_items())
caveats = "".join(f"<li><strong>{e(h)}.</strong> {e(d)}</li>" for h, d in caveats_items())
fold = POOR_HN["saturday"] / POOR_HN["weekday_day"]
fold_words = "about ten times as many" if 8 <= fold <= 12 else f"{fold:.0f} times as many"

page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Tulsa Pantry Gap Map</title>
<meta name="description" content="When Tulsa's food pantries are open, and who can reach one without a car: weekdays, weekday evenings and Saturdays.">
<link rel="icon" href="data:,">
<link rel="preload" href="assets/fonts/PublicSans-var.woff2" as="font" type="font/woff2" crossorigin>
<link rel="stylesheet" href="assets/fonts/board-fonts.css"><link rel="stylesheet" href="assets/board.css">
</head><body>
<header class="strip"><a class="strip-title" href="#top">Tulsa Pantry Gap Map</a>
<nav aria-label="Sections"><a href="#map-fig">Map</a><a href="#wall">Every pantry</a><a href="#gaps">Gaps</a><a href="#mobile">Mobile</a><a href="#packet">Method</a></nav>
<button id="theme" class="theme" aria-label="Toggle dark mode">Lights</button></header>
<main id="top">

<section class="first">
<article class="sheet notice" style="--r:-0.8deg"><span class="tape" aria-hidden="true"></span>
<h1>After 5pm and on Saturdays, about half of Tulsa's highest-need neighborhoods can reach an open pantry without a car.</h1>
<p class="dek">On a weekday, <mark>{pct(DAY)}</mark> of people in the county's {C["high_need_tracts"]} highest-need tracts can walk or ride the bus to an open food pantry within {CFG["budget_min"]} minutes. After 5pm it's <mark>{pct(EVE)}</mark>. On a Saturday, <mark>{pct(SAT)}</mark>.</p>
<p class="byline">By <a href="{AUTHOR_URL}">{AUTHOR}</a>, from public data. Not a product of the Food Bank of Eastern Oklahoma.</p>
</article>
<div class="pick"><p class="pick-q">When do you need a pantry?</p>
{window_sheets("Top")}</div>

<figure class="sheet mapsheet" id="map-fig" style="--r:0.3deg"><span class="pin big" aria-hidden="true"></span>
<div class="map-main"><figcaption><span class="map-title" id="map-title">Where the gaps are</span><span class="map-sub" id="map-sub"></span></figcaption>
<div class="ticks">
<div class="tick-group" data-ctl="layer" role="group" aria-label="Map shows"><span class="tg-lab">Show</span>
<button data-v="gap" aria-pressed="true">Gap</button><button data-v="noaccess" aria-pressed="false">Can't reach</button><button data-v="need" aria-pressed="false">Need</button></div>
<div class="tick-group" data-ctl="wait" role="group" aria-label="How riders catch the bus"><span class="tg-lab">Riders</span>
<button data-v="planned" aria-pressed="true">Check the schedule</button><button data-v="walk_up" aria-pressed="false">Just walk up</button></div>
</div>
<div class="mapbox"><div id="map"></div>
<div class="zoom"><button id="zin" aria-label="Zoom in">+</button><button id="zout" aria-label="Zoom out">−</button><button id="zreset" aria-label="Reset zoom">Reset</button></div></div>
<div class="legend" id="legend"></div></div>
<div class="map-side"><aside class="sticky" id="info" aria-live="polite"></aside>
<p class="src">Sources: {src_links("", "acs", "fbeo_finder", "gtfs", "tiger")}.</p>
<details class="table-view"><summary>Every tract as a table (<span id="tract-table-win"></span>)</summary>
<div class="table-scroll"><table class="ruled" id="tract-table"><thead><tr><th>Where</th><th class="num">Poverty</th><th class="num">No car</th><th class="num">SNAP</th><th class="num">Can reach</th><th class="num">People in poverty with none in reach</th></tr></thead><tbody></tbody></table></div></details></div>
</figure>
</section>

<section class="memo-row" aria-labelledby="memo-h">
<article class="sheet memo" style="--r:0.4deg"><span class="staple" aria-hidden="true"></span>
<dl class="memo-head"><dt>To</dt><dd>Anyone planning a pantry, a route or a mobile distribution</dd><dt>From</dt><dd>{AUTHOR}</dd><dt>Re</dt><dd id="memo-h">When the pantries are open</dd></dl>
<p>The pantry network covers Tulsa's highest-need neighborhoods well on a weekday: pantries cluster where need is highest, and so do bus routes. Of the {PT["general_in_county"]} general-public pantries in the county, {OPEN["weekday_day"]} keep weekday daytime hours.</p>
<p>After work and on weekends it thins out. {OPEN["weekday_evening"]} are open on a weekday evening and {OPEN["saturday"]} on a Saturday ({W["saturday"]["pantries_weekly_in_county"]} of those every Saturday). The buses thin out too: at a typical stop one comes every {HW["weekday_day"]:.0f} minutes on a weekday, every {HW["weekday_evening"]:.0f} after 5pm.</p>
<p>In the high-need tracts, the number of people in poverty with no open pantry within reach goes from {about(POOR_HN["weekday_day"])} on a weekday to {about(POOR_HN["weekday_evening"])} on an evening and {about(POOR_HN["saturday"])} on a Saturday: {fold_words}. A pantry open only 10 to 2 on weekdays does not help a parent who works those hours.</p>
<p>The clearest case is the tract around {e(short_label(TOP_SAT["label"]))}: {pct(TOP_SAT["poverty_rate"])} of residents below the poverty line and {pct(TOP_SAT["no_vehicle_rate"])} of households without a car. On a weekday {LEAD["weekday_day"]["within_1_6km"]} pantries are open within a mile. After 5pm the nearest open one is {LEAD["weekday_evening"]["nearest_km"]} km away, on a Saturday {LEAD["saturday"]["nearest_km"]} km, and no part of the tract can reach one in {CFG["budget_min"]} minutes.</p>
<p class="ps">P.S. These numbers assume riders check the schedule. Someone who just walks to the stop waits half the time between buses; then only {pct(WALK["saturday"]["share_high_need"])} of high-need residents reach an open pantry on a Saturday.</p>
</article>
<figure class="print" style="--r:2.2deg"><span class="tape" aria-hidden="true"></span>
<img src="assets/photos/aero-stop-8005.jpg" alt="An AERO rapid bus stop on Peoria Avenue at 38th Street North in Tulsa: a tall green AERO sign, a shelter and a bike rack beside a wide road." width="1000" height="667" loading="lazy">
<figcaption><span class="marker">{e(ph38["stop"])}</span> On the AERO, the one route that runs on Sundays. {pct(ph38["share_saturday"])} of the tract around it can reach a pantry on a Saturday. <small>Photo: {e(ph38["credit"])}, <a href="{e(ph38["source_url"])}">{e(ph38["license"])}</a></small></figcaption>
</figure>
</section>

<section class="wall-sec" id="wall" aria-labelledby="wall-h">
<div class="label-strip"><h2 id="wall-h">Every county pantry's posted hours</h2>
<p>As listed in the public Food Finder, with what the sheet doesn't say written on in marker. Pantries open in the window you picked come to the front.</p>
<p class="wall-count" aria-live="polite" id="wall-count"></p></div>
<ul class="wall" id="wall-list">{wall()}</ul>
</section>

<section class="clip-sec" id="gaps" aria-labelledby="gaps-h">
<div class="clipboard"><span class="clip" aria-hidden="true"></span>
<h2 id="gaps-h" class="visually-hidden">The biggest gaps</h2>
{"".join(clipboard(w) for w in ORDER)}
<p class="clip-foot">The ten high-need tracts with the most people in poverty who can't reach an open pantry within {CFG["budget_min"]} minutes. Follows the window you picked; tap a row to find it on the map. "People in poverty with none in reach" assumes poverty is spread across a tract like its population.</p>
</div>
</section>

<section class="flyer-sec" id="mobile" aria-labelledby="mobile-h">
<h2 id="mobile-h" class="visually-hidden">Where a mobile pantry would help most</h2>
{flyer("saturday", "Saturday mobile pantry: best stops", 5)}
{flyer("weekday_evening", "Weekday evening mobile pantry: best stops", 8)}
<p class="flyer-note">A first-cut screen: every bus stop is tried as a mobile pantry spot, best first, then the best next one given the first. Real siting needs a host, parking and a partner, and should start from what churches and meal programs already do nearby.</p>
</section>

<section class="packet-sec" id="packet" aria-labelledby="packet-h">
<article class="packet"><span class="staple" aria-hidden="true"></span>
<h2 id="packet-h">How this was worked out</h2>
<div class="packet-cols">
<div>
<h3>Need</h3><p>An equal blend of three tract shares from the ACS 2020-2024: people below the poverty line, households without a car, households on SNAP. "High need" is the top quarter of the county's {C["tracts"]} tracts ({C["high_need_tracts"]} tracts, {n(C["high_need_pop"])} people).</p>
<h3>Pantries</h3><p>The Food Finder's general-public pantries and their regular sessions, including "2nd &amp; 4th Saturday" rules. A pantry counts in a window if a session overlaps it by 30 minutes. City, ZIP and school-district limits are applied.</p>
<h3>Getting there</h3><p>From every populated census block: walking at {CFG["walk_mph"]} mph, or walking to a stop, riding (one transfer at most) and walking on, all within {CFG["budget_min"]} minutes, on MetroLink's published schedule. A rider who checks the schedule waits {CFG["planned_first_wait_min"]} minutes for the first bus.</p>
</div>
<div><h3>Checked</h3><ul class="checks">{checks}</ul></div>
<div>
<h3>What could be wrong</h3><ul class="caveats">{caveats}</ul>
<p class="fine">All sources, licenses and caveats: <a href="sources.html">sources page</a>. Code and data: <a href="{REPO_URL}">{REPO_URL.removeprefix("https://")}</a>. The same story as a plain article: <a href="classic/">classic edition</a>.</p>
</div>
</div>
</article>
</section>

<section class="close" aria-label="Pick a time again">
<p class="close-line">Pick a time. The map, the sheets and the gap list all change with it.</p>
{window_sheets("Bottom")}
<p class="foot">By <a href="{AUTHOR_URL}">{AUTHOR}</a>. Built {e(S["built"])} from public data. Pantry hours change, so call before going, or dial 2-1-1. Not affiliated with the Food Bank of Eastern Oklahoma or MetroLink Tulsa. Photo by {e(ph38["credit"])}, {e(ph38["license"])}. Text and data CC BY 4.0, code MIT.</p>
</section>
</main>
<script>window.PANTRY_GAP = {{"mapAspect": 0.78, "focusHighNeed": true, "windows": {window_js()}, "ranking": {rank_js()}}};</script>
<script src="assets/vendor/d3.min.js"></script>
<script src="assets/map.js"></script>
<script src="assets/board.js"></script>
</body></html>
"""
(OUT / "index.html").write_text(page)
print(f"wrote site/index.html ({len(page) / 1e3:.0f} kB)")
