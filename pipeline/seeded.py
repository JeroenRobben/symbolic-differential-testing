"""Seeded 'miscompilations': single-site source mutants compiled on the binary side only.

Used to measure recall of the pipeline: a process change that loses seeded bugs is suspect.
"""
import random
import re

MUTATIONS = [
    (r"(?<![<>=!])<(?![<=])", "<="),
    (r"<=", "<"),
    (r"(?<![<>])>(?![>=])", ">="),
    (r">=", ">"),
    (r"==", "!="),
    (r"\)\s\+\s\(", ") - ("),
    (r"\)\s\^\s\(", ") | ("),
    (r"\b(\d+)U\b", lambda m: f"{int(m.group(1)) + 1}U"),
]


def mutate(src: str, seed: int):
    """Mutate one site inside __test's body. Returns (mutant_source, description) or None."""
    rng = random.Random(seed)
    start = src.index("void __test(void) {")
    body = src[start:]
    sites = []
    for k, (pat, rep) in enumerate(MUTATIONS):
        for m in re.finditer(pat, body):
            line = body[:m.start()].rsplit("\n", 1)[-1]
            if "__builtin_memcpy" in line or "__out[" in line or "for (" in line:
                continue
            ctx = body[max(0, m.start() - 4):m.end() + 6]
            if "== 0 ||" in ctx or "== -1)" in ctx or "1 <<" in ctx:  # division guards
                continue
            sites.append((k, m))
    if not sites:
        return None
    k, m = rng.choice(sites)
    rep = MUTATIONS[k][1]
    new = rep(m) if callable(rep) else rep
    body = body[:m.start()] + new + body[m.end():]
    return src[:start] + body, f"{m.group(0)!r}->{new!r} @{start + m.start()}"
