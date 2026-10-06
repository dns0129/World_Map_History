#!/bin/sh
# Rebuild the whole database from scratch.
#   pip install shapely pyproj rasterio numpy scipy pillow matplotlib pyshp pandas pyreadr osmium
#   ./build_all.sh            (add "hyde" to also download HYDE 3.5 where reachable)
set -e
cd "$(dirname "$0")/scripts"
python3 fetch_sources.py ghs ne terrain git "$@"
python3 build_country_series.py
python3 build_base_grids.py
python3 build_subnational.py
python3 build_terrain.py
python3 build_yearly.py
python3 build_database.py
python3 export_years.py
python3 render_maps.py
python3 verify_database.py

# 1900-1991 historical administrative divisions, control databases and interactive maps
#   (also needs: pip install osmium)
python3 ww2_fetch.py          # geoBoundaries, US county atlas, K. Lawson's East Asia layers
python3 ww2_ohm.py            # OpenHistoricalMap planet -> administrative areas dated 1900-1991
python3 ww2_reference.py      # present-day reference names for the control rules (internal)
# the three sets of dates (1939-45, 1900-34, 1946-91), the 2026 tab and the maps, each step and date a job
# of its own: run within the memory limit, skipped when its inputs are unchanged, so that running it again
# after an interruption carries on where it stopped (see the docstring of scripts/pipeline.py)
python3 pipeline.py
