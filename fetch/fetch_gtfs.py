"""MetroLink Tulsa (MTTA) static GTFS feed, linked from metrolinkok.org/open-data/.

MTTA changes schedules about three times a year (April, August, November); the
feed's feed_info.txt states its valid date range, which build_data.py checks.
"""
from common import download

download("gtfs", "mtta_gtfs.zip", "https://tulsa.rideralerts.com/InfoPoint/GTFS-Zip.ashx")
