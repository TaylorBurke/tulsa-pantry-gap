"""Package the derived tract and block tables as a Kaggle dataset -> dist/kaggle/.

Only Census/TIGER/GTFS-derived numbers go out. Pantry listings (names, addresses,
hours) belong to the Food Finder's publisher and are not included, nor is anything
from data/raw/.

    make kaggle                      # build dist/kaggle/
    KAGGLE_OWNER=<username> make kaggle
    kaggle datasets create -p dist/kaggle      # first upload (private by default)
    kaggle datasets version -p dist/kaggle -m "rebuild YYYY-MM-DD"   # later
"""
import json
import os
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import geopandas as gpd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analysis"))
from config import DERIVED, CRS_M, WINDOWS, WINDOW_ORDER, BUDGET_MIN  # noqa: E402

OUT = ROOT / "dist" / "kaggle"
OWNER = os.environ.get("KAGGLE_OWNER", "OWNER")
SLUG = "tulsa-pantry-gap"
SITE = "https://tulsa-pantry-gap.pages.dev/"
REPO = "https://github.com/TaylorBurke/tulsa-pantry-gap"

WAITS = {"planned": "rider checks the schedule (5-minute first wait)",
         "walk_up": "rider walks up without checking (waits half the headway)"}

# Columns used only to place map labels; not useful as data.
DROP_TRACT = ["geometry", "cx", "cy", "near_m"]

BASE_DESC = {
    "GEOID": "11-digit census tract FIPS code (state 40, county 143)",
    "NAME": "Census tract number, e.g. 68.01",
    "label": "Human-readable location: city and nearest named arterial intersection",
    "near": "Nearest named arterial or intersection used in the label",
    "city": "Place the tract centroid falls in (or Unincorporated)",
    "ALAND": "Land area, square metres (TIGER)",
    "pop": "Total population, ACS 2020-24 5-year",
    "pov_universe": "Population for whom poverty status is determined",
    "poor": "People below the poverty line",
    "poverty_rate": "Share of people below the poverty line",
    "below_200": "People below 200% of the poverty line",
    "below_200_rate": "Share of people below 200% of the poverty line",
    "households": "Households",
    "no_vehicle_hh": "Households with no vehicle available",
    "no_vehicle_rate": "Share of households with no vehicle",
    "snap_hh": "Households receiving SNAP",
    "snap_rate": "Share of households receiving SNAP",
    "scored": "Tract has at least 100 households and gets a need score",
    "need": "Need index: equal-weight mean of z-scores of poverty, no-vehicle and SNAP rates",
    "need_vehicle_heavy": "Sensitivity need index, no-vehicle double-weighted",
    "need_poverty_200": "Sensitivity need index using 200%-of-poverty instead of poverty",
    "need_poverty_only": "Sensitivity need index, poverty rate only",
    "need_pctl": "Percentile rank of need among scored tracts",
    "high_need": "Top quarter of need (need_pctl > 0.75)",
    "n_shaky_components": "Number of need components with coefficient of variation > 40%",
    "usda_lila_half": "USDA 2025 SRAM low-income/low-access flag at 1/2 mile (reference)",
    "block_pop": "2020 census population of the tract's populated blocks (trip origins)",
    "n_blocks": "Number of populated 2020 blocks in the tract",
}


def window_desc(col):
    """Describe a <measure>_<window>_<wait> column, or return None."""
    for w in WINDOW_ORDER:
        for wait in WAITS:
            sfx = f"_{w}_{wait}"
            if not col.endswith(sfx):
                continue
            m = col[: -len(sfx)]
            when = f"{WINDOWS[w]['label']}, {WAITS[wait]}"
            reach = f"reach an open general-public pantry within {BUDGET_MIN} min by walking + bus"
            d = {
                "share": f"Population-weighted share of block residents who {reach}",
                "share_weekly": "Same, counting only pantries open every week in the window",
                "share_noelig": "Same, ignoring pantry service-area (eligibility) limits",
                "share_unlisted": "Same, counting pantries that list no hours as open (upper bound)",
                "median_min": f"Median minutes to the nearest open pantry (blank if none within {BUDGET_MIN})",
                "poor_no_access": "People in poverty x share without access",
                "nov_no_access": "No-vehicle households x share without access",
                "gap": "Gap tract: high need and under half of residents have access",
                "min": f"Minutes to the nearest open pantry; blank if none within {BUDGET_MIN}",
                "n": f"Number of open pantries reachable within {BUDGET_MIN} min",
                "min_weekly": "Minutes, counting only every-week pantries",
                "min_noelig": "Minutes, ignoring service-area limits",
                "min_unlisted": "Minutes, counting no-hours pantries as open",
            }.get(m)
            return f"{d}. {when}." if d else None
    return None


def describe(col):
    if col in BASE_DESC:
        return BASE_DESC[col]
    if col.endswith("_moe") and col[:-4] in BASE_DESC:
        return "90% margin of error of " + BASE_DESC[col[:-4]].lower()
    for pre, what in (("z_", "z-score of "), ("cv_", "Coefficient of variation of ")):
        if col.startswith(pre) and col[len(pre):] in BASE_DESC:
            return what + BASE_DESC[col[len(pre):]].lower()
    return window_desc(col) or ""


def kaggle_type(s):
    if pd.api.types.is_bool_dtype(s):
        return "boolean"
    if pd.api.types.is_integer_dtype(s):
        return "integer"
    if pd.api.types.is_float_dtype(s):
        return "number"
    return "string"


def schema(df, overrides=None):
    overrides = overrides or {}
    return {"fields": [{"name": c, "description": overrides.get(c) or describe(c), "type": kaggle_type(df[c])}
                       for c in df.columns]}


def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    story = json.loads((DERIVED / "story.json").read_text())

    # Tracts: one row per tract; geometry goes to its own file.
    t = gpd.read_parquet(DERIVED / "tracts.parquet")
    tracts = pd.DataFrame(t.drop(columns=DROP_TRACT)).replace([np.inf, -np.inf], np.nan)
    tracts.to_csv(OUT / "tracts.csv", index=False)
    t[["GEOID", "NAME", "label", "geometry"]].to_crs("EPSG:4326").to_file(OUT / "tracts.geojson", driver="GeoJSON")

    # Blocks: UTM -> lon/lat; inf (nothing in reach) -> blank.
    b = pd.read_parquet(DERIVED / "blocks_access.parquet")
    pts = gpd.GeoSeries(gpd.points_from_xy(b.x, b.y), crs=CRS_M).to_crs("EPSG:4326")
    b = b.drop(columns=["x", "y"])
    b.insert(3, "lon", np.round(pts.x.values, 6))
    b.insert(4, "lat", np.round(pts.y.values, 6))
    b = b.replace([np.inf, -np.inf], np.nan)
    b.to_csv(OUT / "blocks_access.csv", index=False)

    rank = pd.read_csv(DERIVED / "gap_ranking.csv", dtype={"GEOID": str, "tract": str})
    rank.to_csv(OUT / "gap_ranking.csv", index=False)
    transit = pd.read_csv(DERIVED / "transit_summary.csv")
    transit.to_csv(OUT / "transit_summary.csv", index=False)

    block_over = {"GEOID20": "15-digit 2020 census block code", "tract": "Tract GEOID the block belongs to",
                  "POP20": "2020 census block population", "lon": "Block centroid longitude (WGS84)",
                  "lat": "Block centroid latitude (WGS84)"}
    rank_over = {"window": "Time window: weekday_day, weekday_evening or saturday",
                 "rank": "Gap rank within the window (1 = most people in poverty without access)",
                 "tract": "Census tract number",
                 "share_access": "Share of residents who reach an open pantry (planned wait)",
                 "people_in_poverty_no_access": "People in poverty x share without access",
                 "no_vehicle_hh_no_access": "No-vehicle households x share without access",
                 "shaky_components": "Need components with CV > 40%"}
    transit_over = {"window": "Time window", "wait": "planned or walk_up",
                    "median_headway_min": "Median minutes between buses across served stops",
                    "served_stops": "Stops with service in the window",
                    "median_stops_within_budget": f"Median number of stops reachable within {BUDGET_MIN} min"}

    c, wins = story["county"], story["windows"]
    hl = {w: f"{round(100 * wins[w]['planned']['share_high_need'])}%" for w in WINDOW_ORDER}
    description = f"""Where in Tulsa County, Oklahoma, food need is high but **no food pantry is open and reachable without a car**, on weekday daytimes, weekday evenings (after 5pm) and Saturdays.

This is the data behind the [Tulsa Pantry Gap Map]({SITE}) ([code and full method]({REPO})), built {story['built']}. A personal project on public data only; it is not a product of, or endorsed by, the Food Bank of Eastern Oklahoma.

## Headline
In the {c['high_need_tracts']} highest-need tracts ({c['high_need_pop']:,} people), the share of residents who can reach an open pantry within {BUDGET_MIN} minutes by walking and bus is **{hl['weekday_day']}** on a weekday daytime, **{hl['weekday_evening']}** after 5pm and **{hl['saturday']}** on Saturday. It's *when*, not *where*.

## Files
| file | rows | what |
|---|---|---|
| `tracts.csv` | {len(tracts)} | One row per census tract: ACS need measures with margins of error, the need index, and access/gap measures per window and wait assumption |
| `tracts.geojson` | {len(t)} | Tract outlines (WGS84), join on `GEOID` |
| `blocks_access.csv` | {len(b):,} | One row per populated 2020 block: minutes to the nearest open pantry and count of pantries in reach, per window |
| `gap_ranking.csv` | {len(rank)} | Top gap tracts per window |
| `transit_summary.csv` | {len(transit)} | Bus service summary per window |

Column names follow `<measure>_<window>_<wait>`: window is `weekday_day`, `weekday_evening` or `saturday`; wait is `planned` (rider checks the schedule, 5-minute first wait; the primary assumption) or `walk_up` (waits half the headway). Every column is described in the column metadata.

To reproduce the headline: take blocks in `high_need` tracts and compute the `POP20`-weighted share with a non-blank `min_<window>_planned`.

## Method in brief
- **Need**: equal-weight z-score blend of tract poverty rate, zero-vehicle household share and SNAP share (ACS 2020-24). High need = top quarter. Three alternative weightings are included for sensitivity.
- **Pantries**: general-public pantry programs from the Food Bank's public Food Finder, with regular weekly/monthly sessions and service-area limits. A pantry counts in a window if a session overlaps it by 30+ minutes. Pantry listings themselves are **not** in this dataset.
- **Travel**: from each populated block, walk (3 mph, straight line x 1.3) or walk + bus (MetroLink GTFS, up to one transfer) + walk, within {BUDGET_MIN} minutes. A frequency-based approximation; an R5 router cross-check agrees for 93-98% of residents, and the model runs 1-3 points optimistic.
- **Gap**: high need and under half of residents reach an open pantry; ranked by people in poverty without access.

## Caveats
- Tract-level ACS margins of error are wide; MOE and CV columns are included, and `n_shaky_components` flags measures with CV > 40%.
- Pantry hours are self-reported and may be stale; holiday closures are not modeled; the public map covers only part of the Food Bank network.
- Bus times are scheduled, not real-time; no return trip, no sidewalk data. Block populations are 2020.

## Sources and license
ACS and TIGER (U.S. Census Bureau) and USDA SRAM 2025 are public domain; MetroLink Tulsa GTFS is a public feed. Derived data: **CC BY 4.0**, credit "Taylor Burke, Tulsa Pantry Gap Map" with a link to {SITE}.
"""

    meta = {
        "title": "Tulsa Food Pantry Access Gaps",
        "subtitle": "Census tracts where need is high but no pantry is open and reachable by bus",
        "id": f"{OWNER}/{SLUG}",
        # metadata --update sets visibility from this field (missing = public), so it must be explicit.
        # Flip to False only when the owner says to publish.
        "isPrivate": os.environ.get("KAGGLE_PUBLIC") != "1",
        "licenses": [{"name": "Attribution 4.0 International (CC BY 4.0)"}],  # server-side name; the short id fails on --update
        "keywords": ["food", "public health", "transportation", "cities and urban areas", "united states",
                     "geospatial analysis", "social issues and advocacy"],
        "description": description,
        "resources": [
            {"path": "tracts.csv", "description": "One row per Tulsa County census tract: need and access",
             "schema": schema(tracts)},
            {"path": "tracts.geojson", "description": "Tract outlines, WGS84; join to tracts.csv on GEOID"},
            {"path": "blocks_access.csv", "description": "One row per populated 2020 block: travel minutes per window",
             "schema": schema(b, block_over)},
            {"path": "gap_ranking.csv", "description": "Top gap tracts per window", "schema": schema(rank, rank_over)},
            {"path": "transit_summary.csv", "description": "Bus service per window and wait assumption",
             "schema": schema(transit, transit_over)},
        ],
    }
    (OUT / "dataset-metadata.json").write_text(json.dumps(meta, indent=2))

    missing = [f["name"] for r in meta["resources"] for f in r.get("schema", {}).get("fields", [])
               if not f["description"]]
    if missing:
        sys.exit(f"columns without a description: {missing}")

    # The headline must reproduce from the packaged files alone.
    hn = set(tracts.loc[tracts.high_need, "GEOID"].astype(str))
    hb = b[b.tract.astype(str).isin(hn)]
    for w in WINDOW_ORDER:
        got = round(float(np.average(hb[f"min_{w}_planned"].notna(), weights=hb.POP20)), 3)
        want = wins[w]["planned"]["share_high_need"]
        if abs(got - want) > 0.001:
            sys.exit(f"headline mismatch for {w}: packaged {got} vs story {want}")

    for f in sorted(OUT.iterdir()):
        print(f"{f.stat().st_size:>10,}  {f.name}")
    if OWNER == "OWNER":
        print("note: set KAGGLE_OWNER=<your kaggle username> before uploading")


if __name__ == "__main__":
    main()
