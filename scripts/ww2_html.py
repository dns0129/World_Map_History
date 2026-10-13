"""Write ww2/maps/index.html and one page per snapshot from ww2/maps/template.html.

The MapLibre stylesheet is inlined (the published page may load styles only
from Google Fonts); the script is vendored and falls back to public CDNs.
Each per-date page opens on its own snapshot and can switch to the others.
"""
import shutil
import struct

from PIL import Image

from common import WORK
from added_dates import SNAPSHOTS_ADDED
from ww2_common import SNAPSHOTS_EARLY, SNAPSHOTS_POSTWAR, SNAPSHOTS_WW2, WW2_OUT

MAPS = WW2_OUT / "maps"


def pack_png(data, dst, width=1024):
    """data as the pixels of an opaque RGB PNG: 4-byte length, 4-byte sum of the bytes (mod 2**32), the bytes."""
    raw = struct.pack(">II", len(data), sum(data) & 0xFFFFFFFF) + data
    height = -(-len(raw) // (3 * width))
    raw += bytes(3 * width * height - len(raw))
    Image.frombytes("RGB", (width, height), raw).save(dst, compress_level=1)


def main():
    tpl = (MAPS / "template.html").read_text()
    css = (MAPS / "vendor" / "maplibre-gl.css").read_text()
    tpl = tpl.replace("/*__MAPLIBRE_CSS__*/", css)
    head = ('<!doctype html>\n<html lang="zh-CN">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n')
    dates = sorted(SNAPSHOTS_EARLY + SNAPSHOTS_ADDED + SNAPSHOTS_WW2 + SNAPSHOTS_POSTWAR)
    pages = [("index.html", "1942-11-01")] + [(f"{d}.html", d) for d, _, _ in dates
                                               if (MAPS / "data" / f"snap-{d}.json").exists()]
    if (MAPS / "data" / "snap-2026.json").exists():
        pages.append(("2026.html", "2026"))
    for name, snap in pages:
        body = tpl.replace("__DEFAULT_SNAPSHOT__", snap)
        (MAPS / name).write_text(head + body + "\n</html>\n")
        print(MAPS / name)
    # work/artifact/: the page as published on claude.ai. The host supplies the document skeleton itself and
    # serves only text and media types, so the binary data files go along packed into the pixels of a lossless
    # PNG (<name>.png, which the page asks for when <name>.bin is missing; base64 would add a third to their
    # size); the relief sheets and the vendored script are published as they are
    out = WORK / "artifact"
    shutil.rmtree(out, ignore_errors=True)
    (out / "data" / "glyphs" / "sans").mkdir(parents=True)
    (out / "index.html").write_text(tpl.replace("__DEFAULT_SNAPSHOT__", "1942-11-01"))
    data = MAPS / "data"
    for f in sorted(data.glob("*.json")):
        shutil.copy(f, out / "data" / f.name)
    for f in sorted(data.glob("*.bin")) + sorted((data / "glyphs" / "sans").glob("*.pbf")):
        pack_png(f.read_bytes(), out / f.relative_to(MAPS).with_suffix(".png"))
    print(out)


if __name__ == "__main__":
    main()
