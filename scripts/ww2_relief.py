"""Shaded relief for the 1939-1945 maps (ww2/maps/data/relief/).

Elevation: Mapzen/AWS Terrarium tiles at zoom 5 (about 4.9 km per pixel at the equator),
already in Web Mercator, mosaicked to one 8192 x 8192 grid. Land: Natural Earth 10m land
and minor islands.

Two rasters, each written as a pyramid of zoom levels 0-5 cut into 2048-pixel WebP sheets
(the map page slices them into 256-pixel tiles itself, so the published files stay few):

  r<z>_<col>_<row>.webp   colour relief: hypsometric tints (green lowlands, tan uplands,
                          rose-brown high mountains) multiplied by a hillshade; sea transparent
  s<z>_<col>_<row>.webp   shading alone (dark shadows and pale highlights with alpha), drawn
                          over the political colours so the mountains show through them
  d<z>_<col>_<row>.webp   elevation for the 3D terrain, zoom levels 0-6 (Terrarium tiles at zoom 6,
                          about 2.4 km per pixel at the equator): Terrarium encoding (metres + 32768 =
                          red * 256 + green), whole metres, the sea at 0, lossless; sheets with no land
                          are left out (the page treats them as flat)

A sheet whose pixels come out the same as the file already there is not written again.
"""
import json
import math

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

from common import RAW
from fetch_sources import TERRARIUM, fetch
from ww2_common import WW2_OUT

OUT = WW2_OUT / "maps" / "data" / "relief"
Z = 5                      # elevation zoom: 32 x 32 tiles of 256 px
N = 256 * 2 ** Z
SHEET = 2048
LAT_MAX = 85.0511287798
EXAGGERATION = 7.0         # vertical exaggeration: at 5 km per pixel real slopes look flat
ZENITH = math.radians(48)

# hypsometric tints (metres -> RGB): pale green lowlands, cream and tan uplands,
# rose-brown high mountains, pale tops above 6000 m
TINTS = [(-500, (214, 226, 196)), (0, (218, 229, 199)), (150, (226, 232, 203)), (400, (236, 235, 208)),
         (800, (238, 230, 196)), (1300, (230, 214, 172)), (2000, (217, 194, 150)), (2800, (202, 172, 136)),
         (3600, (190, 156, 132)), (4500, (184, 152, 140)), (5500, (204, 186, 180)), (7000, (232, 226, 222))]


def mosaic(z=Z):
    jobs = [(TERRARIUM.format(z=z, x=x, y=y), RAW / "terrarium" / str(z) / f"{x}_{y}.png") for x in range(2 ** z)
            for y in range(2 ** z)]
    import concurrent.futures as cf
    with cf.ThreadPoolExecutor(8) as ex:
        list(ex.map(lambda j: fetch(j[0], j[1], 100), jobs))
    n = 256 * 2 ** z
    elev = np.zeros((n, n), np.float32)
    for x in range(2 ** z):
        for y in range(2 ** z):
            a = np.asarray(Image.open(RAW / "terrarium" / str(z) / f"{x}_{y}.png").convert("RGB"), dtype=np.float32)
            elev[y * 256:(y + 1) * 256, x * 256:(x + 1) * 256] = a[..., 0] * 256 + a[..., 1] + a[..., 2] / 256 - 32768
    return elev


def save_sheet(img, path, **kw):
    """Write a sheet unless the file there already has the same pixels (encoders may differ byte by byte)."""
    if path.exists():
        with Image.open(path) as old:
            if old.size == img.size and old.mode == img.mode and np.array_equal(np.asarray(old), np.asarray(img)):
                return
    img.save(path, "WEBP", **kw)


def merc_px(lon, lat):
    lat = np.clip(lat, -LAT_MAX, LAT_MAX)
    x = (np.asarray(lon) + 180) / 360 * N
    y = (1 - np.log(np.tan(np.pi / 4 + np.radians(lat) / 2)) / np.pi) / 2 * N
    return x, y


def land_mask():
    img = Image.new("L", (N, N), 0)
    d = ImageDraw.Draw(img)
    for layer in ("ne_10m_land", "ne_10m_minor_islands"):
        path = RAW / "naturalearth" / f"{layer}.geojson"
        if not path.exists():
            fetch(f"https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/{layer}.geojson", path, 1000)
        for f in json.load(open(path))["features"]:
            g = f["geometry"]
            polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
            for rings in polys:
                for k, ring in enumerate(rings):
                    c = np.asarray(ring)
                    x, y = merc_px(c[:, 0], c[:, 1])
                    d.polygon(list(zip(x.tolist(), y.tolist())), fill=255 if k == 0 else 0)
    return np.asarray(img, dtype=np.float32) / 255


def hillshade(elev):
    """Hillshade in Web Mercator: ground pixel size shrinks with cos(latitude)."""
    rows = np.arange(N) + 0.5
    lat = np.degrees(np.arctan(np.sinh(np.pi * (1 - 2 * rows / N))))
    px_m = (2 * math.pi * 6378137 / N) * np.cos(np.radians(lat))
    e = ndimage.gaussian_filter(np.maximum(elev, -50), 0.6) * EXAGGERATION
    gy, gx = np.gradient(e)          # gx: rise to the east, gy: rise to the south (rows run south)
    gx /= px_m[:, None]
    gy /= px_m[:, None]
    norm = np.sqrt(gx * gx + gy * gy + 1)
    out = np.zeros_like(e)
    # light mostly from the north-west, softened by two neighbouring directions
    for az, w in ((315, 0.6), (270, 0.2), (0, 0.2)):
        a = math.radians(az)
        le, ln, lu = math.sin(a) * math.sin(ZENITH), math.cos(a) * math.sin(ZENITH), math.cos(ZENITH)
        out += w * (-gx * le + gy * ln + lu) / norm
    return np.clip(out, 0, 1)


def tint(elev):
    zs = np.array([t[0] for t in TINTS], np.float32)
    rgb = np.stack([np.interp(elev, zs, np.array([t[1][i] for t in TINTS], np.float32)) for i in range(3)], -1)
    return rgb


def write_pyramid(rgba, prefix):
    OUT.mkdir(parents=True, exist_ok=True)
    img = Image.fromarray(rgba, "RGBA").convert("RGBa")
    for z in range(Z, -1, -1):
        size = 256 * 2 ** z
        lvl = img if size == N else img.resize((size, size), Image.LANCZOS)
        lvl = lvl.convert("RGBA")
        k = max(1, size // SHEET)
        for i in range(k):
            for j in range(k):
                sheet = lvl.crop((i * SHEET, j * SHEET, i * SHEET + min(size, SHEET), j * SHEET + min(size, SHEET)))
                save_sheet(sheet, OUT / f"{prefix}{z}_{i}_{j}.webp", quality=84, alpha_quality=90, method=6)
        print(prefix, z, size, k * k, "sheets", flush=True)


DEM_Z = 6


def dem_sheets():
    """Elevation for the page's 3D terrain: Terrarium-encoded lossless sheets, zoom 0-6, sea at 0 m."""
    e = np.maximum(mosaic(DEM_Z), 0)
    for z in range(DEM_Z, -1, -1):
        size = 256 * 2 ** z
        f = e.shape[0] // size
        lvl = e if f == 1 else e.reshape(size, f, size, f).mean(axis=(1, 3))  # mean of the finer pixels
        v = np.round(lvl).astype(np.int32) + 32768
        rgb = np.stack([v // 256, v % 256, np.zeros_like(v)], -1).astype(np.uint8)
        k = max(1, size // SHEET)
        kept = 0
        for i in range(k):
            for j in range(k):
                block = (slice(j * SHEET, j * SHEET + min(size, SHEET)), slice(i * SHEET, i * SHEET + min(size, SHEET)))
                path = OUT / f"d{z}_{i}_{j}.webp"
                if not (lvl[block] > 0).any():
                    path.unlink(missing_ok=True)  # open sea: flat
                    continue
                save_sheet(Image.fromarray(rgb[block]), path, lossless=True, quality=100, method=6)
                kept += 1
        print("d", z, size, kept, "sheets", flush=True)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    dem_sheets()
    elev = mosaic()
    land = land_mask()
    hs = hillshade(elev)
    flat = math.cos(ZENITH)
    rel = hs - flat
    # colour relief: tint darkened in shadow and lifted on sunny slopes
    shade = np.clip(1 + 1.25 * rel, 0.42, 1.18)
    rgb = np.clip(tint(np.maximum(elev, 0)) * shade[..., None], 0, 255)
    alpha = ndimage.gaussian_filter(land, 0.5)
    rgba = np.dstack([rgb, alpha * 255]).astype(np.uint8)
    write_pyramid(rgba, "r")
    # shading alone: black shadows and white highlights, alpha by strength, land only
    a_sh = np.clip(-rel * 2.2, 0, 0.85)
    a_hi = np.clip(rel * 1.4, 0, 0.35)
    v = np.where(a_sh > a_hi, 0, 255).astype(np.uint8)
    a = np.maximum(a_sh, a_hi) * alpha * 255
    write_pyramid(np.dstack([v, v, v, a.astype(np.uint8)]), "s")
    total = sum(p.stat().st_size for p in OUT.iterdir())
    print(f"relief: {len(list(OUT.iterdir()))} files, {total / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
