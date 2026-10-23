"""georef.py: the models fitted to control points, and lines densified before they are transformed."""
import unittest

import _path  # noqa: F401
import numpy as np

import georef as G


def quadratic(x, y):
    u, v = x / 1000, y / 1000
    return 10 + 2 * u - 0.5 * v + 0.1 * u * u - 0.05 * u * v, 50 - 1.5 * v + 0.2 * u + 0.03 * v * v


class Polynomial(unittest.TestCase):
    def test_exact_on_a_quadratic(self):
        pts = [(x, y) for x in (0, 900, 2100, 3000) for y in (0, 1200, 2500)]
        gcps = [dict(name=f"p{i}", x=x, y=y, lon=quadratic(x, y)[0], lat=quadratic(x, y)[1]) for i, (x, y) in enumerate(pts)]
        m = G.Polynomial(gcps)
        self.assertLess(max(m.residuals.values()), 0.05)
        lon, lat = m.lonlat(1500, 700)
        self.assertAlmostEqual(float(lon), quadratic(1500, 700)[0], places=6)
        self.assertAlmostEqual(float(lat), quadratic(1500, 700)[1], places=6)
        self.assertIs(G.Georef, G.Polynomial)


class Lambert(unittest.TestCase):
    def test_round_trip(self):
        n, a, b = 0.75, 3000 * np.exp(0.3j), 1500 + 9000j
        gcps = []
        for i, (lon, lat) in enumerate([(-2, 47), (3, 51), (8, 49), (1, 44), (6, 53), (-1, 50)]):
            w = a * G.lcc(lon, lat, n) + b
            gcps.append(dict(name=f"g{i}", lon=lon, lat=lat, x=float(w.real), y=float(-w.imag)))
        s = G.LambertSheet(gcps)
        self.assertAlmostEqual(s.n, n, places=3)
        x, y = s.pixel(4.0, 48.5)
        lon, lat = s.lonlat(x, y)
        self.assertAlmostEqual(float(lon), 4.0, places=5)
        self.assertAlmostEqual(float(lat), 48.5, places=5)


class Densify(unittest.TestCase):
    def test_keeps_vertices_and_steps(self):
        pts = G.densify([(0, 0), (35, 0), (35, 20)], closed=True, step=10)
        self.assertEqual(pts[0], pts[-1])
        for v in [(0.0, 0.0), (35.0, 0.0), (35.0, 20.0)]:
            self.assertIn(v, pts)
        gaps = [np.hypot(p[0] - q[0], p[1] - q[1]) for p, q in zip(pts, pts[1:])]
        self.assertLessEqual(max(gaps), 10 + 1e-9)

    def test_line_lonlat_follows_the_curve(self):
        class Bend:  # a model that bends a straight pixel line
            def lonlat(self, x, y):
                x, y = np.asarray(x, float), np.asarray(y, float)
                return x / 100, y / 100 + (x / 100) ** 2 / 10
        line = G.line_lonlat(Bend(), [(0, 0), (1000, 0)])
        self.assertGreater(len(line), 50)
        mid = min(line, key=lambda p: abs(p[0] - 5))
        self.assertAlmostEqual(mid[1], 2.5, places=2)       # on the curve, not on the chord (5.0)
        self.assertEqual(G.line_lonlat(Bend(), []), [])


if __name__ == "__main__":
    unittest.main()
