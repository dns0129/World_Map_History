"""The build tools: publish batches, the data release archives, the pipeline's module graph, path B rule matching."""
import gzip
import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import _path  # noqa: F401
from shapely.geometry import box

import data_release as D
import pipeline
import publish_artifact as P
import verify_geometry as V
import ww2_snapshots as S


class PublishBatches(unittest.TestCase):
    def test_limit_order_and_last(self):
        sizes = {"a": 40, "b": 30, "c": 30, "data/index.json": 1, "index.html": 1}
        src = {k: "src/" + k for k in sizes}
        b = P.make_batches(["a", "data/index.json", "b", "c", "index.html"], {"old.png"}, sizes, src, limit=70)
        self.assertEqual([list(x) for x in b], [["a", "b"], ["c", "data/index.json", "index.html", "old.png"]])
        self.assertIsNone(b[-1]["old.png"])
        b = P.make_batches(["a", "b", "c", "data/index.json"], set(), sizes, src, limit=60)
        self.assertEqual([list(x) for x in b], [["a"], ["b", "c"], ["data/index.json"]])   # 60 + 1 > 60
        self.assertEqual(P.make_batches([], set(), {}, {}), [])

    def test_tail_joins_the_last_batch_when_it_fits(self):
        sizes = {"a": 10, "data/index.json": 5}
        b = P.make_batches(["a", "data/index.json"], set(), sizes, {k: k for k in sizes}, limit=60)
        self.assertEqual(b, [{"a": "a", "data/index.json": "data/index.json"}])


class DataRelease(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        (root / "db").mkdir()
        (root / "db" / "x.sqlite").write_bytes(b"sqlite" * 100)
        (root / "maps").mkdir()
        (root / "maps" / "1900.png").write_bytes(b"png1900")
        (root / "maps" / "1942.png").write_bytes(b"kept in git")
        self.patches = [mock.patch.object(D, "ROOT", root), mock.patch.object(D, "MANIFEST", root / "data_release.json"),
                        mock.patch.object(D, "DATASETS", {"db.tar.gz": ("db", "*.sqlite"), "maps.tar.gz": ("maps", "*.png")})]
        for p in self.patches:
            p.start()
        self.root = root

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_manifest_pack_fetch(self):
        man = D.make_manifest("data-test")
        self.assertEqual(sorted(man["assets"]["maps.tar.gz"]), ["maps/1900.png"])   # 1942.png stays in git
        D.MANIFEST.write_text(json.dumps(man))
        out = self.root / "dist"
        D.pack(out)
        first = (out / "maps.tar.gz").read_bytes()
        D.pack(out)
        self.assertEqual((out / "maps.tar.gz").read_bytes(), first)                  # same files, same bytes
        with tarfile.open(out / "db.tar.gz") as t:
            self.assertEqual([(m.name, m.mtime, m.uid) for m in t.getmembers()], [("db/x.sqlite", 0, 0)])
        (self.root / "maps" / "1900.png").unlink()
        (self.root / "db" / "x.sqlite").write_bytes(b"changed")
        self.assertEqual(sorted(D.differences(man)[0]), ["db/x.sqlite", "maps/1900.png"])

        class R:
            def __init__(self, req):
                self.name = req.full_url.rsplit("/", 1)[1]

            def read(self):
                return (out / self.name).read_bytes()
        with mock.patch.object(D.urllib.request, "urlopen", lambda req, timeout=0: R(req)):
            D.fetch()
        self.assertEqual(D.differences(man), ([], []))

    def test_fetch_rejects_a_wrong_file(self):
        man = D.make_manifest("data-test")
        D.MANIFEST.write_text(json.dumps(man))
        (self.root / "maps" / "1900.png").unlink()
        buf = io.BytesIO()
        with gzip.GzipFile(fileobj=buf, mode="wb") as gz, tarfile.open(fileobj=gz, mode="w") as t:
            info = tarfile.TarInfo("maps/1900.png")
            info.size = 3
            t.addfile(info, io.BytesIO(b"bad"))

        class R:
            def read(self):
                return buf.getvalue()
        with mock.patch.object(D.urllib.request, "urlopen", lambda req, timeout=0: R()), \
                self.assertRaises(SystemExit):
            D.fetch(["maps.tar.gz"])
        self.assertFalse((self.root / "maps" / "1900.png").exists())


class Checks(unittest.TestCase):
    def test_segment_key_ignores_direction_and_small_moves(self):
        self.assertEqual(V.segment_key((4.55, 51.70), (5.20, 51.75)), V.segment_key((5.21, 51.74), (4.56, 51.71)))
        self.assertEqual(V.segment_key((0, 0), (1, 0)), "0.00,0.00,1.00,0.00")

    def test_pipeline_follows_imports(self):
        mods = pipeline.local_modules("ww2_snapshots")
        self.assertTrue({"ww2_snapshots", "controllers", "ww2_common", "ww2_geo", "topo"} <= mods)
        self.assertNotIn("add_snapshots", mods)


class PathBRules(unittest.TestCase):
    def test_rule_match(self):
        c = dict(iso3="POL", name_1="Mazowieckie", unit="Poland", unit_cs="Poland", label_lon=21.0, label_lat=52.2,
                 hist_names=["Warschau", "Generalgouvernement", None])
        r = dict(iso3="POL|LTU", field="name_1", match="Mazow*")
        self.assertTrue(S.rule_match(r, c))
        self.assertFalse(S.rule_match(dict(r, iso3="DEU"), c))
        self.assertTrue(S.rule_match(dict(iso3="*", field="geo", match="box:20,51,22,53"), c))
        self.assertFalse(S.rule_match(dict(iso3="*", field="geo", match="circle:10,50,100"), c))
        self.assertTrue(S.rule_match(dict(iso3="*", field="hist", match="Generalgouvernement"), c))
        self.assertTrue(S.rule_match(dict(iso3="POL", field="unit", match="Poland"), c))

    def test_control_pieces_keeps_small_parts_whole(self):
        g = box(0, 0, 10, 10)
        refs = [dict(geom=box(0, 0, 9.9, 10), c="A"), dict(geom=box(9.9, 0, 10, 10), c="B")]
        ctrl = lambda r: dict(gw=r["c"], en=r["c"], zh=None, detail=None, detail_zh=None, type="t", source="s", conf="whole")
        self.assertEqual(len(S.control_pieces(g, refs, ctrl)), 2)       # 1% but over CONTROL_MIN_KM2
        tiny = [dict(geom=box(0, 0, 9.999, 10), c="A"), dict(geom=box(9.999, 0, 10, 10), c="B")]
        pieces = S.control_pieces(g, tiny, ctrl)
        self.assertEqual(len(pieces), 1)
        self.assertIsNone(pieces[0][1])                                  # whole: the unit's own outline


if __name__ == "__main__":
    unittest.main()
