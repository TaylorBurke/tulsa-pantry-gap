"""ACS 2020-2024 5-year estimates, Tulsa County tracts, from the keyless table-based summary file.

The Census API now requires a key, so we read the public summary-file tables
instead. Each national table is streamed and only Tulsa County rows are kept
(the county row 0500000US40143 and its tracts 1400000US40143*). The manifest
records the sha256 of the full national file so the subset can be audited.
"""
import hashlib
import urllib.request

from common import UA, download, have, save

BASE = "https://www2.census.gov/programs-surveys/acs/summary_file/2024/table-based-SF"
TABLES = {
    "b01003": "total population",
    "b17001": "poverty status in the past 12 months (persons)",
    "c17002": "ratio of income to poverty level (persons)",
    "b25044": "tenure by vehicles available (households)",
    "b22003": "SNAP receipt in the past 12 months (households)",
}
KEEP = ("0500000US40143", "1400000US40143")

for t, what in TABLES.items():
    name = f"acsdt5y2024-{t}-tulsa.dat"
    if have("acs", name):
        print(f"acs/{name}: cached")
        continue
    url = f"{BASE}/data/5YRData/acsdt5y2024-{t}.dat"
    h = hashlib.sha256()
    kept = []
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=600) as r:
        header = None
        for raw in r:
            h.update(raw)
            line = raw.decode("utf-8")
            if header is None:
                header = line
                kept.append(line)
            elif line.startswith(KEEP):
                kept.append(line)
    assert len(kept) > 200, f"{t}: only {len(kept)} rows kept, expected ~250 Tulsa County tracts"
    save("acs", name, url, "".join(kept).encode(),
         {"filter": "GEO_ID starts with 0500000US40143 or 1400000US40143",
          "full_file_sha256": h.hexdigest(), "table": what})

download("acs", "ACS20245YR_Table_Shells.txt", f"{BASE}/documentation/ACS20245YR_Table_Shells.txt")
