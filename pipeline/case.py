"""Run one test case end to end and print one JSON record.

python -m pipeline.case --campaign C --gen arith --seed 7 [--seeded] [--configs O1,O2] [--budget 60]
"""
import argparse
import json
import random
import sys
import time
import traceback
from pathlib import Path

from . import bin as binside
from . import build, confirm, gen, localize, oracle, ref, seeded

CONFIGS = {
    "O1": ("-O1", ()),
    "O2": ("-O2", ()),
    "O3": ("-O3", ()),
    "Os": ("-Os", ()),
    "O2-v3": ("-O2", ("-march=x86-64-v3",)),
}


def fuzz_inputs(seed, n_in, n=2000):
    rng = random.Random(seed ^ 0x5EED)
    pick = [0, 1, 2, 0x7f, 0x80, 0xfe, 0xff]
    return [bytes(rng.choice(pick) if rng.random() < 0.5 else rng.getrandbits(8) for _ in range(n_in))
            for _ in range(n)]


def run_case(campaign, gen_name, seed, configs, seeded_mode=False, budget=60, do_localize=True):
    t0 = time.time()
    rec = {"campaign": campaign, "gen": gen_name, "seed": seed, "seeded": None, "cc": build.CLANG}
    work = build.ROOT / "work" / campaign / f"{gen_name}-{seed}"
    work.mkdir(parents=True, exist_ok=True)
    prog = gen.generate(gen_name, seed)
    src = work / "prog.c"
    src.write_text(prog.source)
    bin_src = src
    if seeded_mode:
        m = seeded.mutate(prog.source, seed)
        if m is None:
            rec["error"] = "no mutation site"
            return rec
        bin_src = work / "mutant.c"
        bin_src.write_text(m[0])
        rec["seeded"] = m[1]

    r = ref.run(src, work / "ref", prog.n_in, prog.n_out, max_time=budget)
    rec["ref"] = {"paths": len(r.paths), "error_paths": r.error_paths, "error_kinds": r.error_kinds,
                  "complete": r.complete, "seconds": round(r.seconds, 2), "note": r.note}
    natives = confirm.Natives(src, work, prog.n_in, prog.n_out)
    concrete_inputs = oracle.path_inputs(r.paths, prog.n_in)
    fuzz = fuzz_inputs(seed, prog.n_in)
    fuzz_ref = build.replay_many(natives.ref_clang(), fuzz)
    rec["configs"] = {}
    for name in configs:
        opt, extra = CONFIGS[name]
        c = {}
        rec["configs"][name] = c
        try:
            exe = binside.compile_exe(bin_src, work / f"dut-{name}", prog.n_in, prog.n_out, opt=opt, extra=extra)
        except build.BuildError as e:
            c["error"] = f"build: {str(e)[:300]}"
            continue
        b = binside.run(exe, prog.n_in, prog.n_out, max_time=budget)
        c["bin"] = {"paths": len(b.paths), "errored": b.errored, "complete": b.complete,
                    "seconds": round(b.seconds, 2), "note": b.note}
        to = time.time()
        o = oracle.compare(r.paths, b.paths, prog.n_in, prog.n_out, budget=2 * budget)
        c["oracle"] = {"pairs": o.pairs, "overlapping": o.overlapping, "unknown": o.unknown,
                       "ref_covered": o.ref_covered, "complete": o.complete, "seconds": round(time.time() - to, 2)}
        cands = []
        for mm in o.mismatches:
            verdict, info = confirm.classify(natives, exe, mm.witness, mm.ref_out, mm.bin_out)
            cands.append({"verdict": verdict, "witness": mm.witness.hex(), "ref_path": mm.ref_path,
                          "bin_path": mm.bin_path, **info})
        c["candidates"] = cands
        # concrete channel: replay one input per reference path natively
        conc = {"inputs": len(concrete_inputs), "differs": None}
        for inp in concrete_inputs:
            v, info = confirm.classify(natives, exe, inp)
            if v == "confirmed":
                conc["differs"] = {"witness": inp.hex(), **info}
                break
        c["concrete"] = conc
        # fuzz channel: random inputs natively (baseline)
        fd = build.replay_many(exe, fuzz)
        hits = [k for k, (x, y) in enumerate(zip(fuzz_ref, fd)) if x != y]
        c["fuzz"] = {"inputs": len(fuzz), "differs": len(hits), "witness": fuzz[hits[0]].hex() if hits else None}
        confirmed = [x for x in cands if x["verdict"] == "confirmed"]
        if confirmed and do_localize and not seeded_mode:
            w = bytes.fromhex(confirmed[0]["witness"])
            c["localize"] = localize.bisect(src, work / "bisect", prog.n_in, prog.n_out, opt, extra, w,
                                            confirmed[0]["ref_native"])
    rec["seconds"] = round(time.time() - t0, 2)
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--campaign", required=True)
    ap.add_argument("--gen", default="arith")
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--seeded", action="store_true")
    ap.add_argument("--configs", default="O1,O2,O3,Os")
    ap.add_argument("--budget", type=int, default=60)
    a = ap.parse_args()
    try:
        rec = run_case(a.campaign, a.gen, a.seed, a.configs.split(","), a.seeded, a.budget)
    except Exception as e:  # record, don't lose the case
        rec = {"campaign": a.campaign, "gen": a.gen, "seed": a.seed, "seeded": a.seeded,
               "error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-2000:]}
    sys.stdout.write(json.dumps(rec) + "\n")


if __name__ == "__main__":
    main()
