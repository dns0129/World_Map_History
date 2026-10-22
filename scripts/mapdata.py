"""The data files of the interactive maps (ww2/maps/data): their encoding and the record of what the added dates
append to admin.bin. ww2_webmap.py writes the files of the sets' own dates, add_snapshots.py appends the added
dates; both go through this module, so that the format is defined in one place.

Files (FORMAT_VERSION; the page, ww2/maps/template.html, reads them):
  admin.bin        gzip JSON: the historical divisions (columns admin_id, tier, partial, merged, area, label and the
                   look-up columns of `cols`), and feature_admin (the division of every map feature)
  geo-<date>.bin   gzip: outlines as zigzag-varint deltas of 1/Q degree (encode / decode_geo): the date's
                   divisions, cut pieces, political units and control areas, in that order
  snap-<date>.json the date's features, units, countries and look-up tables
  index.json       the dates
  added-build.json what ww2_webmap.py wrote, as lengths and a checksum (Appended), so that add_snapshots.py can take
                   its own additions off again and append them anew
"""
import gzip
import hashlib
import json

import numpy as np
from shapely.geometry import MultiPolygon, Polygon

FORMAT_VERSION = 1
Q = 1000  # coordinate units per degree
TOL_PROV = 0.008   # simplification of the outlines (degrees): divisions and pieces, political units, control areas
TOL_UNIT = 0.02
TOL_CTRL = 0.012
ADMIN_COLUMNS = ("admin_id", "tier", "partial", "merged", "area", "label")


def varint(n, out):
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return


def zz(n):
    return (n << 1) ^ (n >> 63)


def packed(path, data):
    """gzip-compressed file (mtime 0, so that the same data gives the same bytes); the page inflates it."""
    path.write_bytes(gzip.compress(data, compresslevel=9, mtime=0))


def encode(geoms, tol):
    buf = bytearray()
    for g in geoms:
        s = g.simplify(tol, preserve_topology=True)
        ps = [p for p in getattr(s, "geoms", [s]) if p.geom_type == "Polygon" and not p.is_empty]
        ps = [p for p in ps if p.area > (tol * tol) / 4] or ps[:1]
        polys_ = []
        for p in ps:
            rings = []
            for r in [p.exterior, *p.interiors]:
                c = np.round(np.asarray(r.coords)[:-1] * Q).astype(np.int64)
                c = c[np.r_[True, np.any(np.diff(c, axis=0) != 0, axis=1)]]
                if len(c) > 1 and (c[0] == c[-1]).all():
                    c = c[:-1]
                if len(c) >= 3:
                    rings.append(c)
                elif not rings:
                    break  # exterior collapsed: drop the polygon
            if rings:
                polys_.append(rings)
        if not polys_:  # keep tiny units clickable: a small triangle at the label point
            pt = g.representative_point()
            x, y = round(pt.x * Q), round(pt.y * Q)
            polys_ = [[np.array([[x - 2, y - 2], [x + 2, y - 2], [x, y + 2]], dtype=np.int64)]]
        varint(len(polys_), buf)
        px = py = 0
        for rings in polys_:
            varint(len(rings), buf)
            for c in rings:
                varint(len(c), buf)
                for x, y in c:
                    varint(zz(int(x - px)), buf)
                    varint(zz(int(y - py)), buf)
                    px, py = int(x), int(y)
    return bytes(buf)


def table(values):
    """Deduplicate strings into a lookup list and index array."""
    lut, idx = [], {}
    out = []
    for v in values:
        v = None if (isinstance(v, float) and np.isnan(v)) else v
        if v not in idx:
            idx[v] = len(lut)
            lut.append(v)
        out.append(idx[v])
    return lut, out


def read_json(path):
    return json.loads(path.read_text())


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")))


def unpack(path):
    """A data file as bytes, gunzipped when it is gzip-compressed."""
    raw = path.read_bytes()
    return gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw


def decode_geo(raw):
    """Outlines of a geo-<date>.bin (unpacked), with the byte offset where each ends."""
    pos = 0
    boundaries = [0]
    geoms = []

    def varint():
        nonlocal pos
        value = shift = 0
        while True:
            if pos >= len(raw):
                raise ValueError("Truncated map geometry")
            b = raw[pos]
            pos += 1
            value |= (b & 127) << shift
            if not b & 128:
                return value
            shift += 7
            if shift > 63:
                raise ValueError("Invalid map geometry varint")

    while pos < len(raw):
        parts = []
        x = y = 0
        for _ in range(varint()):
            rings = []
            for _ in range(varint()):
                points = []
                for _ in range(varint()):
                    dx, dy = varint(), varint()
                    x += (dx >> 1) ^ -(dx & 1)
                    y += (dy >> 1) ^ -(dy & 1)
                    points.append((x / 1000, y / 1000))
                rings.append(points)
            parts.append(Polygon(rings[0], rings[1:]))
        geoms.append(MultiPolygon(parts) if len(parts) > 1 else parts[0])
        boundaries.append(pos)
    return geoms, boundaries


def static_hash(static):
    return hashlib.sha256(json.dumps(static, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def append_admin(static, a, prefix):
    """The index of a division in admin.bin (prefix: its set's, as ww2_webmap.py writes the ids), appended when
    it is not there yet."""
    aid = prefix + a["admin_id"]
    if aid in static["admin_id"]:
        return static["admin_id"].index(aid)
    i = static["n"]
    static["n"] += 1
    static["admin_id"].append(aid)
    for key, value in dict(tier=a["tier"], partial=a["partial"] or 0, merged=a["merged_units"] or 0,
                           area=round(a["area_km2"], 1), label=[round(a["label_lon"], 3), round(a["label_lat"], 3)]).items():
        static[key].append(value)
    for key, col in static["cols"].items():
        value = a.get({"start": "start_date", "end": "end_date"}.get(key, key))
        if value not in col["lut"]:
            col["lut"].append(value)
        col["idx"].append(col["lut"].index(value))
    return i


class Appended:
    """What the added dates appended to admin.bin, recorded in added-build.json.

    record(static) notes the lengths of the columns, look-up lists and feature list and the checksum of admin.bin as
    ww2_webmap.py wrote it; strip(static, record) cuts a later admin.bin back to those lengths and checks the
    checksum (anything else changed since: ww2_webmap.py has to run again first)."""

    @staticmethod
    def record(static):
        return {"format": FORMAT_VERSION, "admins": static["n"], "features": len(static["feature_admin"]),
                "luts": {k: len(c["lut"]) for k, c in static["cols"].items()}, "sha256": static_hash(static)}

    @staticmethod
    def strip(static, rec):
        if rec.get("format", 1) != FORMAT_VERSION:
            raise ValueError("added-build.json is of another format version; run ww2_webmap.py first")
        n = static["n"] = rec["admins"]
        for col in ADMIN_COLUMNS:
            static[col] = static[col][:n]
        for key, col in static["cols"].items():
            col["idx"] = col["idx"][:n]
            col["lut"] = col["lut"][:rec["luts"][key]]
        static["feature_admin"] = static["feature_admin"][:rec["features"]]
        if static_hash(static) != rec["sha256"]:
            raise ValueError("admin.bin changed since add_snapshots.py last ran; run ww2_webmap.py before add_snapshots.py")
        return static
