"""mapdata.py: the outline encoding the page decodes, the look-up tables and the record of the added dates."""
import copy
import unittest

import _path  # noqa: F401
from shapely.geometry import MultiPolygon, Polygon, box

import mapdata as M


class Encoding(unittest.TestCase):
    def test_zigzag_varint(self):
        for n in (0, 1, -1, 63, -64, 300, -300, 2 ** 40, -(2 ** 40)):
            buf = bytearray()
            M.varint(M.zz(n), buf)
            v, shift = 0, 0
            for b in buf:
                v |= (b & 127) << shift
                shift += 7
            self.assertEqual((v >> 1) ^ -(v & 1), n)

    def test_round_trip(self):
        hole = Polygon([(10, 10), (11, 10), (11, 11), (10, 11)])
        a = box(8, 8, 14, 14).difference(hole)
        b = MultiPolygon([box(-3.0004, 50, -2, 51), box(0, 0, 0.5, 0.5)])
        geoms, ends = M.decode_geo(M.encode([a, b], M.TOL_PROV))
        self.assertEqual(len(geoms), 2)
        self.assertEqual(ends[-1] > ends[1] > 0, True)
        self.assertEqual(len(geoms[0].interiors), 1)                     # the hole survives
        self.assertAlmostEqual(geoms[0].area, a.area, places=2)
        self.assertEqual(geoms[1].geom_type, "MultiPolygon")
        self.assertLess(geoms[1].symmetric_difference(b).area, 0.002)  # 1/1000 degree quantum

    def test_tiny_unit_stays_clickable(self):
        tiny = box(5, 5, 5.0001, 5.0001)
        geoms, _ = M.decode_geo(M.encode([tiny], M.TOL_PROV))
        self.assertTrue(geoms[0].buffer(0.01).contains(tiny.centroid))

    def test_truncated(self):
        raw = M.encode([box(0, 0, 1, 1)], M.TOL_PROV)
        with self.assertRaises(ValueError):
            M.decode_geo(raw[:-1])

    def test_table(self):
        lut, idx = M.table(["a", "b", "a", float("nan"), None])
        self.assertEqual(lut, ["a", "b", None])
        self.assertEqual(idx, [0, 1, 0, 2, 2])


def static():
    return {"n": 2, "admin_id": ["A", "B"], "tier": [3, 3], "partial": [0, 0], "merged": [0, 0], "area": [1.0, 2.0],
            "label": [[0, 0], [1, 1]], "cols": {"name": {"lut": ["a", "b"], "idx": [0, 1]},
                                                "start": {"lut": [None], "idx": [0, 0]}},
            "feature_admin": [0, 1]}


class AppendedRecord(unittest.TestCase):
    def test_strip_takes_the_additions_off(self):
        base = static()
        rec = M.Appended.record(base)
        self.assertEqual(rec["format"], M.FORMAT_VERSION)
        grown = copy.deepcopy(base)
        i = M.append_admin(grown, dict(admin_id="C", tier=4, partial=None, merged_units=None, area_km2=3.04,
                                       label_lon=2.0001, label_lat=2.0, name="c", start_date="1942-01-01"), "")
        self.assertEqual(i, 2)
        self.assertEqual(M.append_admin(grown, dict(admin_id="C"), ""), 2)   # already there
        grown["feature_admin"].append(2)
        M.Appended.strip(grown, rec)
        self.assertEqual(grown, base)

    def test_strip_refuses_another_build(self):
        base = static()
        rec = M.Appended.record(base)
        changed = copy.deepcopy(base)
        changed["area"][0] = 9.0
        with self.assertRaises(ValueError):
            M.Appended.strip(changed, rec)
        with self.assertRaises(ValueError):
            M.Appended.strip(copy.deepcopy(base), dict(rec, format=M.FORMAT_VERSION + 1))


if __name__ == "__main__":
    unittest.main()
