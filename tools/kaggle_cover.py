"""Render dist/kaggle/dataset-cover-image.png (560x280) for the Kaggle dataset.

Kaggle crops the cover from the top-left 560x280 and the thumbnail from the
centre 280x280 (x 140-420), so the three window maps sit side by side with the
evening map in the middle. Run by `make kaggle` after kaggle_package.py.
"""
from pathlib import Path

import pandas as pd
import geopandas as gpd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "dist" / "kaggle"
KRAFT, PAPER, ORANGE = "#b89b72", "#fcfcfb", "#eb6834"
# Sequential blue, light -> dark = share of residents cut off (dataviz reference ramp).
RAMP = LinearSegmentedColormap.from_list("blues", ["#cde2fb", "#86b6ef", "#3987e5", "#1c5cab", "#0d366b"])
WINDOWS = ("weekday_day", "weekday_evening", "saturday")
W_IN, H_IN = 5.6, 2.8

g = gpd.read_file(OUT / "tracts.geojson").to_crs("EPSG:32615")
t = pd.read_csv(OUT / "tracts.csv", dtype={"GEOID": str})
g = g.merge(t[["GEOID", "high_need"] + [f"share_{w}_planned" for w in WINDOWS]], on="GEOID")
x0, y0, x1, y1 = g.total_bounds

fig = plt.figure(figsize=(W_IN, H_IN), dpi=100, facecolor=KRAFT)
for i, w in enumerate(WINDOWS):
    # Each map on its own paper card, a third of the width.
    box = [i / 3 + 0.012, 0.04, 1 / 3 - 0.024, 0.92]
    ax = fig.add_axes(box)
    ax.set_facecolor(PAPER)
    g.assign(cut=1 - g[f"share_{w}_planned"]).plot(column="cut", cmap=RAMP, vmin=0, vmax=1, ax=ax,
                                                    edgecolor=PAPER, linewidth=0.15)
    g[g.high_need].boundary.plot(ax=ax, color=ORANGE, linewidth=0.45)
    ax.set_xticks([]); ax.set_yticks([])
    for s in ax.spines.values():
        s.set_visible(False)
    # Fit the whole county inside the card, centred, true aspect.
    ax.set_xlabel(""); ax.set_ylabel("")
    card = (box[2] * W_IN) / (box[3] * H_IN)  # width / height of the card
    w, h = (x1 - x0) * 1.08, (y1 - y0) * 1.08
    if w / h > card:
        h = w / card
    else:
        w = h * card
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    ax.set_xlim(cx - w / 2, cx + w / 2)
    ax.set_ylim(cy - h / 2, cy + h / 2)
    ax.set_aspect("auto")
fig.savefig(OUT / "dataset-cover-image.png", dpi=100, facecolor=KRAFT)
print("wrote", OUT / "dataset-cover-image.png")
