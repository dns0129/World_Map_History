"""Check database joins, date validity, map references and WWI event-day facts."""
import hashlib
import json
import sqlite3

from shapely.geometry import Point, shape

from common import DB_DIR
from ww1_maps import DATA, DATABASE, DATES, MARKER, decode_geo


def main():
    con = sqlite3.connect(f"file:{DATABASE}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    static = json.loads((DATA / "admin.json").read_text())
    marker = json.loads(MARKER.read_text())
    counts = {}
    for name in ("geo", "geo-admin", "geo-units", "geo-ctrl"):
        raw = (DATA / f"{name}.bin").read_bytes()
        assert hashlib.sha256(raw[:marker["bytes"][name]]).hexdigest() == marker["sha256"][name], name
        counts[name] = len(decode_geo(raw)[0])
    assert static["n"] == counts["geo-admin"] == len(static["admin_id"])
    assert len(static["feature_admin"]) == counts["geo"]
    for col in ("tier", "partial", "merged", "area", "label"):
        assert len(static[col]) == static["n"], col
    for col in static["cols"].values():
        assert len(col["idx"]) == static["n"]
        assert all(0 <= i < len(col["lut"]) for i in col["idx"])
    index = json.loads((DATA / "index.json").read_text())
    assert len({s["snapshot"] for s in index["snapshots"]}) == len(index["snapshots"])
    assert DATES <= {s["snapshot"] for s in index["snapshots"]}
    for s in index["snapshots"]:
        snap = s["snapshot"]
        doc = json.loads((DATA / f"snap-{snap}.json").read_text())
        n = len(doc["feature"])
        for col in ("unit", "country", "nation", "bloc", "conf", "ctrl_gw", "split", "area", "pop"):
            assert len(doc[col]) == n, (snap, col)
        assert len(set(doc["feature"])) == n
        assert all(0 <= v < counts["geo"] for v in doc["feature"])
        assert all(-1 <= v < counts["geo-units"] for v in doc["unit"])
        assert all(0 <= v < len(doc["countries"]) for v in doc["country"])
        assert all(0 <= v < len(doc["nations"]) for v in doc["nation"])
        assert all(0 <= v[8] < counts["geo-ctrl"] for v in doc["countries"])
        assert all(0 <= v < static["n"] for v in doc["admin_active"])
        assert sum(doc["pop"]) == sum(doc["bloc_pop"].values()) == s["population"]
        assert sum(c[5] for c in doc["countries"]) == sum(n[6] for n in doc["nations"]) == sum(doc["pop"])
        for col, vals in doc["rows"].items():
            assert len(vals) == n and all(0 <= v < len(doc["luts"][col]) for v in vals)
        if snap not in DATES:
            continue
        db_rows = list(con.execute("SELECT s.*,p.geometry AS pg,a.geometry AS ag FROM snapshot_full s "
                                   "JOIN pieces p USING(piece_id) JOIN admin_units a USING(admin_id) WHERE s.snapshot=?", (snap,)))
        assert len(db_rows) == n == con.execute("SELECT COUNT(*) FROM piece_snapshot WHERE snapshot=?", (snap,)).fetchone()[0]
        assert sum(r["population_est"] for r in db_rows) == sum(doc["pop"])
        assert con.execute("SELECT COUNT(*) FROM admin_units a JOIN snapshot_full s USING(admin_id) WHERE s.snapshot=? "
                           "AND ((a.start_date IS NOT NULL AND a.start_date>?) OR (a.end_date IS NOT NULL AND a.end_date<?))",
                           (snap, snap, snap)).fetchone()[0] == 0
        assert all(r["population_est"] >= 0 and r["area_km2"] > 0 for r in db_rows)
        for gw, expected in [(325, "allied"), (255, "axis"), (300, "axis"), (710, "neutral"),
                             (2, "allied" if snap.startswith("1917") else "neutral"),
                             (355, "neutral" if snap.startswith("1915") else "axis"),
                             (235, "neutral" if snap.startswith("1915") else "allied")]:
            blocs = {r["bloc"] for r in db_rows if r["controller_gwcode"] == gw}
            assert blocs == {expected}, (snap, gw, blocs)
        lookup = [(shape(json.loads(r["pg"] or r["ag"])), r) for r in db_rows]

        def at(lon, lat):
            point = Point(lon, lat)
            return [r for geom, r in lookup if geom.covers(point)]

        for place, lon, lat, gw in [("Paris", 2.35, 48.86, 220), ("Berlin", 13.4, 52.52, 255),
                                     ("Beijing", 116.4, 39.9, 710), ("Riga", 24.11, 56.95, 365),
                                     ("Basra", 47.78, 30.51, 200), ("Istanbul", 28.97, 41.04, 640),
                                     ("Warsaw", 21.01, 52.23, 365 if snap.startswith("1915") else 255)]:
            hits = at(lon, lat)
            assert len(hits) == 1 and hits[0]["controller_gwcode"] == gw, (snap, place, [(r["controller_gwcode"],r["admin_id"]) for r in hits])
        city_names = [c[0] for c in doc["cities"]]
        assert len({(c[1], c[2]) for c in doc["cities"]}) == len(doc["cities"]), (snap, "duplicate city")
        assert "彼得格勒" in city_names and "圣彼得堡" not in city_names
        if snap.startswith("1917"):
            assert "雅西" in city_names
            hits = at(44.37, 33.32)
            assert len(hits) == 1 and hits[0]["controller_gwcode"] == 200
            assert {r["controller_name_zh"] for r in db_rows if r["controller_gwcode"] == 365} == {"俄国（临时政府）"}
        assert (DATA.parent / f"{snap}.html").exists()
        print(snap, n, "pieces; database, date validity, map references and historical checks passed")
    con.close()
    print("All shared map references and original geometry prefixes passed")


if __name__ == "__main__":
    main()
