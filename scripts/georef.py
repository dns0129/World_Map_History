"""Georeferencing of scanned maps: pixel <-> lon/lat models fitted to control points, and the transform of traced
lines and rings.

Models (each with .lonlat(x, y) -> (lon, lat) arrays and .residuals {control point: km}):
  Polynomial    second-order polynomial in the pixels, fitted to control points (towns, coast features, graticule
                crossings) by least squares; for maps of unknown projection (the OKH situation maps, the Japanese
                army maps, the War Department atlas). Georef is the same class (its earlier name)
  LambertSheet  Lambert conformal conic on the sphere plus a similarity (complex a * lcc + b), the cone constant
                searched by least squares; for sheets drawn on that projection (the 12th Army Group maps), where a
                polynomial would go astray beyond the control points

line_lonlat(model, pixels, closed=False) is the one way a traced line or ring becomes lon/lat: the polyline is
first densified to STEP_PX in pixel space, because a model bends straight pixel lines and transforming only the
vertices would put a chord in their place (on the 1945 atlas pages a chord between corners lay up to 0.1 degree off
the page edge and left slivers of land on neither side; SOP item 22).
"""
import math

import numpy as np
from shapely.geometry import LineString

STEP_PX = 10


def km(lon1, lat1, lon2, lat2):
    return math.hypot((lon1 - lon2) * 111.32 * math.cos(math.radians(lat2)), (lat1 - lat2) * 110.57)


def _terms(u, v):
    u, v = np.asarray(u, float), np.asarray(v, float)
    return np.stack([np.ones_like(u), u, v, u * u, u * v, v * v], -1)


class Polynomial:
    """Pixels -> lon/lat by a second-order polynomial fitted to the control points ({name, x, y, lon, lat})."""

    def __init__(self, gcps):
        P = np.array([[g["x"], g["y"]] for g in gcps], float)
        L = np.array([[g["lon"], g["lat"]] for g in gcps], float)
        self.mean = L.mean(0)
        self.coef = np.linalg.lstsq(_terms(P[:, 0] / 1000, P[:, 1] / 1000), L - self.mean, rcond=None)[0]
        self.residuals = {g["name"]: round(km(*self.lonlat(g["x"], g["y"]), g["lon"], g["lat"]), 1) for g in gcps}

    def lonlat(self, x, y):
        r = _terms(np.asarray(x) / 1000, np.asarray(y) / 1000) @ self.coef + self.mean
        return r[..., 0], r[..., 1]

    km = staticmethod(km)


Georef = Polynomial


def lcc(lon, lat, n, lon0=5.0):
    """Lambert conformal conic on the sphere, as complex x + iy (x east, y north), unit scale."""
    lon, lat = np.radians(np.asarray(lon, float)), np.radians(np.asarray(lat, float))
    rho = 1 / np.tan(math.pi / 4 + lat / 2) ** n
    th = n * (lon - math.radians(lon0))
    return rho * np.sin(th) - 1j * rho * np.cos(th)


class LambertSheet:
    """lon/lat <-> sheet pixels: pixel = a * lcc(lon, lat; n) + b (complex, pixel y downwards). `ticks` are border
    ticks of a sheet whose edges are not graticule lines: a "lon" tick fixes only the longitude of its pixel, a
    "lat" tick only the latitude; the other coordinate comes from the model, and the fit is repeated."""

    def __init__(self, gcps, ticks=()):
        full = [(g["lon"], g["lat"], g["x"], g["y"]) for g in gcps]
        self._fit(full)
        for _ in range(8):
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
        lo, la = np.mean([p[0] for p in pts]), np.mean([p[1] for p in pts])  # km per pixel near the centre
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


def densify(pixels, closed=False, step=STEP_PX):
    """The polyline (or ring) with a vertex at least every `step` pixels, the original vertices kept."""
    pts = [tuple(map(float, p)) for p in pixels]
    if closed and pts and pts[0] != pts[-1]:
        pts.append(pts[0])
    if len(pts) < 2:
        return pts
    return [tuple(c) for c in LineString(pts).segmentize(step).coords]


def line_lonlat(model, pixels, closed=False, step=STEP_PX, digits=4):
    """A traced line or ring (pixels) as lon/lat points, densified in pixel space first (see the module docstring)."""
    pts = densify(pixels, closed, step)
    if not pts:
        return []
    lon, lat = model.lonlat([p[0] for p in pts], [p[1] for p in pts])
    return [(round(float(a), digits), round(float(b), digits)) for a, b in zip(np.atleast_1d(lon), np.atleast_1d(lat))]
