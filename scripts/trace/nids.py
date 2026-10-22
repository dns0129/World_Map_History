"""Download the appendix maps of the Senshi Sosho (National Institute for Defense Studies, Japan) that the curated
tracings were read on, into raw/trace/nids/<file>.jpg, checked against the sha256 in sources.json ("nids").

  python3 scripts/trace/nids.py              every map listed in sources.json
  python3 scripts/trace/nids.py 050_332      one map

The image is served only within a session that has opened the volume's page and the appendix page: the volume
page (SoshoView?kanno=<vol>) and the appendix page (SoshoAppendixView?no=<vol>&f=<file>.jpg) are visited first,
keeping the session cookie, then GetImage?sa=<vol>/appendix/<file>.jpg is fetched with the appendix page as
Referer; the server sometimes answers with an HTML page instead, so this is tried up to four times.
"""
import hashlib
import http.cookiejar
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common import RAW  # noqa: E402
from sources import load  # noqa: E402

BASE = "https://www.nids.mod.go.jp/military_history_search"
OUT = RAW / "trace" / "nids"


def fetch(name):
    """raw/trace/nids/<name>.jpg (name: <volume>_<file number>, e.g. 050_332)."""
    want = load()["nids"][name]["sha256"]
    path = OUT / f"{name}.jpg"
    if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == want:
        return path
    OUT.mkdir(parents=True, exist_ok=True)
    vol = name.split("_")[0]
    page = f"{BASE}/SoshoAppendixView?no={vol}&f={name}.jpg"
    for attempt in range(4):
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        opener.addheaders = [("User-Agent", "World_Map_History build (trace/nids.py)")]
        opener.open(f"{BASE}/SoshoView?kanno={vol}", timeout=60).read()
        opener.open(page, timeout=60).read()
        req = urllib.request.Request(f"{BASE}/GetImage?sa={vol}/appendix/{name}.jpg", headers={"Referer": page})
        data = opener.open(req, timeout=300).read()
        if data[:3] == b"\xff\xd8\xff":  # a JPEG, not the error page
            if hashlib.sha256(data).hexdigest() != want:
                raise SystemExit(f"{name}: the served image is not the one sources.json pins")
            path.write_bytes(data)
            return path
        time.sleep(3)
    raise SystemExit(f"{name}: no image after four attempts")


def main():
    for name in sys.argv[1:] or load()["nids"]:
        print(fetch(name))


if __name__ == "__main__":
    main()
