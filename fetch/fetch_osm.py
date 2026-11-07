"""OpenStreetMap extract for Oklahoma (Geofabrik), used only by analysis/validate_r5.py.

The main pipeline does not need it; `make validate` fetches it (~170 MB).
OSM data: (c) OpenStreetMap contributors, ODbL.
"""
from common import download

download("osm", "oklahoma-latest.osm.pbf",
         "https://download.geofabrik.de/north-america/us/oklahoma-latest.osm.pbf")
