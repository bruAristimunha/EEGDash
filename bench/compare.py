"""Compare two digests of the same dataset: record count, sizing, normalised sha256."""
import json, sys, hashlib, collections
out = {}
for d in sys.argv[1:]:
    recs = json.load(open(f"{d}/nm000281/nm000281_records.json"))["records"]
    summ = json.load(open(f"{d}/nm000281/nm000281_summary.json"))
    norm = sorted(json.dumps({k: v for k, v in r.items() if k not in ("digested_at", "_id")}, sort_keys=True) for r in recs)
    out[d] = dict(method=summ.get("digest_method"), records=len(recs),
                  no_ntimes=sum(1 for r in recs if not r.get("ntimes")),
                  hours=round(sum(r.get("duration_seconds") or 0 for r in recs) / 3600, 1),
                  prov=dict(collections.Counter((r.get("_metadata_provenance") or {}).get("ntimes") for r in recs)),
                  sha256=hashlib.sha256("\n".join(norm).encode()).hexdigest())
    print(d, out[d])
print("PARITY", len({v["sha256"] for v in out.values()}) == 1)
json.dump(out, open("compare.json", "w"), indent=1)
