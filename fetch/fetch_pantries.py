"""Pantry locations and hours from the Food Bank of Eastern Oklahoma's public Food Finder.

okfoodbank.org/pantry-finder/ embeds the AccessFood (Vivery) map widget. This
script makes the same public, unauthenticated GET requests the widget makes in
any visitor's browser: the map config (RegionMap), a location search around
Tulsa County (LocationSearch, paged), then hours (LocationSchedules), programs
(LocationServices) and per-program hours (LocationServiceSchedules), plus any
posted special hours/closures. Only the default in-network listings the public
map shows are requested. Requests are spaced out to be polite.
"""
import json
import time

from common import get, have, save

API = "https://api.accessfood.org/api/MapInformation"
MAP_TOKEN = "67c93e53-9399-4d67-990e-ca26f27cfc9b"  # public id in the okfoodbank.org embed
# Search circle: centered in Tulsa County, 30 miles covers the whole county
# (build_data.py keeps only points inside the county outline).
LAT, LNG, RADIUS = 36.12, -95.94, 30
PAUSE = 1.0


def j(url, headers=None):
    time.sleep(PAUSE)
    return json.loads(get(url, headers=headers))


if have("fbeo_finder", "locations.json") and have("fbeo_finder", "schedules.json"):
    print("fbeo_finder: cached")
    raise SystemExit

region = j(f"{API}/RegionMap?isMapV2=true", headers={"X-Vivery-Map-Token": MAP_TOKEN})
rid, rmid = region["regionId"], region["regionMapId"]
save("fbeo_finder", "region_map.json", f"{API}/RegionMap?isMapV2=true",
     json.dumps(region, indent=1).encode())

empty = "&".join(f"{k}=" for k in ["dayAv", "foodProgramAv", "serviceTypeAv", "foodOfferingAv",
                                    "dietRestrictionAv", "locationFeatureAv", "languagesAv",
                                    "serviceCategoriesAv"])
locs, page, total = [], 0, None
search_url = (f"{API}/LocationSearch?radius={RADIUS}&lat={LAT}&lng={LNG}&{empty}"
              f"&regionId={rid}&regionMapId={rmid}&showOutOfNetwork=0"
              f"&includeLocationOperatingHours=true&isMapV2=true&page={{page}}")
while True:
    d = j(search_url.format(page=page))
    total = d["item5"]
    if not d["item1"]:
        break
    locs += d["item1"]
    page += 1
    if len(locs) >= total or page > 50:
        break
ids = sorted({l["locationId"] for l in locs})
assert len(ids) == total, f"search returned {len(ids)} unique locations, API says {total}"
save("fbeo_finder", "locations.json", search_url.format(page="N"),
     json.dumps(locs, indent=1).encode(), {"locations": len(ids), "search": f"{RADIUS} mi of {LAT},{LNG}"})

out = {"schedules": [], "services": [], "service_schedules": [], "special_hours": []}
for i in range(0, len(ids), 20):
    batch = ",".join(map(str, ids[i:i + 20]))
    pairs = ",".join(f"{x}|{rid}" for x in ids[i:i + 20])
    out["schedules"] += j(f"{API}/LocationSchedules?LocationIds={batch}")
    out["services"] += j(f"{API}/LocationServices?LocationIds={pairs}&PreviewMode=false&MapRegionId={rid}")
    out["service_schedules"] += j(f"{API}/LocationServiceSchedules?LocationIds={batch}&MapRegionId={rid}")
    sp = j(f"{API}/MultipleLocations_LocationSpecialHoursByFirstPage?LocationIds={batch}"
           f"&TimezoneOffsetMinutes=360&PageSize=5")
    out["special_hours"] += sp if isinstance(sp, list) else [sp]
save("fbeo_finder", "schedules.json", f"{API}/LocationSchedules|LocationServices|LocationServiceSchedules",
     json.dumps(out, indent=1).encode(), {k: len(v) for k, v in out.items()})
