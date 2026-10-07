"""OpenHistoricalMap: download the planet file and extract dated administrative areas.

Keeps every boundary=administrative relation (admin_level 3-8) whose start_date/end_date
overlap 1900-01-01 .. 1945-09-02 (the earliest to the latest snapshot), assembled into
(multi)polygons.

  python3 ww2_ohm.py            download the newest planet (about 1.3 GB) and extract
  python3 ww2_ohm.py <planet>   extract from a planet file already on disk

Output: raw/ohm/areas_1900_45.jsonl, one JSON object per line: id, tags, wkb (hex).
Needs: pip install osmium
"""
import json
import re
import sys
import urllib.request

import osmium

from common import RAW

BUCKET = "https://s3.amazonaws.com/planet.openhistoricalmap.org"   # listing
FILES = "https://planet.openhistoricalmap.org"   # downloads (CloudFront; the bucket refuses direct GETs)
OUT = RAW / "ohm"
FIRST, LAST = "1900-01-01", "1945-09-02"


def latest_planet():
    """Newest planet-YYMMDD_HHMM.osm.pbf in the public bucket (older ones are archived)."""
    keys = []
    after = "planet/planet-25"
    while True:
        url = f"{BUCKET}/?list-type=2&prefix=planet/planet-&start-after={after}"
        page = urllib.request.urlopen(url, timeout=60).read().decode()
        found = re.findall(r"<Key>(planet/planet-\d{6}_\d{4}\.osm\.pbf)</Key>", page)
        allk = re.findall(r"<Key>([^<]+)</Key>", page)
        keys += found
        if "<IsTruncated>true</IsTruncated>" not in page or not allk:
            break
        after = allk[-1]
    return sorted(keys)[-1]


def date_of(d, end=False):
    if not d:
        return None
    m = re.match(r"^~?(-?\d{1,4})(?:-(\d{2}))?(?:-(\d{2}))?", d.strip())
    if not m:
        return None
    y, mo, da = int(m.group(1)), m.group(2), m.group(3)
    return f"{y:04d}-{mo or ('12' if end else '01')}-{da or ('31' if end else '01')}"


class Wanted(osmium.SimpleHandler):
    """Ids of administrative relations in force at some time in the window."""

    def __init__(self):
        super().__init__()
        self.ids = set()

    def relation(self, r):
        t = r.tags
        if t.get("boundary") != "administrative" or t.get("admin_level") not in tuple("345678"):
            return
        sd, ed = date_of(t.get("start_date")), date_of(t.get("end_date"), True)
        if sd and sd <= LAST and (ed is None or ed >= FIRST):
            self.ids.add(r.id)


def extract(planet):
    w = Wanted()
    w.apply_file(str(planet))
    print("relations in force 1900-1945:", len(w.ids), flush=True)
    wkb = osmium.geom.WKBFactory()
    n = bad = 0
    idx = osmium.index.create_map("sparse_file_array," + str(OUT / "nodes.idx"))
    fp = osmium.FileProcessor(str(planet)).with_locations(idx) \
        .with_areas(osmium.filter.TagFilter(("boundary", "administrative")))
    with open(OUT / "areas_1900_45.jsonl", "w") as out:
        for o in fp:
            if isinstance(o, osmium.osm.Area) and not o.from_way() and o.orig_id() in w.ids:
                try:
                    g = wkb.create_multipolygon(o)
                except Exception:
                    bad += 1
                    continue
                out.write(json.dumps({"id": o.orig_id(), "tags": {k.k: k.v for k in o.tags}, "wkb": g}) + "\n")
                n += 1
    (OUT / "nodes.idx").unlink(missing_ok=True)
    print("areas:", n, "not assembled (broken relations):", bad)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    if len(sys.argv) > 1:
        planet = sys.argv[1]
    else:
        key = latest_planet()
        planet = OUT / key.split("/")[-1]
        if not planet.exists():
            print("downloading", key, flush=True)
            urllib.request.urlretrieve(f"{FILES}/{key}", planet)
    extract(planet)


if __name__ == "__main__":
    main()
