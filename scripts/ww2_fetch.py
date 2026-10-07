"""Download the sources for the 1939-1945 county database into raw/.

  raw/geoboundaries/   geoBoundaries gbOpen ADM1/ADM2/ADM3 (simplified) for every country
  raw/ww2/             US historical counties (Newberry AHCB via USAboundariesData),
                       Konrad Lawson's East Asia 1930-1942 layers, NIKH Korea places,
                       provinces of the 1897 Russian census (heiDATA), British colonial provinces in Africa
                       (Princeton University Library), Swedish counties (Swedish National Archives, via the
                       histmaps R package), Romanian counties of 1930 (geo-spatial.org)
All hosts are GitHub (git, raw and LFS media), except heidata.uni-heidelberg.de for the 1897 provinces,
figgy.princeton.edu for the colonial provinces and geo-spatial.org for the Romanian counties.
"""
import concurrent.futures as cf
import re
import shutil
import subprocess
import time
import urllib.request
import zipfile

from common import RAW

GB = RAW / "geoboundaries"
WW2 = RAW / "ww2"
LAWSON_FILES = [
    "LICENSE.md",
    "tools/cache/taiwan_1930.geojson", "tools/cache/taiwan_1930_shu.geojson",
    "tools/cache/korea_13_provinces_fine.json", "tools/cache/republican-china-provinces-v5.geojson", "tools/cache/adm2_PHL_1939.json",
    "tools/cache/manchukuo-provinces-v2.geojson", "tools/cache/mengjiang-1940.geojson",
    "tools/cache/princely-states-india-1931-v1.2026.8.11.geojson", "tools/cache/kwantung-1935.geojson",
    "tools/cache/ccp-resistance-areas-1941-1942-p199-v2.geojson",
    "deploy/gis/occupied-zone-1942.geojson", "occupation-maps/mengjiang-control-1942.geojson",
    "data/burma/burma-1931-admin-units.geojson", "data/dei/dei-1941-admin.geojson",
    "data/indochina/french-indochina-admin.geojson", "data/nikh-korea/mk_mod_info.zip",
    "data/population/japan-1940.csv", "data/population/korea-1942.csv", "data/population/taiwan-1941.csv",
    "data/population/manchukuo-1943.csv",
]

# Sablin et al., Transcultural Empire GIS (heiDATA doi:10.11588/data/10064, version 3.0): file ids of the
# 1897 shapefile
RU1897_FILES = {2082: "1897RussianEmpire.cpg", 2083: "1897RussianEmpire.dbf", 2084: "1897RussianEmpire.prj",
                2087: "1897RussianEmpire.shp", 2088: "1897RussianEmpire.shx"}


# Princeton University Library, Map and Geospatial Information Center: "conflated historical administrative
# boundaries" of British colonies (GADM outlines conflated with Colonial Office maps), by catalog id
# (https://maps.princeton.edu/catalog/princeton-<id>); the files are served by figgy.princeton.edu
PRINCETON = {
    "nigeria_1934": ("5712mb02k", "1525bc8f-790d-467a-b436-14d860388292/file/66484866-b484-450e-b6d8-175ece3dfb90"),
    "nigeria_1939": ("zp38wh12z", "6469a34a-4f58-4bd4-bf1b-e71bbc09b318/file/b81a75bd-1f00-4823-8460-1aba51e597a5"),
    "zambia_1938": ("m900nx92q", "30e70bc2-8cb5-4fd1-bade-e7fef25672a6/file/e7faf734-316a-4d5a-8605-c58712cedcb5"),
    "uganda_1948": ("kk91fq05g", "d86d87b1-a14e-455c-99a3-0aae4a04c8af/file/537d9416-9c13-4e0e-b282-a8d206c18578"),
    "kenya_1948": ("4j03d315k", "a2386226-a6c1-4d62-a2f8-696c2f4599b8/file/8c0f32d4-2c6c-4e65-84be-1388939e4dc5"),
    "ghana_1948": ("9593tz627", "76666f9b-db7b-4f1e-a604-ffae40ad7d08/file/b206a01b-295d-49cb-8299-a0e7db72ac32"),
    "sierra_leone_1922": ("qf85nf92z", "072fb9ec-ccd8-4a97-8cab-bc983492ba30/file/460f37b4-5c0c-402c-be7c-9e424f78018f"),
}
# Swedish historical boundaries 1600-1990 (Riksarkivet, CC0), as packaged by J. Junkka's histmaps (MIT)
HISTMAPS = "https://raw.githubusercontent.com/junkka/histmaps/3861a14cda6346b710c7e7f42581e0957233d73c/data/geom_sp.rda"
# Romanian counties (judete) of 1930, WGS84 shapefile (geo-spatial.org, CC BY-SA 3.0)
ROMANIA_1930 = "http://geo-spatial.org/vechi/file_download/29417"


def get(url, dest, tries=5):
    for a in range(tries):
        try:
            data = urllib.request.urlopen(url, timeout=300).read()
            dest.write_bytes(data)
            return
        except Exception:
            time.sleep(2 ** a)
    raise RuntimeError(url)


def sparse(url, dest, paths=None):
    if not dest.exists():
        subprocess.run(["git", "clone", "-q", "--depth", "1", "--filter=blob:none", "--no-checkout", url, str(dest)],
                       check=True)
    if paths:
        subprocess.run(["git", "-C", str(dest), "checkout", "-q", "HEAD", "--", *paths], check=True)


def geoboundaries():
    GB.mkdir(parents=True, exist_ok=True)
    src = RAW / "geoboundaries-src"
    sparse("https://github.com/wmgeolab/geoBoundaries", src)
    names = subprocess.run(["git", "-C", str(src), "ls-tree", "-r", "--name-only", "HEAD", "releaseData/gbOpen"],
                           capture_output=True, text=True, check=True).stdout.split()
    files = [n for n in names if re.search(r"/ADM[123]/.*_simplified\.geojson$", n)]

    def one(f):
        dest = GB / f.split("gbOpen/")[1].replace("/", "_")
        if not (dest.exists() and dest.stat().st_size > 200):
            get("https://media.githubusercontent.com/media/wmgeolab/geoBoundaries/main/" + f, dest)

    with cf.ThreadPoolExecutor(12) as ex:
        list(ex.map(one, files))
    print("geoBoundaries files:", len(files))


def russia_1897():
    dest = WW2 / "russia1897"
    dest.mkdir(exist_ok=True)
    for fid, name in RU1897_FILES.items():
        if not (dest / name).exists():
            get(f"https://heidata.uni-heidelberg.de/api/access/datafile/{fid}", dest / name)


def zipped(url, dest):
    """Download a zipped shapefile and unpack it into dest (skipping macOS metadata)."""
    if dest.exists() and any(dest.rglob("*.shp")):
        return
    dest.mkdir(parents=True, exist_ok=True)
    z = dest / "download.zip"
    get(url, z)
    with zipfile.ZipFile(z) as f:
        for n in f.namelist():
            if "__MACOSX" not in n and not n.endswith("/"):
                (dest / n.split("/")[-1]).write_bytes(f.read(n))
    z.unlink()


def colonial_and_europe():
    for key, (_, path) in PRINCETON.items():
        zipped("https://figgy.princeton.edu/downloads/" + path, WW2 / "princeton" / key)
    if not (WW2 / "sweden_geom_sp.rda").exists():
        get(HISTMAPS, WW2 / "sweden_geom_sp.rda")
    zipped(ROMANIA_1930, WW2 / "romania1930")


def main():
    WW2.mkdir(parents=True, exist_ok=True)
    geoboundaries()
    russia_1897()
    colonial_and_europe()
    base = "https://raw.githubusercontent.com/ropensci/USAboundariesData/master/data-raw/historical/"
    for f in ("histcounties.geojson", "histstates.geojson"):
        if not (WW2 / f"us_{f}").exists():
            get(base + f, WW2 / f"us_{f}")
    src = RAW / "lawson-src"
    sparse("https://github.com/kmlawson/japanese-empire-student-map", src, LAWSON_FILES)
    (WW2 / "lawson").mkdir(exist_ok=True)
    for f in LAWSON_FILES:
        shutil.copy(src / f, WW2 / "lawson" / f.split("/")[-1])
    with zipfile.ZipFile(WW2 / "lawson" / "mk_mod_info.zip") as z:
        for n in z.namelist():
            if n.startswith("place_modern_open."):
                (WW2 / "lawson" / n).write_bytes(z.read(n))
    print("done")


if __name__ == "__main__":
    main()
