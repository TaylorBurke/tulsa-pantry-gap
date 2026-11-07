# Tulsa Pantry Gap Map: one command rebuilds everything from the raw downloads.
#   make           fetch what's missing, run the analysis, run the checks, build the site
#   make refresh   re-download every source, then rebuild
#   make validate  optional: R5 router cross-check (needs Java 21+, ~170 MB OSM extract)
#   make serve     preview at http://localhost:8765
#   make smoke     headless browser test of the classic page (needs `make serve` running)
#   make audit     check the Food Finder listings for data problems -> reports/ (git-ignored)
#   make brief     print the two-page brief (site/brief/) to PDF with headless Chrome
PY := uv run --frozen python -W ignore
A := cd analysis &&

.PHONY: all fetch refresh analysis check site brief audit validate serve smoke clean

all: fetch analysis check site

fetch:
	cd fetch && $(PY) fetch_acs.py && $(PY) fetch_geo.py && $(PY) fetch_usda.py && $(PY) fetch_gtfs.py && $(PY) fetch_pantries.py

refresh:
	cd fetch && REFRESH=1 $(PY) fetch_acs.py && REFRESH=1 $(PY) fetch_geo.py && REFRESH=1 $(PY) fetch_usda.py && REFRESH=1 $(PY) fetch_gtfs.py && REFRESH=1 $(PY) fetch_pantries.py
	$(MAKE) analysis check site

analysis:
	$(A) $(PY) need.py && $(PY) pantries.py && $(PY) transit.py && $(PY) access.py && $(PY) gap.py && $(PY) siting.py

check:
	$(A) $(PY) checks.py

site:
	$(A) $(PY) story.py
	$(PY) build_site.py
	$(PY) build_board.py
	$(PY) build_brief.py

brief: site
	node tools/pdf.mjs site/brief/index.html site/brief/tulsa-pantry-gap-brief.pdf 2

audit:
	$(PY) tools/listing_audit.py
	node tools/pdf.mjs reports/food-finder-audit.html reports/food-finder-audit.pdf

validate:
	cd fetch && $(PY) fetch_osm.py
	$(A) uv run --frozen --group validate python -W ignore validate_r5.py
	$(MAKE) site

serve:
	cd site && python3 -m http.server 8765

smoke:
	node tools/smoke.mjs http://localhost:8765/classic/ /tmp

clean:
	rm -f data/derived/*.parquet data/derived/*.npz data/derived/tracts_access.csv site/data/*.geojson site/data/places.json
