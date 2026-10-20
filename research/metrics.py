"""Scorecard for one or more campaigns.

python research/metrics.py results/c001.jsonl [more.jsonl ...]   (prints JSON + a readable summary)
"""
import json
import sys
from collections import Counter


def load(paths):
    recs = []
    for p in paths:
        with open(p) as f:
            recs += [json.loads(l) for l in f if l.strip()]
    return recs


def score(recs):
    s = Counter()
    verdicts = Counter()
    passes = Counter()
    cpu = 0.0
    for r in recs:
        s["cases"] += 1
        if "error" in r:
            s["case_errors"] += 1
            continue
        cpu += r.get("seconds", 0)
        ref = r["ref"]
        s["ref_complete"] += ref["complete"]
        s["ref_paths"] += ref["paths"]
        s["ref_error_paths"] += ref["error_paths"] > 0
        for name, c in r["configs"].items():
            s["configs"] += 1
            if "error" in c:
                s["config_errors"] += 1
                continue
            s["bin_complete"] += c["bin"]["complete"]
            s["bin_errored"] += c["bin"]["errored"] > 0
            o = c["oracle"]
            s["oracle_unknown"] += o["unknown"]
            s["oracle_incomplete"] += not o.get("complete", True)
            s["ref_paths_covered"] += o["ref_covered"]
            s["ref_paths_total"] += ref["paths"]
            cands = c.get("candidates", [])
            for x in cands:
                verdicts[x["verdict"]] += 1
            sym = any(x["verdict"] == "confirmed" for x in cands)
            conc = bool(c.get("concrete", {}).get("differs"))
            fz = bool(c.get("fuzz", {}).get("differs"))
            s["detect_symbolic"] += sym
            s["detect_concrete"] += conc
            s["detect_fuzz"] += fz
            s["detect_any"] += sym or conc or fz
            s["detect_symbolic_only"] += sym and not (conc or fz)
            loc = c.get("localize")
            if loc:
                passes[loc.get("pass", loc.get("note", "?"))] += 1
    total_c = sum(verdicts.values())
    fp = sum(v for k, v in verdicts.items() if k not in ("confirmed",))
    out = dict(s)
    out["verdicts"] = dict(verdicts)
    out["fp_rate"] = round(fp / total_c, 3) if total_c else None
    out["recall_symbolic"] = round(s["detect_symbolic"] / s["detect_any"], 3) if s["detect_any"] else None
    out["path_coverage"] = round(s["ref_paths_covered"] / s["ref_paths_total"], 3) if s["ref_paths_total"] else None
    out["cpu_hours"] = round(cpu / 3600, 3)
    out["confirmed_per_cpu_hour"] = round(verdicts["confirmed"] / (cpu / 3600), 2) if cpu else None
    out["bisected_passes"] = dict(passes)
    return out


if __name__ == "__main__":
    print(json.dumps(score(load(sys.argv[1:])), indent=1))
