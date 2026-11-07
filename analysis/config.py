"""Every tunable assumption in one place. The README and the site's methodology
section quote these values; build_site.py reads them from here so the prose and
the analysis cannot drift apart."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
MANUAL = ROOT / "data" / "manual"
DERIVED = ROOT / "data" / "derived"
DERIVED.mkdir(parents=True, exist_ok=True)

STATE, COUNTY = "40", "143"
GEOID_PREFIX = STATE + COUNTY
CRS_M = "EPSG:32615"  # UTM zone 15N, metres: all distance work happens in this CRS

# ---- Need index -------------------------------------------------------------
# Equal-weight z-score blend. Each component is a tract share; z-scores are taken
# across Tulsa County tracts that pass MIN_HOUSEHOLDS.
NEED_WEIGHTS = {"poverty_rate": 1 / 3, "no_vehicle_rate": 1 / 3, "snap_rate": 1 / 3}
# Alternatives used only for the sensitivity check (do top tracts survive?).
NEED_ALTERNATIVES = {
    "vehicle_heavy": {"poverty_rate": 0.25, "no_vehicle_rate": 0.5, "snap_rate": 0.25},
    "poverty_200": {"below_200_rate": 1 / 3, "no_vehicle_rate": 1 / 3, "snap_rate": 1 / 3},
    "poverty_only": {"poverty_rate": 1.0},
}
MIN_HOUSEHOLDS = 100  # tracts with fewer households (airport, river, institutions) are not scored
HIGH_NEED_PCTL = 0.75  # "high need" = top quarter of scored tracts
CV_UNRELIABLE = 0.40  # coefficient of variation above this: estimate flagged as shaky

# ---- Walking and transit ----------------------------------------------------
WALK_M_PER_MIN = 80.47  # 3 mph
CIRCUITY = 1.3  # straight-line distance x 1.3 ~ street-network walking distance
BUDGET_MIN = 30  # door-to-door limit, walk + wait + ride + walk
STOP_SEARCH_M = 1500  # straight-line radius to look for boarding/alighting stops
TRANSFER_M = 300  # max straight-line walk between stops for a transfer
MAX_BOARDINGS = 2  # i.e. at most one transfer
# Waiting for the first bus. A rider going to a pantry can check the schedule and
# leave home to meet the bus, so the default counts a 5-minute cushion rather than
# half the headway. The sensitivity run ("walk_up") uses half the headway instead.
PLANNED_FIRST_WAIT_MIN = 5
WAIT_MODES = ["planned", "walk_up"]
PRIMARY_WAIT = "planned"

# ---- Time windows -----------------------------------------------------------
# A pantry counts in a window if it has a regular session that overlaps it by at
# least min_overlap minutes. The transit span is the stretch of the bus schedule
# used to measure headways and run times for that window.
WINDOWS = {
    "weekday_day": {
        "label": "Weekday daytime", "short": "Weekday day",
        "days": [2, 3, 4, 5, 6],  # AccessFood dayOfWeek: 1=Sun ... 7=Sat
        "open_overlap": (8 * 60, 17 * 60),
        "min_overlap": 30,
        "gtfs_days": "weekday", "span": (9 * 60, 16 * 60),
    },
    "weekday_evening": {
        "label": "Weekday evening (after 5pm)", "short": "Weekday evening",
        "days": [2, 3, 4, 5, 6],
        "open_overlap": (17 * 60, 22 * 60),
        "min_overlap": 30,
        "gtfs_days": "weekday", "span": (17 * 60, 20 * 60),
    },
    "saturday": {
        "label": "Saturday", "short": "Saturday",
        "days": [7],
        "open_overlap": (0, 24 * 60),
        "min_overlap": 30,
        "gtfs_days": "saturday", "span": (9 * 60, 14 * 60),
    },
}
WINDOW_ORDER = ["weekday_day", "weekday_evening", "saturday"]

# ---- Pantry programs ----------------------------------------------------------
# Program types open to the general public count as supply. School pantries
# (enrolled students), CSFP (seniors 60+ who applied) and meal programs are shown
# on the map but do not count: a working parent can't use them for groceries.
GENERAL_PANTRY_TYPES = {"Pantry", "Pop-Up/Mobile Resource", "Food Distribution"}
RESTRICTED_SERVICE_PATTERNS = {
    "school": ["School Pantry", "Youth Program"],
    "senior": ["CSFP", "Senior Program"],
}
WEEKS_PER_MONTH = 4.33
