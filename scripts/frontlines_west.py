"""Front lines of the Western Front in 1944 from the daily situation maps of the US Twelfth Army Group.

Source: "HQ Twelfth Army Group situation map", one sheet per day from 6 June 1944 to July 1945, Library of Congress,
Geography and Map Division, World War II Military Situation Maps (www.loc.gov/collections/world-war-ii-maps-military-
situation-maps-from-1944-to-1945; US government work, no known copyright restrictions). curated/loc_west_<year>.json
holds, per date, the sheet used (its LOC item and image id; pixels are those of the IIIF image at pct:50) and:
  gcps   control points with their lon/lat: graticule intersections (the 1:500,000 sheets of the Normandy period) or
         towns read on the sheet (the 1:1,000,000 outline maps of the autumn)
  ticks  border ticks of a sheet whose edges are not graticule lines: a "lon" tick on the bottom edge fixes only the
         longitude at its pixel, a "lat" tick on the right edge only the latitude
  front  the front line ("front line" symbol, a heavy line with ticks on the enemy side) read along the sheet
A stretch may instead be {"lonlat": [...], "note": ...}: written as lon/lat after the map where no front line is drawn
(the sheets of the pursuit in September and of 1 October show unit positions only; the line then runs between the
Allied and German unit symbols, along the features named in the note) or where the line leaves the sheet.
The sheets are drawn on a conical orthomorphic (Lambert conformal conic) projection ("Projection Europe (Air)
Conical Orthomorphic"): a Lambert conformal conic of cone constant n with a similarity transform (scale, rotation,
offset) is fitted to the control points (least squares, n by search), each tick contributing the point on its edge
whose other coordinate the model gives (repeated until stable); residuals are written out with the result.
Per date `head` and `tail` take the line's ends out to sea or to a neutral border, `close` returns from the tail to
the head round the Allied side, `adjustments` records any point moved and why, and `pockets` are lon/lat polygons the line cannot express (German pockets behind the
Allied front: Dunkirk, the Atlantic ports; side "allied" for Allied areas beyond a German corridor, as southern
France on 1 September). A pocket drawn on the sheet is given in pixels and closed along the coast by lon/lat points.

Writes curated/frontlines_west_<year>/<date>.geojson (python3 scripts/frontlines_west.py [year ...]):
  front         the front line
  allied        the Allied side (head + line + tail + close)
  axis          the rest of the box the Western Front lies in
  axis_pocket   German pockets behind the Allied front
  allied_pocket Allied areas the line does not reach
"""
import json
import math
import sys
from pathlib import Path

import numpy as np
from shapely.geometry import LineString, Polygon, box, mapping

ROOT = Path(__file__).resolve().parent.parent
YEARS = ("1944",)
WEST = box(-30, 30, 30, 62)


def lcc(lon, lat, n, lon0=5.0):
    """Lambert conformal conic on the sphere, as complex x + iy (x east, y north), unit scale."""
    lon, lat = np.radians(np.asarray(lon, float)), np.radians(np.asarray(lat, float))
    rho = 1 / np.tan(math.pi / 4 + lat / 2) ** n
    th = n * (lon - math.radians(lon0))
    return rho * np.sin(th) - 1j * rho * np.cos(th)


class Sheet:
    """lon/lat <-> sheet pixels: pixel = a * lcc(lon, lat; n) + b (complex, pixel y downwards)."""

    def __init__(self, gcps, ticks=()):
        full = [(g["lon"], g["lat"], g["x"], g["y"]) for g in gcps]
        self._fit(full)
        for _ in range(8):  # ticks: the other coordinate from the model, then fit again
            extra = []
            for t in ticks:
                if "lon" in t:
                    lats = np.linspace(40, 56, 16001)
                    ys = self.pixel(np.full_like(lats, t["lon"]), lats)[1]
                    extra.append((t["lon"], float(lats[np.argmin(abs(ys - t["y"]))]), t["x"], t["y"]))
                else:
                    lons = np.linspace(-10, 15, 25001)
                    xs = self.pixel(lons, np.full_like(lons, t["lat"]))[0]
                    extra.append((float(lons[np.argmin(abs(xs - t["x"]))]), t["lat"], t["x"], t["y"]))
            self._fit(full + extra)
        names = [g["name"] for g in gcps] + [t["name"] for t in ticks]
        self.residuals = {k: round(float(r) * self.km_px, 1) for k, r in zip(names, self.r)}

    def _fit(self, pts):
        w = np.array([p[2] - 1j * p[3] for p in pts])
        best = None
        for n in np.linspace(0.55, 0.95, 401):
            z = lcc([p[0] for p in pts], [p[1] for p in pts], n)
            A = np.stack([z, np.ones_like(z)], -1)
            c = np.linalg.lstsq(A, w, rcond=None)[0]
            r = np.abs(A @ c - w)
            if best is None or (r ** 2).sum() < best[0]:
                best = ((r ** 2).sum(), n, c, r)
        _, self.n, (self.a, self.b), self.r = best
        # km per pixel near the sheet centre
        lo, la = np.mean([p[0] for p in pts]), np.mean([p[1] for p in pts])
        x0, y0 = self.pixel(lo, la)
        x1, y1 = self.pixel(lo, la + 0.1)
        self.km_px = 11.12 / math.hypot(float(x1 - x0), float(y1 - y0))

    def pixel(self, lon, lat):
        w = self.a * lcc(lon, lat, self.n) + self.b
        return w.real, -w.imag

    def lonlat(self, px, py):
        px, py = np.asarray(px, float), np.asarray(py, float)
        lon, lat = np.full(px.shape, 5.0), np.full(px.shape, 49.5)
        for _ in range(40):  # Newton on the forward model
            x, y = self.pixel(lon, lat)
            e = 1e-4
            xa, ya = self.pixel(lon + e, lat)
            xb, yb = self.pixel(lon, lat + e)
            j11, j12, j21, j22 = (xa - x) / e, (xb - x) / e, (ya - y) / e, (yb - y) / e
            dx, dy = px - x, py - y
            det = j11 * j22 - j12 * j21
            lon, lat = lon + (j22 * dx - j12 * dy) / det, lat + (-j21 * dx + j11 * dy) / det
        return lon, lat


def main(year):
    data = json.loads((ROOT / "curated" / f"loc_west_{year}.json").read_text())
    out = ROOT / "curated" / f"frontlines_west_{year}"
    out.mkdir(exist_ok=True)
    for date, d in sorted(data["dates"].items()):
        sheet = Sheet(d["gcps"], d.get("ticks", []))
        line = [tuple(p) for p in d.get("head", [])]
        for part in d["front"]:
            if "lonlat" in part:
                line += [tuple(p) for p in part["lonlat"]]
            else:
                lon, lat = sheet.lonlat([p[0] for p in part["pixels"]], [p[1] for p in part["pixels"]])
                line += [(round(float(a), 4), round(float(b), 4)) for a, b in zip(lon, lat)]
        line += [tuple(p) for p in d.get("tail", [])]
        allied = Polygon(line + [tuple(p) for p in d["close"]]).buffer(0)
        feats = [dict(type="Feature", properties=dict(side="front"), geometry=mapping(LineString(line))),
                 dict(type="Feature", properties=dict(side="allied"), geometry=mapping(allied)),
                 dict(type="Feature", properties=dict(side="axis"), geometry=mapping(WEST.difference(allied)))]
        for p in d.get("pockets", []):
            ring = [tuple(q) for q in p.get("lonlat", [])]
            if "pixels" in p:  # a pocket drawn on the sheet, closed along the coast by lon/lat points
                lon, lat = sheet.lonlat([q[0] for q in p["pixels"]], [q[1] for q in p["pixels"]])
                ring = [(round(float(a), 4), round(float(b), 4)) for a, b in zip(lon, lat)] + [tuple(q) for q in p["lonlat_close"]]
            feats.append(dict(type="Feature", properties=dict(side=p["side"] + "_pocket", name=p["name"], note=p["note"]),
                              geometry=mapping(Polygon(ring).buffer(0))))
        src = dict(archive="Library of Congress, Geography and Map Division, " + d["title"], map_time=d["map_time"],
                   url=d["url"], image=d["image"], cone_constant=round(float(sheet.n), 3),
                   residuals_km=sheet.residuals)
        (out / f"{date}.geojson").write_text(json.dumps(dict(type="FeatureCollection", source=src, features=feats),
                                                        ensure_ascii=False, separators=(",", ":")))
        print(date, len(line), "points; control point residuals up to", max(sheet.residuals.values()), "km")


if __name__ == "__main__":
    for y in sys.argv[1:] or YEARS:
        main(y)
