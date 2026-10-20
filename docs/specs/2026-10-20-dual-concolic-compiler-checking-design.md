# Dual symbolic-execution compiler checking — design

Date: 2026-10-20

## Goal

Find miscompilations by comparing the semantics of a program **as written** (reference: clang `-O0` IR,
executed symbolically by KLEE) with the semantics of the **compiled code** (x86-64 binary built by the
compiler under test, executed symbolically by angr). Any intermediate stage (IR after a given pass,
`-O1`, …) may serve as either side. A long-running **overview agent** runs the pipeline, keeps a lab
notebook, measures the process, and improves it.

## Pipeline (`pipeline/`)

One test case = one generated C program with a harness exposing
`uint8_t __in[N]` (symbolic input bytes `b0..b{N-1}`) and `uint64_t __out[M]` (observable outputs).

| Stage | Module | What it does |
|---|---|---|
| generate | `gen.py` | Produces program + harness. Generators: `arith` (own, integer-arithmetic functions with branches/bounded loops, UB-free via safe ops), `csmith` (Csmith program, K scalar globals made symbolic, all scalar globals as outputs). |
| reference | `ref.py` | clang-18 `-O0 -Xclang -disable-O0-optnone` → bitcode → KLEE (Z3, `--write-smt2s`). Each completed path's SMT2 = `π_ref(b) ∧ o = f_ref(b)`. Paths ending in errors (UB, div0, OOB) are recorded and excluded. |
| binary | `bin.py` | clang-23 `-O{1,2,3,s}` → ELF → angr: symbolic `__in`, run harness entry to return, collect per path `π_bin(b)` and `f_bin(b)` as z3 terms. |
| oracle | `oracle.py` | For each ref path i, bin path j: `SAT? π_ref_i ∧ π_bin_j ∧ ∨_k o_k ≠ f_bin_j,k` → witness bytes. Also records coverage agreement. |
| confirm | `confirm.py` | Native replay of witness: build native harness with clang-23 `-O0`, gcc `-O0` (reference agreement) and the config under test. Confirmed iff references agree with each other and differ from the config under test. Otherwise classified as an FP with cause (`ref-engine`, `bin-engine`, `ub`, `harness`). |
| localize | `localize.py` | `-mllvm -opt-bisect-limit` binary search with the witness → first bad pass. |
| campaign | `run.py` | N programs × configs, parallel; appends one JSON record per test to `results/<campaign>.jsonl`. |

Reduction (cvise/creduce) is a backlog item.

## Overview agent (`research/`)

The self-paced `/loop` session in Claude Code is the overview agent. Its procedure is
`research/LOOP.md`. State lives in files so it survives context compaction:

- `NOTEBOOK.md` — dated entries: what was done, observed, decided.
- `experiments.jsonl` — one row per process experiment: hypothesis, change (git commit), metrics before/after, verdict (keep/revert).
- `BACKLOG.md` — ranked ideas; the agent pulls the top item when no campaign/triage is pending.
- `metrics.py` — computes the scorecard from `results/*.jsonl`.
- `findings/<id>/` — confirmed bugs: source, witness, configs, bisected pass, status.

The overview agent delegates bounded work (implementing a backlog item, triaging a batch of candidates)
to worker subagents and keeps judgement for itself: choosing what to do next and accepting or
rejecting changes.

### Scorecard

- confirmed miscompilations (unique by bisected pass + reduced signature)
- candidates / CPU-hour, confirmed / CPU-hour
- false-positive rate, broken down by cause
- path agreement: fraction of ref paths with a jointly-satisfiable bin path, and the reverse
- per-stage failure/timeouts rates (KLEE, angr, oracle)
- **seeded-bug recall** (see below)

### Guarding against self-deception

- "Confirmed" is defined only by native replay (above) and may not be weakened.
- Seeded-bug benchmark (`pipeline/seeded.py`): the binary side is compiled from a single-site mutant of
  the reference program (e.g. `<`→`<=`, `+1`), simulating a miscompilation. Any change that filters or
  suppresses candidates must not lower seeded recall; this is checked before a change is kept.
- Every process change is a git commit with an `experiments.jsonl` row; reverted changes are logged too.

## Phasing

1. Toolchain: KLEE (built against LLVM 18 + Z3), Csmith, angr (Python 3.12 via uv).
2. End-to-end on `arith` generator with seeded bugs → recall works.
3. Campaigns on clang-23 `-O1/-O2/-O3/-Os`; triage; FP reduction.
4. Csmith programs; then real-code harnesses once FP rate < 20 % on generated code.
5. Open: concolic seeding for scale, second engine pair (SymCC/SymQEMU) for cross-checks, other targets.
