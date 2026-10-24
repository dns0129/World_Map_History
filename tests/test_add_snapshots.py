"""add_snapshots.py: the rule matching, masks, population rounding and the outline decisions of path A."""
import unittest

import _path  # noqa: F401
from shapely.geometry import box

import add_snapshots as A


def rule(**kw):
    r = dict(snapshots="1942-01-01", unit_match="*", admin_match="*", mask=None, bounds=None, controller_gwcode="255",
             control_type="military_occupation", source="s", confidence="whole", controller_name="Germany",
             controller_name_zh="德国", row=2)
    r.update(kw)
    if r["mask"] is not None:
        r["bounds"] = r["mask"].bounds
    return r


class Matching(unittest.TestCase):
    def test_matches(self):
        self.assertTrue(A.matches("Poland|USSR*", "USSR (Soviet Union)"))
        self.assertTrue(A.matches("*", None))
        self.assertFalse(A.matches("Poland", "poland"))         # case matters
        self.assertTrue(A.overlaps((0, 0, 1, 1), (1, 1, 2, 2)))
        self.assertFalse(A.overlaps((0, 0, 1, 1), (1.1, 0, 2, 1)))

    def test_control_parts_cut_by_a_mask(self):
        base = A.controller(365, {365: ("Soviet Union", "苏联")})
        g = box(30, 50, 32, 52)
        hits = set()
        parts = A.control_parts(g, {"admin_id": "SU-x"}, {"cshapes_name": "Soviet Union"}, "1942-01-01", base,
                                [rule(mask=box(31, 49, 33, 53)), rule(snapshots="1942-02-01", row=3)], {}, hits)
        held = {p[1]["controller_gwcode"]: p[0].area for p in parts}
        self.assertAlmostEqual(held[255], 2.0)
        self.assertAlmostEqual(held[365], 2.0)
        self.assertEqual(hits, {("1942-01-01", 2)})             # the rule of another date does not apply

    def test_later_rule_wins_and_unmatched_unit(self):
        base = A.controller(365, {})
        g = box(0, 0, 1, 1)
        parts = A.control_parts(g, {"admin_id": "a"}, {"cshapes_name": "X"}, "1942-01-01", base,
                                [rule(), rule(controller_gwcode="-20", row=3), rule(unit_match="Y", row=4)], {}, set())
        self.assertEqual([p[1]["controller_gwcode"] for p in parts], [-20])


class Population(unittest.TestCase):
    def test_rounded_total_is_kept(self):
        rows = [dict(weight=w, area_km2=1) for w in (1, 1, 1)]
        A.allocate_population(rows, 100)
        self.assertEqual(sum(r["population_est"] for r in rows), 100)
        self.assertEqual(sorted(r["population_est"] for r in rows), [33, 33, 34])

    def test_area_when_no_weights(self):
        rows = [dict(weight=0, area_km2=a) for a in (1, 3)]
        A.allocate_population(rows, 8)
        self.assertEqual([r["population_est"] for r in rows], [2, 6])

    def test_absorb_merges_slivers(self):
        rows = [dict(admin_id="a", geom=box(0, 0, 1, 1), area_km2=10000, weight=5),
                dict(admin_id="a", geom=box(1, 0, 1.01, 1), area_km2=12, weight=1),
                dict(admin_id="b", geom=box(5, 5, 6, 6), area_km2=10000, weight=2)]
        A.absorb(rows, 30)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["area_km2"], 10012)
        self.assertEqual(rows[0]["weight"], 6)


class Outlines(unittest.TestCase):
    def test_own_outline(self):
        self.assertTrue(A.own_outline(dict(control_split=1, admin_id="x"), {}))
        self.assertFalse(A.own_outline(dict(control_split=0, admin_id="FR1939-ardennes", area_km2=5), {"area_km2": 1}))
        land = dict(control_split=0, admin_id="ADD-CSH-12-3_4", area_km2=1000)
        self.assertFalse(A.own_outline(land, {"area_km2": 1005}))   # within 1%
        self.assertTrue(A.own_outline(land, {"area_km2": 1100}))

    def test_unit_counter(self):
        c = A.UnitCounter(5)
        self.assertEqual([next(c), next(c)], [5, 6])
        self.assertEqual(c.value, 7)


if __name__ == "__main__":
    unittest.main()
