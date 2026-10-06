"""Geometry helpers shared by the 1939-1945 build."""
import json
import os
import pickle
import re
import unicodedata

import numpy as np
from pyproj import Transformer
import shapely
from shapely import make_valid
from shapely.errors import GEOSException
from shapely import transform as shp_transform
from shapely.geometry import MultiPolygon, Polygon, shape

from ww2_common import GB

EQ = Transformer.from_crs("EPSG:4326", "+proj=eqearth +datum=WGS84", always_xy=True)


def eq_area_km2(g):
    return shp_transform(g, lambda c: np.column_stack(EQ.transform(c[:, 0], c[:, 1]))).area / 1e6


def polys(g):
    """Polygonal part of a geometry as Polygon/MultiPolygon, or None."""
    if g is None or g.is_empty:
        return None
    g = make_valid(g)
    ps = [p for p in getattr(g, "geoms", [g]) if p.geom_type == "Polygon" and not p.is_empty]
    ps += [q for p in getattr(g, "geoms", []) if p.geom_type == "MultiPolygon" for q in p.geoms]
    if not ps:
        return None
    return MultiPolygon(ps) if len(ps) > 1 else ps[0]


def _safe(op, a, b):
    try:
        return op(a, b)
    except GEOSException:
        try:
            return op(make_valid(a).buffer(0), make_valid(b).buffer(0))
        except GEOSException:
            return op(a, b, grid_size=1e-6)


def diff(a, b):
    """a minus b, robust to the small topology errors traced layers produce."""
    return _safe(shapely.difference, a, b)


def inter(a, b):
    return _safe(shapely.intersection, a, b)


def union(gs):
    gs = [g for g in gs if g is not None and not g.is_empty]
    if not gs:
        return None
    try:
        return shapely.union_all(gs)
    except GEOSException:
        return shapely.union_all([make_valid(g).buffer(0) for g in gs], grid_size=1e-6)


def fix_rings(g):
    """Rebuild a (multi)polygon without the degenerate rings (fewer than four points) that some
    source outlines contain and GEOS refuses to process."""
    if g is None or g.is_empty:
        return g
    out = []
    for p in getattr(g, "geoms", [g]):
        if p.geom_type != "Polygon" or len(set(p.exterior.coords)) < 3:
            continue
        holes = [r.coords for r in p.interiors if len(set(r.coords)) >= 3]
        out.append(Polygon(p.exterior.coords, holes))
    if not out:
        return None
    m = MultiPolygon(out) if len(out) > 1 else out[0]
    return m if m.is_valid else make_valid(m).buffer(0)


def clip_to(gs, bounds, pad=0.05):
    """Cut large geometries down to a padded bounding box before set operations."""
    x0, y0, x1, y1 = bounds
    out = []
    for g in gs:
        try:
            c = shapely.clip_by_rect(g, x0 - pad, y0 - pad, x1 + pad, y1 + pad)
        except GEOSException:  # a degenerate ring in the source outline
            try:
                g = fix_rings(g)
                if g is None:
                    continue
                c = shapely.clip_by_rect(g, x0 - pad, y0 - pad, x1 + pad, y1 + pad)
            except GEOSException:
                continue
        if not c.is_empty:
            out.append(c)
    return out


def opening(g, d=0.005):
    """Drop sliver components: parts whose mean width (2*area/perimeter) is under d degrees or
    whose area is under (2d)^2. Cheap stand-in for a morphological opening."""
    if g is None or g.is_empty:
        return None
    keep = [p for p in getattr(g, "geoms", [g])
            if p.area >= 4 * d * d and 2 * p.area / max(p.length, 1e-12) >= d]
    if not keep:
        return None
    return keep[0] if len(keep) == 1 else MultiPolygon(keep)


def read_geojson(path):
    d = json.load(open(path))
    return [(f["properties"], polys(shape(f["geometry"]))) for f in d["features"] if f.get("geometry")]


def wkb_path(path):
    return path.with_suffix(".wkb")


def write_outlines(path, items):
    """Outlines passed between the build steps, as {id: WKB} next to `path` (path.wkb in place of path.geojson):
    read many times faster than GeoJSON, with the same coordinates."""
    items = list(items)
    blobs = shapely.to_wkb([g for _, g in items])
    tmp = wkb_path(path).with_suffix(f".{os.getpid()}.tmp")
    with open(tmp, "wb") as f:
        pickle.dump({"ids": [k for k, _ in items], "wkb": list(blobs)}, f, protocol=pickle.HIGHEST_PROTOCOL)
    tmp.replace(wkb_path(path))  # whole file or nothing, should the process be killed while writing
    if path.suffix == ".geojson" and path.exists():
        path.unlink()  # an older build's copy would otherwise shadow nothing but take space


def read_outlines(path, key, only=None):
    """{id: geometry} written by write_outlines, or read from the GeoJSON of an older build (id = properties[key]);
    with `only` (a set of ids), just those outlines are decoded."""
    w = wkb_path(path)
    if w.exists():
        with open(w, "rb") as f:
            d = pickle.load(f)
        ids, blobs = d["ids"], d["wkb"]
        if only is not None:
            keep = [i for i, k in enumerate(ids) if k in only]
            ids, blobs = [ids[i] for i in keep], [blobs[i] for i in keep]
        return dict(zip(ids, shapely.from_wkb(blobs)))
    feats = json.load(open(path))["features"]
    return {f["properties"][key]: shape(f["geometry"]) for f in feats
            if only is None or f["properties"][key] in only}


def read_projected(path, epsg):
    tr = Transformer.from_crs(f"EPSG:{epsg}", "EPSG:4326", always_xy=True)
    return [(p, polys(shp_transform(g, lambda c: np.column_stack(tr.transform(c[:, 0], c[:, 1])))))
            for p, g in read_geojson(path)]


def gb_path(iso, lv):
    return GB / f"{iso}_{lv}_geoBoundaries-{iso}-{lv}_simplified.geojson"


def norm(s):
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z]", "", s)
