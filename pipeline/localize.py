"""Localize a confirmed miscompilation to the first LLVM pass that introduces it (opt-bisect)."""
import re
import subprocess
from pathlib import Path

from . import build


def _differs(src, work, n_in, n_out, opt, extra, witness, expected, limit):
    exe = build.native(src, work / f"bisect-{limit}", n_in, n_out, cc=build.CLANG, opt=opt,
                       extra=(*extra, "-mllvm", f"-opt-bisect-limit={limit}"))
    try:
        return build.replay(exe, witness) != expected
    except build.BuildError:
        return True


def bisect(src: Path, work: Path, n_in, n_out, opt, extra, witness: bytes, expected: list):
    """Returns {"limit": N, "pass": "..."} for the first bad pass, or a note if not bisectable."""
    work.mkdir(parents=True, exist_ok=True)
    p = subprocess.run([build.CLANG, opt, *extra, "-w", "-c", str(src), "-o", "/dev/null",
                        "-mllvm", "-opt-bisect-limit=-1"], capture_output=True, text=True)
    runs = re.findall(r"BISECT: running pass \((\d+)\) (.*)", p.stderr)
    if not runs:
        return {"note": "no bisect output"}
    hi = max(int(n) for n, _ in runs)
    if _differs(src, work, n_in, n_out, opt, extra, witness, expected, 0):
        return {"note": "differs with all optional passes disabled (non-skippable pass / backend)"}
    if not _differs(src, work, n_in, n_out, opt, extra, witness, expected, hi):
        return {"note": "does not reproduce under bisect"}
    lo = 0  # lo: good, hi: bad
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if _differs(src, work, n_in, n_out, opt, extra, witness, expected, mid):
            hi = mid
        else:
            lo = mid
    name = dict((int(n), s) for n, s in runs).get(hi, "?")
    return {"limit": hi, "pass": name}
