"""Shared helpers for the page builders (build_board.py, build_timetable.py).

Loads data/derived/story.json once, formats numbers for prose, and asserts the
headline claims every version of the page makes, so a data refresh that breaks
one stops the build instead of publishing stale words.
"""
import datetime as dt
import html
import json
import tomllib
from pathlib import Path

import geopandas as gpd
import pandas as pd

ROOT = Path(__file__).parent
S = json.loads((ROOT / "data" / "derived" / "story.json").read_text())
REG = tomllib.loads((ROOT / "sources.toml").read_text())
AUTHOR, AUTHOR_URL = "Taylor Burke", "https://www.taylorburke.me/"
REPO_URL = "https://github.com/TaylorBurke/tulsa-pantry-gap"
e = html.escape
W = S["windows"]
ORDER = ["weekday_day", "weekday_evening", "saturday"]
P = S["config"]["primary_wait"]
CFG = S["config"]
DAY_NAME = {1: "Sun", 2: "Mon", 3: "Tue", 4: "Wed", 5: "Thu", 6: "Fri", 7: "Sat"}
DAY_LONG = {1: "Sunday", 2: "Monday", 3: "Tuesday", 4: "Wednesday", 5: "Thursday", 6: "Friday", 7: "Saturday"}
ORD = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th", 5: "5th"}


def pct(v):
    return f"{round(v * 100)}%"


def n(v):
    return f"{int(round(v)):,}"


def about(v, word="about "):
    step = 1000 if v >= 20000 else 100
    return f"{word}{int(round(v / step) * step):,}"


def fmt_feed_date(d):
    return dt.date(int(d[:4]), int(d[4:6]), int(d[6:8])).strftime("%b %-d, %Y")


def hour_label(h):
    return {0: "12am", 12: "noon"}.get(h, f"{h % 12}{'am' if h < 12 else 'pm'}")


def and_list(items):
    items = list(items)
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " & " + items[-1]


# ---- headline numbers ---------------------------------------------------------------
HN = {w: W[w][P] for w in ORDER}
DAY, EVE, SAT = (HN[w]["share_high_need"] for w in ORDER)
OPEN = {w: W[w]["pantries_open_in_county"] for w in ORDER}
POOR_HN = {w: HN[w]["poor_no_access_high_need"] for w in ORDER}
C = S["county"]
PT = S["pantries"]
RANK = S["ranking"]
TOP_SAT, TOP_EVE = RANK["saturday"][0], RANK["weekday_evening"][0]
R5 = S["r5"]
SITING = S["siting"]
WALK = {w: W[w]["walk_up"] for w in ORDER}
LEAD = S["lead_example"]
HW = S["median_headway_min"]
GTFS_FROM, GTFS_TO = fmt_feed_date(S["gtfs"]["feed_start"]), fmt_feed_date(S["gtfs"]["feed_end"])
PHOTOS = S["photos"]

assert DAY >= 0.9 and EVE <= 0.6 and SAT <= 0.6, "headline: nearly all on weekdays, about half after 5pm/Sat"
assert OPEN["weekday_day"] > 2 * OPEN["weekday_evening"] and OPEN["weekday_day"] > 3 * OPEN["saturday"]
assert POOR_HN["saturday"] > 5 * POOR_HN["weekday_day"]
assert TOP_SAT["share_access"] == 0 and TOP_EVE["GEOID"] == TOP_SAT["GEOID"]
assert "61st St" in TOP_SAT["label"] and "Peoria" in TOP_SAT["label"]
assert R5 and all(R5[w]["planned_vs_r5_p5_agree"] >= 0.9 for w in ORDER)
assert all(v["ok"] for v in S["checks"].values())


def half_words(v):
    return "about half" if 0.45 <= v <= 0.55 else pct(v)


def short_label(label):
    """'Tulsa: near E 61st St & Peoria Ave' -> 'E 61st St & Peoria Ave'."""
    return label.split(": near ")[-1]


def window_js():
    return json.dumps({w: {"label": W[w]["label"], "short": W[w]["short"]} for w in ORDER})


def rank_js():
    return json.dumps({w: [r["GEOID"] for r in RANK[w]] for w in ORDER})


# ---- pantries, with the conditions a volunteer would write on the sheet --------------
def pantry_sheets():
    """County general pantries: listed hours split into lines, open flags per
    window, and the conditions taken from the listing itself (monthly sessions,
    service areas, no hours, posted closures, implausible hours)."""
    p = gpd.read_parquet(ROOT / "data" / "derived" / "pantries.parquet")
    p = p[p.general & p.in_county].copy()
    sess = pd.read_csv(ROOT / "data" / "derived" / "pantry_sessions.csv", dtype={"weeks": str})
    sess = sess[sess["class"] == "general"]
    special = S["special_hours"]
    susp = {x["name"] for x in PT["suspicious_hours"]}
    out = []
    for r in p.itertuples():
        notes = []
        if not r.hours_listed:
            notes.append("No hours listed. Call first.")
        for s in sess[sess.location_id == r.location_id].itertuples():
            if s.every_other:
                notes.append(f"{DAY_NAME[s.day]}: every other week")
            elif isinstance(s.weeks, str) and s.weeks and s.per_month < CFG["weeks_per_month"] - 0.01:
                notes.append(f"{DAY_NAME[s.day]}: {and_list(ORD[int(x)] for x in s.weeks.split(','))} only")
        areas = [a.strip() for a in (r.restriction_areas or "").split(";") if a.strip()]
        if r.restriction_rule == "place":
            notes.append(f"{and_list(areas)} residents only")
        elif r.restriction_rule == "zip":
            notes.append(f"ZIPs {', '.join(areas)} only")
        elif r.restriction_rule == "school_district":
            notes.append(f"{and_list(a.replace(' Public Schools', '') for a in areas)} school districts only")
        noted = [x["note"] for x in special if x["name"] == r.name and x["closed"] and x["note"]]
        closed = sorted({x["date"] for x in special if x["name"] == r.name and x["closed"]})
        if noted:  # the pantry's own wording, e.g. "Closed Thanksgiving Holiday 11/20/26-11/27/26"
            notes.append(noted[0].replace("-", "–"))
        elif closed:
            d = [dt.date.fromisoformat(x) for x in closed]
            notes.append("Closed " + d[0].strftime("%b %-d") + ("" if len(d) == 1 else f"–{d[-1].day}"))
        for x in special:
            if x["name"] == r.name and not x["closed"] and x["note"]:
                notes.append(f'{dt.date.fromisoformat(x["date"]).strftime("%b %-d")}: {x["note"].lower()}')
        if r.name in susp:
            notes.append("Fri till 11pm? Call to check.")
        uniq = list(dict.fromkeys(notes))
        out.append({
            "id": int(r.location_id), "name": r.name, "address": r.address, "city": r.city,
            "hours": [h.strip() for h in r.hours.split(";")] if r.hours_listed else [],
            "listed": bool(r.hours_listed), "notes": uniq[:3],
            **{f"open_{w}": bool(getattr(r, f"open_{w}")) for w in ORDER},
            **{f"pm_{w}": float(getattr(r, f"pm_{w}")) for w in ORDER},
        })
    # The finder lists a few pantries twice (one copy without hours); keep the listed one.
    listed_names = {x["name"] for x in out if x["listed"]}
    out = [x for x in out if x["listed"] or x["name"] not in listed_names]
    return sorted(out, key=lambda x: x["name"].lower())


def checks_items():
    """The independent checks as (headline, detail) pairs, shared by every version."""
    ck = S["checks"]
    spot = ck["hand_spot_check_three_tracts"]["tracts"][0]["raw"]
    tt = ck["travel_time_brute_force"]
    usda = ck["usda_sram_cross_source"]["correlations"]
    return [
        ("Totals add up",
         f'Tract populations sum to the county ({n(ck["acs_tracts_sum_to_county"]["tract_sum"])}), and the 2020 census '
         f'blocks used as trip origins sum to the official 2020 count ({n(ck["blocks_sum_to_2020_census"]["block_sum"])}).'),
        ("Three tracts recomputed by hand",
         f'From the raw Census rows, the highest-, median- and lowest-need tracts match exactly. Tract 10: '
         f'{spot["B17001_E002"]} of {spot["B17001_E001"]} people below poverty, '
         f'{int(spot["B25044_E003"]) + int(spot["B25044_E010"])} of {spot["B25044_E001"]} households without a car.'),
        ("USDA agrees",
         f'Its own tract tabulation correlates {usda["poverty"]:.2f} (poverty), {usda["no_vehicle"]:.2f} (no car) and '
         f'{usda["snap"]:.2f} (SNAP) with these figures.'),
        ("Bus trips checked against the timetable",
         f'In {tt["pairs"]} sampled trips, the best one-bus trip found straight from the schedule never beat the model '
         f'by more than 3 minutes, and gave the same reachable-or-not answer in {pct(tt["same_reachable_verdict"])}.'),
        ("A real trip planner agrees",
         "R5, routing on the street network and the full timetable for 500 sample blocks, gives the same "
         "reachable-or-not answer for " + ", ".join(f'{pct(R5[w]["planned_vs_r5_p5_agree"])} ({W[w]["short"].lower()})'
                                                     for w in ORDER)
         + " of residents. The shortcut runs 1 to 3 points optimistic."),
    ]


def caveats_items():
    sat_unlisted = W["saturday"][P]["share_high_need_unlisted_counted_open"]
    return [
        ("Survey margins", f"Tract figures come from a sample, so every rate on the map shows its 90% margin. "
                           f"{S['top_tracts_with_shaky_component']} of the {S['top_tracts_total']} tracts on any "
                           f"top-ten list has a measure with a wide margin."),
        ("Hours go stale", f"Pantries post their own hours, and they change. {PT['general_in_county_no_hours']} county "
                           f"pantries list none. Counting all of those as open in every window lifts the Saturday share "
                           f"in high-need tracts from {pct(SAT)} to {pct(sat_unlisted)}, an upper bound."),
        ("The bus is a model", f"Scheduled service only, from the feed valid {GTFS_FROM} to {GTFS_TO}. No late buses, "
                               "no trip home, no groceries to carry, and walking is measured in straight lines."),
        ("Tracts are averages", "Need is a tract average and hides pockets inside better-off tracts. Access is worked out "
                                "block by block, but those block populations date from 2020."),
        ("Not every pantry", "Only the public Food Finder's listings: school, senior and meal programs are left out, and "
                             "pantries outside the Food Bank's network are missing."),
    ]


def src_links(prefix, *ids):
    return ", ".join(f'<a href="{prefix}sources.html#{i}">{e(REG[i]["name"].split(" (")[0])}</a>' for i in ids)
