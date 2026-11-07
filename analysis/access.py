"""Block-level access to an open, eligible pantry within the budget, per window.

Origins are 2020 census blocks in Tulsa County with people in them (POP20 > 0),
placed at the Census internal point. A trip is either a straight walk, or
walk -> bus (transit.py matrix, up to one transfer) -> walk. Walking distance is
straight-line x CIRCUITY at 3 mph.

A pantry is a destination in a window if it is a general-public pantry with a
regular session in that window (pantries.py) and the origin satisfies its
modeled service-area rule (data/manual/service_areas.csv).

Writes data/derived/blocks_access.parquet (one row per block: population,
tract, minutes to nearest open eligible pantry per window and wait mode) and
data/derived/tracts_access.csv (population-weighted shares per tract).
"""
import numpy as np
import pandas as pd
import geopandas as gpd
import pyogrio
from scipy.spatial import cKDTree

from config import (RAW, DERIVED, CRS_M, GEOID_PREFIX, WINDOW_ORDER, WAIT_MODES, BUDGET_MIN,
                    WALK_M_PER_MIN, CIRCUITY, STOP_SEARCH_M)

WALK_BUDGET_M = BUDGET_MIN * WALK_M_PER_MIN / CIRCUITY  # straight-line metres walkable in budget


def walk_min(d):
    return d * CIRCUITY / WALK_M_PER_MIN


def load_blocks():
    df = pyogrio.read_dataframe(
        RAW / "tiger" / "tl_2020_40_tabblock20.zip",
        columns=["GEOID20", "COUNTYFP20", "POP20", "INTPTLAT20", "INTPTLON20"],
        where=f"COUNTYFP20 = '{GEOID_PREFIX[2:]}'", read_geometry=False)
    df = df[df.POP20 > 0].copy()
    g = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df.INTPTLON20.astype(float),
                                                         df.INTPTLAT20.astype(float)),
                         crs="EPSG:4269").to_crs(CRS_M)
    g["tract"] = g.GEOID20.str[:11]
    return g.reset_index(drop=True)


def eligibility(blocks, pantries):
    """bool matrix blocks x pantries: is the origin inside the pantry's modeled service area?"""
    elig = np.ones((len(blocks), len(pantries)), dtype=bool)
    if not pantries.restriction_modeled.any():
        return elig
    places = gpd.read_file(f"zip://{RAW / 'tiger' / 'tl_2024_40_place.zip'}").to_crs(CRS_M)
    zctas = gpd.read_file(f"zip://{RAW / 'tiger' / 'cb_2020_us_zcta520_500k.zip'}",
                          bbox=tuple(blocks.to_crs("EPSG:4269").total_bounds)).to_crs(CRS_M)
    unsd = gpd.read_file(f"zip://{RAW / 'tiger' / 'tl_2024_40_unsd.zip'}").to_crs(CRS_M)
    pts = blocks[["geometry"]]

    def inside(layer, field, names):
        sub = layer[layer[field].isin(names)]
        missing = set(names) - set(sub[field])
        assert not missing, f"service area names not found in {field}: {missing}"
        hit = gpd.sjoin(pts, sub[[field, "geometry"]], predicate="within", how="left")
        return hit.groupby(level=0)[field].count().reindex(pts.index, fill_value=0).to_numpy() > 0

    for j, p in pantries.reset_index(drop=True).iterrows():
        if not p.restriction_modeled:
            continue
        names = [x.strip() for x in p.restriction_areas.split(";") if x.strip()]
        if p.restriction_rule == "place":
            elig[:, j] = inside(places, "NAME", names)
        elif p.restriction_rule == "zip":
            elig[:, j] = inside(zctas, "ZCTA5CE20", names)
        elif p.restriction_rule == "school_district":
            elig[:, j] = inside(unsd, "NAME", names)
        elif p.restriction_rule == "county":
            elig[:, j] = GEOID_PREFIX in names
        else:
            raise ValueError(f"unknown modeled rule {p.restriction_rule}")
    return elig


def min_times(blocks, pantries, window, wait):
    """Minutes from each block to each pantry (inf when beyond the budget)."""
    z = np.load(DERIVED / f"transit_{window}_{wait}.npz")
    T, sxy = z["T"].astype(np.float64), z["xy"]
    bxy = np.c_[blocks.geometry.x, blocks.geometry.y]
    pxy = np.c_[pantries.geometry.x, pantries.geometry.y]
    stree = cKDTree(sxy)

    # Egress: minutes from every boarding stop to each pantry via its best alighting stop.
    A = np.full((len(sxy), len(pxy)), np.inf)
    for j, (px, py) in enumerate(pxy):
        near = stree.query_ball_point((px, py), STOP_SEARCH_M)
        if near:
            eg = walk_min(np.hypot(sxy[near, 0] - px, sxy[near, 1] - py))
            A[:, j] = np.min(T[:, near] + eg[None, :], axis=1)

    # Access: block -> boarding stops within STOP_SEARCH_M.
    pairs = stree.query_ball_point(bxy, STOP_SEARCH_M)
    o_idx = np.repeat(np.arange(len(bxy)), [len(p) for p in pairs])
    s_idx = np.concatenate([np.asarray(p, dtype=int) for p in pairs])
    acc = walk_min(np.hypot(bxy[o_idx, 0] - sxy[s_idx, 0], bxy[o_idx, 1] - sxy[s_idx, 1]))
    best = np.full((len(bxy), len(pxy)), np.inf)
    for lo in range(0, len(o_idx), 200_000):  # chunks keep memory modest
        sl = slice(lo, lo + 200_000)
        np.minimum.at(best, o_idx[sl], acc[sl, None] + A[s_idx[sl], :])

    # Direct walk.
    for i, near in enumerate(cKDTree(pxy).query_ball_point(bxy, WALK_BUDGET_M)):
        if near:
            d = walk_min(np.hypot(pxy[near, 0] - bxy[i, 0], pxy[near, 1] - bxy[i, 1]))
            best[i, near] = np.minimum(best[i, near], d)
    best[best > BUDGET_MIN] = np.inf
    return best


def build():
    blocks = load_blocks()
    pantries = gpd.read_parquet(DERIVED / "pantries.parquet").to_crs(CRS_M)
    # Destinations: general-public pantries. Those without listed hours can't be
    # placed in a window; they enter only the "unlisted counted open" upper bound.
    pantries = pantries[pantries.general].reset_index(drop=True)
    elig = eligibility(blocks, pantries)

    out = blocks[["GEOID20", "tract", "POP20"]].copy()
    out["x"], out["y"] = blocks.geometry.x, blocks.geometry.y
    unlisted = ~pantries.hours_listed.to_numpy()
    for wait in WAIT_MODES:
        for w in WINDOW_ORDER:
            t = min_times(blocks, pantries, w, wait)
            open_w = pantries[f"open_{w}"].to_numpy()
            weekly_w = pantries[f"weekly_{w}"].to_numpy()
            ok = np.where(elig & open_w[None, :], t, np.inf)
            out[f"min_{w}_{wait}"] = ok.min(axis=1)
            out[f"n_{w}_{wait}"] = np.isfinite(ok).sum(axis=1)
            # Sensitivity variants.
            out[f"min_weekly_{w}_{wait}"] = np.where(weekly_w[None, :], ok, np.inf).min(axis=1)
            out[f"min_noelig_{w}_{wait}"] = np.where(open_w[None, :], t, np.inf).min(axis=1)
            out[f"min_unlisted_{w}_{wait}"] = np.where(elig & (open_w | unlisted)[None, :], t, np.inf).min(axis=1)
        print(f"access[{wait}]: " + ", ".join(
            f"{w} {np.average(np.isfinite(out[f'min_{w}_{wait}']), weights=out.POP20):.1%}"
            for w in WINDOW_ORDER) + " of county residents reach an open pantry")
    out.to_parquet(DERIVED / "blocks_access.parquet")

    rows = []
    for tract, g in out.groupby("tract"):
        r = {"GEOID": tract, "block_pop": int(g.POP20.sum()), "n_blocks": len(g)}
        for wait in WAIT_MODES:
            for w in WINDOW_ORDER:
                for kind in ["", "weekly_", "noelig_", "unlisted_"]:
                    col = f"min_{kind}{w}_{wait}"
                    r[f"share_{kind}{w}_{wait}"] = float(np.average(np.isfinite(g[col]), weights=g.POP20))
                m = g[f"min_{w}_{wait}"].replace(np.inf, np.nan)
                r[f"median_min_{w}_{wait}"] = float(m.median()) if m.notna().any() else np.nan
        rows.append(r)
    pd.DataFrame(rows).to_csv(DERIVED / "tracts_access.csv", index=False)
    print(f"access: {len(out):,} populated blocks, {int(out.POP20.sum()):,} people (2020 census)")


if __name__ == "__main__":
    build()
