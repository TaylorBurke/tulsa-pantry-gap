"""Tract need index from ACS 2020-2024 5-year estimates.

Reads data/raw/acs/*-tulsa.dat (pipe-delimited summary-file rows) and
data/raw/tiger/cb_2024_40_tract_500k.zip. Writes data/derived/tracts_need.parquet
(one row per Tulsa County tract, with geometry in EPSG:4326).

Rates carry 90% margins of error computed with the Census Bureau's formula for
derived proportions (ACS General Handbook ch. 8); the coefficient of variation
flags estimates too noisy to rank on.
"""
import numpy as np
import pandas as pd
import geopandas as gpd

from config import (RAW, DERIVED, GEOID_PREFIX, NEED_WEIGHTS, NEED_ALTERNATIVES,
                    MIN_HOUSEHOLDS, HIGH_NEED_PCTL, CV_UNRELIABLE)


def read_table(t):
    df = pd.read_csv(RAW / "acs" / f"acsdt5y2024-{t}-tulsa.dat", sep="|", dtype={"GEO_ID": str})
    df = df.set_index("GEO_ID")
    df = df.apply(pd.to_numeric, errors="coerce")
    # Summary-file jam values (-666666666 etc.) mean "not available": treat as missing.
    return df.mask(df < 0)


def col(df, table, n, kind="E"):
    return df[f"{table.upper()}_{kind}{n:03d}"]


def agg_moe(*moes):
    return np.sqrt(sum(m ** 2 for m in moes))


def prop_moe(num, num_moe, den, den_moe):
    """Census formula for a proportion; falls back to the ratio formula when the
    term under the root goes negative."""
    p = num / den
    inner = num_moe ** 2 - p ** 2 * den_moe ** 2
    ratio_inner = num_moe ** 2 + p ** 2 * den_moe ** 2
    return np.sqrt(np.where(inner >= 0, inner, ratio_inner)) / den


def frame(t, ix):
    b01, b17, c17, b25, b22 = (t[k].loc[ix] for k in ["b01003", "b17001", "c17002", "b25044", "b22003"])
    out = pd.DataFrame(index=ix)
    out["pop"] = col(b01, "b01003", 1)
    out["pop_moe"] = col(b01, "b01003", 1, "M")
    out["pov_universe"] = col(b17, "b17001", 1)
    out["poor"] = col(b17, "b17001", 2)
    out["poor_moe"] = col(b17, "b17001", 2, "M")
    out["poverty_rate"] = out.poor / out.pov_universe
    out["poverty_rate_moe"] = prop_moe(out.poor, out.poor_moe, out.pov_universe,
                                       col(b17, "b17001", 1, "M"))
    # Below 200% of poverty: C17002 rows 2-7 (ratio under 0.50 ... 1.85-1.99).
    out["below_200"] = sum(col(c17, "c17002", n) for n in range(2, 8))
    b200_moe = agg_moe(*(col(c17, "c17002", n, "M") for n in range(2, 8)))
    out["below_200_rate"] = out.below_200 / col(c17, "c17002", 1)
    out["below_200_rate_moe"] = prop_moe(out.below_200, b200_moe, col(c17, "c17002", 1),
                                         col(c17, "c17002", 1, "M"))
    out["households"] = col(b25, "b25044", 1)
    out["households_moe"] = col(b25, "b25044", 1, "M")
    # Zero-vehicle households: owner-occupied (row 3) + renter-occupied (row 10).
    out["no_vehicle_hh"] = col(b25, "b25044", 3) + col(b25, "b25044", 10)
    out["no_vehicle_hh_moe"] = agg_moe(col(b25, "b25044", 3, "M"), col(b25, "b25044", 10, "M"))
    out["no_vehicle_rate"] = out.no_vehicle_hh / out.households
    out["no_vehicle_rate_moe"] = prop_moe(out.no_vehicle_hh, out.no_vehicle_hh_moe,
                                          out.households, out.households_moe)
    out["snap_hh"] = col(b22, "b22003", 2)
    out["snap_hh_moe"] = col(b22, "b22003", 2, "M")
    out["snap_rate"] = out.snap_hh / col(b22, "b22003", 1)
    out["snap_rate_moe"] = prop_moe(out.snap_hh, out.snap_hh_moe, col(b22, "b22003", 1),
                                    col(b22, "b22003", 1, "M"))
    return out


def build():
    t = {k: read_table(k) for k in ["b01003", "b17001", "c17002", "b25044", "b22003"]}
    county_id = f"0500000US{GEOID_PREFIX}"
    for name, tab in t.items():
        assert county_id in tab.index, f"{name}: county row missing"

    tract_ids = [i for i in t["b01003"].index if i.startswith("1400000US")]
    df = frame(t, tract_ids)
    county = frame(t, [county_id]).iloc[0]
    df.index = df.index.str.replace("1400000US", "", regex=False)
    df.index.name = "GEOID"

    # Control totals: ACS tract estimates are controlled to the county, so the
    # tract sums must match the county row.
    assert abs(df["pop"].sum() - county["pop"]) <= 5, (df["pop"].sum(), county["pop"])
    assert abs(df["households"].sum() - county["households"]) <= 5

    scored = df.households >= MIN_HOUSEHOLDS
    df["scored"] = scored
    for c in ["poverty_rate", "no_vehicle_rate", "snap_rate", "below_200_rate"]:
        mu, sd = df.loc[scored, c].mean(), df.loc[scored, c].std(ddof=0)
        df[f"z_{c}"] = (df[c] - mu) / sd
        # CV of the rate: (MOE / 1.645) / estimate. Zero estimates get no CV.
        df[f"cv_{c}"] = (df[f"{c}_moe"] / 1.645) / df[c].where(df[c] > 0)

    def index(weights):
        return sum(w * df[f"z_{c}"] for c, w in weights.items()) / sum(weights.values())

    df["need"] = index(NEED_WEIGHTS).where(scored)
    for name, w in NEED_ALTERNATIVES.items():
        df[f"need_{name}"] = index(w).where(scored)
    df["need_pctl"] = df.need.rank(pct=True)
    df["high_need"] = df.need_pctl > HIGH_NEED_PCTL
    comps = ["poverty_rate", "no_vehicle_rate", "snap_rate"]
    df["n_shaky_components"] = sum((df[f"cv_{c}"] > CV_UNRELIABLE).astype(int) for c in comps)

    # Geometry: 2024 cartographic-boundary tracts (2020 tract definitions).
    g = gpd.read_file(f"zip://{RAW / 'tiger' / 'cb_2024_40_tract_500k.zip'}")
    g = g[g.GEOID.str.startswith(GEOID_PREFIX)][["GEOID", "NAME", "ALAND", "geometry"]]
    missing = set(df.index) ^ set(g.GEOID)
    assert not missing, f"tract ids differ between ACS and TIGER: {sorted(missing)[:5]}"
    g = g.merge(df.reset_index(), on="GEOID").to_crs("EPSG:4326")
    g.to_parquet(DERIVED / "tracts_need.parquet")
    pd.Series({k: float(v) for k, v in county.items()}).to_json(DERIVED / "county_acs.json", indent=1)
    print(f"need: {len(g)} tracts, {int(scored.sum())} scored, county pop {county['pop']:,.0f}")
    return g


if __name__ == "__main__":
    build()
