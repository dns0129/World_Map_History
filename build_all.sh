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
# one process per date, as many at a time as fit in the memory available (GB per process first; WW2_POOL
# fixes the number); {} stands for the date
per_date() {
  gb=$1; shift
  ds=$(python3 -c "from ww2_common import SNAP_DATES; print(*SNAP_DATES)")
  printf "%s\n" $ds | xargs -P "$(python3 ww2_common.py jobs "$(echo $ds | wc -w)" "$gb")" -I{} "$@"
}
# the steps of one set of dates (WW2_SET): divisions in force on each date, control and population,
# counties and districts dissolved into their provinces (borders still cut them), database, coverage
build_set() {
  per_date 3 python3 ww2_histunits.py --part {}
  python3 ww2_histunits.py --merge
  per_date 4.5 python3 ww2_snapshots.py {}
  python3 ww2_provinces.py      # dates whose inputs are unchanged are read from work/<set>/prov_part_<date>.pkl
  python3 ww2_database.py
  python3 ww2_coverage.py
}
export WW2_SET=ww2
build_set                     # db/ww2_divisions_1939_1945.sqlite (six dates of the war)
export WW2_SET=early
build_set                     # db/divisions_1900_1934.sqlite (1900-08-14, 1914-08-04, 1918-11-11, 1934-10-16)
export WW2_SET=postwar
build_set                     # db/divisions_1946_1991.sqlite (1946-06-26 ... 1991-12-26)
unset WW2_SET
python3 ww2_relief.py         # shaded relief sheets for the maps (Terrarium elevation tiles)
python3 modern_2026.py        # the 2026 tab: present-day provinces, control and population
python3 ww2_webmap.py
python3 ww2_html.py
