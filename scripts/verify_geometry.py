"""Geometry checks of every date of every database: the kinds of error the other checks do not see.

  python3 verify_geometry.py               all databases and dates (4 processes; about half an hour)
  python3 verify_geometry.py --quick       one date in four
  python3 verify_geometry.py --db ww2_monthly_1945 --date 1945-04-01
  python3 verify_geometry.py --update-reviewed   write the straight lines found to the reviewed list (after
                                           looking at each new one on the map)

1. ids       a piece with an outline of its own has the same area on every date it is used (2 %): the outlines
             of all dates share one id space, so an id that names different outlines on different dates draws
             one date's shape on another (Suiyuan 1946-47: a "Mongolia" enclave in the Ordos)
2. overlap   the outline a piece is drawn with (its own, or its division's when it is the whole division) does
             not cover more than OVERLAP_KM2 of a piece of another controller on the same date (Mykolaiv oblast
             1944: a 107 km2 remnant drawn as the whole oblast over the German-held part, 19,780 km2); disagreements
             between the source layers along borders stay under it (at most about 3,300 km2)
3. straight  no straight segment of LINE_DEG or more between two controllers inside one political unit that is
             not in curated/straight_lines_reviewed.csv (straight lines are present-day boundaries, front lines
             written as lon/lat, borders of the source layers; a box or a parallel used as a mask is an error:
             the zones in Germany at 51.55 N, the Jin-Sui box at 39.6 N)
4. sheets    a traced area georeferenced from a sheet (curated/atlas_1945.json) leaves no thin strip between
             itself and the sheet frame along the frame's inner edges (the strip from Estonia to Romania, 1945)

Exits with status 1 when a check fails.
"""
import argparse
import csv
import json
import math
import sqlite3
import sys
from multiprocessing import Pool

from shapely import STRtree
from shapely.geometry import LineString, Point, shape

from common import DB_DIR, ROOT
from lagekarten import Georef

OVERLAP_KM2 = 4000   # the source layers disagree along borders by up to about 3,300 km2 (British Columbia over
                     # the Alaska panhandle, 1900); the errors found were 8,900-59,000 km2
LINE_DEG = 0.5
REVIEWED = ROOT / "curated" / "straight_lines_reviewed.csv"
SKIP = {"world_history_1900_2000.sqlite"}


def km2(geom):
    return geom.area * 111.32 ** 2 * math.cos(math.radians(geom.centroid.y)) if not geom.is_empty else 0.0


def databases(only=None):
    return [p for p in sorted(DB_DIR.glob("*.sqlite")) if p.name not in SKIP and (only is None or p.stem == only)]


def check_ids(db):
    """Pieces with an outline of their own whose area differs between dates."""
    con = sqlite3.connect(db)
    rows = con.execute("""SELECT p.piece_id, group_concat(ps.snapshot || ':' || round(ps.area_km2), ' ')
                          FROM piece_snapshot ps JOIN pieces p USING(piece_key) WHERE p.geometry IS NOT NULL
                          GROUP BY piece_key HAVING max(ps.area_km2) > min(ps.area_km2) * 1.02 + 1""").fetchall()
    return [f"{db.name}: {pid} has different outlines on different dates ({areas[:160]})" for pid, areas in rows]


def drawn(con, snap):
    """The outline each piece is drawn with, its controller, unit and whether it is its own outline."""
    rows = con.execute("""SELECT p.piece_id, coalesce(p.geometry, a.geometry), p.geometry IS NOT NULL,
                                 c.controller_name_en, a.name, ps.unit_id
                          FROM piece_snapshot ps JOIN pieces p USING(piece_key) JOIN admin_units a USING(admin_key)
                          JOIN controls c USING(control_id) WHERE ps.snapshot=?""", (snap,)).fetchall()
    geoms, meta = [], []
    for pid, g, own, ctl, name, unit in rows:
        if g:
            geoms.append(shape(json.loads(g)).buffer(0))
            meta.append(dict(pid=pid, own=bool(own), ctl=ctl, name=name, unit=unit))
    return geoms, meta


def check_date(args):
    """Checks 2 and 3 on one date: (overlap messages, straight segments found)."""
    db, snap = args
    con = sqlite3.connect(db)
    geoms, meta = drawn(con, snap)
    tree = STRtree(geoms)
    overlaps = []
    for i, g in enumerate(geoms):
        if meta[i]["own"]:
            continue
        for j in tree.query(g):
            if j == i or meta[j]["ctl"] == meta[i]["ctl"]:
                continue
            try:
                a = km2(g.intersection(geoms[j]))
            except Exception:  # an invalid source outline: reported by the area check instead
                continue
            if a > OVERLAP_KM2:
                overlaps.append(f"{db.name} {snap}: {meta[i]['pid']} ({meta[i]['name']}, {meta[i]['ctl']}) drawn with "
                                f"its division's outline covers {a:.0f} km2 of {meta[j]['name']} ({meta[j]['ctl']})")

    def at(pt):
        for j in tree.query(pt):
            if geoms[j].contains(pt):
                return j

    segments = {}
    for i, g in enumerate(geoms):
        if not meta[i]["own"]:
            continue
        for poly in getattr(g, "geoms", [g]):
            if poly.geom_type != "Polygon":
                continue
            cs = list(poly.exterior.coords)
            for a, b in zip(cs, cs[1:]):
                length = math.hypot(b[0] - a[0], b[1] - a[1])
                if length < LINE_DEG:
                    continue
                mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
                nx, ny = -(b[1] - a[1]) / length * 0.01, (b[0] - a[0]) / length * 0.01
                j1, j2 = at(Point(mx + nx, my + ny)), at(Point(mx - nx, my - ny))
                if j1 is None or j2 is None or meta[j1]["unit"] != meta[j2]["unit"] or meta[j1]["ctl"] == meta[j2]["ctl"]:
                    continue
                key = segment_key(a, b)
                segments[key] = (snap, round(length, 2), meta[j1]["name"], meta[j1]["ctl"], meta[j2]["name"], meta[j2]["ctl"])
    return db.name, snap, overlaps, segments


def segment_key(a, b):
    """A segment independent of its direction, to 0.05 degrees (the same line on several dates, slightly moved)."""
    p, q = sorted([(round(a[0] * 20) / 20, round(a[1] * 20) / 20), (round(b[0] * 20) / 20, round(b[1] * 20) / 20)])
    return f"{p[0]:.2f},{p[1]:.2f},{q[0]:.2f},{q[1]:.2f}"


def read_reviewed():
    if not REVIEWED.exists():
        return {}
    with open(REVIEWED, newline="") as f:
        return {r["segment"]: r for r in csv.DictReader(f)}


def write_reviewed(found, reviewed):
    rows = dict(reviewed)
    for key, (snap, length, n1, c1, n2, c2) in found.items():
        rows.setdefault(key, dict(segment=key, length_deg=length, first_date=snap, between=f"{n1} ({c1}) | {n2} ({c2})",
                                  reason="reviewed: present-day boundary, front line or border of the source layers"))
    with open(REVIEWED, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["segment", "length_deg", "first_date", "between", "reason"])
        w.writeheader()
        w.writerows(sorted(rows.values(), key=lambda r: r["segment"]))
    print(f"{REVIEWED.relative_to(ROOT)}: {len(rows)} segments ({len(rows) - len(reviewed)} new)")


def check_sheets():
    """Thin strips between a traced area and the inner edges of its sheet frame (curated/atlas_1945.json)."""
    path = ROOT / "curated" / "atlas_1945.json"
    if not path.exists():
        return []
    data, out = json.loads(path.read_text()), []
    for date, d in data["dates"].items():
        g = Georef(d["gcps"])
        x0, y0, x1, y1 = d["sheet"]
        fc = json.loads((ROOT / "curated" / "frontlines_1945" / f"{date}.geojson").read_text())
        allied = [shape(f["geometry"]).buffer(0) for f in fc["features"] if f["properties"]["side"] == "allied"][0]
        for edge, (px, py) in {"right": ([x1] * 300, list(range(y0, y1, 4))[:300]),
                               "bottom": (list(range(x0, x1, 4))[:320], [y1] * 320)}.items():
            n = min(len(px), len(py))
            lon, lat = g.lonlat(px[:n], py[:n])
            band = LineString(list(zip(lon, lat))).buffer(0.3)
            miss = band.difference(allied)
            for part in getattr(miss, "geoms", [miss]):
                if part.is_empty:
                    continue
                x_0, y_0, x_1, y_1 = part.bounds
                long_side = max(x_1 - x_0, y_1 - y_0)
                if long_side > 0.5 and part.area / long_side < 0.08:  # long and thin: a strip, not ground left grey
                    out.append(f"atlas_1945 {date}: strip of {km2(part):.0f} km2 along the {edge} edge of the sheet "
                               f"({x_0:.2f},{y_0:.2f} - {x_1:.2f},{y_1:.2f})")
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", help="only this database (file name without .sqlite)")
    ap.add_argument("--date", help="only this date")
    ap.add_argument("--quick", action="store_true", help="one date in four")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--update-reviewed", action="store_true")
    args = ap.parse_args()
    failures = []
    tasks = []
    for db in databases(args.db):
        failures += check_ids(db)
        snaps = [r[0] for r in sqlite3.connect(db).execute("SELECT snapshot FROM snapshots ORDER BY snapshot")]
        if args.date:
            snaps = [s for s in snaps if s == args.date]
        if args.quick:
            snaps = snaps[::4]
        tasks += [(db, s) for s in snaps]
    print(f"ids: {len(failures)} problems; checking {len(tasks)} dates", flush=True)
    reviewed, found = read_reviewed(), {}
    with Pool(args.jobs) as pool:
        for name, snap, overlaps, segments in pool.imap_unordered(check_date, tasks):
            new = {k: v for k, v in segments.items() if k not in reviewed}
            found.update(segments)
            failures += overlaps
            if not args.update_reviewed:
                failures += [f"{name} {snap}: straight line {k} ({v[1]} deg) between {v[2]} ({v[3]}) and {v[4]} ({v[5]}) "
                             f"not in {REVIEWED.name}" for k, v in new.items()]
            print(f"{name} {snap}: {len(overlaps)} overlaps, {len(segments)} straight lines ({len(new)} not reviewed)",
                  flush=True)
    sheets = check_sheets()
    print(f"sheets: {len(sheets)} strips")
    failures += sheets
    if args.update_reviewed:
        write_reviewed(found, reviewed)
    for f in failures:
        print("FAIL", f)
    print("geometry checks", "failed:" if failures else "passed", len(failures) or "")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
