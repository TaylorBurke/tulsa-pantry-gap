"""Pantry supply: locations, program class, regular sessions, and window flags.

Reads data/raw/fbeo_finder/{locations,schedules}.json (public Food Finder) and
data/manual/service_areas.csv. Writes data/derived/pantries.parquet (points,
EPSG:4326) and data/derived/pantry_sessions.csv.

Only public listing fields are kept (name, address, programs, hours, eligibility
summary). Contact names, emails and the finder's audit fields are dropped.
"""
import json
import re

import pandas as pd
import geopandas as gpd

from config import (RAW, MANUAL, DERIVED, WINDOWS, WINDOW_ORDER, GENERAL_PANTRY_TYPES,
                    RESTRICTED_SERVICE_PATTERNS, WEEKS_PER_MONTH)

DAY = {1: "Sun", 2: "Mon", 3: "Tue", 4: "Wed", 5: "Thu", 6: "Fri", 7: "Sat"}
ORD = {"1st": 1, "2nd": 2, "3rd": 3, "4th": 4, "5th": 5, "last": 5}
# Listings with no program record but a school's name are student pantries.
SCHOOL_NAME = re.compile(r"\b(school|academy|university|tulsa tech|tulsa met)\b", re.I)
ORD_TXT = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th", 5: "5th"}


def minutes(ts):
    """'1900-01-01T13:30:00' -> 810."""
    return int(ts[11:13]) * 60 + int(ts[14:16])


def clock(m):
    h, mm = divmod(int(m) % 1440, 60)
    suffix = "am" if h < 12 else "pm"
    h12 = h % 12 or 12
    return f"{h12}{suffix}" if mm == 0 else f"{h12}:{mm:02d}{suffix}"


def service_class(name, ptype):
    if ptype == "Hot/Cold Meal Program":
        return "meal"
    for cls, pats in RESTRICTED_SERVICE_PATTERNS.items():
        if any(p.lower() in (name or "").lower() for p in pats):
            return cls
    if ptype in GENERAL_PANTRY_TYPES:
        return "general"
    return "other"


def location_class(food_programs, name=""):
    """Class for a location the finder lists without program records."""
    if SCHOOL_NAME.search(name or ""):
        return "school"
    fp = food_programs or ""
    if any(t in fp for t in ["Pantry", "Food Distribution", "Pop-Up"]):
        return "general"
    if "Meal" in fp:
        return "meal"
    return "other"


def weeks(rec):
    """Ordinal weeks a session runs, e.g. {2, 4}; empty set = every week."""
    txt = f"{rec.get('weeksOfMonth') or ''},{rec.get('daysOfMonth') or ''}".lower()
    return {ORD[w] for w in re.findall(r"1st|2nd|3rd|4th|5th|last", txt)}


def per_month(wk, every_other):
    if every_other:
        return WEEKS_PER_MONTH / 2
    if not wk or wk >= {1, 2, 3, 4}:
        return WEEKS_PER_MONTH  # weekly ("1st-4th" means every week but the odd 5th)
    return float(len(wk))


def session_rows(lid, recs, cls, source):
    out = []
    for r in recs:
        start, end = minutes(r["startTime"]), minutes(r["endTime"])
        if end <= start:
            end += 1440
        wk = weeks(r)
        eo = bool(r.get("everyOtherWeekInd"))
        out.append({
            "location_id": lid, "class": cls, "source": source, "day": r["dayOfWeek"],
            "start": start, "end": end, "weeks": ",".join(map(str, sorted(wk))),
            "every_other": eo, "per_month": per_month(wk, eo),
        })
    return out


def in_window(s, w):
    lo, hi = w["open_overlap"]
    return s["day"] in w["days"] and (min(s["end"], hi) - max(s["start"], lo)) >= w["min_overlap"]


def hours_text(sess):
    if sess.empty:
        return "Hours not listed"
    parts = []
    for _, s in sess.sort_values(["day", "start"]).drop_duplicates(["day", "start", "end", "weeks"]).iterrows():
        q = ""
        if s.every_other:
            q = " (every other week)"
        elif s.weeks and s.per_month < WEEKS_PER_MONTH:
            q = " (" + ", ".join(ORD_TXT[int(x)] for x in s.weeks.split(",")) + ")"
        parts.append(f"{DAY[s.day]} {clock(s.start)}-{clock(s.end)}{q}")
    return "; ".join(parts)


def build():
    locs = json.loads((RAW / "fbeo_finder" / "locations.json").read_text())
    sch = json.loads((RAW / "fbeo_finder" / "schedules.json").read_text())
    services = {s["locationServiceId"]: s for s in sch["services"]}
    by_loc_services = {}
    for s in sch["services"]:
        by_loc_services.setdefault(s["locationId"], []).append(s)

    def loc_classes(l):
        svcs = by_loc_services.get(l["locationId"], [])
        if svcs:
            return {service_class(s["serviceName"], s["foodProgramTypeDescription"]) for s in svcs}
        return {location_class(l["foodPrograms"], l["locationName"])}

    sessions = []
    for l in locs:
        lid = l["locationId"]
        mine = []
        for x in (x for x in sch["service_schedules"] if x["locationId"] == lid):
            s = services.get(x["locationServiceId"])
            # A few schedules point at a service the finder didn't return; fall
            # back to the location's own program list for their class.
            cls = (service_class(s["serviceName"], s["foodProgramTypeDescription"]) if s
                   else location_class(l["foodPrograms"], l["locationName"]))
            mine += session_rows(lid, [x], cls, "service")
        # Location-level hours count as general-pantry hours only when the
        # location's programs include a general pantry.
        if not any(r["class"] == "general" for r in mine) and "general" in loc_classes(l):
            loc_sched = [x for x in sch["schedules"] if x["locationId"] == lid]
            mine += session_rows(lid, loc_sched, "general", "location")
        sessions += mine
    sess = pd.DataFrame(sessions)
    for wk in WINDOW_ORDER:
        sess[wk] = sess.apply(lambda s: in_window(s, WINDOWS[wk]), axis=1)
    sess.to_csv(DERIVED / "pantry_sessions.csv", index=False)

    areas = pd.read_csv(MANUAL / "service_areas.csv", dtype={"location_id": int}).set_index("location_id")

    rows = []
    for l in locs:
        lid = l["locationId"]
        classes = sorted(loc_classes(l))
        gen = sess[(sess.location_id == lid) & (sess["class"] == "general")]
        row = {
            "location_id": lid,
            "name": l["locationName"].strip(),
            "address": l["address1"].strip(),
            "city": l["city"].strip(),
            "zip": (l["zipCode"] or "").strip()[:5],
            "lat": l["latitude"], "lon": l["longitude"],
            "programs": l["foodPrograms"].strip(),
            "classes": ";".join(classes),
            "general": "general" in classes,
            "hours_listed": not gen.empty,
            "hours": hours_text(gen) if "general" in classes else "",
            "restriction_rule": areas.rule.get(lid, ""),
            "restriction_areas": areas.areas.get(lid, ""),
            "restriction_modeled": bool(areas.modeled.get(lid, 0)),
        }
        for wk in WINDOW_ORDER:
            g = gen[gen[wk]]
            row[f"pm_{wk}"] = float(g.per_month.sum())  # regular sessions per month in the window
            row[f"open_{wk}"] = not g.empty
            row[f"weekly_{wk}"] = row[f"pm_{wk}"] >= WEEKS_PER_MONTH - 0.01
        rows.append(row)
    df = pd.DataFrame(rows).fillna({"restriction_rule": "", "restriction_areas": ""})
    g = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df.lon, df.lat), crs="EPSG:4326")

    tracts = gpd.read_parquet(DERIVED / "tracts_need.parquet")
    g["in_county"] = g.within(tracts.union_all())
    assert g.location_id.is_unique
    assert set(areas.index) <= set(g.location_id), "service_areas.csv names an unknown location"
    g.to_parquet(DERIVED / "pantries.parquet")

    # Posted special hours and closures (public fields only; the finder's
    # add/update user names are dropped).
    special = []
    for x in sch["special_hours"]:
        for d in x.get("data") or []:
            special.append({
                "location_id": d["locationId"], "date": d["specialDate"][:10],
                "closed": bool(d["closedInd"]),
                "start": (d.get("startTimeDescr") or "").strip(),
                "end": (d.get("endTimeDescr") or "").strip(),
                "note": (d.get("notes") or "").strip(),
            })
    pd.DataFrame(special, columns=["location_id", "date", "closed", "start", "end", "note"]) \
        .to_csv(DERIVED / "pantry_special_hours.csv", index=False)
    gp = g[g.general]
    print(f"pantries: {len(g)} listings, {len(gp)} general pantries "
          f"({int(gp.in_county.sum())} in county), {int((~gp.hours_listed).sum())} without hours; "
          + ", ".join(f"{w}: {int(gp[f'open_{w}'].sum())} open" for w in WINDOW_ORDER))
    return g


if __name__ == "__main__":
    build()
