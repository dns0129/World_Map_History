"""Build the 1900-1991 province-level sets and the interactive maps, resumably and within the memory limit.

Every step of every set (and every date of the per-date steps) is a job run as a process of its own:

  <set>:prepare           candidate units                         ww2_histunits.py --prepare
  <set>:part:<date>       divisions in force on the date           ww2_histunits.py --part DATE
  <set>:merge             distinct units of all dates              ww2_histunits.py --merge
  <set>:snapshot:<date>   control and population on the date       ww2_snapshots.py DATE
  <set>:province:<date>   provinces of the date                    ww2_provinces.py --date DATE
  <set>:provinces         province units and pieces of all dates   ww2_provinces.py --merge
  <set>:database          db/*.sqlite                              ww2_database.py
  <set>:coverage          ww2/coverage*.csv                        ww2_coverage.py
  relief, modern          relief sheets, the 2026 tab              ww2_relief.py, modern_2026.py
  webmap, html            ww2/maps                                 ww2_webmap.py, ww2_html.py

for the sets ww2 (1939-45), early (1900-34) and postwar (1946-91).

Skipping. A job records a fingerprint when it succeeds (work/pipeline/stamps/): the content of its script
and of every local module the script imports, the content of the work files it reads (outputs of earlier
jobs; hashes cached by size and time) and the size and time of the downloaded sources it reads. A job whose
fingerprint is unchanged and whose outputs exist is skipped, so running this again after an interruption (a
container restart, a killed process) carries on where the build stopped, and a job whose inputs came out the
same as before is not repeated.

Memory. Jobs run side by side while the memory they are expected to need fits within the limit (the
cgroup's, see ww2_common.memory_limit_gb). The expectation is the peak measured on earlier runs
(work/pipeline/stats.json), or a default per step. A job killed for memory (SIGKILL) is run again on its own
with a larger expectation; any other failure stops the run, and the end of the job's log is printed.

  python3 pipeline.py                     everything that is out of date
  python3 pipeline.py --sets postwar      one set (and the maps)
  python3 pipeline.py --only snapshot     only jobs whose name contains this text
  python3 pipeline.py --force province    rerun matching jobs even when up to date
  python3 pipeline.py --dry-run           list the jobs and whether they would run
  python3 pipeline.py --adopt             take the existing outputs as up to date (no job runs)
Logs: work/pipeline/logs/<job>.log, and a line per job in work/pipeline/pipeline.log.
"""
import argparse
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from common import RAW, ROOT, WORK
from ww2_common import SNAPSHOTS_EARLY, SNAPSHOTS_POSTWAR, SNAPSHOTS_WW2, memory_free_gb, memory_limit_gb

SCRIPTS = ROOT / "scripts"
STATE = WORK / "pipeline"
SETS = {"ww2": SNAPSHOTS_WW2, "early": SNAPSHOTS_EARLY, "postwar": SNAPSHOTS_POSTWAR}
RESERVE_GB = 1.0          # kept free for this process, the shell and the page cache
TIMEOUT_S = 4 * 3600      # a job running longer than this is taken to hang
STAGES = ["prepare", "part", "relief", "modern", "merge", "snapshot", "province", "provinces", "database", "coverage",
          "webmap", "html"]
# expected peak memory (GB) of a step before it has been measured here
DEFAULT_GB = {"prepare": 4, "part": 4, "merge": 4, "snapshot": 5, "province": 8, "provinces": 3, "database": 3,
              "coverage": 2, "relief": 2, "modern": 6, "webmap": 0, "html": 1}

# sources: compared by size and time (some are gigabytes); work files: by content
SOURCES = [RAW / "ww2", RAW / "geoboundaries", RAW / "ohm" / "areas_1900_91.jsonl", RAW / "cshapes_2_gw.topojson",
           RAW / "ghs_pop", RAW / "naturalearth", RAW / "terrarium", ROOT / "ww2" / "maps" / "template.html"]
CURATED = ROOT / "curated"
RULES = {"ww2": "ww2_region_control.csv", "early": "region_control_1900_1934.csv",
         "postwar": "region_control_1946_1991.csv"}
CITIES = {"ww2_cities.csv", "cities_1900_1934.csv", "cities_1946_1991.csv", "cities_2026.csv"}


def curated(s=None):
    """The curated tables a step reads: the city lists only for the web map; control rules only for the steps
    of their own set that apply them (curated(set)), none for the units (curated())."""
    skip = CITIES | {f for k, f in RULES.items() if k != s}
    return [p for p in sorted(CURATED.rglob("*")) if p.is_file() and p.name not in skip]
BASE_WORK = [WORK / "unit_year.csv", WORK / "admin1_targets.csv", WORK / "years.csv", WORK / "ww2" / "ref_units.csv",
             WORK / "ww2" / "ref_units.wkb", WORK / "ww2" / "ref_units.geojson"]


@dataclass
class Job:
    name: str
    cmd: list
    deps: list = field(default_factory=list)
    reads: list = field(default_factory=list)      # files or directories
    outputs: list = field(default_factory=list)
    env: dict = field(default_factory=dict)
    step: str = ""
    exclusive: bool = False                         # runs alone (it has worker processes of its own)


# ---------------------------------------------------------------- fingerprints

def local_modules(script, seen=None):
    """The script and the modules of this repository it imports, directly or not."""
    seen = set() if seen is None else seen
    p = SCRIPTS / f"{script}.py"
    if script in seen or not p.exists():
        return seen
    seen.add(script)
    for m in re.findall(r"^\s*(?:from|import)\s+(\w+)", p.read_text(), re.M):
        local_modules(m, seen)
    return seen


class Hashes:
    """Content hashes of work files, kept by (size, time) so that each file is read once."""

    def __init__(self, path):
        self.path = path
        self.d = json.loads(path.read_text()) if path.exists() else {}

    def of(self, p):
        st = p.stat()
        key, sig = str(p), [st.st_size, st.st_mtime_ns]
        if self.d.get(key, [None])[:2] != sig:
            h = hashlib.md5()
            with open(p, "rb") as f:
                for block in iter(lambda: f.read(1 << 24), b""):
                    h.update(block)
            self.d[key] = sig + [h.hexdigest()]
        return self.d[key][2]

    def save(self):
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.d))
        tmp.replace(self.path)


def files_of(p):
    if p.is_dir():
        return sorted(q for q in p.rglob("*") if q.is_file())
    return [p] if p.exists() else []


def fingerprint(job, hashes):
    h = hashlib.md5(json.dumps([job.cmd, job.env]).encode())
    for m in sorted(local_modules(Path(job.cmd[1]).stem)):
        h.update((SCRIPTS / f"{m}.py").read_bytes())
    for r in job.reads:
        for p in files_of(r):
            if WORK in p.parents:
                h.update(f"{p}|{hashes.of(p)}".encode())
            else:
                st = p.stat()
                h.update(f"{p}|{st.st_size}|{st.st_mtime_ns}".encode())
        if not r.exists():
            h.update(f"{r}|missing".encode())
    return h.hexdigest()


# ---------------------------------------------------------------- the jobs

def jobs_for(sets):
    py = lambda script, *a: [sys.executable, str(SCRIPTS / script), *a]
    jobs = []
    for s in sets:
        w = WORK / s
        dates = [d for d, _, _ in SETS[s]]
        env = {"WW2_SET": s}
        J = lambda name, cmd, step, **kw: jobs.append(Job(f"{s}:{name}", cmd, env=env, step=step, **kw))
        J("prepare", py("ww2_histunits.py", "--prepare"), "prepare", reads=SOURCES + curated() + BASE_WORK,
          outputs=[w / "candidates.pkl"])
        for d in dates:
            J(f"part:{d}", py("ww2_histunits.py", "--part", d), "part", deps=[f"{s}:prepare"],
              reads=SOURCES + curated() + BASE_WORK + [w / "candidates.pkl"], outputs=[w / f"hist_part_{d}.pkl"])
        J("merge", py("ww2_histunits.py", "--merge"), "merge", deps=[f"{s}:part:{d}" for d in dates],
          reads=[w / f"hist_part_{d}.pkl" for d in dates], outputs=[w / "hist_units.csv", w / "hist_units.wkb"])
        units = [w / "hist_units.csv", w / "hist_units.wkb"]
        for d in dates:
            J(f"snapshot:{d}", py("ww2_snapshots.py", d), "snapshot", deps=[f"{s}:merge"],
              reads=SOURCES + curated(s) + BASE_WORK + units, outputs=[w / f"snapshot_{d}.csv", w / f"split_{d}.wkb"])
            J(f"province:{d}", py("ww2_provinces.py", "--date", d), "province", deps=[f"{s}:snapshot:{d}"],
              reads=SOURCES + [CURATED / "east_asia"] + units + [w / f"snapshot_{d}.csv", w / f"split_{d}.wkb"],
              outputs=[w / f"prov_part_{d}.pkl"])
        J("provinces", py("ww2_provinces.py", "--merge"), "provinces", deps=[f"{s}:province:{d}" for d in dates],
          reads=[w / f"prov_part_{d}.pkl" for d in dates],
          outputs=[w / "prov_units.csv", w / "prov_units.wkb"] + [w / f"prov_snapshot_{d}.csv" for d in dates])
        prov = [w / "prov_units.csv", w / "prov_units.wkb"] + \
            [w / f"prov_{k}_{d}.{e}" for d in dates for k, e in (("snapshot", "csv"), ("split", "wkb"))]
        J("database", py("ww2_database.py"), "database", deps=[f"{s}:provinces"], reads=SOURCES + curated(s) + prov)
        J("coverage", py("ww2_coverage.py"), "coverage", deps=[f"{s}:provinces"], reads=prov)
    jobs.append(Job("relief", py("ww2_relief.py"), step="relief", reads=[RAW / "terrarium"]))
    jobs.append(Job("modern", py("modern_2026.py"), step="modern", reads=SOURCES + [WORK / "ww2" / "ref_units.csv"]))
    maps = [WORK / s / f for s in SETS for f in ("prov_units.csv", "prov_units.wkb")] + \
        [WORK / s / f"prov_{k}_{d}.{e}" for s in SETS for d, _, _ in SETS[s] for k, e in
         (("snapshot", "csv"), ("split", "wkb"))]
    jobs.append(Job("webmap", py("ww2_webmap.py"), step="webmap", exclusive=True,
                    deps=[j.name for j in jobs if j.step in ("provinces", "relief", "modern")],
                    reads=SOURCES + [CURATED / c for c in sorted(CITIES)] + maps + [WORK / "modern"]))
    jobs.append(Job("html", py("ww2_html.py"), step="html", deps=["webmap"],
                    reads=[ROOT / "ww2" / "maps" / "template.html", ROOT / "ww2" / "maps" / "data" / "index.json"]))
    return jobs


# ---------------------------------------------------------------- running

class Runner:
    def __init__(self, jobs, args):
        self.jobs = {j.name: j for j in jobs}
        self.order = [j.name for j in jobs]
        self.args = args
        (STATE / "stamps").mkdir(parents=True, exist_ok=True)
        (STATE / "logs").mkdir(parents=True, exist_ok=True)
        self.hashes = Hashes(STATE / "hashes.json")
        self.stats = json.loads((STATE / "stats.json").read_text()) if (STATE / "stats.json").exists() else {}
        self.limit = memory_limit_gb() - RESERVE_GB
        self.done, self.failed, self.running = set(), set(), {}   # running: pid -> (job, Popen, start, gb, log)
        self.need = {}           # job -> GB expected
        self.alone = set()       # jobs to run with nothing else (killed for memory before)
        self.tries = {}

    def log(self, msg):
        line = time.strftime("%H:%M:%S ") + msg
        print(line, flush=True)
        with open(STATE / "pipeline.log", "a") as f:
            f.write(line + "\n")

    def expected(self, job):
        return self.need.get(job.name) or self.stats.get(job.step) or DEFAULT_GB.get(job.step, 4)

    def stamp_path(self, job):
        return STATE / "stamps" / (job.name.replace(":", "_") + ".json")

    def up_to_date(self, job):
        if self.args.force and self.args.force in job.name:
            return False
        sp = self.stamp_path(job)
        if not sp.exists() or not all(p.exists() for p in job.outputs):
            return False
        st = json.loads(sp.read_text())
        # the outputs as the job left them (not cut short by a kill, nor changed by hand since)
        if any(self.hashes.of(Path(p)) != h for p, h in st.get("outputs", {}).items() if Path(p).exists()):
            return False
        return st.get("fingerprint") == fingerprint(job, self.hashes)

    def output_hashes(self, job):
        return {str(p): self.hashes.of(p) for p in job.outputs if WORK in p.parents}

    def launch(self, job):
        logp = STATE / "logs" / (job.name.replace(":", "_") + ".log")
        f = open(logp, "w")
        env = dict(os.environ, **job.env, PYTHONUNBUFFERED="1")
        proc = subprocess.Popen(job.cmd, cwd=SCRIPTS, env=env, stdout=f, stderr=subprocess.STDOUT,
                                start_new_session=True)
        self.running[proc.pid] = (job, proc, time.time(), self.expected(job), f, logp)
        self.log(f"start  {job.name}  (expects {self.expected(job):.1f} GB; {len(self.running)} running)")

    def finish(self, pid, status, usage):
        job, proc, t0, gb, f, logp = self.running.pop(pid)
        f.close()
        rc = os.waitstatus_to_exitcode(status)
        peak = usage.ru_maxrss / 2 ** 20  # KB -> GB
        secs = time.time() - t0
        if job.step and peak > 0:
            self.stats[job.step] = round(max(self.stats.get(job.step, 0), peak), 2)
        if rc == 0:
            missing = [str(p) for p in job.outputs if not p.exists()]
            if missing:
                return self.fail(job, logp, f"finished without writing {missing}")
            self.stamp_path(job).write_text(json.dumps({"fingerprint": fingerprint(job, self.hashes),
                                                        "outputs": self.output_hashes(job),
                                                        "seconds": round(secs), "peak_gb": round(peak, 2)}))
            self.done.add(job.name)
            self.log(f"done   {job.name}  {secs / 60:.1f} min, peak {peak:.1f} GB")
        elif rc == -signal.SIGKILL and self.tries.get(job.name, 0) < 2:
            # killed for memory (or by hand): once more, alone, expecting more than it reached
            self.tries[job.name] = self.tries.get(job.name, 0) + 1
            self.need[job.name] = max(peak * 1.3, gb * 1.5)
            self.alone.add(job.name)
            self.log(f"killed {job.name} at {peak:.1f} GB after {secs / 60:.1f} min; will run again on its own")
        else:
            self.fail(job, logp, f"exit code {rc} after {secs / 60:.1f} min")
        (STATE / "stats.json").write_text(json.dumps(self.stats, indent=1))
        self.hashes.save()

    def fail(self, job, logp, why):
        self.failed.add(job.name)
        tail = logp.read_text(errors="replace").splitlines()[-25:]
        self.log(f"FAILED {job.name}: {why}; end of {logp}:\n    " + "\n    ".join(tail))

    def ready(self):
        """Jobs whose dependencies are done, later stages first (they are closer to a finished set)."""
        for n in sorted(self.order, key=lambda n: -STAGES.index(self.jobs[n].step)):
            j = self.jobs[n]
            if n in self.done or n in self.failed or any(pid_job[0].name == n for pid_job in self.running.values()):
                continue
            if all(d in self.done or d not in self.jobs for d in j.deps):
                yield j

    def committed(self):
        return sum(gb for _, _, _, gb, _, _ in self.running.values())

    def fits(self, job):
        if not self.running:
            return True
        if job.exclusive or job.name in self.alone or any(j.exclusive or j.name in self.alone
                                                            for j, *_ in self.running.values()):
            return False
        return self.committed() + self.expected(job) <= self.limit and self.expected(job) <= memory_free_gb() - 0.5

    def stop(self, signum, frame):
        """Stopped by hand or by the system: the jobs run in sessions of their own, so stop them too."""
        for pid, (j, *_) in list(self.running.items()):
            self.log(f"stopping {j.name}")
            try:
                os.killpg(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        self.hashes.save()
        sys.exit(128 + signum)

    def run(self):
        signal.signal(signal.SIGTERM, self.stop)
        signal.signal(signal.SIGINT, self.stop)
        self.log(f"memory limit {self.limit + RESERVE_GB:.1f} GB; {len(self.jobs)} jobs")
        while True:
            settled = 0  # jobs found up to date (or listed by --dry-run) in this pass: their dependants may be ready
            if not self.failed:
                for j in list(self.ready()):
                    if self.up_to_date(j):
                        self.done.add(j.name)
                        settled += 1
                        self.log(f"skip   {j.name}  (up to date)")
                        continue
                    if self.args.adopt and all(p.exists() for p in j.outputs):
                        self.stamp_path(j).write_text(json.dumps({"fingerprint": fingerprint(j, self.hashes),
                                                                  "outputs": self.output_hashes(j), "adopted": True}))
                        self.done.add(j.name)
                        settled += 1
                        self.log(f"adopt  {j.name}  (existing outputs taken as up to date)")
                        continue
                    if self.args.dry_run:
                        self.done.add(j.name)
                        settled += 1
                        self.log(f"would run {j.name}  (expects {self.expected(j):.1f} GB)")
                        continue
                    if not self.fits(j):
                        break  # wait for memory rather than let smaller jobs of earlier stages overtake it
                    self.launch(j)
                self.hashes.save()
            if not self.running:
                if settled:
                    continue
                break
            pid, status, usage = os.wait4(-1, os.WNOHANG)
            if pid == 0:  # nothing finished yet
                for p, (j, proc, t0, *_) in list(self.running.items()):
                    if time.time() - t0 > TIMEOUT_S:
                        self.log(f"timeout {j.name}: stopping it")
                        os.killpg(p, signal.SIGTERM)
                time.sleep(2)
            elif pid in self.running:
                self.finish(pid, status, usage)
        left = [n for n in self.order if n not in self.done]
        if self.failed or left:
            self.log(f"stopped: failed {sorted(self.failed)}; not run {len(left)} jobs")
            return 1
        self.log("all jobs done")
        return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sets", default="ww2,early,postwar", help="comma-separated sets (default: all three)")
    ap.add_argument("--only", help="run only the jobs whose name contains this text (their inputs must exist)")
    ap.add_argument("--force", help="rerun the jobs whose name contains this text even when up to date")
    ap.add_argument("--no-maps", action="store_true", help="leave out relief, modern, webmap and html")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--adopt", action="store_true", help="record the existing outputs as up to date without running "
                    "(after the code changed in a way that does not change the results, or a build by hand)")
    args = ap.parse_args()
    sets = [s for s in args.sets.split(",") if s]
    jobs = jobs_for(sets)
    if args.no_maps:
        jobs = [j for j in jobs if j.step not in ("relief", "modern", "webmap", "html")]
    if args.only:
        keep = {j.name for j in jobs if args.only in j.name}
        jobs = [j for j in jobs if j.name in keep]
        for j in jobs:
            j.deps = [d for d in j.deps if d in keep]
    sys.exit(Runner(jobs, args).run())


if __name__ == "__main__":
    main()
