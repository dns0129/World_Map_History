"""The scripts form layers (docs/architecture.md): a module imports only modules of its own layer or below, and the
pipeline imports no build step (it runs them as processes). Every script must be placed in a layer."""
import re
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
LAYERS = [
    ("data", {"common", "added_dates", "controllers", "ww2_territories"}),
    ("library", {"topo", "georef", "mapdata", "ww2_common", "ww2_geo", "cities", "sources"}),
    ("sources", {"fetch_sources", "ww2_fetch", "ww2_ohm", "okh_lage_ost", "lagekarten", "frontlines_west", "frontlines_china",
                 "ccp_areas", "atlas_fronts", "trace/atlas_1945", "trace/ccp_050_332", "trace/china_055_294",
                 "trace/nids"}),
    ("build", {"build_country_series", "build_base_grids", "build_subnational", "build_terrain", "build_yearly",
               "build_database", "ww2_reference", "ww2_histunits", "ww2_snapshots", "ww2_provinces", "ww2_database",
               "ww2_relief", "modern_2026", "add_snapshots"}),
    ("export", {"export_years", "render_maps", "ww2_webmap", "ww2_html", "publish_artifact", "data_release"}),
    ("verify", {"verify_database", "verify_added_snapshots", "verify_geometry", "ww2_coverage"}),
    ("run", {"pipeline"}),
]
# known upward imports, each with its reason
ALLOWED = {
    ("add_snapshots", "ww2_webmap"): "path A writes the map data of its dates with the web map's colours and labels",
}
LEVEL = {m: i for i, (_, mods) in enumerate(LAYERS) for m in mods}


def local_imports(path):
    found = set()
    for m in re.findall(r"^\s*(?:from|import)\s+(\w+)", path.read_text(), re.M):
        for cand in (m, f"{path.parent.name}/{m}"):
            if cand in LEVEL and cand != module_name(path):
                found.add(cand)
    return found


def module_name(path):
    rel = path.relative_to(SCRIPTS).with_suffix("").as_posix()
    return rel


class Layers(unittest.TestCase):
    def test_every_script_has_a_layer(self):
        scripts = {module_name(p) for p in SCRIPTS.rglob("*.py") if "__pycache__" not in p.parts}
        self.assertEqual(sorted(scripts - set(LEVEL)), [], "place the new script in a layer of tests/test_layers.py")
        self.assertEqual(sorted(set(LEVEL) - scripts), [], "a layer lists a script that no longer exists")

    def test_imports_go_down(self):
        bad = []
        for m, level in LEVEL.items():
            for d in local_imports(SCRIPTS / f"{m}.py"):
                if LEVEL[d] > level and (m, d) not in ALLOWED:
                    bad.append(f"{m} ({LAYERS[level][0]}) imports {d} ({LAYERS[LEVEL[d]][0]})")
        self.assertEqual(bad, [])

    def test_pipeline_imports_no_step(self):
        self.assertTrue(all(LEVEL[d] <= 1 for d in local_imports(SCRIPTS / "pipeline.py")))

    def test_data_modules_are_light(self):
        heavy = re.compile(r"^\s*(?:from|import)\s+(numpy|pandas|shapely|rasterio|scipy|pyproj|osmium)\b", re.M)
        for m in LAYERS[0][1]:
            self.assertIsNone(heavy.search((SCRIPTS / f"{m}.py").read_text()), m)


if __name__ == "__main__":
    unittest.main()
