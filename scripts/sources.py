"""The pinned versions of the downloaded sources (sources.json) and a check of raw/ against them.

The download scripts (fetch_sources.py, ww2_fetch.py, ww2_ohm.py) take every git commit, branch file and planet
file from sources.json instead of "the newest", so that a rebuild reads the same data as the build it repeats
(an OpenHistoricalMap planet of another day moves province outlines; a geoBoundaries commit of another month
moves coastlines).

  python3 sources.py --check     digest of each folder of raw/ against sources.json (exit 1 on a difference)
  python3 sources.py --record    write the digests of the folders as they are now (after a deliberate update
                                 of a source: change its commit or file in sources.json, download, record)
"""
import argparse
import hashlib
import json
import sys

from common import RAW, ROOT

MANIFEST = ROOT / "sources.json"


def load():
    return json.loads(MANIFEST.read_text())


def commit(name):
    """The pinned commit of a git source (sources.json "git")."""
    return load()["git"][name]["commit"]


def digest(folder):
    """sha256 over the relative path and content of every file of a folder (git checkouts and partial downloads
    left out), or of one file."""
    path = RAW / folder
    files = [path] if path.is_file() else sorted(p for p in path.rglob("*") if p.is_file()
                                                   and ".git" not in p.parts and not p.name.endswith(".part")
                                                   and p.suffix != ".idx")
    h = hashlib.sha256()
    for p in files:
        f = hashlib.sha256()
        with open(p, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 22), b""):
                f.update(chunk)
        h.update(f"{p.relative_to(RAW)}\0{f.hexdigest()}\n".encode())
    return h.hexdigest(), len(files)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--record", action="store_true")
    args = ap.parse_args()
    m = load()
    bad = 0
    for folder, rec in m["digests"].items():
        if not (RAW / folder).exists():
            print(f"{folder}: missing (download it first)")
            bad += 1
            continue
        d, n = digest(folder)
        if args.record:
            m["digests"][folder] = dict(sha256=d, files=n)
            print(f"{folder}: {n} files recorded")
        elif d != rec["sha256"] or n != rec["files"]:
            print(f"{folder}: DIFFERS ({n} files, recorded {rec['files']})")
            bad += 1
        else:
            print(f"{folder}: ok ({n} files)")
    for name, g in m["git"].items():
        head = RAW / g["dest"] / ".git"
        if head.exists():
            import subprocess
            cur = subprocess.run(["git", "-C", str(RAW / g["dest"]), "rev-parse", "HEAD"], capture_output=True,
                                 text=True).stdout.strip()
            ok = cur == g["commit"]
            bad += not ok and not args.record
            print(f"{name}: {'ok' if ok else 'at ' + cur[:12] + ', pinned ' + g['commit'][:12]}")
    if args.record:
        MANIFEST.write_text(json.dumps(m, indent=1, ensure_ascii=False) + "\n")
    sys.exit(1 if bad and not args.record else 0)


if __name__ == "__main__":
    main()
