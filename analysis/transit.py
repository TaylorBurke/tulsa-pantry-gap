"""Frequency-based bus travel times between every pair of stops, per time window.

Reads data/raw/gtfs/mtta_gtfs.zip. For each window it keeps the trips of the
matching service day (weekday or Saturday) that run during the window's span,
then builds a graph:

  stop --(wait)--> on route pattern --(ride)--> ... --(alight)--> stop
                                                      stop --(walk <=300 m)--> stop

Ride times are the median scheduled run time between consecutive stops in the
span. Waiting is approximated from frequency: half the headway of the route
(both its patterns, one direction) at that stop during the span. The first wait
is either a fixed 5-minute cushion (rider checks the schedule, the default) or
half the headway (rider walks up without checking). At most two boardings (one
transfer). This is the classic headway approximation, not a timetable router:
it ignores timed transfers and how a specific clock time lines up with the
schedule. analysis/validate_r5.py compares it with a full router on a sample.

Writes data/derived/transit_<window>_<wait>.npz with stop ids, stop coordinates
and the stop-to-stop minutes matrix (inf beyond the budget).
"""
import io
import zipfile

import numpy as np
import pandas as pd
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import dijkstra
from scipy.spatial import cKDTree
import geopandas as gpd

from config import (RAW, DERIVED, CRS_M, WINDOWS, WINDOW_ORDER, WAIT_MODES, WALK_M_PER_MIN,
                    CIRCUITY, TRANSFER_M, BUDGET_MIN, PLANNED_FIRST_WAIT_MIN)

EPS = 1e-4  # scipy's sparse graphs drop zero-weight edges; alighting costs this instead


def hms(s):
    h, m, sec = (int(x) for x in s.strip().split(":"))
    return h * 60 + m + sec / 60


def load():
    z = zipfile.ZipFile(RAW / "gtfs" / "mtta_gtfs.zip")
    rd = lambda n: pd.read_csv(io.BytesIO(z.read(n)), dtype=str)
    stops, trips, st, cal, info = (rd(n) for n in ["stops.txt", "trips.txt", "stop_times.txt",
                                                   "calendar.txt", "feed_info.txt"])
    st["arr"] = st.arrival_time.map(hms)
    st["dep"] = st.departure_time.map(hms)
    st["seq"] = st.stop_sequence.astype(int)
    st = st.merge(trips[["trip_id", "route_id", "direction_id", "service_id"]], on="trip_id")
    stops = gpd.GeoDataFrame(stops, geometry=gpd.points_from_xy(stops.stop_lon.astype(float),
                                                                stops.stop_lat.astype(float)),
                             crs="EPSG:4326").to_crs(CRS_M)
    return stops, st, cal, info


def services_for(cal, kind):
    days = ["monday", "tuesday", "wednesday", "thursday", "friday"] if kind == "weekday" else ["saturday"]
    out = cal.loc[cal[days].astype(int).all(axis=1), "service_id"].tolist()
    assert out, f"no {kind} service in calendar.txt"
    return out


def stop_matrix(stops, st, cal, window, wait):
    w = WINDOWS[window]
    lo, hi = w["span"]
    span = hi - lo
    s = st[st.service_id.isin(services_for(cal, w["gtfs_days"]))]
    # Trips that serve at least one stop inside the span.
    active = s.groupby("trip_id").dep.agg(["min", "max"])
    active = active[(active["max"] >= lo) & (active["min"] < hi)].index
    s = s[s.trip_id.isin(active)].sort_values(["trip_id", "seq"]).copy()
    s["pos"] = s.groupby("trip_id").cumcount()  # stop_sequence numbering varies between trips

    # Headway per (route, direction, stop): departures inside the span.
    inspan = s[(s.dep >= lo) & (s.dep < hi)]
    n_dep = inspan.groupby(["route_id", "direction_id", "stop_id"]).size()
    headway = (span / n_dep).clip(upper=span)

    # Patterns: distinct ordered stop lists per route/direction.
    meta = s.groupby("trip_id")[["route_id", "direction_id"]].first()
    meta["stops"] = s.groupby("trip_id").stop_id.agg(tuple)
    meta["pattern"] = pd.factorize(meta.route_id + "|" + meta.direction_id + "|"
                                   + meta.stops.map("|".join))[0]

    stop_ids = stops.stop_id.tolist()
    sidx = {x: i for i, x in enumerate(stop_ids)}
    ns = len(stop_ids)

    def S(i, b):  # stop node in boarding layer b (0 = not yet boarded)
        return b * ns + i

    nxt = 3 * ns
    edges = []
    for pid, grp in meta.groupby("pattern"):
        seq = grp.stops.iloc[0]
        route, direction = grp.route_id.iloc[0], grp.direction_id.iloc[0]
        tt = s[s.trip_id.isin(grp.index)]
        arr = tt.pivot_table(index="trip_id", columns="pos", values="arr")
        dep = tt.pivot_table(index="trip_id", columns="pos", values="dep")
        cols = list(arr.columns)
        assert len(cols) == len(seq), "pattern stop count mismatch"
        base = {k: nxt + 2 * k for k in range(len(seq))}  # +0: layer 1, +1: layer 2
        nxt += 2 * len(seq)
        for k, stop in enumerate(seq):
            i = sidx[stop]
            hw = headway.get((route, direction, stop), np.nan)
            if k < len(seq) - 1 and not np.isnan(hw):
                first = PLANNED_FIRST_WAIT_MIN if wait == "planned" else hw / 2
                edges.append((S(i, 0), base[k], max(first, EPS)))       # first boarding
                edges.append((S(i, 1), base[k] + 1, max(hw / 2, EPS)))  # transfer boarding
            if k > 0:
                edges.append((base[k], S(i, 1), EPS))  # alight
                edges.append((base[k] + 1, S(i, 2), EPS))
            if k < len(seq) - 1:
                ride = float(np.nanmedian(arr[cols[k + 1]] - dep[cols[k]]))
                edges.append((base[k], base[k + 1], max(ride, EPS)))
                edges.append((base[k] + 1, base[k + 1] + 1, max(ride, EPS)))

    # Transfer walks between nearby stops, after the first ride only.
    xy = np.c_[stops.geometry.x, stops.geometry.y]
    for i, j in cKDTree(xy).query_pairs(TRANSFER_M):
        d = np.hypot(*(xy[i] - xy[j])) * CIRCUITY / WALK_M_PER_MIN
        edges.append((S(i, 1), S(j, 1), max(d, EPS)))
        edges.append((S(j, 1), S(i, 1), max(d, EPS)))

    e = pd.DataFrame(edges, columns=["a", "b", "w"]).groupby(["a", "b"], as_index=False).w.min()
    g = coo_matrix((e.w, (e.a, e.b)), shape=(nxt, nxt)).tocsr()
    dist = dijkstra(g, directed=True, indices=[S(i, 0) for i in range(ns)], limit=BUDGET_MIN)
    T = np.minimum(dist[:, ns:2 * ns], dist[:, 2 * ns:3 * ns])
    np.fill_diagonal(T, 0.0)
    return np.array(stop_ids), xy, T.astype(np.float32), headway


def build():
    stops, st, cal, info = load()
    start, end = info.feed_start_date.iloc[0], info.feed_end_date.iloc[0]
    print(f"gtfs: feed valid {start}-{end}, {len(stops)} stops")
    summary = []
    for w in WINDOW_ORDER:
        for wait in WAIT_MODES:
            ids, xy, T, hw = stop_matrix(stops, st, cal, w, wait)
            np.savez_compressed(DERIVED / f"transit_{w}_{wait}.npz", stop_ids=ids, xy=xy, T=T)
            reach = np.isfinite(T).sum(axis=1)
            summary.append({"window": w, "wait": wait, "median_headway_min": round(float(hw.median()), 1),
                            "served_stops": int((reach > 1).sum()),
                            "median_stops_within_budget": float(np.median(reach[reach > 1]))})
    df = pd.DataFrame(summary)
    df.to_csv(DERIVED / "transit_summary.csv", index=False)
    print(df.to_string(index=False))
    pd.Series({"feed_start": start, "feed_end": end}).to_json(DERIVED / "gtfs_info.json")


if __name__ == "__main__":
    build()
