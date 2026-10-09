"""Check the map data of every date, and for the dates of added_dates.py the database joins, date validity and
the historical facts each date lists in its checks."""
import json
import sqlite3

from shapely.geometry import Point, shape

from add_snapshots import DATA, MARKER, decode_geo, static_hash, unpack
from added_dates import GROUPS
from ww2_common import DATABASES


def check_map(static, index):
    """admin.bin as ww2_webmap.py wrote it, with the additions after it; every date's data file and outlines."""
    marker = json.loads(MARKER.read_text())
    # what ww2_webmap.py wrote is unchanged: admin.bin cut back to the recorded lengths has the recorded checksum
    base = json.loads(json.dumps(static))
    base["n"] = marker["admins"]
    for col in ("admin_id", "tier", "partial", "merged", "area", "label"):
        base[col] = base[col][:marker["admins"]]
    for key, col in base["cols"].items():
        col["idx"], col["lut"] = col["idx"][:marker["admins"]], col["lut"][:marker["luts"][key]]
    base["feature_admin"] = base["feature_admin"][:marker["features"]]
    assert static_hash(base) == marker["sha256"]
    assert static["n"] == len(static["admin_id"]) == len(set(static["admin_id"]))
    for col in ("tier", "partial", "merged", "area", "label"):
        assert len(static[col]) == static["n"], col
    for col in static["cols"].values():
        assert len(col["idx"]) == static["n"]
        assert all(0 <= i < len(col["lut"]) for i in col["idx"])
    assert len({s["snapshot"] for s in index["snapshots"]}) == len(index["snapshots"])
    docs = {}
    for s in index["snapshots"]:
        snap = s["snapshot"]
        doc = docs[snap] = json.loads((DATA / f"snap-{snap}.json").read_text())
        n = len(doc["feature"])
        for col in ("unit", "country", "nation", "bloc", "conf", "ctrl_gw", "split", "area", "pop"):
            assert len(doc[col]) == n, (snap, col)
        assert len(set(doc["feature"])) == n
        assert all(0 <= v < len(static["feature_admin"]) for v in doc["feature"])
        assert all(v == -1 or v in set(doc["units_active"]) for v in doc["unit"])
        assert all(0 <= v < len(doc["countries"]) for v in doc["country"])
        assert all(0 <= v < len(doc["nations"]) for v in doc["nation"])
        assert sorted(v[8] for v in doc["countries"]) == list(range(len(doc["countries"])))
        assert all(0 <= v < static["n"] for v in doc["admin_active"])
        assert {static["feature_admin"][f] for f in doc["feature"]} <= set(doc["admin_active"])
        # the date's outlines: its divisions (those its base date's file lacks), cut pieces, units and control areas
        n_geo = len(decode_geo(unpack(DATA / f"geo-{snap}.bin"))[0])
        own = doc.get("admin_geo", doc["admin_active"])
        assert n_geo == len(own) + len(doc["geo_feature"]) + len(doc["units_active"]) + len(doc["countries"]), snap
        if "admin_base" in doc:  # the rest of the outlines come from the base date's file
            base = json.loads((DATA / f"snap-{doc['admin_base']}.json").read_text())
            assert set(doc["admin_active"]) <= set(own) | set(base["admin_active"]), snap
        assert sum(doc["pop"]) == sum(doc["bloc_pop"].values()) == s["population"]
        assert sum(c[5] for c in doc["countries"]) == sum(n[6] for n in doc["nations"]) == sum(doc["pop"])
        for col, vals in doc["rows"].items():
            assert len(vals) == n and all(0 <= v < len(doc["luts"][col]) for v in vals)
    return docs


def check_date(con, s, doc):
    """One added date: database rows against the map data, dates in force, and the date's own checks."""
    snap, checks = s.date, s.checks
    n = len(doc["feature"])
    db_rows = list(con.execute("SELECT s.*,p.geometry AS pg,a.geometry AS ag FROM snapshot_full s "
                               "JOIN pieces p USING(piece_id) JOIN admin_units a USING(admin_id) WHERE s.snapshot=?", (snap,)))
    assert len(db_rows) == n == con.execute("SELECT COUNT(*) FROM piece_snapshot WHERE snapshot=?", (snap,)).fetchone()[0]
    assert sum(r["population_est"] for r in db_rows) == sum(doc["pop"])
    assert con.execute("SELECT COUNT(*) FROM admin_units a JOIN snapshot_full s USING(admin_id) WHERE s.snapshot=? "
                       "AND ((a.start_date IS NOT NULL AND a.start_date>?) OR (a.end_date IS NOT NULL AND a.end_date<?))",
                       (snap, snap, snap)).fetchone()[0] == 0
    assert all(r["population_est"] >= 0 and r["area_km2"] > 0 for r in db_rows)
    for gw, expected in checks.get("blocs", {}).items():
        blocs = {r["bloc"] for r in db_rows if r["controller_gwcode"] == gw}
        assert blocs == {expected}, (snap, gw, blocs)
    lookup = [(shape(json.loads(r["pg"] or r["ag"])), r) for r in db_rows]
    for place, lon, lat, gw in checks.get("places", []):
        hits = [r for geom, r in lookup if geom.covers(Point(lon, lat))]
        assert len(hits) == 1 and hits[0]["controller_gwcode"] == gw, \
            (snap, place, [(r["controller_gwcode"], r["admin_id"]) for r in hits])
    city_names = [c[0] for c in doc["cities"]]
    assert len({(c[1], c[2]) for c in doc["cities"]}) == len(doc["cities"]), (snap, "duplicate city")
    for name in checks.get("cities_in", []):
        assert name in city_names, (snap, name)
    for name in checks.get("cities_out", []):
        assert name not in city_names, (snap, name)
    for gw, expected in checks.get("controller_zh", {}).items():
        assert {r["controller_name_zh"] for r in db_rows if r["controller_gwcode"] == gw} == expected, (snap, gw)
    assert (DATA.parent / f"{snap}.html").exists()
    print(snap, n, "pieces; database, date validity, map references and historical checks passed")


def main():
    static = json.loads(unpack(DATA / "admin.bin"))
    index = json.loads((DATA / "index.json").read_text())
    docs = check_map(static, index)
    for set_name in dict.fromkeys(g.set for g in GROUPS):
        con = sqlite3.connect(f"file:{DATABASES[set_name]}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        for group in GROUPS:
            if group.set == set_name:
                for s in group.snapshots:
                    assert s.date in docs, (s.date, "not in index.json")
                    check_date(con, s, docs[s.date])
        con.close()
    print("All map references passed; admin.bin as ww2_webmap.py wrote it, with the added dates after it")


if __name__ == "__main__":
    main()
