"""Independent checks. Each recomputes something by a different code path than the
pipeline and fails the build (exit 1) if the two disagree. Results are written to
data/derived/checks.json and summarized in the README and on the site.

1. Control totals: tract ACS population sums to the county; 2020 block
   population sums to the official 2020 census count for Tulsa County.
2. Hand spot-check: three tracts recomputed from the raw summary-file text with
   the csv module only (no pandas), compared with the pipeline's rates.
3. Cross-source: tract poverty, zero-vehicle and SNAP rates against USDA's SRAM
   file (an independent tabulation of an overlapping ACS period).
4. Travel-time cross-check: for a sample of block -> pantry pairs, the best
   one-bus trip found by brute force over stop_times.txt must not beat the
   model by more than run-time noise (the model also allows a transfer).
5. Pantry hours sanity: flag sessions that are implausibly long.
"""
import csv
import json
import zipfile

import numpy as np
import pandas as pd
import geopandas as gpd

from config import (RAW, DERIVED, CRS_M, WINDOWS, WALK_M_PER_MIN, CIRCUITY, STOP_SEARCH_M,
                    PLANNED_FIRST_WAIT_MIN, BUDGET_MIN)
from access import load_blocks, min_times
from transit import load, services_for

COUNTY_2020_CENSUS = 669_279  # 2020 Census, Tulsa County OK (P1 total population)
SPOT_TRACTS = ["40143001000", "40143009200", "40143009016"]  # highest-need, median, lowest-need
results = {}
failures = []


def check(name, ok, detail):
    results[name] = {"ok": bool(ok), **detail}
    print(("PASS " if ok else "FAIL ") + name + ": " + json.dumps(detail, default=str)[:400])
    if not ok:
        failures.append(name)


# 1. Control totals -----------------------------------------------------------
t = gpd.read_parquet(DERIVED / "tracts.parquet")
county = json.loads((DERIVED / "county_acs.json").read_text())
check("acs_tracts_sum_to_county", abs(t["pop"].sum() - county["pop"]) <= 5,
      {"tract_sum": int(t["pop"].sum()), "county_row": int(county["pop"])})
blocks = pd.read_parquet(DERIVED / "blocks_access.parquet")
check("blocks_sum_to_2020_census", int(blocks.POP20.sum()) == COUNTY_2020_CENSUS,
      {"block_sum": int(blocks.POP20.sum()), "census_2020": COUNTY_2020_CENSUS})
check("every_tract_has_blocks", bool((t.block_pop > 0).all()), {"tracts": len(t)})


# 2. Hand spot-check from raw text ---------------------------------------------
def raw_row(table, geoid):
    with open(RAW / "acs" / f"acsdt5y2024-{table}-tulsa.dat", newline="") as f:
        rd = csv.reader(f, delimiter="|")
        head = next(rd)
        for row in rd:
            if row[0] == f"1400000US{geoid}":
                return dict(zip(head, row))
    raise KeyError(geoid)


spot = []
tt_ = t.set_index("GEOID")
for g in SPOT_TRACTS:
    b17, b25, b22 = raw_row("b17001", g), raw_row("b25044", g), raw_row("b22003", g)
    hand = {
        "poverty_rate": int(b17["B17001_E002"]) / int(b17["B17001_E001"]),
        "no_vehicle_rate": (int(b25["B25044_E003"]) + int(b25["B25044_E010"])) / int(b25["B25044_E001"]),
        "snap_rate": int(b22["B22003_E002"]) / int(b22["B22003_E001"]),
    }
    row = tt_.loc[g]
    diffs = {k: abs(v - row[k]) for k, v in hand.items()}
    spot.append({"GEOID": g, "label": row.label,
                 "raw": {"B17001_E001": b17["B17001_E001"], "B17001_E002": b17["B17001_E002"],
                         "B25044_E001": b25["B25044_E001"], "B25044_E003": b25["B25044_E003"],
                         "B25044_E010": b25["B25044_E010"], "B22003_E001": b22["B22003_E001"],
                         "B22003_E002": b22["B22003_E002"]},
                 **{k: round(v, 4) for k, v in hand.items()},
                 "max_abs_diff": max(diffs.values())})
check("hand_spot_check_three_tracts", all(s["max_abs_diff"] < 1e-9 for s in spot), {"tracts": spot})

# 3. Cross-source against USDA SRAM ------------------------------------------------
z = zipfile.ZipFile(RAW / "usda_sram" / "2025-sram-data.zip")
sram = pd.read_csv(z.open("SRAM General Tract Characteristics Data.csv"), encoding="latin1",
                   dtype={"CensusTract20": str})
sram = sram[sram.CensusTract20.str.startswith("40143")].set_index("CensusTract20")
j = tt_.join(sram, how="inner")
pov_scale = 100 if j.PovertyRate.max() > 1 else 1
j["usda_novehicle"] = j.TractHUNV / j.OHU2020
j["usda_snap"] = j.TractSNAP / j.OHU2020
corr = {
    "poverty": j.poverty_rate.corr(j.PovertyRate / pov_scale),
    "no_vehicle": j.no_vehicle_rate.corr(j.usda_novehicle),
    "snap": j.snap_rate.corr(j.usda_snap),
}
check("usda_sram_cross_source", len(j) >= 200 and min(corr.values()) > 0.75,
      {"tracts_matched": len(j), "correlations": {k: round(v, 3) for k, v in corr.items()},
       "note": "USDA's household denominators are 2020-census counts, so zero-vehicle and SNAP shares "
               "differ slightly; poverty rates should match"})
sd = pd.read_csv(z.open("SRAM Straight Line Distance Data.csv"), encoding="latin1",
                 dtype={"CensusTract20": str}, usecols=["CensusTract20", "SD_SRAM_LILATracts_halfAnd10", "SD_SRAM_LILATracts_Vehicle"])
sd = sd[sd.CensusTract20.str.startswith("40143")].set_index("CensusTract20")
jj = tt_.join(sd, how="left")
results["usda_lila_overlap"] = {
    "lila_vehicle_tracts": int((jj.SD_SRAM_LILATracts_Vehicle == 1).sum()),
    "lila_half_tracts": int((jj.SD_SRAM_LILATracts_halfAnd10 == 1).sum()),
    "lila_half_and_high_need": int(((jj.SD_SRAM_LILATracts_halfAnd10 == 1) & jj.high_need).sum()),
    "high_need_tracts": int(jj.high_need.sum()),
}
print("info usda_lila_overlap:", results["usda_lila_overlap"])


# 4. Travel time cross-check ---------------------------------------------------------
def brute_one_bus(o_xy, p_xy, window, stops_xy, stop_ids, st, cal):
    """Best walk + 5-min wait + ride + walk on ONE trip, straight from stop_times."""
    w = WINDOWS[window]
    lo, hi = w["span"]
    s = st[st.service_id.isin(services_for(cal, w["gtfs_days"]))]
    d_o = np.hypot(stops_xy[:, 0] - o_xy[0], stops_xy[:, 1] - o_xy[1])
    d_p = np.hypot(stops_xy[:, 0] - p_xy[0], stops_xy[:, 1] - p_xy[1])
    board = {stop_ids[i]: d_o[i] * CIRCUITY / WALK_M_PER_MIN for i in np.where(d_o <= STOP_SEARCH_M)[0]}
    alight = {stop_ids[i]: d_p[i] * CIRCUITY / WALK_M_PER_MIN for i in np.where(d_p <= STOP_SEARCH_M)[0]}
    if not board or not alight:
        return np.inf
    sb = s[s.stop_id.isin(board) & (s.dep >= lo) & (s.dep < hi)][["trip_id", "stop_id", "seq", "dep"]]
    sa = s[s.stop_id.isin(alight)][["trip_id", "stop_id", "seq", "arr"]]
    m = sb.merge(sa, on="trip_id", suffixes=("_b", "_a"))
    m = m[m.seq_a > m.seq_b]
    if m.empty:
        return np.inf
    tot = m.stop_id_b.map(board) + PLANNED_FIRST_WAIT_MIN + (m.arr - m.dep) + m.stop_id_a.map(alight)
    return float(tot.min())


stops, st, cal, _ = load()
stops_xy = np.c_[stops.geometry.x, stops.geometry.y]
stop_ids = stops.stop_id.to_numpy()
bl = load_blocks()
pantries = gpd.read_parquet(DERIVED / "pantries.parquet").to_crs(CRS_M)
pantries = pantries[pantries.general].reset_index(drop=True)
rng = np.random.default_rng(7)
window = "weekday_day"
M = min_times(bl, pantries, window, "planned")
pairs = [(int(i), int(rng.integers(len(pantries)))) for i in rng.choice(len(bl), 150, replace=False)]
fin = np.argwhere(np.isfinite(M))  # plus pairs the model says are reachable
pairs += [tuple(map(int, fin[k])) for k in rng.choice(len(fin), 150, replace=False)]
rows = []
for i, j_ in pairs:
    o = (bl.geometry.x.iloc[i], bl.geometry.y.iloc[i])
    p = (pantries.geometry.x.iloc[j_], pantries.geometry.y.iloc[j_])
    b = brute_one_bus(o, p, window, stops_xy, stop_ids, st, cal)
    walk = np.hypot(o[0] - p[0], o[1] - p[1]) * CIRCUITY / WALK_M_PER_MIN
    rows.append({"block": bl.GEOID20.iloc[i], "pantry": pantries.name.iloc[j_],
                 "model": M[i, j_], "brute_one_bus": b, "walk": walk})
tt = pd.DataFrame(rows)
tt["brute_best"] = np.minimum(tt.brute_one_bus, tt.walk)
tt.loc[tt.brute_best > BUDGET_MIN, "brute_best"] = np.inf
# The model uses MEDIAN run times; brute force takes each trip's own run time, so
# one fast trip can beat the median by a few minutes. Allow 3 minutes.
beats = tt[tt.brute_best < tt.model - 3]
agree = float((np.isfinite(tt.model) == np.isfinite(tt.brute_best)).mean())
check("travel_time_brute_force", len(beats) <= 0.02 * len(tt),
      {"pairs": len(tt), "brute_beats_model_by_3min_plus": len(beats),
       "same_reachable_verdict": round(agree, 3),
       "model_reaches_but_one_bus_cannot": int((np.isfinite(tt.model) & ~np.isfinite(tt.brute_best)).sum()),
       "one_bus_reaches_but_model_cannot": int((~np.isfinite(tt.model) & np.isfinite(tt.brute_best)).sum())})
tt.replace(np.inf, np.nan).to_csv(DERIVED / "check_travel_times.csv", index=False)

# 5. Pantry hours sanity ---------------------------------------------------------------
sess = pd.read_csv(DERIVED / "pantry_sessions.csv")
long = sess[(sess["class"] == "general") & (sess.end - sess.start > 10 * 60)]
names = gpd.read_parquet(DERIVED / "pantries.parquet").set_index("location_id").name
results["suspicious_hours"] = [
    {"name": names[r.location_id], "day": int(r.day), "start": int(r.start), "end": int(r.end)}
    for r in long.itertuples()]
print("info suspicious_hours:", results["suspicious_hours"])

(DERIVED / "checks.json").write_text(json.dumps(results, indent=1, default=str))
if failures:
    raise SystemExit(f"checks failed: {failures}")
print("all checks passed")
