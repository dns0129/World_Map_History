"""SQLite database of historical province-level divisions and de facto control, 1939-1945.

Only divisions in force at the time are stored (see ww2_histunits.py), dissolved to the
province level (ww2_provinces.py). Geometry is GeoJSON text (EPSG:4326), simplified for
size; full-detail geometry stays in work/ww2/. Tables are documented in ww2/README.md.
"""
import datetime as dt
import json
import sqlite3

import numpy as np
import pandas as pd
from shapely.geometry import mapping, shape

from common import ROOT
from ww2_common import SNAPSHOTS, WW2_DB, WW2_WORK

TOL = 0.006  # degrees (~600 m) for stored geometry
ND = 3  # decimals kept (~110 m)

SOURCES = [
    ("ohm", "OpenHistoricalMap", "OpenHistoricalMap contributors, planet file of 2026-10-03; administrative boundary "
     "relations with start_date/end_date in force on each snapshot date.", "https://www.openhistoricalmap.org/",
     "CC0", "Dated administrative units worldwide (admin_level 3-6)"),
    ("ahcb", "Atlas of Historical County Boundaries", "Newberry Library, Dr. William M. Scholl Center (2010). Via R package "
     "USAboundariesData (rOpenSci).", "https://github.com/ropensci/USAboundariesData", "CC0",
     "United States counties with exact validity dates"),
    ("sinica_taiwan", "Taiwan 1930 gun/shi", "Academia Sinica, Center for GIS, Japanese-era administrative boundaries; "
     "via K. Lawson, japanese-empire-student-map.", "https://github.com/kmlawson/japanese-empire-student-map",
     "CC BY-NC-SA 4.0", "Taiwan districts and prefectures (1930)"),
    ("nikh", "NIKH Modern Geographic Information DB", "National Institute of Korean History, 근대지리정보 (1914-1926 "
     "place records); via K. Lawson.", "https://hgis.history.go.kr/", "KOGL (attribution)",
     "Korean county/city (gun/bu) boundaries reconstructed from township office and facility points"),
    ("lawson", "An interactive map of the Japanese Empire", "Lawson, K. Georeferencing and tracing of East and South-East "
     "Asian historical maps (Burma 1931, DEI 1941, Indochina, Philippines 1939, Korea provinces, Manchukuo, Mengjiang, "
     "Kwantung, occupied China 1942, CCP base areas 1941-42, Indian princely states 1931).",
     "https://github.com/kmlawson/japanese-empire-student-map", "CC0 (tracing); underlying sources vary",
     "East and South-East Asian historical divisions and occupation layers"),
    ("enp_china", "ENP-China provincial boundaries", "Elites, Networks and Power in Modern China, Aix-Marseille University; "
     "adjusted by K. Lawson.", "https://www.enp-china.eu/", "CC BY 4.0", "Republican Chinese provinces 1928-1945"),
    ("cshapes2", "CShapes 2.0", "Schvitz, G. et al. (2022). Mapping the International System, 1886-2019. JCR 66(1).",
     "https://icr.ethz.ch/data/cshapes/", "CC BY-NC-SA 4.0",
     "Country and colony borders on each date; whole-unit areas where no subdivision layer exists"),
    ("geoboundaries", "geoBoundaries gbOpen", "Runfola, D. et al. (2020) geoBoundaries: A global database of political "
     "administrative boundaries. PLoS ONE 15(4): e0231866.", "https://github.com/wmgeolab/geoBoundaries",
     "CC BY 4.0 (per country, see metadata)",
     "Outlines of Japanese prefectures and French departements (same units as in 1939), land outline, and the "
     "present-day region names the control rules refer to"),
    ("ghspop", "GHS-POP R2023A", "European Commission JRC (2023).", "https://human-settlement.emergency.copernicus.eu/",
     "CC BY 4.0", "Spatial pattern for population estimates (1975 grid)"),
    ("curated", "Curated control rules", "Compiled for this database from standard histories of the war "
     "(curated/ww2_region_control.csv, curated/control_events.csv).", "curated/", "CC0",
     "De facto control on each snapshot date"),
]

SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE sources (source_id TEXT PRIMARY KEY, name TEXT, citation TEXT, url TEXT, license TEXT, used_for TEXT);
CREATE TABLE snapshots (snapshot TEXT PRIMARY KEY, title_zh TEXT, title_en TEXT, n_admin_units INTEGER,
  population_est REAL, pop_allied REAL, pop_axis REAL, pop_neutral REAL, pop_contested REAL);
CREATE TABLE admin_units (
  admin_key INTEGER PRIMARY KEY, admin_id TEXT UNIQUE, name TEXT, name_zh TEXT, name_en TEXT,
  tier INTEGER, tier_zh TEXT, tier_en TEXT, kind TEXT, basis TEXT, source TEXT, note TEXT,
  start_date TEXT, end_date TEXT, partial INTEGER, parent TEXT, parent_zh TEXT, grandparent TEXT,
  ohm_level INTEGER, wikidata TEXT, merged_units INTEGER, snapshots TEXT, area_km2 REAL, label_lon REAL,
  label_lat REAL, geometry TEXT);
CREATE TABLE pieces (piece_key INTEGER PRIMARY KEY, piece_id TEXT UNIQUE, admin_key INTEGER, area_km2 REAL,
  geometry TEXT);
CREATE TABLE unit_snapshot (snapshot TEXT, unit_id INTEGER, unit_gwcode INTEGER, unit_name_en TEXT,
  unit_name_zh TEXT, unit_status TEXT, sovereign_gwcode INTEGER, sovereign_name_en TEXT, sovereign_name_zh TEXT,
  partial_control_events TEXT, PRIMARY KEY (snapshot, unit_id)) WITHOUT ROWID;
CREATE TABLE controls (control_id INTEGER PRIMARY KEY, controller_gwcode INTEGER, controller_name_en TEXT,
  controller_name_zh TEXT, controller_detail_en TEXT, controller_detail_zh TEXT, control_type TEXT,
  control_source TEXT, control_confidence TEXT, bloc TEXT);
CREATE TABLE pop_methods (pop_method_id INTEGER PRIMARY KEY, pop_method TEXT);
CREATE TABLE piece_snapshot (
  snapshot TEXT, piece_key INTEGER, unit_id INTEGER, control_id INTEGER, control_split INTEGER,
  area_km2 REAL, population_est INTEGER, pop_method_id INTEGER,
  PRIMARY KEY (snapshot, piece_key)) WITHOUT ROWID;
CREATE VIEW snapshot_full AS
  SELECT s.snapshot, p.piece_id, a.admin_id, a.name, a.name_zh, a.tier, a.tier_zh, a.kind, a.basis, a.parent,
    a.parent_zh, s.unit_id, u.unit_gwcode, u.unit_name_en, u.unit_name_zh, u.unit_status,
    u.sovereign_gwcode, u.sovereign_name_en, u.sovereign_name_zh, c.controller_gwcode, c.controller_name_en,
    c.controller_name_zh, c.controller_detail_en, c.controller_detail_zh, c.control_type, c.control_source,
    c.control_confidence, c.bloc, s.control_split, u.partial_control_events, s.area_km2, s.population_est, m.pop_method
  FROM piece_snapshot s JOIN pieces p USING (piece_key) JOIN admin_units a USING (admin_key)
  JOIN unit_snapshot u USING (snapshot, unit_id) JOIN controls c USING (control_id)
  JOIN pop_methods m USING (pop_method_id);
CREATE TABLE control_rules (row INTEGER PRIMARY KEY, snapshots TEXT, iso3 TEXT, field TEXT, match TEXT,
  controller_name TEXT, controller_name_zh TEXT, controller_gwcode INTEGER, control_type TEXT, confidence TEXT, note TEXT);
CREATE TABLE control_events (event_id TEXT PRIMARY KEY, unit_name TEXT, unit_gwcode INTEGER, start_date TEXT,
  end_date TEXT, scope TEXT, control_type TEXT, controller_name TEXT, controller_name_zh TEXT, controller_gwcode INTEGER,
  note TEXT);
CREATE INDEX ps_piece ON piece_snapshot(piece_key);
CREATE INDEX pieces_admin ON pieces(admin_key);
CREATE INDEX admin_parent ON admin_units(parent);
"""


def gj(g, tol=TOL, nd=ND):
    g = g.simplify(tol, preserve_topology=True)

    def r(c):
        if isinstance(c, (list, tuple)) and c and isinstance(c[0], (int, float)):
            return [round(c[0], nd), round(c[1], nd)]
        return [r(x) for x in c]
    m = mapping(g)
    return json.dumps({"type": m["type"], "coordinates": r(m["coordinates"])}, separators=(",", ":"))


def v(x):
    return None if (isinstance(x, float) and np.isnan(x)) else x


def main():
    if WW2_DB.exists():
        WW2_DB.unlink()
    con = sqlite3.connect(WW2_DB)
    con.executescript(SCHEMA)
    df = pd.concat([pd.read_csv(WW2_WORK / f"prov_snapshot_{s[0]}.csv", low_memory=False) for s in SNAPSHOTS],
                   ignore_index=True).drop_duplicates(["snapshot", "piece_id"])
    pgeom = {}
    for s in SNAPSHOTS:
        for f in json.load(open(WW2_WORK / f"prov_split_{s[0]}.geojson"))["features"]:
            pgeom[f["properties"]["piece_id"]] = shape(f["geometry"])
    hist = pd.read_csv(WW2_WORK / "prov_units.csv", low_memory=False)
    hgeom = {f["properties"]["unit_id"]: shape(f["geometry"])
             for f in json.load(open(WW2_WORK / "prov_units.geojson"))["features"]}

    meta = {
        "title": "Historical province-level divisions and de facto control, 1939-1945",
        "snapshots": ";".join(s[0] for s in SNAPSHOTS),
        "crs": "EPSG:4326", "geometry": f"GeoJSON text simplified at {TOL} deg, coordinates rounded to {ND} decimals",
        "main_view": "snapshot_full (one row per piece and snapshot, all attributes)",
        "admin_units": "province-level divisions in force on each date: 3 province (counties and districts of the "
                       "time dissolved into the province above them), 4 region (no province level known), 5 whole "
                       "country or colony (no subdivision data), 6 territory not drawn by CShapes",
        "pieces": "a province, cut where a border runs through it: where it lies in two political units or where "
                  "the controller changes (front lines, annexations, occupation zones)",
        "population": "estimate: GHS-POP 1975 pattern scaled to each political unit's population for the snapshot "
                      "year, computed on the finer historical units and summed per province piece",
        "built_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    con.executemany("INSERT INTO meta VALUES (?,?)", meta.items())
    con.executemany("INSERT INTO sources VALUES (?,?,?,?,?,?)", SOURCES)
    for snap, tzh, ten in SNAPSHOTS:
        d = df[df.snapshot == snap]
        b = d.groupby("bloc").population_est.sum()
        con.execute("INSERT INTO snapshots VALUES (?,?,?,?,?,?,?,?,?)",
                    (snap, tzh, ten, int(d.admin_id.nunique()), float(d.population_est.sum()), float(b.get("allied", 0)),
                     float(b.get("axis", 0)), float(b.get("neutral", 0)), float(b.get("contested", 0))))

    used = set(df.admin_id)
    akey = {aid: i + 1 for i, aid in enumerate(a for a in hist.unit_id if a in used)}
    rows = []
    for h in hist.itertuples():
        if h.unit_id not in used:
            continue
        rows.append((akey[h.unit_id], h.unit_id, v(h.name), v(h.name_zh), v(h.name_en), int(h.tier), h.tier_zh,
                     h.tier_en, v(h.kind), h.basis, h.source, v(h.note), v(h.start), v(h.end), int(bool(h.partial)),
                     v(h.parent), v(h.parent_zh), v(h.grandparent),
                     None if v(h.ohm_level) is None else int(h.ohm_level), v(h.wikidata),
                     int(v(h.merged_units) or 0), h.snapshots, h.area_km2, h.label_lon, h.label_lat, gj(hgeom[h.unit_id])))
    con.executemany("INSERT INTO admin_units VALUES (" + ",".join("?" * 26) + ")", rows)
    pids = sorted(set(df.piece_id))
    pkey = {p: i + 1 for i, p in enumerate(pids)}
    parea = df.groupby("piece_id").area_km2.max().to_dict()
    padmin = df.groupby("piece_id").admin_id.first().to_dict()
    con.executemany("INSERT INTO pieces VALUES (?,?,?,?,?)",
                    [(pkey[p], p, akey[padmin[p]], parea[p], gj(pgeom[p]) if p in pgeom else None) for p in pids])
    ucols = ["unit_gwcode", "unit_name_en", "unit_name_zh", "unit_status", "sovereign_gwcode", "sovereign_name_en",
             "sovereign_name_zh", "partial_control_events"]
    df.drop_duplicates(["snapshot", "unit_id"])[["snapshot", "unit_id"] + ucols] \
        .to_sql("unit_snapshot", con, if_exists="append", index=False)
    ccols = ["controller_gwcode", "controller_name_en", "controller_name_zh", "controller_detail_en",
             "controller_detail_zh", "control_type", "control_source", "control_confidence", "bloc"]
    codes, _ = pd.factorize(df[ccols].fillna("").astype(str).agg("\x1f".join, axis=1))
    df["control_id"] = codes + 1
    df.drop_duplicates("control_id").sort_values("control_id")[["control_id"] + ccols] \
        .to_sql("controls", con, if_exists="append", index=False)
    mcodes, methods = pd.factorize(df.pop_method)
    df["pop_method_id"] = mcodes + 1
    con.executemany("INSERT INTO pop_methods VALUES (?,?)", [(i + 1, m) for i, m in enumerate(methods)])
    df["piece_key"] = df.piece_id.map(pkey)
    df[["snapshot", "piece_key", "unit_id", "control_id", "control_split", "area_km2", "population_est",
        "pop_method_id"]].to_sql("piece_snapshot", con, if_exists="append", index=False)
    rules = pd.read_csv(ROOT / "curated" / "ww2_region_control.csv")
    rules.insert(0, "row", range(2, len(rules) + 2))
    rules.to_sql("control_rules", con, if_exists="append", index=False)
    pd.read_csv(ROOT / "curated" / "control_events.csv").to_sql("control_events", con, if_exists="append", index=False)
    con.commit()
    con.execute("VACUUM")
    con.close()
    print(WW2_DB, f"{WW2_DB.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
