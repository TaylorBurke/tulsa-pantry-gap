"""Validate the headway approximation against a full timetable router (r5py / R5).

Not part of the main build (`make validate`; needs Java 21+ and the OSM extract
from fetch/fetch_osm.py). For a random sample of populated blocks, R5 routes on
the real street network and the real timetable to every pantry open in the
window, for every departure minute in a one-hour window on a real date inside
the feed's validity. It reports percentiles of the door-to-door time across
those departure minutes:

  * R5's 5th percentile ~ a rider who times the bus well -> compared with "planned"
  * R5's median         ~ a rider who walks up at a random minute -> compared with "walk_up"

For each block we compare the verdict "an open pantry is reachable within 30
minutes" and the minutes to the nearest one. Writes data/derived/validate_r5.json.
"""
import datetime as dt
import json
import sys
import zipfile

import numpy as np
import pandas as pd
import geopandas as gpd

from config import RAW, DERIVED, CRS_M, BUDGET_MIN, WALK_M_PER_MIN

N_SAMPLE = 500
# Dates inside the GTFS feed (2026-09-10 to 2026-12-05), avoiding holidays.
DEPARTURES = {
    "weekday_day": dt.datetime(2026, 11, 10, 10, 0),      # Tuesday
    "weekday_evening": dt.datetime(2026, 11, 10, 17, 30),  # Tuesday
    "saturday": dt.datetime(2026, 11, 14, 10, 0),          # Saturday
}


def r5_gtfs():
    """R5 rejects tables that are present but empty (this feed ships header-only
    calendar_dates, frequencies and transfers). Write a copy without them."""
    src = zipfile.ZipFile(RAW / "gtfs" / "mtta_gtfs.zip")
    out = DERIVED / "mtta_gtfs_for_r5.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for n in src.namelist():
            body = src.read(n)
            if len(body.strip().splitlines()) > 1:
                z.writestr(n, body)
    return out


def reach(x):
    x = x.astype(float).fillna(np.inf)
    return np.isfinite(x) & (x <= BUDGET_MIN)


def main():
    sys.argv += ["--max-memory", "12G"]
    import r5py  # imported late: starts a JVM

    blocks = pd.read_parquet(DERIVED / "blocks_access.parquet")
    rng = np.random.default_rng(11)
    sample = blocks.iloc[rng.choice(len(blocks), N_SAMPLE, replace=False)].copy()
    origins = gpd.GeoDataFrame({"id": sample.GEOID20.values},
                               geometry=gpd.points_from_xy(sample.x, sample.y), crs=CRS_M).to_crs("EPSG:4326")
    pantries = gpd.read_parquet(DERIVED / "pantries.parquet")
    pantries = pantries[pantries.general & pantries.hours_listed]

    tn = r5py.TransportNetwork(RAW / "osm" / "oklahoma-latest.osm.pbf", [r5_gtfs()])
    out = {}
    s = sample.set_index("GEOID20")
    pw = s.POP20
    for w, when in DEPARTURES.items():
        dest = pantries[pantries[f"open_{w}"]]
        dests = gpd.GeoDataFrame({"id": dest.location_id.astype(str).values},
                                 geometry=dest.geometry.values, crs="EPSG:4326")
        ttm = r5py.TravelTimeMatrix(
            tn, origins=origins, destinations=dests, departure=when,
            departure_time_window=dt.timedelta(minutes=60),
            transport_modes=[r5py.TransportMode.TRANSIT, r5py.TransportMode.WALK],
            percentiles=[5, 50], max_time=dt.timedelta(minutes=BUDGET_MIN),
            speed_walking=WALK_M_PER_MIN * 60 / 1000,
        )
        best = ttm.groupby("from_id")[["travel_time_p5", "travel_time_p50"]].min()
        # R5 doesn't know the eligibility rules, so compare with the model's
        # "ignore eligibility" variant.
        m_plan, m_walk = s[f"min_noelig_{w}_planned"], s[f"min_noelig_{w}_walk_up"]
        r_p5 = best.travel_time_p5.reindex(s.index)
        r_p50 = best.travel_time_p50.reindex(s.index)
        res = {
            "departure": when.isoformat(),
            "blocks": int(len(s)),
            "planned_vs_r5_p5_agree": float(np.average(reach(m_plan) == reach(r_p5), weights=pw)),
            "walkup_vs_r5_p50_agree": float(np.average(reach(m_walk) == reach(r_p50), weights=pw)),
            "share_reach_model_planned": float(np.average(reach(m_plan), weights=pw)),
            "share_reach_r5_p5": float(np.average(reach(r_p5), weights=pw)),
            "share_reach_model_walkup": float(np.average(reach(m_walk), weights=pw)),
            "share_reach_r5_p50": float(np.average(reach(r_p50), weights=pw)),
        }
        both = reach(m_plan) & reach(r_p5)
        if both.sum() > 10:
            d = m_plan[both].astype(float) - r_p5[both].astype(float)
            res["minutes_model_minus_r5_p5_median"] = float(d.median())
            res["minutes_model_minus_r5_p5_iqr"] = [float(d.quantile(.25)), float(d.quantile(.75))]
        out[w] = res
        print(w, json.dumps(res))
    (DERIVED / "validate_r5.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
