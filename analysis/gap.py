"""Gap = high need + low access. Joins need.py and access.py, labels tracts, ranks gaps.

Writes data/derived/tracts.parquet (everything per tract) and
data/derived/gap_ranking.csv (top gap tracts per window).

Ranking: among high-need tracts (top quarter of the need index), rank by the
estimated number of people in poverty who live where no open pantry is
reachable within the budget: ACS poverty count x share of the tract's
population (2020 blocks) without access. That assumes poverty is spread
across a tract like its population, which is one of the caveats.
"""
import zipfile

import numpy as np
import pandas as pd
import geopandas as gpd

from config import RAW, DERIVED, CRS_M, WINDOW_ORDER, WAIT_MODES, PRIMARY_WAIT

LOW_ACCESS = 0.5  # "low access": fewer than half the tract's residents can reach an open pantry
TOP_N = 10
# Tract labels: the nearest east-west and north-south arterial. TIGER codes almost
# every Tulsa street S1400 (local) and carries stray short segments under arterial
# names, so each long, straight named road is reduced to one line: its
# length-weighted median latitude (east-west roads) or longitude (north-south).
NOT_A_STREET = r"Hwy|Expy|Tpke|Turnpike|Interstate|\bI- ?\d|\bUS\b|Byp|Ramp|Frontage|Pkwy"
GRID_MIN_KM = 8      # total named length to count as an arterial
GRID_ASPECT = 4      # bbox long side / short side: straight grid roads only
FAR_M = 1500         # beyond this, the line isn't a useful landmark
# Only Tulsa's mile-grid arterials (and a few well-known half-mile roads) are used.
_S = "|".join(f"{n}{'st' if n % 10 == 1 and n % 100 != 11 else 'th'}" for n in range(11, 162, 10))
_N = "|".join(f"{n}th" for n in range(36, 127, 10))
EW_NAMES = (rf"^[EW] ({_S}) St( S)?$|^[EW] ({_N}) St N$"
            r"|^[EW] (Admiral Pl|Pine St|Apache St|Archer St|Charles Page Blvd|Kenosha St)$")
NS_NAMES = (r"^[NS] (Peoria|Lewis|Harvard|Yale|Sheridan|Memorial|Mingo|Garnett|Union|Elwood|Utica|"
            r"Cincinnati|Martin Luther King Jr) (Ave|Rd|Dr|Blvd)$"
            r"|^[NS] (129th|145th|161st|177th|193rd) E(ast)? Ave$|^[NS] (33rd|49th|65th) W(est)? Ave$")


def grid_lines(roads):
    r = roads[roads.FULLNAME.notna() & ~roads.FULLNAME.str.contains(NOT_A_STREET, regex=True)]
    r = r[r.FULLNAME.str.match(EW_NAMES) | r.FULLNAME.str.match(NS_NAMES)].copy()
    r["len"] = r.length
    c = r.geometry.centroid
    r["x"], r["y"] = c.x, c.y
    rows = []
    for name, g in r.groupby("FULLNAME"):
        if g.len.sum() < GRID_MIN_KM * 1000:
            continue
        g = g.sort_values("x")
        # Trim the farthest-flung 5% of length at each end before measuring shape.
        def wq(v, q):
            o = np.argsort(v.to_numpy()); cw = np.cumsum(g.len.to_numpy()[o]) / g.len.sum()
            return v.to_numpy()[o][np.searchsorted(cw, q)]
        dx = wq(g.x, 0.95) - wq(g.x, 0.05)
        dy = wq(g.y, 0.95) - wq(g.y, 0.05)
        named_ew = bool(pd.Series([name]).str.match(EW_NAMES).iloc[0])
        if named_ew and dx >= GRID_ASPECT * max(dy, 1):
            rows.append({"name": name, "ew": True, "pos": wq(g.y, 0.5),
                         "lo": wq(g.x, 0.05), "hi": wq(g.x, 0.95)})
        elif not named_ew and dy >= GRID_ASPECT * max(dx, 1):
            rows.append({"name": name, "ew": False, "pos": wq(g.x, 0.5),
                         "lo": wq(g.y, 0.05), "hi": wq(g.y, 0.95)})
    return pd.DataFrame(rows)


def nearest_line(x, y, lines, ew):
    L = lines[lines.ew == ew]
    along, across = (x, y) if ew else (y, x)
    ok = (L.lo - FAR_M <= along) & (along <= L.hi + FAR_M)  # line must actually run past here
    d = (L.pos - across).abs().where(ok)
    if d.isna().all():
        return None, np.inf
    i = d.idxmin()
    return L.name[i], d[i]


def label_tracts(blocks):
    roads = gpd.read_file(f"zip://{RAW / 'tiger' / 'tl_2024_40143_roads.zip'}").to_crs(CRS_M)
    lines = grid_lines(roads)
    places = gpd.read_file(f"zip://{RAW / 'tiger' / 'tl_2024_40_place.zip'}").to_crs(CRS_M)
    places = places[places.LSAD == "25"]  # incorporated cities and towns

    # Population-weighted centre of each tract (2020 blocks), so the label lands
    # where people live rather than in a park or along the river.
    b = blocks.groupby("tract").apply(
        lambda g: pd.Series({"x": np.average(g.x, weights=g.POP20), "y": np.average(g.y, weights=g.POP20)}),
        include_groups=False)
    centres = gpd.GeoDataFrame(b, geometry=gpd.points_from_xy(b.x, b.y), crs=CRS_M)
    ew = [nearest_line(p.x, p.y, lines, True) for p in centres.geometry]
    ns = [nearest_line(p.x, p.y, lines, False) for p in centres.geometry]
    ew_n, ew_d = pd.Series([e[0] for e in ew], index=centres.index), np.array([e[1] for e in ew])
    ns_n, ns_d = pd.Series([e[0] for e in ns], index=centres.index), np.array([e[1] for e in ns])
    city = gpd.sjoin(centres, places[["NAME", "geometry"]], how="left", predicate="within")
    city = city[~city.index.duplicated()]
    ll = centres.to_crs("EPSG:4326")
    # Display: "E 61st St S" -> "E 61st St"; "N Mingo Rd" -> "Mingo Rd" (one name for the whole road).
    ew_n = ew_n.str.replace(r" S$", "", regex=True)
    ns_n = ns_n.str.replace(r"^[NS] ", "", regex=True)
    near = np.where((ew_d <= FAR_M) & (ns_d <= FAR_M), ew_n + " & " + ns_n,
                    np.where(ew_d <= ns_d, ew_n, ns_n))
    return pd.DataFrame({"near": near, "near_m": np.minimum(ew_d, ns_d),
                         "city": city.NAME.fillna("Unincorporated"),
                         "cx": ll.geometry.x, "cy": ll.geometry.y})


def build():
    need = gpd.read_parquet(DERIVED / "tracts_need.parquet")
    acc = pd.read_csv(DERIVED / "tracts_access.csv", dtype={"GEOID": str})
    blocks = pd.read_parquet(DERIVED / "blocks_access.parquet")
    t = need.merge(acc, on="GEOID", how="left")
    assert t.block_pop.notna().all(), "tract with no populated blocks"
    t = t.merge(label_tracts(blocks), left_on="GEOID", right_index=True, how="left")
    t["label"] = t.city + ": near " + t.near.fillna("?")

    # USDA reference layer: low income and more than 1/2 mile (urban) from any
    # SNAP-authorized retailer (2025 SRAM, straight-line distance).
    z = zipfile.ZipFile(RAW / "usda_sram" / "2025-sram-data.zip")
    sd = pd.read_csv(z.open("SRAM Straight Line Distance Data.csv"), encoding="latin1",
                     dtype={"CensusTract20": str}, usecols=["CensusTract20", "SD_SRAM_LILATracts_halfAnd10"])
    t["usda_lila_half"] = t.GEOID.map(sd.set_index("CensusTract20").SD_SRAM_LILATracts_halfAnd10).fillna(0) == 1

    for wait in WAIT_MODES:
        for w in WINDOW_ORDER:
            sh = t[f"share_{w}_{wait}"]
            t[f"poor_no_access_{w}_{wait}"] = t.poor * (1 - sh)
            t[f"nov_no_access_{w}_{wait}"] = t.no_vehicle_hh * (1 - sh)
            t[f"gap_{w}_{wait}"] = t.high_need & (sh < LOW_ACCESS)

    rank_rows = []
    for w in WINDOW_ORDER:
        col = f"poor_no_access_{w}_{PRIMARY_WAIT}"
        top = t[t.high_need].sort_values(col, ascending=False).head(TOP_N)
        for r, (_, x) in enumerate(top.iterrows(), 1):
            rank_rows.append({
                "window": w, "rank": r, "GEOID": x.GEOID, "tract": x.NAME, "label": x.label,
                "need_pctl": round(x.need_pctl, 3), "poverty_rate": round(x.poverty_rate, 3),
                "poverty_rate_moe": round(x.poverty_rate_moe, 3),
                "no_vehicle_rate": round(x.no_vehicle_rate, 3), "snap_rate": round(x.snap_rate, 3),
                "share_access": round(x[f"share_{w}_{PRIMARY_WAIT}"], 3),
                "people_in_poverty_no_access": round(x[col]),
                "no_vehicle_hh_no_access": round(x[f"nov_no_access_{w}_{PRIMARY_WAIT}"]),
                "shaky_components": int(x.n_shaky_components),
            })
    rk = pd.DataFrame(rank_rows)
    rk.to_csv(DERIVED / "gap_ranking.csv", index=False)
    t.to_parquet(DERIVED / "tracts.parquet")
    for w in WINDOW_ORDER:
        n = int(t[f"gap_{w}_{PRIMARY_WAIT}"].sum())
        print(f"gap[{w}]: {n} high-need tracts where under half of residents reach an open pantry")
    return t, rk


if __name__ == "__main__":
    build()
