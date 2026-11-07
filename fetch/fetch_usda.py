"""USDA ERS Food Access Research Atlas, 2025 SNAP-authorized Retailer Access Map (SRAM).

SRAM (updated 7/27/2026) replaces the 2019 Large Retailer Access Map (formerly FARA)
and uses 2020 census tracts, which match the ACS tracts.
"""
from common import download

download("usda_sram", "2025-sram-data.zip",
         "https://www.ers.usda.gov/media/29395/2025-snap-authorized-retailer-access-map-sram-data.zip")
