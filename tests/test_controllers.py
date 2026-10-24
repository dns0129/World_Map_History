"""controllers.py: the bloc rule of both paths and the East Asian occupation layers."""
import unittest

import _path  # noqa: F401
import controllers as C


class Blocs(unittest.TestCase):
    def test_membership_and_front(self):
        self.assertEqual(C.bloc(-20, {-20}, set()), "contested")  # the front line before membership
        self.assertEqual(C.bloc(2, {2}, {255}), "allied")
        self.assertEqual(C.bloc(255, {2}, {255}), "axis")
        self.assertEqual(C.bloc(230, {2}, {255}), "neutral")

    def test_detail_rules(self):
        self.assertEqual(C.bloc_on("ww2", 220, "1942-11-01", "Vichy France"), "neutral")
        self.assertEqual(C.bloc_on("ww2", 220, "1939-09-01", "France"), "allied")
        self.assertEqual(C.bloc_on("early", 710, "1900-08-14", "Southeast Mutual Protection (Liu Kunyi)"), "neutral")
        self.assertEqual(C.bloc_on("early", 710, "1900-08-14", "Qing court"), "axis")
        self.assertEqual(C.bloc_on("early", 740, "1934-10-16", "Manchukuo (Fengtian Province)"), "axis")
        self.assertEqual(C.bloc_on("postwar", 365, "1991-12-26", "Russia"), "axis")
        self.assertEqual(C.bloc_on("postwar", 365, "1991-12-26", "Soviet Union"), "axis")  # a member anyway
        self.assertEqual(C.bloc_on("postwar", 365, "1953-07-27", None), "axis")

    def test_no_controller_in_both_blocs(self):
        for name, table in C.BLOCS.items():
            for snap, b in table.items():
                self.assertFalse(b["allied"] & b["axis"], f"{name} {snap}")

    def test_names_on(self):
        self.assertEqual(C.names_on("postwar", "1949-10-01")[-2][0], "People's Republic of China")
        self.assertEqual(C.names_on("postwar", "1948-09-12")[-2][0], "Chinese Communist Party")
        self.assertEqual(C.names_on("early", "1918-11-11")[300][0], "Austria-Hungary")
        self.assertNotIn(300, C.names_on("early", "1914-08-04"))


def place(iso3="CHN", kind=None, parent=None, parent_zh=None):
    return dict(iso3=iso3, defacto_parent_kind=kind, defacto_parent=parent, defacto_parent_zh=parent_zh)


def inside(*layers):
    return lambda k: k in layers


class OverlayRules(unittest.TestCase):
    def ctrl(self, snap, county, layers=()):
        r = C.overlay_control(snap, county, inside(*layers))
        return r and (r[0], r[4], r[5])

    def test_manchukuo_before_its_provinces(self):
        roc = place(kind="ROC Manchuria", parent="Jehol")
        self.assertIsNone(self.ctrl("1932-03-01", roc))          # Jehol taken in March 1933
        self.assertEqual(self.ctrl("1933-03-04", roc), (740, "overlay:manchukuo_roc", "whole"))
        self.assertIsNone(self.ctrl("1932-02-29", place(kind="ROC Manchuria", parent="Liaoning")))
        r = C.overlay_control("1934-10-16", place(kind="ROC Manchuria", parent="Liaoning"), inside())
        self.assertEqual(r[1:3], ("Manchukuo (Fengtian Province)", "伪满洲国（奉天省）"))

    def test_kwantung(self):
        lt = place(kind="leased territory")
        self.assertEqual(self.ctrl("1905-09-04", lt)[0], 365)    # Russian until the Treaty of Portsmouth
        self.assertEqual(self.ctrl("1905-09-05", lt)[0], 740)
        self.assertEqual(self.ctrl("1945-09-02", lt)[0], 365)    # Soviet occupation
        self.assertEqual(self.ctrl("1949-09-30", lt)[0], 365)
        self.assertIsNone(self.ctrl("1949-10-01", lt))

    def test_war_layers(self):
        self.assertEqual(self.ctrl("1942-11-01", place(), ["ccp", "occ"]), (-2, "overlay:ccp_bases_1941_42", "approximate"))
        self.assertEqual(self.ctrl("1943-01-01", place(), ["ccp", "occ"]), (740, "overlay:occupied_zone_1942", "whole"))
        self.assertEqual(self.ctrl("1939-09-01", place(), ["meng"]), (740, "overlay:mengjiang", "approximate"))
        self.assertIsNone(self.ctrl("1945-09-02", place(), ["meng"]))
        self.assertEqual(self.ctrl("1945-09-02", place(), ["occ"])[0:2], (740, "overlay:occupied_zone_1942"))
        self.assertIsNone(self.ctrl("1942-11-01", place("FRA"), ["occ"]))   # the layers are Chinese only

    def test_indochina(self):
        self.assertIsNone(self.ctrl("1941-05-08", place("KHM"), ["ceded"]))
        self.assertEqual(self.ctrl("1941-05-09", place("KHM"), ["ceded"])[0], 800)
        self.assertEqual(self.ctrl("1946-11-17", place("LAO"), ["ceded"])[0], 800)
        self.assertIsNone(self.ctrl("1946-11-18", place("LAO"), ["ceded"]))
        self.assertIsNone(self.ctrl("1942-11-01", place("KHM")))


if __name__ == "__main__":
    unittest.main()
