"""The built data (databases, map data, exports, yearly maps) as attachments of a GitHub release instead of in git.

  python3 scripts/data_release.py fetch [ARCHIVE ...]
                                               download the release named in data_release.json (all archives, or
                                               those named), unpack it and check every file against its sha256
                                               (an archive whose files are all right already is skipped)
  python3 scripts/data_release.py check        the data in the working tree against data_release.json
  python3 scripts/data_release.py manifest TAG data_release.json := this working tree's data, to be released as TAG
  python3 scripts/data_release.py stage        push the data as data-staging/<tag> for the release workflow
  python3 scripts/data_release.py pack DIR     the archives of the release (one per entry of DATASETS) in DIR;
                                               stops when the working tree differs from data_release.json

data_release.json holds the release tag, the archives, and the sha256 and size of every file in them; it is the
only part of the data in git (.gitignore leaves the data paths out). A new release:
  1. rebuild, then python3 scripts/data_release.py manifest data-<date> and commit the manifest
  2. python3 scripts/data_release.py stage: a commit with the data on top of HEAD, made in a separate index (the
     working tree and the branch stay as they are; switching to a branch that tracks the data and back would
     delete the data files), pushed as data-staging/<tag>. The workflow .github/workflows/data-release.yml packs
     it, checks it against the manifest, makes the release (its tag on HEAD, which has no data) and deletes the
     branch, so the data never stays in the history
"""
import argparse
import gzip
import hashlib
import io
import json
import os
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT  # noqa: E402

MANIFEST = ROOT / "data_release.json"
REPO = "dns0129/World_Map_History"
# archive name -> (directory, glob); maps/1942.png stays in git (the README shows it)
DATASETS = {
    "db.tar.gz": ("db", "*.sqlite"),
    "ww2-maps-data.tar.gz": ("ww2/maps/data", "**/*"),
    "exports.tar.gz": ("exports", "**/*"),
    "maps.tar.gz": ("maps", "*.png"),
}
KEEP = {"maps/1942.png"}


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def files_of(archive):
    folder, pattern = DATASETS[archive]
    return sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / folder).glob(pattern)
                  if p.is_file() and p.relative_to(ROOT).as_posix() not in KEEP)


def make_manifest(tag):
    assets = {}
    for archive in DATASETS:
        assets[archive] = {p: {"sha256": sha256(ROOT / p), "size": (ROOT / p).stat().st_size} for p in files_of(archive)}
    return {"tag": tag, "repo": REPO, "assets": assets}


def differences(man):
    """Paths whose file is missing or differs from the manifest, and data files the manifest does not list."""
    bad = [p for files in man["assets"].values() for p, f in files.items()
           if not (ROOT / p).exists() or (ROOT / p).stat().st_size != f["size"] or sha256(ROOT / p) != f["sha256"]]
    extra = [p for archive in DATASETS for p in files_of(archive) if p not in man["assets"].get(archive, {})]
    return bad, extra


def pack(out):
    """Archives with fixed metadata (names sorted, mtime 0, no owner), so packing the same files gives the same bytes."""
    out.mkdir(parents=True, exist_ok=True)
    man = json.loads(MANIFEST.read_text())
    bad, extra = differences(man)
    if bad or extra:
        raise SystemExit(f"the working tree differs from {MANIFEST.name}: {(bad + extra)[:5]} ... ({len(bad + extra)})")
    for archive, files in man["assets"].items():
        with open(out / archive, "wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0, compresslevel=6) as gz, \
                tarfile.open(fileobj=gz, mode="w", format=tarfile.PAX_FORMAT) as tar:
            for p in sorted(files):
                info = tarfile.TarInfo(p)
                info.size, info.mode, info.mtime = (ROOT / p).stat().st_size, 0o644, 0
                with open(ROOT / p, "rb") as f:
                    tar.addfile(info, f)
        print(out / archive, f"{(out / archive).stat().st_size / 1e6:.1f} MB, {len(files)} files")


def fetch(only=()):
    man = json.loads(MANIFEST.read_text())
    for archive, files in man["assets"].items():
        if only and archive not in only:
            continue
        need = [p for p, f in files.items()
                if not (ROOT / p).exists() or (ROOT / p).stat().st_size != f["size"] or sha256(ROOT / p) != f["sha256"]]
        if not need:
            print(archive, "up to date")
            continue
        url = f"https://github.com/{man['repo']}/releases/download/{man['tag']}/{archive}"
        print("download", url, flush=True)
        data = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "World_Map_History"}),
                                      timeout=600).read()
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
            for m in tar.getmembers():
                if m.name not in files or not m.isfile():
                    raise SystemExit(f"{archive}: unexpected member {m.name}")
                dest = ROOT / m.name
                dest.parent.mkdir(parents=True, exist_ok=True)
                tmp = dest.with_name(dest.name + ".part")
                tmp.write_bytes(tar.extractfile(m).read())
                if sha256(tmp) != files[m.name]["sha256"]:
                    tmp.unlink()
                    raise SystemExit(f"{m.name}: sha256 differs from {MANIFEST.name}")
                os.replace(tmp, dest)
        print(archive, len(files), "files")


def stage():
    """Push HEAD plus the data files as data-staging/<tag> without touching the working tree or the branch."""
    man = json.loads(MANIFEST.read_text())
    bad, extra = differences(man)
    if bad or extra:
        raise SystemExit(f"the working tree differs from {MANIFEST.name}: {(bad + extra)[:5]} ... ({len(bad + extra)})")
    def git(*a, **kw):
        return subprocess.run(["git", *a], cwd=ROOT, check=True, capture_output=True, text=True, **kw).stdout.strip()
    if git("status", "--porcelain", "--", MANIFEST.name):
        raise SystemExit(f"commit {MANIFEST.name} first: the release is tagged on HEAD")
    index = ROOT / ".git" / "data-release-index"
    env = dict(os.environ, GIT_INDEX_FILE=str(index))
    try:
        git("read-tree", "HEAD", env=env)
        paths = [p for files in man["assets"].values() for p in files]
        for i in range(0, len(paths), 200):
            git("add", "-f", "--", *paths[i:i + 200], env=env)
        tree = git("write-tree", env=env)
    finally:
        index.unlink(missing_ok=True)
    commit = git("commit-tree", tree, "-p", "HEAD", "-m", f"data for the release {man['tag']}")
    branch = f"data-staging/{man['tag']}"
    subprocess.run(["git", "push", "origin", f"{commit}:refs/heads/{branch}"], cwd=ROOT, check=True)
    print(f"pushed {branch} ({commit[:10]}): the workflow makes the release {man['tag']} and deletes the branch")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["fetch", "check", "manifest", "pack", "stage"])
    ap.add_argument("args", nargs="*")
    args = ap.parse_args()
    if args.command == "fetch":
        fetch(args.args)
    elif args.command == "check":
        bad, extra = differences(json.loads(MANIFEST.read_text()))
        for p in bad:
            print("differs from the manifest:", p)
        for p in extra:
            print("not in the manifest:", p)
        print("data:", "as in" if not bad and not extra else "DIFFERENT from", MANIFEST.name)
        sys.exit(1 if bad or extra else 0)
    elif args.command == "manifest":
        if len(args.args) != 1:
            raise SystemExit("give the release tag, e.g. data-2026-10-23")
        man = make_manifest(args.args[0])
        MANIFEST.write_text(json.dumps(man, indent=1, sort_keys=True) + "\n")
        n = sum(len(f) for f in man["assets"].values())
        size = sum(x["size"] for f in man["assets"].values() for x in f.values())
        print(f"wrote {MANIFEST.name}: {args.args[0]}, {n} files, {size / 1e6:.1f} MB")
    elif args.command == "stage":
        stage()
    else:
        pack(Path(args.args[0] if args.args else "dist"))


if __name__ == "__main__":
    main()
