"""Where does per-file time go under threads? Wraps the S3 range fetch and extract_record."""
import json, shutil, sys, time, importlib.util, pathlib, threading, os, statistics
T, CLONE, OUT, N = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]), pathlib.Path(sys.argv[3]), int(sys.argv[4])
sys.path.insert(0, str(T / "scripts/ingestions"))
spec = importlib.util.spec_from_file_location("digest3", T / "scripts/ingestions/3_digest.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
import _parser_utils, _remote_header, _bids_digest
lock = threading.Lock(); fetch_t = []; rec_t = []
orig_fetch = _parser_utils.fetch_bytes_from_s3
def fetch(*a, **k):
    t = time.perf_counter(); r = orig_fetch(*a, **k)
    with lock: fetch_t.append(time.perf_counter() - t)
    return r
_parser_utils.fetch_bytes_from_s3 = fetch; _remote_header.fetch_bytes_from_s3 = fetch
orig_rec = _bids_digest._extract_record_safe
def rec(*a, **k):
    t = time.perf_counter(); r = orig_rec(*a, **k)
    with lock: rec_t.append(time.perf_counter() - t)
    return r
_bids_digest._extract_record_safe = rec
import subprocess
src = CLONE / "nm000281"; sub = OUT / "subset" / "nm000281"
if not sub.exists():
    sub.mkdir(parents=True)
    for p in src.iterdir():
        if not p.name.startswith("sub-") and p.name != ".git":
            subprocess.run(["cp", "-a", str(p), str(sub / p.name)], check=True)
    n = 0
    for s in sorted(p for p in src.iterdir() if p.name.startswith("sub-")):
        k = sum(1 for _ in s.rglob("*.bdf"))
        if n and n + k > N: break
        subprocess.run(["cp", "-a", str(s), str(sub / s.name)], check=True); n += k
    print("subset BDF files:", n, flush=True)
res = {}
q = lambda xs, p: round(statistics.quantiles(xs, n=20)[int(p * 20) - 1], 3) if len(xs) > 20 else None
for nj in [int(x) for x in os.environ.get("BENCH_NJ", "1,8,1,8").split(",")]:
    fetch_t.clear(); rec_t.clear(); o = OUT / f"nj{nj}"; shutil.rmtree(o, ignore_errors=True)
    t0 = time.perf_counter(); c0 = time.process_time()
    s = m.digest_dataset("nm000281", OUT / "subset", o, n_jobs=nj)
    wall = time.perf_counter() - t0; cpu = time.process_time() - c0
    summ = json.load(open(o / "nm000281" / "nm000281_summary.json"))
    if summ.get("digest_method") != "bids_filesystem": sys.exit("INVALID: " + str(summ.get("digest_method")))
    r = dict(n_jobs=nj, wall_s=round(wall, 1), cpu_s=round(cpu, 1), files=len(rec_t), files_per_s=round(len(rec_t) / wall, 2),
             fetches=len(fetch_t), fetch_sum_s=round(sum(fetch_t), 1), fetch_median_s=q(fetch_t, .5), fetch_p95_s=q(fetch_t, .95),
             record_median_s=q(rec_t, .5), record_p95_s=q(rec_t, .95), record_sum_s=round(sum(rec_t), 1),
             non_fetch_per_record_s=round((sum(rec_t) - sum(fetch_t)) / max(len(rec_t), 1), 3))
    res.setdefault("runs", []).append(r); print(r, flush=True)
json.dump(res, open(OUT / "instrument.json", "w"), indent=1)
