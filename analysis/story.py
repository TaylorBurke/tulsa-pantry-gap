"""Collect every number the site quotes into data/derived/story.json, and write the
map layers to site/data/. Prose is filled from story.json by build_site.py, so a
data refresh can't leave stale numbers in the text.

Map layers (EPSG:4326, simplified, coordinates rounded to ~1 m):
  site/data/tracts.geojson    tract outlines + need, access, gap per window
  site/data/pantries.geojson  public listing fields only (no contacts)
  site/data/routes.geojson    bus route shapes
"""
import io
import re
import json
import zipfile
from datetime import date

import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.geometry import LineString

from config import (ROOT, RAW, DERIVED, CRS_M, WINDOWS, WINDOW_ORDER, WAIT_MODES, PRIMARY_WAIT,
                    NEED_WEIGHTS, NEED_ALTERNATIVES, MIN_HOUSEHOLDS, HIGH_NEED_PCTL, CV_UNRELIABLE,
                    WALK_M_PER_MIN, CIRCUITY, BUDGET_MIN, STOP_SEARCH_M, TRANSFER_M,
                    PLANNED_FIRST_WAIT_MIN, WEEKS_PER_MONTH)
from gap import LOW_ACCESS, TOP_N

PLACE_LABELS = ["Broken Arrow", "Owasso", "Sand Springs", "Jenks", "Bixby", "Glenpool",
                "Collinsville", "Skiatook", "Sperry"]
SITE_DATA = ROOT / "site" / "data"
SITE_DATA.mkdir(parents=True, exist_ok=True)


def r(x, n=3):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x), n)


def write_geojson(gdf, name, tol_m, keep):
    g = gdf.to_crs(CRS_M)
    if tol_m:
        g["geometry"] = g.geometry.simplify(tol_m, preserve_topology=True)
    g = g.to_crs("EPSG:4326")[keep + ["geometry"]]
    d = json.loads(g.to_json(drop_id=True))

    def rnd(c):  # 5 decimals ~ 1 m
        return [rnd(x) for x in c] if isinstance(c[0], list) else [round(c[0], 5), round(c[1], 5)]
    for f in d["features"]:
        f["geometry"]["coordinates"] = rnd(f["geometry"]["coordinates"])
    (SITE_DATA / name).write_text(json.dumps(d, separators=(",", ":")))
    return (SITE_DATA / name).stat().st_size


def build():
    t = gpd.read_parquet(DERIVED / "tracts.parquet")
    b = pd.read_parquet(DERIVED / "blocks_access.parquet")
    p = gpd.read_parquet(DERIVED / "pantries.parquet")
    rank = pd.read_csv(DERIVED / "gap_ranking.csv", dtype={"GEOID": str, "tract": str})
    checks = json.loads((DERIVED / "checks.json").read_text())
    siting = json.loads((DERIVED / "siting.json").read_text())
    r5p = DERIVED / "validate_r5.json"
    r5 = json.loads(r5p.read_text()) if r5p.exists() else None
    gtfs = json.loads((DERIVED / "gtfs_info.json").read_text())
    county = json.loads((DERIVED / "county_acs.json").read_text())
    pc = p[p.general & p.in_county]
    hn = t[t.high_need]
    hn_blocks = b[b.tract.isin(hn.GEOID)]

    def share(blocks, col):
        return float(np.average(np.isfinite(blocks[col]), weights=blocks.POP20))

    win = {}
    for w in WINDOW_ORDER:
        d = {"label": WINDOWS[w]["label"], "short": WINDOWS[w]["short"],
             "pantries_open_in_county": int(pc[f"open_{w}"].sum()),
             "pantries_weekly_in_county": int(pc[f"weekly_{w}"].sum())}
        for wait in WAIT_MODES:
            k = f"{w}_{wait}"
            d[wait] = {
                "share_county": r(share(b, f"min_{k}")),
                "share_high_need": r(share(hn_blocks, f"min_{k}")),
                "poor_no_access_county": round(float(t[f"poor_no_access_{k}"].sum())),
                "poor_no_access_high_need": round(float(hn[f"poor_no_access_{k}"].sum())),
                "nov_no_access_county": round(float(t[f"nov_no_access_{k}"].sum())),
                "gap_tracts": int(t[f"gap_{k}"].sum()),
                "share_county_weekly_only": r(share(b, f"min_weekly_{k}")),
                "share_county_ignore_eligibility": r(share(b, f"min_noelig_{k}")),
                "share_county_unlisted_counted_open": r(share(b, f"min_unlisted_{k}")),
                "share_high_need_unlisted_counted_open": r(share(hn_blocks, f"min_unlisted_{k}")),
            }
        win[w] = d

    # Need-index robustness: how many of the primary top-10 gap tracts stay in the
    # top 10 under each alternative weighting, and under walk-up waiting?
    robust = {}
    for w in WINDOW_ORDER:
        col = f"poor_no_access_{w}_{PRIMARY_WAIT}"
        base = set(rank[rank.window == w].GEOID)
        robust[w] = {}
        for alt in NEED_ALTERNATIVES:
            hi = t[f"need_{alt}"].rank(pct=True) > HIGH_NEED_PCTL
            top = set(t[hi].sort_values(col, ascending=False).head(TOP_N).GEOID)
            robust[w][alt] = len(base & top)
        top = set(t[t.high_need].sort_values(f"poor_no_access_{w}_walk_up", ascending=False).head(TOP_N).GEOID)
        robust[w]["walk_up_wait"] = len(base & top)

    top_tr = t[t.GEOID.isin(set(rank.GEOID))]

    # The lead example: distance from the top Saturday gap tract's population
    # centre to open pantries in each window (checked by hand in the README).
    lead = t.set_index("GEOID").loc[rank[rank.window == "saturday"].GEOID.iloc[0]]
    centre = gpd.GeoSeries(gpd.points_from_xy([lead.cx], [lead.cy]), crs="EPSG:4326").to_crs(CRS_M).iloc[0]
    pg = p[p.general & p.hours_listed].to_crs(CRS_M)
    dist_km = pg.distance(centre) / 1000
    lead_example = {"GEOID": lead.name, "label": lead.label}
    for w in WINDOW_ORDER:
        d = dist_km[pg[f"open_{w}"].to_numpy()].sort_values()
        lead_example[w] = {"nearest_km": r(d.iloc[0], 1), "within_1_6km": int((d <= 1.6).sum()),
                           "nearest_3_km": [r(x, 1) for x in d.head(3)]}

    # Week grid: for each day and hour, county general pantries holding a regular
    # session that overlaps the hour (any week, and every week), and buses on the
    # road (trips running during the hour) for that service day.
    from transit import load as load_gtfs
    sess = pd.read_csv(DERIVED / "pantry_sessions.csv")
    sess = sess[(sess["class"] == "general") & sess.location_id.isin(set(pc.location_id))]
    _, st_, cal_, _ = load_gtfs()
    trips_ = st_.groupby("trip_id").agg(dep=("dep", "min"), arr=("arr", "max"), svc=("service_id", "first"))
    svc_for = {1: cal_.loc[cal_.sunday.astype(int) == 1, "service_id"].tolist(),
               7: cal_.loc[cal_.saturday.astype(int) == 1, "service_id"].tolist()}
    weekday_svc = cal_.loc[cal_[["monday", "tuesday", "wednesday", "thursday", "friday"]].astype(int)
                           .all(axis=1), "service_id"].tolist()
    HOURS = list(range(6, 22))
    grid = []
    for d in range(1, 8):
        tr = trips_[trips_.svc.isin(svc_for.get(d, weekday_svc))]
        for h in HOURS:
            a = sess[(sess.day == d) & (sess.start < (h + 1) * 60) & (sess.end > h * 60)]
            weekly = a[a.per_month >= WEEKS_PER_MONTH - 0.01].location_id.nunique()
            grid.append({"day": d, "hour": h, "pantries": int(a.location_id.nunique()),
                         "pantries_weekly": int(weekly),
                         "buses": int(((tr.dep < (h + 1) * 60) & (tr.arr > h * 60)).sum())})
    week_grid = {"hours": HOURS, "cells": grid}

    # Posted special hours for county pantries (holiday closures etc.).
    sp = pd.read_csv(DERIVED / "pantry_special_hours.csv")
    names = p.set_index("location_id").name
    county_ids = set(pc.location_id)
    txt = lambda v: v if isinstance(v, str) else ""
    special = [{"name": names.get(r.location_id, ""), "date": r.date, "closed": bool(r.closed),
                "start": txt(r.start), "end": txt(r.end), "note": txt(r.note)}
               for r in sp.itertuples() if r.location_id in county_ids]

    # Photo captions: the tract each photographed bus stop sits in, and its access.
    zg = zipfile.ZipFile(RAW / "gtfs" / "mtta_gtfs.zip")
    gstops = pd.read_csv(io.BytesIO(zg.read("stops.txt")), dtype=str).set_index("stop_id")
    gtrips = pd.read_csv(io.BytesIO(zg.read("trips.txt")), dtype=str)
    gcal = pd.read_csv(io.BytesIO(zg.read("calendar.txt")), dtype=str)
    sunday_routes = sorted(gtrips[gtrips.service_id.isin(gcal[gcal.sunday == "1"].service_id)].route_id.unique())
    photos = {}
    for key, stop_id in {"aero-stop-8005": "8005", "aero-peoria-11th": "7015"}.items():
        srow = gstops.loc[stop_id]
        pt = gpd.GeoDataFrame(geometry=gpd.points_from_xy([float(srow.stop_lon)], [float(srow.stop_lat)]), crs="EPSG:4326")
        hit = gpd.sjoin(pt, t[["GEOID", "NAME", "label", "high_need", "poverty_rate", "geometry"]
                              + [f"share_{w}_{PRIMARY_WAIT}" for w in WINDOW_ORDER]], predicate="within").iloc[0]
        photos[key] = {"stop": re.sub(r"^\(\d+\)\s*|\s+(NB|SB|EB|WB)$", "", srow.stop_name).strip(),
                       "tract": str(hit.NAME), "GEOID": hit.GEOID, "high_need": bool(hit.high_need),
                       "poverty_rate": r(hit.poverty_rate),
                       **{f"share_{w}": r(hit[f"share_{w}_{PRIMARY_WAIT}"]) for w in WINDOW_ORDER},
                       "credit": "G. Edward Johnson", "license": "CC BY 4.0",
                       "source_url": "https://commons.wikimedia.org/wiki/File:" + {
                           "aero-stop-8005": "Tulsa_Transit_Aero_bus_stop_8005_OK_2025-03-16_16-05-20_1.jpg",
                           "aero-peoria-11th": "Aero_bus_stop_7015_S_Peoria_Ave_and_11th_St_Tulsa_OK_2025-07-21_10-08-39.jpg"}[key]}
    # Publish resized copies (1000px wide) for the site.
    from PIL import Image
    (ROOT / "site" / "assets" / "photos").mkdir(parents=True, exist_ok=True)
    for key in photos:
        im = Image.open(RAW / "photos" / f"{key}.jpg")
        im.thumbnail((1000, 1000))
        im.save(ROOT / "site" / "assets" / "photos" / f"{key}.jpg", quality=80, optimize=True, progressive=True)

    tsum = pd.read_csv(DERIVED / "transit_summary.csv")
    headways = {w: float(tsum[(tsum.window == w) & (tsum.wait == PRIMARY_WAIT)].median_headway_min.iloc[0])
                for w in WINDOW_ORDER}
    zc = t[["z_poverty_rate", "z_no_vehicle_rate", "z_snap_rate"]].corr().to_numpy()
    need_corr = [r(zc[0, 1], 2), r(zc[0, 2], 2), r(zc[1, 2], 2)]
    story = {
        "built": date.today().isoformat(),
        # when the Food Finder listings (the fast-changing input) were last downloaded
        "data_as_of": max(i["fetched_at"] for i in
                          json.loads((RAW / "fbeo_finder" / "manifest.json").read_text()))[:10],
        "county": {"acs_pop": int(county["pop"]), "census_2020_pop": int(b.POP20.sum()),
                   "tracts": len(t), "high_need_tracts": int(t.high_need.sum()),
                   "people_in_poverty": int(county["poor"]),
                   "poverty_rate": r(county["poverty_rate"]),
                   "no_vehicle_households": int(county["no_vehicle_hh"]),
                   "no_vehicle_rate": r(county["no_vehicle_rate"]),
                   "snap_rate": r(county["snap_rate"]),
                   "high_need_pop": int(hn["pop"].sum()), "high_need_poor": int(hn["poor"].sum()),
                   "high_need_no_vehicle_hh": int(hn["no_vehicle_hh"].sum())},
        "pantries": {"listings": len(p), "general_total": int(p.general.sum()),
                     "general_in_county": len(pc),
                     "general_in_county_no_hours": int((~pc.hours_listed).sum()),
                     "not_general": int((~p.general).sum()),
                     "with_modeled_service_area": int(p.restriction_modeled.sum()),
                     "suspicious_hours": checks.get("suspicious_hours", [])},
        "windows": win,
        "ranking": {w: rank[rank.window == w].to_dict("records") for w in WINDOW_ORDER},
        "robustness_top10_overlap": robust,
        "top_tracts_with_shaky_component": int((top_tr.n_shaky_components > 0).sum()),
        "top_tracts_total": len(top_tr),
        "lead_example": lead_example,
        "week_grid": week_grid,
        "photos": photos,
        "sunday_routes": sunday_routes,
        "special_hours": special,
        "median_headway_min": headways,
        "need_component_correlations": need_corr,
        "siting": siting,
        "checks": {k: v for k, v in checks.items() if isinstance(v, dict) and "ok" in v},
        "usda": checks.get("usda_lila_overlap", {}),
        "r5": r5,
        "gtfs": gtfs,
        "config": {"walk_mph": round(WALK_M_PER_MIN * 60 / 1609.34, 1), "circuity": CIRCUITY,
                   "budget_min": BUDGET_MIN, "stop_search_m": STOP_SEARCH_M, "transfer_m": TRANSFER_M,
                   "planned_first_wait_min": PLANNED_FIRST_WAIT_MIN, "primary_wait": PRIMARY_WAIT,
                   "need_weights": NEED_WEIGHTS, "min_households": MIN_HOUSEHOLDS,
                   "high_need_pctl": HIGH_NEED_PCTL, "low_access": LOW_ACCESS,
                   "cv_unreliable": CV_UNRELIABLE, "weeks_per_month": WEEKS_PER_MONTH,
                   "windows": {w: {"label": WINDOWS[w]["label"], "span": WINDOWS[w]["span"],
                                   "open_overlap": WINDOWS[w]["open_overlap"]} for w in WINDOW_ORDER}},
    }
    (DERIVED / "story.json").write_text(json.dumps(story, indent=1, default=str))

    # ---- map layers ----
    keep = ["GEOID", "NAME", "label", "pop", "poor", "poverty_rate", "poverty_rate_moe",
            "no_vehicle_rate", "no_vehicle_rate_moe", "no_vehicle_hh", "snap_rate", "snap_rate_moe",
            "need", "need_pctl", "high_need", "n_shaky_components", "usda_lila_half"]
    for w in WINDOW_ORDER:
        for wait in WAIT_MODES:
            keep += [f"share_{w}_{wait}", f"poor_no_access_{w}_{wait}", f"gap_{w}_{wait}",
                     f"median_min_{w}_{wait}"]
    tt = t.copy()
    for c in keep:
        if tt[c].dtype.kind == "f":
            tt[c] = tt[c].round(4)
    s1 = write_geojson(tt, "tracts.geojson", 15, keep)

    pk = ["location_id", "name", "address", "city", "programs", "classes", "general", "hours_listed",
          "hours", "restriction_rule", "restriction_areas", "in_county"] + \
         [f"open_{w}" for w in WINDOW_ORDER] + [f"pm_{w}" for w in WINDOW_ORDER]
    s2 = write_geojson(p, "pantries.geojson", 0, pk)

    z = zipfile.ZipFile(RAW / "gtfs" / "mtta_gtfs.zip")
    rd = lambda n: pd.read_csv(io.BytesIO(z.read(n)), dtype=str)
    shapes, trips, routes = rd("shapes.txt"), rd("trips.txt"), rd("routes.txt")
    shapes["seq"] = shapes.shape_pt_sequence.astype(int)
    lines = [{"shape_id": sid, "geometry": LineString(zip(g.shape_pt_lon.astype(float), g.shape_pt_lat.astype(float)))}
             for sid, g in shapes.sort_values("seq").groupby("shape_id")]
    sh = gpd.GeoDataFrame(lines, crs="EPSG:4326")
    sh["route_id"] = sh.shape_id.map(trips.drop_duplicates("shape_id").set_index("shape_id").route_id)
    sh = sh.merge(routes[["route_id", "route_short_name", "route_long_name"]], on="route_id")
    sh = sh.dissolve("route_id", aggfunc="first").reset_index()
    sh["name"] = sh.route_short_name + " " + sh.route_long_name
    sh = sh[sh.route_id != "900"]  # one daily express trip each way; no use for pantry trips
    s3 = write_geojson(sh, "routes.geojson", 10, ["route_id", "name"])

    # Map labels: towns at their Census representative point; "Downtown" at the
    # Denver Avenue Station bus hub (from the GTFS stops file).
    places = gpd.read_file(f"zip://{RAW / 'tiger' / 'tl_2024_40_place.zip'}")
    places = places[places.NAME.isin(PLACE_LABELS)]
    pts = places.to_crs(CRS_M).representative_point().to_crs("EPSG:4326")
    labels = [{"name": n, "lon": round(p.x, 5), "lat": round(p.y, 5)} for n, p in zip(places.NAME, pts)]
    # Downtown: the Denver Avenue Station bays ("DAS BAY n" in the feed).
    stops = rd("stops.txt")
    das = stops[stops.stop_name.str.contains(r"\bDAS BAY", regex=True)]
    assert len(das) >= 3, "Denver Avenue Station bays not found in stops.txt"
    labels.append({"name": "Downtown", "lon": round(das.stop_lon.astype(float).mean(), 5),
                   "lat": round(das.stop_lat.astype(float).mean(), 5)})
    (SITE_DATA / "places.json").write_text(json.dumps(labels))
    print(f"story.json written; site/data: tracts {s1/1e3:.0f} kB, pantries {s2/1e3:.0f} kB, "
          f"routes {s3/1e3:.0f} kB")


if __name__ == "__main__":
    build()
