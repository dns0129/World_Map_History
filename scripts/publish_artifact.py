"""Plan the upload of the web map to its claude.ai artifact: only the files that changed since the last publish.

  python3 scripts/publish_artifact.py                 compare with the manifest, write the batches, print the plan
  python3 scripts/publish_artifact.py --remote F      also remove published paths not built any more (F: one
                                                      published path per line, from the artifact's file listing)
  python3 scripts/publish_artifact.py --record        after the batches were published: the manifest := this build

Published files (path on the artifact <- source):
  index.html, data/*.json, data/*.png, data/glyphs/sans/*.png   <- work/artifact/ (ww2_html.py)
  data/relief/*.webp                                            <- ww2/maps/data/relief/
  vendor/maplibre-gl.js                                         <- ww2/maps/vendor/

The manifest ww2/maps/published.json holds the sha256 of every file as last published. Changed and new files go
into work/publish/batch-<n>.json ({published path: source path}, the `files` of one publish call), each under
BATCH_MB because one publish carries at most 64 MB; files no longer built map to null. The files the page reads
first and that tie the others together (data/index.json, data/added-build.json, data/admin.png, index.html) go in
the last batch, so a page loaded halfway through still sees the old set. The whole set must stay under
TOTAL_MB (an artifact version holds at most 256 MB).
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT  # noqa: E402

MAPS = ROOT / "ww2" / "maps"
WORK = ROOT / "work"
MANIFEST = MAPS / "published.json"
OUT = WORK / "publish"
BATCH_MB, TOTAL_MB = 60, 250
LAST = ("data/admin.png", "data/added-build.json", "data/index.json", "index.html")


def published():
    """{published path: source path} of this build."""
    art = WORK / "artifact"
    if not (art / "index.html").exists():
        raise SystemExit("work/artifact/ is missing - run python3 scripts/ww2_html.py first")
    files = {f.relative_to(art).as_posix(): f for f in sorted(art.rglob("*")) if f.is_file()}
    files.update({f"data/relief/{f.name}": f for f in sorted((MAPS / "data" / "relief").glob("*.webp"))})
    files["vendor/maplibre-gl.js"] = MAPS / "vendor" / "maplibre-gl.js"
    return files


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_batches(changed, gone, sizes, sources, limit=BATCH_MB * 1e6):
    """The publish calls: {published path: source, or None to remove}, each under `limit` bytes; the changed paths in
    order, those of LAST and the removals in the last call."""
    first = [p for p in changed if p not in LAST]
    last = [p for p in LAST if p in changed]
    batches, cur, size = [], {}, 0
    for p in first:
        if cur and size + sizes[p] > limit:
            batches.append(cur)
            cur, size = {}, 0
        cur[p] = sources[p]
        size += sizes[p]
    if cur:
        batches.append(cur)
    tail = {p: sources[p] for p in last}
    tail.update({p: None for p in sorted(gone)})
    if tail:
        if batches and sum(sizes[p] for p in last) + size <= limit:
            batches[-1].update(tail)
        else:
            batches.append(tail)
    return batches


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--remote", type=Path)
    ap.add_argument("--record", action="store_true")
    args = ap.parse_args()
    files = published()
    sums = {p: sha256(f) for p, f in files.items()}
    total = sum(f.stat().st_size for f in files.values())
    print(f"{len(files)} files, {total / 1e6:.1f} MB")
    if total > TOTAL_MB * 1e6:
        raise SystemExit(f"over {TOTAL_MB} MB: an artifact version holds at most 256 MB")
    if args.record:
        MANIFEST.write_text(json.dumps(sums, indent=0, sort_keys=True) + "\n")
        print("recorded", MANIFEST.relative_to(ROOT))
        return
    old = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}
    changed = [p for p in files if old.get(p) != sums[p]]
    gone = set(old) - set(files)
    if args.remote:
        gone |= {line.strip() for line in args.remote.read_text().splitlines() if line.strip()} - set(files)
    gone.discard("index.html")
    sizes = {p: f.stat().st_size for p, f in files.items()}
    sources = {p: str(f.relative_to(ROOT)) for p, f in files.items()}
    batches = make_batches(changed, gone, sizes, sources)
    OUT.mkdir(parents=True, exist_ok=True)
    for f in OUT.glob("batch-*.json"):
        f.unlink()
    for i, b in enumerate(batches, 1):
        path = OUT / f"batch-{i}.json"
        path.write_text(json.dumps(b, indent=1))
        mb = sum(files[p].stat().st_size for p, s in b.items() if s) / 1e6
        print(f"{path.relative_to(ROOT)}: {sum(1 for s in b.values() if s)} files, {mb:.1f} MB"
              f"{f', {sum(1 for s in b.values() if s is None)} removed' if None in b.values() else ''}")
    if not batches:
        print("nothing changed since the last publish")
    else:
        print("publish the batches in order (Artifact publish, files = the batch, root = the repository), "
              "then: python3 scripts/publish_artifact.py --record")


if __name__ == "__main__":
    main()
