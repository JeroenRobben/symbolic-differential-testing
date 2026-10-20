"""Run a campaign: many cases in parallel, one JSON line per case in results/<campaign>.jsonl.

python -m pipeline.run --campaign c001 --seeds 0:100 [--seeded] [--configs O1,O2,O3,Os] [--jobs 12]
Already-recorded seeds are skipped, so an interrupted campaign can be resumed.
"""
import argparse
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--campaign", required=True)
    ap.add_argument("--gen", default="arith")
    ap.add_argument("--seeds", default="0:50")
    ap.add_argument("--seeded", action="store_true")
    ap.add_argument("--configs", default="O1,O2,O3,Os")
    ap.add_argument("--budget", type=int, default=60)
    ap.add_argument("--jobs", type=int, default=12)
    ap.add_argument("--case-timeout", type=int, default=900)
    a = ap.parse_args()
    lo, hi = map(int, a.seeds.split(":"))
    out = ROOT / "results" / f"{a.campaign}.jsonl"
    out.parent.mkdir(exist_ok=True)
    done = set()
    if out.exists():
        done = {json.loads(l)["seed"] for l in out.read_text().splitlines() if l.strip()}
    seeds = [s for s in range(lo, hi) if s not in done]
    print(f"{a.campaign}: {len(seeds)} cases ({len(done)} already done)", flush=True)

    def one(seed):
        cmd = [sys.executable, "-m", "pipeline.case", "--campaign", a.campaign, "--gen", a.gen,
               "--seed", str(seed), "--configs", a.configs, "--budget", str(a.budget)]
        if a.seeded:
            cmd.append("--seeded")
        try:
            p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=a.case_timeout)
            line = p.stdout.strip().splitlines()[-1] if p.stdout.strip() else None
            rec = json.loads(line) if line else {"error": f"no output rc={p.returncode}: {p.stderr[-500:]}"}
        except subprocess.TimeoutExpired:
            rec = {"error": "case timeout"}
        rec.setdefault("campaign", a.campaign)
        rec.setdefault("gen", a.gen)
        rec["seed"] = seed
        rec["seeded_mode"] = a.seeded
        return rec

    n = 0
    with ThreadPoolExecutor(a.jobs) as ex, out.open("a") as f:
        for rec in ex.map(one, seeds):
            f.write(json.dumps(rec) + "\n")
            f.flush()
            n += 1
            flag = ""
            for name, c in rec.get("configs", {}).items():
                if any(x["verdict"] == "confirmed" for x in c.get("candidates", [])):
                    flag += f" CONFIRMED[{name}]"
            if n % 10 == 0 or flag or "error" in rec:
                print(f"[{n}/{len(seeds)}] seed={rec['seed']}{flag} {rec.get('error', '')[:120]}", flush=True)
    print("done", flush=True)


if __name__ == "__main__":
    main()
