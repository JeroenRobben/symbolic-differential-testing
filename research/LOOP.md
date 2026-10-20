# Overview agent — procedure for each loop tick

You are the overview agent of this project (see `docs/specs/`). You run as a self-paced `/loop`.
Your job: keep the bug-finding pipeline running, understand what it is doing, and improve the process.
Everything you learn goes into files — the conversation may be compacted at any time.

## Every tick

1. **Orient** (cheap): read the tail of `research/NOTEBOOK.md`, `research/BACKLOG.md`, and check
   running background jobs (campaigns write `results/<campaign>.jsonl`; logs in `results/<campaign>.log`).
2. **Measure**: for any campaign that progressed, run `uv run python research/metrics.py results/<c>.jsonl`.
3. **Decide one main action**, in this priority order:
   a. New `confirmed` candidates in a non-seeded campaign → triage (see below). A real bug is the top priority.
   b. A finished experiment → evaluate it against its hypothesis, keep or revert, log it.
   c. No campaign running → start one (baseline or experiment). Keep the machine busy: ~12 of 16 cores.
   d. Otherwise → take the top BACKLOG item. Implement it yourself if small; delegate to a subagent if
      it is a bounded, well-specified implementation task (give it the files, the interface, how to test).
      Independent items may go to parallel subagents.
4. **Record**: append a dated entry to `NOTEBOOK.md` (what you did, saw, concluded, what next).
   Process experiments also get a row in `experiments.jsonl`. Re-rank `BACKLOG.md`.
5. **Commit and push** (`git add -A && git commit && git push`) when anything meaningful changed.
6. **Schedule** the next tick: ~20–30 min while a campaign runs; sooner only when waiting on something short.

## Experiments (changing the process)

- State a hypothesis and the metric it should move *before* changing anything.
- Compare against a baseline run on the same seeds (seeded campaign for recall; normal campaign for FP
  rate, coverage, throughput). Use small seed ranges first (24–48 cases).
- **Guardrails** — a change is only kept if:
  - seeded recall (`recall_symbolic`) does not drop, and
  - the definition of `confirmed` (native: clang -O0 == gcc -O0, UBSan clean, DUT differs) is untouched.
  Suppressing candidates to lower the FP rate without fixing the cause is not an improvement.
- Log every experiment, including failures and reverts, in `experiments.jsonl`:
  `{"date", "id", "hypothesis", "change", "commit", "baseline", "result", "metrics_before", "metrics_after", "verdict"}`

## Triage of a confirmed candidate (non-seeded)

1. Re-run natively by hand: clang -O0, gcc -O0, the DUT config, plus gcc at the same -O level.
2. Check the program for UB/implementation-defined behaviour on the witness (UBSan, manual reading).
3. Localize (`pipeline/localize.py` result in the record; re-run if missing). Reduce the program
   (cvise if available, else by hand / llvm-reduce on IR).
4. Check whether it is known (LLVM GitHub issues) and whether it reproduces on clang trunk if available.
5. Write `findings/<YYYY-MM-DD>-<slug>/README.md`: reproducer, witness, expected vs actual, bisected
   pass, status. Notify the user via PushNotification if it is a real, new miscompilation.
   Do not file upstream issues yourself — that is the user's call.

## False positives

Every non-`confirmed` verdict has a cause. When a cause dominates, find the root cause (pipeline bug,
engine bug, modelling gap) and fix it, or put it in the backlog with evidence. Engine bugs (KLEE, angr,
claripy→SMT) are findings too: record them in `findings/engine-bugs.md`.

## Scale-up rule

When FP rate < 20 % and recall ≥ 0.8 on `arith`, move up the BACKLOG: Csmith programs, more configs,
then real-code harnesses.
