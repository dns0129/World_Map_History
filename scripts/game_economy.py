"""Write game/economy.json: GDP per capita (2011 international dollars) of the historical units in the years of the
map's dates, for the game's income (game/rules.js). Read from db/world_history_1900_2000.sqlite.

  years  the years (each date's year; 2000 stands for 2026, the last year of the database)
  world  world GDP per capita in each year
  unit   per unit name (unit_year.name_zh, as the map data's unit_name_zh): the value in each year, 0 where the unit
         does not exist
  iso    per modern country code (country_series.code, as the 2026 map's "M:<code>" keys): the value in each year
"""
import json
import sqlite3

from common import ROOT
from added_dates import SNAPSHOTS_ADDED
from ww2_common import SNAPSHOTS_EARLY, SNAPSHOTS_POSTWAR, SNAPSHOTS_WW2

DB = ROOT / "db" / "world_history_1900_2000.sqlite"
OUT = ROOT / "game" / "economy.json"


def main():
    dates = SNAPSHOTS_EARLY + SNAPSHOTS_ADDED + SNAPSHOTS_WW2 + SNAPSHOTS_POSTWAR
    years = sorted({int(d[:4]) for d, _, _ in dates} | {2000})
    con = sqlite3.connect(DB)
    q = ",".join("?" * len(years))
    world = dict(con.execute(f"SELECT year, SUM(gdp_2011usd) / SUM(population) FROM unit_year WHERE year IN ({q}) GROUP BY year",
                             years))
    unit, iso = {}, {}
    for name, year, gdp, pop in con.execute(
            f"SELECT name_zh, year, SUM(gdp_2011usd), SUM(population) FROM unit_year WHERE year IN ({q}) AND population > 0 "
            "GROUP BY name_zh, year", years):
        unit.setdefault(name, [0] * len(years))[years.index(year)] = round(gdp / pop)
    for code, year, v in con.execute(f"SELECT code, year, gdppc_2011usd FROM country_series WHERE year IN ({q}) "
                                     "AND gdppc_2011usd > 0", years):
        iso.setdefault(code, [0] * len(years))[years.index(year)] = round(v)
    out = {"years": years, "world": [round(world[y]) for y in years], "unit": dict(sorted(unit.items())),
           "iso": dict(sorted(iso.items()))}
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")) + "\n")
    print(OUT, len(unit), "units", len(iso), "countries")


if __name__ == "__main__":
    main()
