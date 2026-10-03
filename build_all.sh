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

# 1939-1945 historical administrative divisions, control database and interactive maps
#   (also needs: pip install osmium)
python3 ww2_fetch.py          # geoBoundaries, US county atlas, K. Lawson's East Asia layers
python3 ww2_ohm.py            # OpenHistoricalMap planet -> dated administrative areas
python3 ww2_reference.py      # present-day reference names for the control rules (internal)
python3 ww2_histunits.py      # divisions in force on each of the six dates
printf "%s\n" 1939-09-01 1940-07-01 1941-12-07 1942-11-01 1944-06-06 1945-09-02 | xargs -P 3 -I{} python3 ww2_snapshots.py {}
python3 ww2_provinces.py      # counties and districts dissolved into their provinces; borders still cut them
python3 ww2_database.py
python3 ww2_coverage.py
python3 ww2_webmap.py
python3 ww2_html.py
