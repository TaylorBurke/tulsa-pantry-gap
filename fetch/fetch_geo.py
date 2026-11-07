"""Census geography: tract outlines, 2020 blocks with population (trip origins),
places (city names) and roads (tract naming)."""
from common import download

# 2024 cartographic-boundary tracts (2020 tract definitions, clipped to shoreline).
download("tiger", "cb_2024_40_tract_500k.zip",
         "https://www2.census.gov/geo/tiger/GENZ2024/shp/cb_2024_40_tract_500k.zip")
# 2020 tabulation blocks for Oklahoma; the TIGER file carries POP20 and HOUSING20.
download("tiger", "tl_2020_40_tabblock20.zip",
         "https://www2.census.gov/geo/tiger/TIGER2020/TABBLOCK20/tl_2020_40_tabblock20.zip")
# Incorporated places and CDPs (Tulsa, Broken Arrow, Sand Springs...) to name tracts.
download("tiger", "tl_2024_40_place.zip",
         "https://www2.census.gov/geo/tiger/TIGER2024/PLACE/tl_2024_40_place.zip")
# ZIP code tabulation areas and school districts: some pantries only serve listed
# ZIPs or school districts (data/manual/service_areas.csv).
download("tiger", "cb_2020_us_zcta520_500k.zip",
         "https://www2.census.gov/geo/tiger/GENZ2020/shp/cb_2020_us_zcta520_500k.zip")
download("tiger", "tl_2024_40_unsd.zip",
         "https://www2.census.gov/geo/tiger/TIGER2024/UNSD/tl_2024_40_unsd.zip")
# Tulsa County roads, to label tracts by their nearest arterial intersection.
download("tiger", "tl_2024_40143_roads.zip",
         "https://www2.census.gov/geo/tiger/TIGER2024/ROADS/tl_2024_40143_roads.zip")
