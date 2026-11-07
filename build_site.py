"""Build site/classic/index.html (the article edition) and site/sources.html from data/derived/story.json.

Every number in the prose is read from story.json (written by analysis/story.py),
never typed by hand. Headline claims are asserted, so a data refresh that breaks
one stops the build instead of publishing stale words.
"""
import datetime as dt
import html
import json
import tomllib
from pathlib import Path

import geopandas as gpd

ROOT = Path(__file__).parent
AUTHOR, AUTHOR_URL = "Taylor Burke", "https://www.taylorburke.me/"
REPO_URL = "https://github.com/TaylorBurke/tulsa-pantry-gap"
S = json.loads((ROOT / "data" / "derived" / "story.json").read_text())
REG = tomllib.loads((ROOT / "sources.toml").read_text())
e = html.escape
W = S["windows"]
ORDER = ["weekday_day", "weekday_evening", "saturday"]
P = S["config"]["primary_wait"]


def pct(v):
    return f"{round(v * 100)}%"


def n(v):
    return f"{int(round(v)):,}"


def about(v):
    """Round a people count for prose: nearest 100 (nearest 1,000 at 20,000 and up)."""
    step = 1000 if v >= 20000 else 100
    return f"about {int(round(v / step) * step):,}"


def frac_words(v):
    for lo, hi, w in [(0.45, 0.55, "about half of"), (0.3, 0.37, "about a third of"),
                      (0.22, 0.28, "about a quarter of"), (0.63, 0.7, "about two thirds of"),
                      (0.9, 1.0, "nearly all")]:
        if lo <= v <= hi:
            return w
    return pct(v) + " of"


def src(*ids):
    links = ", ".join(f'<a href="../sources.html#{i}">{e(REG[i]["name"].split(" (")[0])}</a>' for i in ids)
    return f'<p class="src">Sources: {links}.</p>'


def fmt_date(d):
    x = dt.date(int(d[:4]), int(d[4:6]), int(d[6:8]))
    return x.strftime("%b %-d, %Y")


def tract_name(geoid):
    base, suf = geoid[5:9].lstrip("0"), geoid[9:]
    return base if suf == "00" else f"{base}.{suf}"


# ---- numbers used in the prose -------------------------------------------------
hn = {w: W[w][P] for w in ORDER}
day, eve, sat = (hn[w]["share_high_need"] for w in ORDER)
open_n = {w: W[w]["pantries_open_in_county"] for w in ORDER}
poor_hn = {w: hn[w]["poor_no_access_high_need"] for w in ORDER}
c = S["county"]
pt = S["pantries"]
rank = S["ranking"]
top_sat, top_eve = rank["saturday"][0], rank["weekday_evening"][0]
r5 = S["r5"]
site_sat, site_eve = S["siting"]["saturday"], S["siting"]["weekday_evening"]
walk = {w: W[w]["walk_up"] for w in ORDER}
gtfs_from, gtfs_to = fmt_date(S["gtfs"]["feed_start"]), fmt_date(S["gtfs"]["feed_end"])
cfg = S["config"]
lead = S["lead_example"]
hw = S["median_headway_min"]

# Headline claims the prose makes. If the data stops supporting one, rewrite the text.
assert day >= 0.9, "dek: nearly all high-need residents reach a pantry on weekdays"
assert eve <= 0.6 and sat <= 0.6, "dek: only about half reach one after 5pm / on Saturday"
assert open_n["weekday_day"] > 2 * open_n["weekday_evening"] and open_n["weekday_day"] > 3 * open_n["saturday"]
assert poor_hn["saturday"] > 5 * poor_hn["weekday_day"], "the fold-change claim"
assert top_sat["share_access"] == 0 and top_eve["GEOID"] == top_sat["GEOID"], "61st & Peoria lead claim"
assert "61st St" in top_sat["label"] and "Peoria" in top_sat["label"], "61st & Peoria heading"
assert lead["GEOID"] == top_sat["GEOID"] and lead["weekday_day"]["within_1_6km"] >= 1
assert min(lead["weekday_evening"]["nearest_km"], lead["saturday"]["nearest_km"]) > 3, "'far away after 5pm' claim"
assert r5 and all(r5[w]["planned_vs_r5_p5_agree"] >= 0.9 for w in ORDER), "validation claim"
assert all(v["ok"] for v in S["checks"].values()), "a check failed"
if frac_words(eve) == frac_words(sat):
    dek_tail = f"After 5pm and on Saturdays, only {frac_words(sat)} them can."
else:
    dek_tail = f"After 5pm, only {frac_words(eve)} them can; on Saturdays, {frac_words(sat)} them."
fold = poor_hn["saturday"] / max(poor_hn["weekday_day"], 1)
fold_words = "roughly tenfold" if 8 <= fold <= 12 else f"about {fold:.0f}-fold"

# ---- hero ---------------------------------------------------------------------------
hero = "".join(
    f'<div><div class="hs-val">{pct(hn[w]["share_high_need"])}</div>'
    f'<div class="meter" aria-hidden="true"><i style="width:{hn[w]["share_high_need"] * 100:.1f}%"></i></div>'
    f'<div class="hs-lab">{e(W[w]["label"])}</div>'
    f'<div class="hs-sub">{open_n[w]} of {pt["general_in_county"]} county pantries open</div></div>'
    for w in ORDER)


# ---- gap tables ------------------------------------------------------------------------
def gap_table(w):
    rows = []
    for r in rank[w]:
        flag = ' <span class="flag">wide margins</span>' if r["shaky_components"] else ""
        rows.append(
            f'<tr data-geoid="{r["GEOID"]}" tabindex="0"><td class="num">{r["rank"]}</td>'
            f'<td class="where">{e(r["label"])}<small>Tract {e(str(r["tract"]))}{flag}</small></td>'
            f'<td class="num">{pct(r["poverty_rate"])} <span class="moe">±{round(r["poverty_rate_moe"] * 100)}</span></td>'
            f'<td class="num">{pct(r["no_vehicle_rate"])}</td>'
            f'<td class="num">{pct(r["share_access"])}</td>'
            f'<td class="num">{n(r["people_in_poverty_no_access"])}</td></tr>')
    return (f'<div data-win-panel="{w}"{"" if w == "saturday" else " hidden"}>'
            f'<h3>{e(W[w]["label"])}</h3><div class="table-wrap"><table class="data">'
            '<thead><tr><th class="num">#</th><th>Where (nearest arterials)</th><th class="num">In poverty</th>'
            '<th class="num">No car</th><th class="num">Reach a pantry</th>'
            '<th class="num">People in poverty without one</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div></div>')


rob = S["robustness_top10_overlap"]
rob_min_alt = min(min(v for k, v in rob[w].items() if k != "walk_up_wait") for w in ORDER)
rob_walk = [rob[w]["walk_up_wait"] for w in ORDER]


# ---- siting -------------------------------------------------------------------------------
def sites(sw):
    items = []
    for s in sw["sites"]:
        stop = s["stop_name"]
        served = sorted({t["label"].split(": near ")[-1] for t in s["main_tracts"]})
        items.append(f'<li><strong>{e(stop)}</strong> (bus stop): '
                     f'{about(s["people_in_poverty_newly_within_budget"])} more people in poverty within '
                     f'{cfg["budget_min"]} minutes ({n(s["residents_newly_within_budget"])} residents in all), '
                     f'mostly around {e("; ".join(served))}.</li>')
    return "<ol>" + "".join(items) + "</ol>"


# ---- pantry table (table view) ---------------------------------------------------------------
pant = gpd.read_parquet(ROOT / "data" / "derived" / "pantries.parquet")
pant = pant[pant.general & pant.in_county].sort_values(["city", "name"])
prow = "".join(
    f'<tr><td>{e(r["name"])}<small style="display:block;color:var(--muted)">{e(r.address)}, {e(r.city)}</small></td>'
    f'<td>{e(r.hours)}</td>'
    + "".join(f'<td class="num">{"●" if r[f"open_{w}"] else ""}</td>' for w in ORDER) + "</tr>"
    for _, r in pant.iterrows())

# ---- checks list ---------------------------------------------------------------------------------
ck = S["checks"]
spot = ck["hand_spot_check_three_tracts"]["tracts"]
tt = ck["travel_time_brute_force"]
usda = ck["usda_sram_cross_source"]["correlations"]
s0 = spot[0]["raw"]
checks_html = "".join([
    f'<li>Tract populations sum to the county total ({n(ck["acs_tracts_sum_to_county"]["tract_sum"])}, ACS 2020-2024), '
    f'and the populated 2020 census blocks used as trip origins sum to the official 2020 count '
    f'({n(ck["blocks_sum_to_2020_census"]["block_sum"])}).</li>',
    f'<li>Three tracts recomputed by hand from the raw Census text rows (highest-need, median and lowest-need) '
    f'match the pipeline exactly. Tract {tract_name(spot[0]["GEOID"])}, for example: {s0["B17001_E002"]} of '
    f'{s0["B17001_E001"]} people below poverty, {int(s0["B25044_E003"]) + int(s0["B25044_E010"])} of '
    f'{s0["B25044_E001"]} households without a car.</li>',
    f'<li>USDA\'s own tract tabulation agrees: correlation {usda["poverty"]:.2f} for poverty, '
    f'{usda["no_vehicle"]:.2f} for zero-vehicle households, {usda["snap"]:.2f} for SNAP.</li>',
    f'<li>The best one-bus trip found by brute force from the raw timetable never beat the model by more than '
    f'3 minutes in {tt["pairs"]} sampled trips, and both gave the same reachable-or-not verdict in '
    f'{pct(tt["same_reachable_verdict"])} of them.</li>',
    "<li>A full timetable router (R5, on the real street network) agrees with the model's reachable-or-not verdict for "
    + ", ".join(f'{pct(r5[w]["planned_vs_r5_p5_agree"])} ({W[w]["short"].lower()})' for w in ORDER)
    + " of residents in a 500-block sample. The model runs slightly optimistic: it puts "
    + ", ".join(f'{pct(r5[w]["share_reach_model_planned"])} within reach where R5 puts '
                f'{pct(r5[w]["share_reach_r5_p5"])}' for w in ORDER)
    + " (weekday day, evening, Saturday).</li>",
])

susp = "; ".join(f'{e(x["name"])} lists a {(x["end"] - x["start"]) / 60:.0f}-hour Friday session'
                 for x in pt["suspicious_hours"]) or "none flagged"

# ---- page --------------------------------------------------------------------------------------
window_js = json.dumps({w: {"label": W[w]["label"], "short": W[w]["short"]} for w in ORDER})
rank_js = json.dumps({w: [r["GEOID"] for r in rank[w]] for w in ORDER})
peoria = e(top_sat["label"].split(": near ")[1])

page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Tulsa Pantry Gap Map</title>
<meta name="description" content="Where food need is high in Tulsa County but no pantry is open and reachable without a car, on weekdays, weekday evenings and Saturdays.">
<link rel="icon" href="data:,"><link rel="stylesheet" href="../assets/style.css">
</head><body>
<nav class="nav"><div class="nav-in"><a class="nav-home" href="#top">Pantry Gap Map</a>
<div class="nav-links"><a href="#map-sec">Map</a><a href="#findings">Findings</a><a href="#gaps">Top gaps</a><a href="#mobile">Mobile pantry</a><a href="#method">Method</a><a href="../sources.html">Sources</a></div>
<button id="theme" aria-label="Toggle dark mode" title="Toggle dark mode">◐</button></div></nav>
<div class="wrap" id="top">
<header class="mast">
<p class="eyebrow">Tulsa County · food access without a car</p>
<h1>Tulsa Pantry Gap Map</h1>
<p class="dek">In Tulsa County's highest-need neighborhoods, {frac_words(day)} residents can reach an open food pantry on foot or by bus within {cfg["budget_min"]} minutes on a weekday. {dek_tail}</p>
<p class="byline">By <a href="{AUTHOR_URL}">{AUTHOR}</a>. A personal project built only on public data. Not a product of, or endorsed by, the Food Bank of Eastern Oklahoma. Pantry hours as listed in its public Food Finder; bus schedule valid {gtfs_from} to {gtfs_to}.</p>
<div class="hero"><p class="hero-head">Share of residents in the {c["high_need_tracts"]} highest-need tracts who can reach an open pantry within {cfg["budget_min"]} minutes, walking and riding the bus</p>
<div class="hero-stats">{hero}</div></div>
</header>

<section class="part" id="map-sec" style="border-top:0;margin-top:0;padding-top:16px">
<figure id="map-fig"><figcaption class="title" id="map-title">Where the gaps are</figcaption>
<figcaption class="sub" id="map-sub"></figcaption>
<div class="controls">
<div class="ctl-group"><span class="ctl-lab">When</span><div class="seg" data-ctl="win" role="group" aria-label="Time window">
<button data-v="weekday_day" aria-pressed="false">Weekday day</button><button data-v="weekday_evening" aria-pressed="false">Weekday evening</button><button data-v="saturday" aria-pressed="true">Saturday</button></div></div>
<div class="ctl-group"><span class="ctl-lab">Show</span><div class="seg" data-ctl="layer" role="group" aria-label="Map layer">
<button data-v="gap" aria-pressed="true">Gap</button><button data-v="noaccess" aria-pressed="false">Can't reach</button><button data-v="need" aria-pressed="false">Need</button></div></div>
<div class="ctl-group"><span class="ctl-lab">Riders</span><div class="seg" data-ctl="wait" role="group" aria-label="Waiting assumption">
<button data-v="planned" aria-pressed="true">Check the schedule</button><button data-v="walk_up" aria-pressed="false">Just walk up</button></div></div>
</div>
<div class="map-layout"><div><div class="mapbox"><div id="map"></div>
<div class="zoom-btns"><button id="zin" aria-label="Zoom in">+</button><button id="zout" aria-label="Zoom out">−</button><button id="zreset" aria-label="Reset zoom">⟲</button></div></div>
<div class="legend" id="legend"></div></div>
<aside class="info" id="info" aria-live="polite"></aside></div>
{src("acs", "fbeo_finder", "gtfs", "tiger")}
<details class="table-view"><summary>Table view: every tract, sorted by the gap (<span id="tract-table-win"></span>)</summary>
<div class="table-wrap"><table class="data" id="tract-table"><thead><tr><th>Where</th><th class="num">Poverty</th><th class="num">No car</th><th class="num">SNAP</th><th class="num">Reach a pantry</th><th class="num">People in poverty without one</th></tr></thead><tbody></tbody></table></div></details>
<details class="table-view"><summary>Table view: the {pt["general_in_county"]} general-public pantries in the county and their listed hours</summary>
<div class="table-wrap"><table class="data"><thead><tr><th>Pantry</th><th>Listed hours</th><th class="num">Wkday</th><th class="num">Eve</th><th class="num">Sat</th></tr></thead><tbody>{prow}</tbody></table></div></details>
</figure>
</section>

<section class="part" id="findings"><h2>It's not where the pantries are. It's when they're open.</h2>
<div class="prose">
<p class="lede">On a weekday daytime, the pantry network reaches Tulsa's highest-need tracts well: {pct(day)} of their residents can get to an open pantry within {cfg["budget_min"]} minutes without a car. Pantries cluster where need is highest, and so do bus routes.</p>
<p>The network thins out after work and on weekends. Of the {pt["general_in_county"]} general-public pantries in the county, <strong>{open_n["weekday_day"]}</strong> hold regular weekday daytime hours, <strong>{open_n["weekday_evening"]}</strong> are open on a weekday evening after 5pm, and <strong>{open_n["saturday"]}</strong> on a Saturday ({W["saturday"]["pantries_weekly_in_county"]} of those every Saturday, the rest once or twice a month). Buses thin out too: at the typical stop a bus comes every {hw["weekday_day"]:.0f} minutes on a weekday daytime, every {hw["weekday_evening"]:.0f} after 5pm and every {hw["saturday"]:.0f} on Saturday, and the last runs of the day start around 9pm.</p>
<p>In the high-need tracts, the number of people in poverty with no open pantry within reach goes from {about(poor_hn["weekday_day"])} on a weekday to {about(poor_hn["weekday_evening"])} on a weekday evening and {about(poor_hn["saturday"])} on Saturday, {fold_words}. A pantry open only 10 to 2 on weekdays does not help a parent who works those hours.</p>
</div>
<div class="kpis">
<div class="tile"><div class="lab">Pantries open: weekday day / evening / Saturday</div><div class="val">{open_n["weekday_day"]} / {open_n["weekday_evening"]} / {open_n["saturday"]}</div><div class="sub">general-public pantries in Tulsa County with listed hours in each window</div></div>
<div class="tile"><div class="lab">People in poverty in high-need tracts with no open pantry in reach on Saturday</div><div class="val">~{n(round(poor_hn["saturday"], -3))}</div><div class="sub">vs ~{n(round(poor_hn["weekday_day"], -2))} on a weekday daytime</div></div>
<div class="tile"><div class="lab">Zero-car households countywide with no open pantry in reach on Saturday</div><div class="val">~{n(round(W["saturday"][P]["nov_no_access_county"], -2))}</div><div class="sub">of {n(c["no_vehicle_households"])} households without a car in the county</div></div>
</div>
<div class="prose">
<h3>The clearest case: {peoria}</h3>
<p>The tract around {peoria} (tract {e(str(top_sat["tract"]))}) is among the county's highest-need: {pct(top_sat["poverty_rate"])} of residents below the poverty line (±{round(top_sat["poverty_rate_moe"] * 100)} points) and {pct(top_sat["no_vehicle_rate"])} of households without a car. On weekdays {lead["weekday_day"]["within_1_6km"]} pantries are open within a mile of where its residents live. After 5pm the nearest open one is {lead["weekday_evening"]["nearest_km"]} km away, and on Saturday {lead["saturday"]["nearest_km"]} km; no part of the tract can reach one in {cfg["budget_min"]} minutes. It tops both the evening and the Saturday gap lists.</p>
<h3>How much the bus assumption matters</h3>
<p>These figures assume a rider who checks the schedule and leaves home to meet the bus. Someone who just walks to the stop waits half the time between buses on average, and on a route that comes once an hour that is the whole budget. Under that assumption only {pct(walk["weekday_day"]["share_high_need"])} of high-need residents reach an open pantry on a weekday, {pct(walk["weekday_evening"]["share_high_need"])} on an evening and {pct(walk["saturday"]["share_high_need"])} on Saturday. The <em>Riders</em> switch on the map shows both.</p>
<h3>Countywide</h3>
<p>Across the whole county, {pct(W["weekday_day"][P]["share_county"])} of residents can reach an open pantry without a car on a weekday, {pct(W["weekday_evening"][P]["share_county"])} on an evening and {pct(W["saturday"][P]["share_county"])} on Saturday. Much of the rest live in suburbs and rural areas with little or no bus service, where most households drive. That is why the map leans on need and ranks gaps by people in poverty, not by area.</p>
</div>
</section>

<section class="part" id="gaps"><h2>The biggest gaps</h2>
<div class="prose"><p>The ten high-need tracts (top quarter of the need index) with the most people in poverty who cannot reach an open pantry within {cfg["budget_min"]} minutes. The table follows the <em>When</em> switch on the map; tap a row to find the tract.</p></div>
{"".join(gap_table(w) for w in ORDER)}
<p class="caveat"><strong>How firm is this list?</strong> The top ten barely move when the need index is weighted differently: at least {rob_min_alt} of the ten stay in under every alternative tried (vehicle access double-weighted, 200% of poverty instead of 100%, poverty alone). They move more with the waiting assumption: {min(rob_walk)} to {max(rob_walk)} of the ten stay under walk-up waiting. Labels name the nearest mile-grid arterials to where each tract's residents live. "People in poverty without one" assumes poverty is spread across a tract like its population.</p>
{src("acs", "fbeo_finder", "gtfs")}
</section>

<section class="part" id="mobile"><h2>Where would a mobile pantry help most?</h2>
<div class="prose">
<p>A first-cut screen, not a plan: treat every bus stop as a possible spot for a mobile distribution, and count the people in poverty who live where nothing is open within {cfg["budget_min"]} minutes today but who could reach that stop. Pick the best spot, then the best next spot given the first.</p>
<h3>Saturday</h3>{sites(site_sat)}
<h3>Weekday evening</h3>{sites(site_eve)}
<p>Of the {about(site_sat["people_in_poverty_without_access"])} people in poverty countywide with no open Saturday pantry in reach, these three Saturday sites would reach {about(sum(s["people_in_poverty_newly_within_budget"] for s in site_sat["sites"]))}. Real siting needs a host site, parking and a partner, and should start from what meal programs and churches already do nearby.</p>
</div></section>

<section class="part" id="method"><h2>Method and caveats</h2>
<dl class="method">
<dt>Need</dt><dd>An equal-weight blend of three tract shares from the ACS 2020-2024 5-year estimates: people below the poverty line, households without a vehicle, and households receiving SNAP. Each becomes a z-score across the county's {c["tracts"]} tracts and the three are averaged (weight 1/3 each). "High need" is the top quarter ({c["high_need_tracts"]} tracts, home to {n(c["high_need_pop"])} people). The three measures move together (correlations {min(S["need_component_correlations"]):.2f} to {max(S["need_component_correlations"]):.2f}), so the blend mostly sharpens the picture rather than changing it.</dd>
<dt>Pantries</dt><dd>The {pt["listings"]} locations the Food Bank of Eastern Oklahoma's public Food Finder lists within 30 miles of Tulsa. {pt["general_total"]} run a pantry open to the general public ({pt["general_in_county"]} inside the county). School pantries for enrolled students, senior commodity boxes (CSFP) and meal programs appear in the finder but are not counted, since a working parent can't use them for groceries. Pantries outside the network, and parts of the network not on the public map, are missing. {pt["with_modeled_service_area"]} pantries limit who they serve by city, ZIP code, school district or county, and those limits are applied; one neighborhood-only limit and one unspecified one could not be mapped and are treated as open to all.</dd>
<dt>Time windows</dt><dd>A pantry counts in a window if it lists a regular session that overlaps it by at least 30 minutes: weekday daytime (Monday to Friday, 8am to 5pm), weekday evening (Monday to Friday, after 5pm) and Saturday. Monthly sessions ("2nd and 4th Saturday") count. Counting only weekly sessions lowers the Saturday county share from {pct(W["saturday"][P]["share_county"])} to {pct(W["saturday"][P]["share_county_weekly_only"])}.</dd>
<dt>Travel time</dt><dd>From each populated 2020 census block (the {n(c["census_2020_pop"])} people who lived in Tulsa County in 2020), the fastest of: walking straight to a pantry, or walking to a bus stop, riding (with up to one transfer) and walking to the pantry, all within {cfg["budget_min"]} minutes. Walking is {cfg["walk_mph"]} mph over straight-line distance × {cfg["circuity"]} to stand in for the street grid. Bus legs use MetroLink Tulsa's published schedule: median scheduled run times between stops, and waits from how often each route comes during the window (half the time between buses for a transfer). The first wait is {cfg["planned_first_wait_min"]} minutes for a rider who checks the schedule; the "walk up" view uses half the headway instead.</dd>
<dt>Why not a full trip planner?</dt><dd>A frequency-based approximation is fast, transparent and reproducible with a few Python libraries. To check it, a full timetable router (R5, via r5py, on the OpenStreetMap street network) routed a random sample of 500 blocks on real dates in the schedule's range. The two agree closely (see Checks), so the router is kept as an optional validation step rather than the main pipeline.</dd>
<dt>Gap</dt><dd>A tract is a gap tract in a window if it is high-need and fewer than half its residents can reach an open pantry. Tracts are ranked by the estimated number of people in poverty who can't.</dd>
</dl>
<h3>Checks</h3>
<ul class="checks">{checks_html}</ul>
<h3>What could be wrong</h3>
<div class="prose"><ul>
<li><strong>ACS margins of error.</strong> Tract estimates come from a sample and carry wide margins, shown as ± in the tract details. Small shares, like zero-car households in a suburban tract, are the noisiest. {S["top_tracts_with_shaky_component"]} of the {S["top_tracts_total"]} tracts that appear in any top-ten list has a need measure with a coefficient of variation above {round(cfg["cv_unreliable"] * 100)}%.</li>
<li><strong>Stale pantry hours.</strong> Hours are self-reported in the Food Finder and change. Holiday closures and one-off changes aren't modeled, {pt["general_in_county_no_hours"]} county pantries list no hours at all, and some listings look off ({susp}; counted as listed). Counting every pantry without listed hours as open in every window raises the Saturday share in high-need tracts from {pct(sat)} to {pct(W["saturday"][P]["share_high_need_unlisted_counted_open"])}: an upper bound, not a likely value.</li>
<li><strong>The bus approximation.</strong> Scheduled service only: late buses, missed transfers and the trip home aren't modeled, and neither is carrying groceries. The schedule changes three times a year (this feed runs {gtfs_from} to {gtfs_to}). Straight-line walking ignores missing sidewalks, highways and the river, so it probably flatters access in places.</li>
<li><strong>Tract averages hide variation.</strong> A tract's poverty rate covers thousands of people, and pockets of need inside a better-off tract don't show. Access is computed block by block and weighted by population, so it carries more detail than need does, but those block populations are from 2020.</li>
<li><strong>Need is not demand.</strong> The index says where hardship is concentrated, not how many people want pantry food, and it can't see people the survey misses.</li>
</ul></div>
{src("acs", "usda_sram", "fbeo_finder", "gtfs", "tiger", "osm")}
</section>

<footer>
<p>By <a href="{AUTHOR_URL}">{AUTHOR}</a>. Built {e(S["built"])} from public data. Code, method and derived data: <a href="{REPO_URL}">{REPO_URL.removeprefix("https://")}</a>; everything rebuilds from the raw downloads with <code>make</code>. Text and derived data CC BY 4.0, code MIT. Not affiliated with the Food Bank of Eastern Oklahoma or MetroLink Tulsa. Pantry information changes: call a pantry before going, or dial 2-1-1.</p>
<p><a href="../sources.html">All sources, licenses and caveats</a></p>
</footer>
</div>
<script>window.PANTRY_GAP = {{"dataRoot": "../", "windows": {window_js}, "ranking": {rank_js}}};</script>
<script src="../assets/vendor/d3.min.js"></script>
<script src="../assets/map.js"></script>
<script src="../assets/ui.js"></script>
</body></html>
"""
(ROOT / "site" / "classic").mkdir(parents=True, exist_ok=True)
(ROOT / "site" / "classic" / "index.html").write_text(page)


# ---- sources page ------------------------------------------------------------------------------
def fetched(sid):
    mf = ROOT / "data" / "raw" / sid / "manifest.json"
    if not mf.exists():
        return "not fetched"
    return e(max(i["fetched_at"] for i in json.loads(mf.read_text()))[:10])


cards = []
for sid, s in REG.items():
    cards.append(f"""<article id="{e(sid)}"><h2>{e(s['name'])}</h2><p class="pub">{e(s['publisher'])}</p><dl>
<dt>Measures</dt><dd>{e(s['measures'])}</dd><dt>Caveat</dt><dd>{e(s['caveat'])}</dd>
<dt>License</dt><dd>{e(s['license'])}</dd><dt>Retrieved</dt><dd>{fetched(sid)} · {e(s['access'])}</dd>
<dt>Link</dt><dd><a href="{e(s['url'])}">{e(s['url'])}</a></dd></dl></article>""")
(ROOT / "site" / "sources.html").write_text(f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Pantry Gap Sources</title><link rel="icon" href="data:,"><link rel="stylesheet" href="assets/style.css"></head>
<body><div class="wrap"><header class="mast"><p class="eyebrow"><a href="index.html">Tulsa Pantry Gap Map</a></p><h1>Sources</h1>
<p class="dek">Every number on the map comes from one of these public sources. Each lists what it measures and where it falls short.</p></header>
<main class="srcs">{''.join(cards)}</main><footer><a href="index.html">Back to the map</a></footer></div>
<script src="assets/ui.js"></script></body></html>""")
print(f"wrote site/classic/index.html ({len(page) / 1e3:.0f} kB) and site/sources.html ({len(REG)} sources)")
