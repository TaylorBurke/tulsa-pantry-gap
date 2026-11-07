"""First-cut mobile pantry siting: which spots would close the biggest gap?

Candidates are bus stops served in the window (a mobile distribution parked by a
stop is reachable by the same walk + bus trips as everywhere else). For each
candidate, count the estimated people in poverty who live in blocks that today
have no open pantry within the budget but would reach the candidate within it.
People in poverty per block = block population (2020) x its tract's ACS poverty
rate. Pick greedily: the best site, then the best next site given the first.

This is a screening tool, not a recommendation: it ignores parking, partner
sites, demand already served by meal programs, and pantry capacity.
Writes data/derived/siting.json.
"""
import io
import json
import re
import zipfile

import numpy as np
import pandas as pd
import geopandas as gpd

from config import RAW, DERIVED, CRS_M, PRIMARY_WAIT
from access import load_blocks, min_times

N_SITES = 3
SITING_WINDOWS = ["weekday_evening", "saturday"]


def clean_stop(name):
    """'(6932) 71ST ST & WHEELING DR WB' -> '71st St & Wheeling Dr'; 'DAS BAY 4' -> 'Denver Avenue Station'."""
    n = re.sub(r"^\(\d+\)\s*", "", str(name)).replace(".", "").strip(" ,")
    n = re.sub(r"\s+(NB|SB|EB|WB)$", "", n, flags=re.I)
    if re.match(r"^DAS BAY", n, re.I):
        return "Denver Avenue Station"
    if n.isupper():
        n = re.sub(r"(\d+)(St|Nd|Rd|Th)\b", lambda m: m.group(1) + m.group(2).lower(), n.title())
    return n


def build():
    blocks = load_blocks()
    acc = pd.read_parquet(DERIVED / "blocks_access.parquet").set_index("GEOID20")
    tracts = pd.read_parquet(DERIVED / "tracts.parquet").set_index("GEOID")
    blocks["poor_est"] = blocks.POP20 * blocks.tract.map(tracts.poverty_rate).fillna(0).to_numpy()
    z0 = zipfile.ZipFile(RAW / "gtfs" / "mtta_gtfs.zip")
    stop_names = pd.read_csv(io.BytesIO(z0.read("stops.txt")), dtype=str).set_index("stop_id").stop_name
    out = {}
    for w in SITING_WINDOWS:
        z = np.load(DERIVED / f"transit_{w}_{PRIMARY_WAIT}.npz")
        served = np.isfinite(z["T"]).sum(axis=1) > 1
        cand = gpd.GeoDataFrame({"stop_id": z["stop_ids"][served]},
                                geometry=gpd.points_from_xy(z["xy"][served, 0], z["xy"][served, 1]),
                                crs=CRS_M).reset_index(drop=True)
        T = min_times(blocks, cand, w, PRIMARY_WAIT)  # blocks x candidates, inf beyond budget
        lacking = ~np.isfinite(acc.loc[blocks.GEOID20, f"min_{w}_{PRIMARY_WAIT}"].to_numpy())
        weight = np.where(lacking, blocks.poor_est.to_numpy(), 0.0)
        reach = np.isfinite(T)
        covered = np.zeros(len(blocks), dtype=bool)
        picks = []
        cand_ll = cand.to_crs("EPSG:4326")
        for _ in range(N_SITES):
            gain = (reach & ~covered[:, None]).T.astype(float) @ weight
            k = int(np.argmax(gain))
            newly = reach[:, k] & ~covered & lacking
            covered |= reach[:, k]
            tr = blocks.loc[newly].groupby("tract").poor_est.sum().sort_values(ascending=False)
            picks.append({
                "stop_id": str(cand.stop_id.iloc[k]),
                "stop_name": clean_stop(stop_names.get(cand.stop_id.iloc[k], "")),  # label by where it is
                "lon": round(cand_ll.geometry.iloc[k].x, 5), "lat": round(cand_ll.geometry.iloc[k].y, 5),
                "people_in_poverty_newly_within_budget": round(float(gain[k])),
                "residents_newly_within_budget": int(blocks.POP20[newly].sum()),
                "main_tracts": [{"GEOID": g, "label": tracts.label[g], "poor_est": round(float(v))}
                                for g, v in tr.head(3).items()],
            })
        total = float(weight.sum())
        out[w] = {"people_in_poverty_without_access": round(total), "sites": picks}
        print(f"siting[{w}]: " + "; ".join(
            f"{p['stop_name']} +{p['people_in_poverty_newly_within_budget']:,}" for p in picks)
            + f" (of {total:,.0f} without access)")
    (DERIVED / "siting.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    build()
