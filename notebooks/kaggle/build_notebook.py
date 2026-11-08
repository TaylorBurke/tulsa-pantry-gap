"""Write the Kaggle starter notebook (tulsa-pantry-gap-starter.ipynb) from the cells below.

Edit cells here, not in the .ipynb. `make kaggle-notebook` rebuilds the notebook and
runs it locally against dist/kaggle/; `kaggle kernels push -p notebooks/kaggle` uploads it.
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent

CELLS = [
    ("md", """# Tulsa pantry gaps: reproduce the headline

In Tulsa County's highest-need neighborhoods, almost everyone can reach an open food pantry by walking and bus on a weekday daytime. After 5pm and on Saturdays, only about half can. **It's when, not where.**

This notebook loads the [Tulsa Food Pantry Access Gaps](https://www.kaggle.com/datasets/taylorwburke/tulsa-pantry-gap) dataset, reproduces that headline from the block-level travel times, maps it, and lists the tracts with the largest gaps.

Data story: [tulsa-pantry-gap.pages.dev](https://tulsa-pantry-gap.pages.dev/) · Code and full method: [GitHub](https://github.com/TaylorBurke/tulsa-pantry-gap). A personal project on public data; not a product of, or endorsed by, the Food Bank of Eastern Oklahoma."""),
    ("code", """from pathlib import Path

import numpy as np
import pandas as pd
import geopandas as gpd
import matplotlib.pyplot as plt

# Works on Kaggle (wherever the dataset is mounted) and locally (dist/kaggle/).
hits = sorted(Path('/kaggle/input').glob('**/tracts.csv')) if Path('/kaggle/input').exists() else []
DATA = hits[0].parent if hits else Path('../../dist/kaggle')

tracts = pd.read_csv(DATA / 'tracts.csv', dtype={'GEOID': str, 'NAME': str})
blocks = pd.read_csv(DATA / 'blocks_access.csv', dtype={'GEOID20': str, 'tract': str})
ranking = pd.read_csv(DATA / 'gap_ranking.csv', dtype={'GEOID': str, 'tract': str})
shapes = gpd.read_file(DATA / 'tracts.geojson')
print(f'{len(tracts)} tracts, {len(blocks):,} populated blocks, {blocks.POP20.sum():,} people (2020)')"""),
    ("md", """## How the data is shaped

- **Windows:** `weekday_day` (8am-5pm), `weekday_evening` (after 5pm) and `saturday`.
- **Wait assumption:** `planned` means the rider checks the schedule (a 5-minute first wait); this is the primary assumption. `walk_up` means the rider waits half the time between buses.
- In `blocks_access.csv`, `min_<window>_<wait>` is the minutes from a block to the nearest pantry open in that window, by walking or walking + bus. It's **blank when nothing is reachable within 30 minutes**.
- `high_need` in `tracts.csv` marks the top quarter of a need index (equal-weight z-scores of poverty, no-vehicle and SNAP rates, ACS 2020-24)."""),
    ("code", """WINDOWS = {'weekday_day': 'Weekday daytime', 'weekday_evening': 'Weekday evening', 'saturday': 'Saturday'}

def reach(b, window, wait='planned'):
    \"\"\"Population-weighted share of residents with an open pantry within 30 minutes.\"\"\"
    return np.average(b[f'min_{window}_{wait}'].notna(), weights=b.POP20)

high_need = set(tracts.loc[tracts.high_need, 'GEOID'])
hn_blocks = blocks[blocks.tract.isin(high_need)]
print(f'{len(high_need)} high-need tracts, {tracts.loc[tracts.high_need, "pop"].sum():,} people (ACS)')

headline = pd.DataFrame({
    'high-need tracts (planned)': [reach(hn_blocks, w) for w in WINDOWS],
    'high-need tracts (walk up)': [reach(hn_blocks, w, 'walk_up') for w in WINDOWS],
    'whole county (planned)': [reach(blocks, w) for w in WINDOWS],
}, index=WINDOWS.values())
headline.style.format('{:.0%}')"""),
    ("md", "The first column is the headline: **95% / 54% / 50%**. Walking up without checking the schedule makes it much worse, especially on Saturdays."),
    ("code", """# Palette: one blue (single series); text in neutral ink.
BLUE, INK, MUTED, SURFACE = '#256abf', '#0b0b0b', '#52514e', '#fcfcfb'
plt.rcParams.update({'figure.facecolor': SURFACE, 'axes.facecolor': SURFACE, 'font.size': 11,
                     'axes.edgecolor': MUTED, 'axes.labelcolor': MUTED, 'xtick.color': MUTED, 'ytick.color': MUTED})

s = headline['high-need tracts (planned)']
fig, ax = plt.subplots(figsize=(7, 2.6))
ax.barh(s.index[::-1], s.values[::-1], height=0.45, color=BLUE)
for y, v in enumerate(s.values[::-1]):
    ax.text(v + 0.015, y, f'{v:.0%}', va='center', color=INK)
ax.set_xlim(0, 1.08)
ax.xaxis.set_major_formatter(lambda x, _: f'{x:.0%}')
ax.spines[['top', 'right', 'left']].set_visible(False)
ax.tick_params(left=False)
ax.grid(axis='x', color='#e4e3df', linewidth=0.8); ax.set_axisbelow(True)
ax.set_title('Residents of high-need tracts who can reach an open pantry\\nwithin 30 minutes by walking and bus',
             loc='left', color=INK, fontsize=12)
plt.tight_layout(); plt.show()"""),
    ("md", """## Where the gaps are

Each map shades tracts by the share of residents who **can't** reach an open pantry within 30 minutes. Darker means more people cut off. High-need tracts are outlined in orange."""),
    ("code", """from matplotlib.colors import LinearSegmentedColormap

# Sequential blue ramp, light -> dark (validated reference palette, steps 100-700).
RAMP = LinearSegmentedColormap.from_list('blues', ['#cde2fb', '#86b6ef', '#3987e5', '#1c5cab', '#0d366b'])

g = shapes.merge(tracts.drop(columns=['NAME', 'label']), on='GEOID')
fig, axes = plt.subplots(1, 3, figsize=(15, 5.6))
for ax, (w, title) in zip(axes, WINDOWS.items()):
    g.assign(cut_off=1 - g[f'share_{w}_planned']).plot(
        column='cut_off', cmap=RAMP, vmin=0, vmax=1, ax=ax, edgecolor=SURFACE, linewidth=0.3,
        missing_kwds={'color': '#e4e3df'})
    g[g.high_need].boundary.plot(ax=ax, color='#eb6834', linewidth=1.2)
    ax.set_title(title, loc='left', color=INK); ax.set_axis_off()
sm = plt.cm.ScalarMappable(cmap=RAMP, norm=plt.Normalize(0, 1))
cb = fig.colorbar(sm, ax=axes, orientation='horizontal', fraction=0.04, pad=0.02, shrink=0.4)
cb.set_label('Share of residents with no open pantry within 30 min (orange outline = high-need tract)')
cb.ax.xaxis.set_major_formatter(lambda x, _: f'{x:.0%}')
plt.show()"""),
    ("md", "## The biggest gaps\n\nTracts ranked by people in poverty who can't reach an open pantry (ACS poverty count x the share without access). ACS margins of error are wide at tract level, so `poverty_rate_moe` is shown next to the rate."),
    ("code", """from IPython.display import display

cols = ['rank', 'tract', 'label', 'poverty_rate', 'poverty_rate_moe', 'no_vehicle_rate',
        'share_access', 'people_in_poverty_no_access']
for w, title in WINDOWS.items():
    print(title)
    display(ranking[ranking.window == w][cols].head(5).style.hide(axis='index')
            .format({c: '{:.0%}' for c in ['poverty_rate', 'poverty_rate_moe', 'no_vehicle_rate', 'share_access']}))"""),
    ("md", """## Things to try

- **Sensitivity:** swap `need` for `need_vehicle_heavy`, `need_poverty_200` or `need_poverty_only` and see which gap tracts survive.
- **Eligibility and stale listings:** compare `share_*` with `share_noelig_*` (ignoring service-area limits) and `share_unlisted_*` (counting pantries with no listed hours as open).
- **Every week vs some weeks:** `share_weekly_*` counts only pantries open every week in the window.
- **Siting:** using `blocks_access.csv`, find the point that would bring the most high-need residents within reach on a Saturday.

**Caveats:** pantry hours are self-reported and may be stale; bus times are scheduled, not real; walking uses straight-line distance x 1.3; block populations are 2020. See the dataset description for the full list."""),
]


def cell(i, kind, src):
    lines = src.splitlines(keepends=True)
    if kind == "md":
        return {"cell_type": "markdown", "id": f"c{i:02d}", "metadata": {}, "source": lines}
    return {"cell_type": "code", "id": f"c{i:02d}", "metadata": {}, "execution_count": None, "outputs": [],
            "source": lines}


nb = {"cells": [cell(i, k, s) for i, (k, s) in enumerate(CELLS)], "nbformat": 4, "nbformat_minor": 5,
      "metadata": {"kernelspec": {"name": "python3", "display_name": "Python 3", "language": "python"},
                   "language_info": {"name": "python"}}}
(HERE / "tulsa-pantry-gap-starter.ipynb").write_text(json.dumps(nb, indent=1))

meta = {"id": "taylorwburke/tulsa-pantry-gaps-reproduce-the-headline", "title": "Tulsa pantry gaps: reproduce the headline",
        "code_file": "tulsa-pantry-gap-starter.ipynb", "language": "python", "kernel_type": "notebook",
        "is_private": False, "enable_gpu": False, "enable_internet": False,
        "dataset_sources": ["taylorwburke/tulsa-pantry-gap"], "competition_sources": [], "kernel_sources": []}
(HERE / "kernel-metadata.json").write_text(json.dumps(meta, indent=2))
print("wrote", HERE / "tulsa-pantry-gap-starter.ipynb")
