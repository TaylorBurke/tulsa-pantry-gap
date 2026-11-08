# tulsa-pantry-gap

**Tulsa Pantry Gap Map.** Where in Tulsa County food need is high but no food pantry is open and reachable without a car, on weekday daytimes, weekday evenings (after 5pm) and Saturdays.

By [Taylor Burke](https://www.taylorburke.me/). Live at **https://tulsa-pantry-gap.pages.dev/**. Data on Kaggle: **[Tulsa Food Pantry Access Gaps](https://www.kaggle.com/datasets/taylorwburke/tulsa-pantry-gap)** (tract and block tables, CC BY 4.0; `make kaggle` builds it).

A personal project built only on public data. It is not a product of, and is not endorsed by, the Food Bank of Eastern Oklahoma; it uses no internal Food Bank data.

## What the data says (build of 2026-11-06)

- **It's when, not where.** In the 52 highest-need tracts (top quarter of the need index, 154,111 people), **95%** of residents can reach an open pantry within 30 minutes by walking and bus on a weekday daytime. After 5pm it's **54%**; on Saturday **50%**.
- Of the 69 general-public pantries in the county, **53** hold weekday daytime hours, **17** weekday evening hours and **12** Saturday hours (only 8 every Saturday).
- People in poverty in high-need tracts with no open pantry in reach: about **2,200** on a weekday daytime, **21,000** on a weekday evening, **22,500** on Saturday.
- The top gap for both evenings and Saturdays is the tract around **E 61st St & Peoria Ave** (tract 68.01): 47% poverty (±13), 28% of households without a car. Two pantries are open within a mile on weekdays; after 5pm the nearest open one is 7.2 km away, on Saturday 5.0 km.
- A first-cut mobile-pantry screen puts the best Saturday site at the bus stop at 71st St & Wheeling Dr, which serves the 61st & Peoria area (about 8,700 more people in poverty within 30 minutes), then 4th St & Harvard Ave (about 8,000 more). For weekday evenings: 31st St & Garnett Rd, then 71st & Wheeling (about 10,000 and 9,900).
- If riders walk up without checking the schedule (waiting half the time between buses), high-need reach falls to 78% / 34% / 19%.

Numbers on the site are regenerated from the data on every build; the list above is a snapshot.

## Sources

| id | what it supplies |
|---|---|
| `acs` | ACS 2020-2024 5-year tract estimates (poverty, income-to-poverty ratio, vehicles available, SNAP), from the keyless summary-file tables. The Census API now requires a key. |
| `tiger` | Tract outlines, 2020 blocks with population (trip origins), places, ZCTAs and school districts (pantry service areas), roads (tract labels) |
| `usda_sram` | USDA Food Access Research Atlas, **2025 SNAP-authorized Retailer Access Map** (July 2026; it replaced the 2019 Large Retailer Access Map, formerly FARA). Reference flag + cross-check. |
| `gtfs` | MetroLink Tulsa GTFS (feed valid 2026-09-10 to 2026-12-05) |
| `fbeo_finder` | Pantry locations, programs, hours and service areas from the Food Bank's **public** Food Finder (okfoodbank.org/pantry-finder, an AccessFood/Vivery widget). Only the requests the widget makes for any visitor; only public listing fields are kept. |
| `osm` | OpenStreetMap extract, only for the optional R5 validation |

**Supply-side note:** the original plan was to reuse `~/Work/tulsa-resources` for pantry locations and hours, but that list has only a few food sites and links out to the Food Finder for the rest, so the Food Finder is the supply source. `tulsa-resources` was not changed.

## Method in brief

- **Need index**: equal-weight mean of z-scores of the tract poverty rate, zero-vehicle household share and SNAP household share (weights in `analysis/config.py`). High need = top quarter. Sensitivity runs: vehicle double-weighted, 200% of poverty, poverty only.
- **Pantries**: general-public pantry programs only; school pantries, senior CSFP and meal programs are excluded. Regular sessions include "2nd and 4th Saturday" rules. City, ZIP, school-district and county service-area limits are applied (`data/manual/service_areas.csv`, hand-coded from the listings' eligibility text).
- **Windows**: weekday 8am-5pm, weekday after 5pm, Saturday; a session counts if it overlaps the window by 30+ minutes.
- **Travel time**: from each populated 2020 block, walk (3 mph, straight line x 1.3) or walk + bus (up to one transfer) + walk, within 30 minutes. Bus legs: frequency-based approximation on the GTFS schedule (median run times; waits from headways; 5-minute first wait for a schedule-checking rider, half-headway in the "walk up" variant).
- **Why not a router?** The approximation is fast and transparent. `analysis/validate_r5.py` runs R5 (r5py) on a 500-block sample with the real street network and timetable: verdicts agree for 93-95% of residents (planned vs R5's 5th percentile) and 96-98% (walk-up vs R5's median); the model is 1-3 points optimistic on reach. Good enough, so R5 stays a validation step.
- **Gap**: high need and under half of residents reach an open pantry. Ranked by people in poverty without access (ACS poverty count x block-weighted no-access share).

## Pipeline

```
fetch/fetch_acs.py        Census summary-file tables (Tulsa rows only) -> data/raw/acs/
fetch/fetch_geo.py        TIGER/cartographic files                      -> data/raw/tiger/
fetch/fetch_usda.py       USDA SRAM 2025                                -> data/raw/usda_sram/
fetch/fetch_gtfs.py       MTTA GTFS                                     -> data/raw/gtfs/
fetch/fetch_pantries.py   public Food Finder JSON                       -> data/raw/fbeo_finder/
analysis/need.py          need index + MOEs                -> data/derived/tracts_need.parquet
analysis/pantries.py      programs, sessions, windows      -> data/derived/pantries.parquet
analysis/transit.py       stop-to-stop minutes per window  -> data/derived/transit_*.npz
analysis/access.py        block access per window          -> data/derived/blocks_access.parquet, tracts_access.csv
analysis/gap.py           labels, gap flags, ranking       -> data/derived/tracts.parquet, gap_ranking.csv
analysis/siting.py        mobile pantry screen             -> data/derived/siting.json
analysis/checks.py        independent checks (exit 1 on failure) -> data/derived/checks.json
analysis/story.py         every quoted number + map layers -> data/derived/story.json, site/data/
build_board.py            story.json -> site/index.html (bulletin-board edition, the default page)
build_site.py             story.json -> site/classic/index.html, site/sources.html (asserts headline claims)
analysis/validate_r5.py   optional R5 cross-check          -> data/derived/validate_r5.json
```

```sh
make            # fetch what's missing, analysis, checks, site (~30 s once raw files exist)
make refresh    # re-download every source first
make validate   # optional R5 check (Java 21+, ~170 MB OSM download); validate_r5.json is committed
make serve      # http://localhost:8765
make smoke      # headless Chrome test of the classic page (with `make serve` running)
```

Python deps are locked with uv (`pyproject.toml`, `uv.lock`); r5py is in the optional `validate` group. Raw downloads are git-ignored; each source folder has a `manifest.json` (url, sha256, fetch time; the ACS subset also records the full national file's hash).

## Checks (all pass)

1. Tract ACS populations sum to the county (680,794); populated 2020 blocks sum to the 2020 census count (669,279).
2. Three tracts (highest-need, median, lowest-need) recomputed from the raw Census text with the `csv` module match exactly. Tract 10: 416 of 1,299 people below poverty, 330 of 711 households without a car, 347 of 711 on SNAP.
3. USDA's tract tabulation: correlation 1.00 (poverty), 0.98 (zero-vehicle), 0.99 (SNAP).
4. Brute-force one-bus trips from `stop_times.txt` never beat the model by more than 3 minutes (300 pairs; same verdict in 100%).
5. R5 cross-check (above).
6. Hand trace of the lead tract (61st & Peoria): nearest open pantries by window, distances and minutes.

## Caveats

- ACS margins of error are wide at tract level; the site shows ± for every rate and flags measures with CV > 40%.
- Pantry hours are self-reported and can be stale; holiday closures aren't modeled; 7 county pantries list no hours (upper-bound sensitivity counts them open); CrossPoint lists a 10am-11pm Friday session (counted as listed). The public map covers only part of the Food Bank network (it cites 333 pantries and feeding programs in the county) and none outside it.
- Bus times are scheduled, not real; no return trip, no groceries, no sidewalk data; straight-line walking flatters access in places.
- Tract averages hide variation within tracts; block populations are 2020.
- Two service-area rules (one neighborhood, one unspecified) aren't mapped and are treated as open to all; income limits aren't modeled.

## Hosting

Cloudflare Pages project `tulsa-pantry-gap`; `site/` is the whole static site. After `make`:

```sh
npx wrangler@4 pages deploy site --project-name tulsa-pantry-gap --branch main --commit-dirty=true
```

## License

- **Code**: MIT, see `LICENSE`.
- **Text, charts and derived data** (`data/derived/`, the published site): [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Census, TIGER and USDA data are public domain; pantry listings belong to their publisher and are shown as public listing fields only; OSM data is ODbL.
- **Vendored**: D3 v7.9.0 (ISC) in `site/assets/vendor/`.
